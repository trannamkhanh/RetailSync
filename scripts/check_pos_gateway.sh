#!/usr/bin/env bash
# PB-48-3: check what the POS gateway forwards. Each request carries the
# client certificate of POS-DN1-01 and no token, so a request that reaches the
# event route gets the middleware's 401 UNAUTHORIZED, while one the gateway
# refuses gets nginx's 404. Paths with "..", "." or encoded characters must be
# refused, or forwarded as /api/v1/pos/events; nothing else may reach the
# middleware. Run it in the middleware image, which has curl with OpenSSL,
# from the repository root with pos-gateway running:
#
#     docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo --entrypoint bash middleware scripts/check_pos_gateway.sh
set -uo pipefail

GATEWAY="${GATEWAY:-pos-gateway:9443}"
BASE=https://localhost:9443
CLIENT=POS-DN1-01
cd "$(dirname "${BASH_SOURCE[0]}")/.."

failures=0

# probe METHOD PATH EXPECTED, where EXPECTED is "forwarded", "refused" or "either".
probe() {
    local body status outcome
    body="$(curl -sS --path-as-is -X "$1" -o - -w '\n%{http_code}' \
        --connect-to "localhost:9443:$GATEWAY" --cacert .certs/ca.crt \
        --cert ".certs/pos/$CLIENT.crt" --key ".certs/pos/$CLIENT.key" \
        -H "Content-Type: application/json" --data-binary '{}' "$BASE$2" 2>&1)"
    status="${body##*$'\n'}"
    if [ "$status" = "401" ] && printf '%s' "$body" | grep -q '"code":"UNAUTHORIZED"'; then
        outcome=forwarded
    elif [ "$status" = "404" ] && printf '%s' "$body" | grep -q '<center>nginx'; then
        outcome=refused
    else
        outcome="unexpected HTTP $status"
    fi
    if [ "$outcome" = "$3" ] || { [ "$3" = "either" ] && [[ "$outcome" =~ ^(forwarded|refused)$ ]]; }; then
        printf 'PASS  %-6s %-40s %s\n' "$1" "$2" "$outcome"
    else
        printf 'FAIL  %-6s %-40s %s, expected %s\n' "$1" "$2" "$outcome" "$3"
        failures=$((failures + 1))
    fi
}

probe POST /api/v1/pos/events forwarded
probe POST /api/v1/x/../pos/events either
probe POST /api/v1/pos/./events either
probe POST /api/v1/pos//events either
probe POST /api/v1/pos/%65vents either
probe POST /api/v1/pos/events/ refused
probe POST /api/v1/pos/events/../../health refused
probe POST /api/v1/pos/events%2F..%2F..%2Fhealth refused
probe POST /api/v1/audit-logs refused
probe POST /api/v1/health refused
probe GET /api/v1/pos/events refused
probe PUT /api/v1/pos/events refused

if [ "$failures" -ne 0 ]; then
    echo "$failures gateway check(s) failed"
    exit 1
fi
echo "All gateway checks passed"
