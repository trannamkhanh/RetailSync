#!/usr/bin/env bash
# PB-48-2: check TLS on the POS gateway. Fails unless TLS 1.2 and TLS 1.3
# connect and TLS 1.1 is refused. Run it from the repository root in Git Bash,
# with pos-gateway running:
#
#     bash scripts/check_pos_tls.sh [host] [port]      # default: localhost 9443
#
# It presents the client certificate of POS-DN1-01 when .certs/pos/ has it. For
# TLS 1.1 the client lowers its own security level, so that a refusal can only
# come from the gateway.
set -uo pipefail

HOST="${1:-localhost}"
PORT="${2:-9443}"
CLIENT=POS-DN1-01

# Git Bash on Windows would rewrite the -cipher and file arguments as paths.
export MSYS_NO_PATHCONV=1
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -s .certs/ca.crt ]; then
    echo "No .certs/ca.crt: run scripts/generate_dev_certs.sh first." >&2
    exit 1
fi
client_args=()
if [ -s ".certs/pos/$CLIENT.crt" ] && [ -s ".certs/pos/$CLIENT.key" ]; then
    client_args=(-cert ".certs/pos/$CLIENT.crt" -key ".certs/pos/$CLIENT.key")
fi

probe() {
    openssl s_client -connect "$HOST:$PORT" -servername "$HOST" -CAfile .certs/ca.crt \
        "${client_args[@]}" "$@" </dev/null 2>&1
}

cipher_of() {
    sed -n 's/^New, [^,]*, Cipher is //p' | head -n 1
}

failures=0

for version in 1.3 1.2; do
    output="$(probe "-tls${version/./_}")"
    cipher="$(printf '%s\n' "$output" | cipher_of)"
    if printf '%s\n' "$output" | grep -qE "^(New, TLSv$version,|    Protocol  : TLSv$version$)" \
            && [ -n "$cipher" ] && [ "$cipher" != "(NONE)" ] \
            && printf '%s\n' "$output" | grep -q "Verify return code: 0 (ok)"; then
        echo "PASS  TLS $version connects ($cipher, server certificate verified)"
    else
        echo "FAIL  TLS $version does not connect"
        printf '%s\n' "$output" | grep -E "error|errno|alert|Verify return code" | head -n 3 | sed 's/^/      /'
        failures=$((failures + 1))
    fi
done

output="$(probe -tls1_1 -cipher "DEFAULT@SECLEVEL=0")"
cipher="$(printf '%s\n' "$output" | cipher_of)"
if printf '%s\n' "$output" | grep -qE "no protocols available|unsupported protocol"; then
    echo "FAIL  TLS 1.1: this openssl cannot offer TLS 1.1, so the check is inconclusive"
    failures=$((failures + 1))
elif printf '%s\n' "$output" | grep -qE "connect:errno|connect error|Connection refused"; then
    echo "FAIL  TLS 1.1: cannot reach $HOST:$PORT"
    failures=$((failures + 1))
elif [ "$cipher" = "(NONE)" ]; then
    written="$(printf '%s\n' "$output" | sed -n 's/^SSL handshake has read \([0-9]*\) bytes and written \([0-9]*\) bytes$/read \1, wrote \2 bytes/p')"
    echo "PASS  TLS 1.1 is refused by the gateway (handshake $written)"
else
    echo "FAIL  TLS 1.1 connects ($cipher)"
    failures=$((failures + 1))
fi

if [ "$failures" -ne 0 ]; then
    echo "$failures check(s) failed on $HOST:$PORT"
    exit 1
fi
echo "All TLS checks passed on $HOST:$PORT"
