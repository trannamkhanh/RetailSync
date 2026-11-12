#!/usr/bin/env bash
# Write the development certificates to .certs/ (PB-02-1, PB-48-5):
#   ca.key, ca.crt              development CA
#   server.key, server.crt      middleware and POS gateway, issued by the CA
#   pos/<pos_id>.key, .crt      one client certificate per seeded terminal
# Safe to run again: a valid certificate is kept. A server certificate the CA
# did not issue, such as the self-signed one from PB-02-1, is replaced once.
# Set RENEW=1 to replace everything. A new client certificate has a new
# fingerprint: register it again with scripts/register_pos_certificates.py.
set -euo pipefail

SERVER_NAMES="DNS:localhost,IP:127.0.0.1,DNS:middleware.retailsync.local,DNS:middleware,DNS:hq-demo,DNS:pos-gateway"
if [ -n "${EXTRA_SANS:-}" ]; then
    SERVER_NAMES="$SERVER_NAMES,$EXTRA_SANS"
fi
# The terminals of database/seed/001_demo_stores_pos.sql.
TERMINALS="POS-DN1-01 POS-DN1-02 POS-DN2-01 POS-DN2-02 POS-DN3-01 POS-DN3-02"
CA_DAYS=3650
DAYS=825
ONE_DAY=86400
RENEW="${RENEW:-0}"

# Git Bash on Windows would rewrite the /CN= subject as a file path, which is
# also why every path below is relative.
export MSYS_NO_PATHCONV=1

public_key_id() {
    openssl "$1" -in "$2" -noout -pubkey 2>/dev/null | openssl sha256
}

# is_usable KEY CERT: both exist, the key matches, the certificate lasts at
# least another day and the CA issued it.
is_usable() {
    [ -s "$1" ] && [ -s "$2" ] || return 1
    openssl x509 -in "$2" -noout -checkend "$ONE_DAY" >/dev/null 2>&1 || return 1
    [ "$(openssl pkey -in "$1" -pubout 2>/dev/null | openssl sha256)" = "$(public_key_id x509 "$2")" ] || return 1
    openssl verify -CAfile ca.crt "$2" >/dev/null 2>&1
}

has_server_names() {
    local names
    names="$(openssl x509 -in server.crt -noout -ext subjectAltName 2>/dev/null | tail -n +2 \
        | tr -d ' ' | sed 's/IPAddress:/IP:/g')"
    [ "$names" = "$SERVER_NAMES" ]
}

has_common_name() {
    [ "$(openssl x509 -in "$1" -noout -subject -nameopt RFC2253 2>/dev/null)" = "subject=CN=$2" ]
}

fail() {
    cat "$temp_dir/errors" >&2
    exit 1
}

issue_ca() {
    openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days "$CA_DAYS" \
        -subj "/CN=RetailSync Development CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -keyout "$temp_dir/ca.key" -out "$temp_dir/ca.crt" 2>"$temp_dir/errors" || fail
    mv "$temp_dir/ca.key" ca.key
    mv "$temp_dir/ca.crt" ca.crt
}

# issue NAME SUBJECT EXTENSIONS: write NAME.key and NAME.crt, signed by the CA.
issue() {
    openssl req -new -newkey rsa:2048 -nodes -sha256 -subj "$2" \
        -keyout "$temp_dir/new.key" -out "$temp_dir/new.csr" 2>"$temp_dir/errors" || fail
    printf '%b\n' "$3" > "$temp_dir/extensions.cnf"
    openssl x509 -req -sha256 -days "$DAYS" -in "$temp_dir/new.csr" -CA ca.crt -CAkey ca.key \
        -set_serial "0x$(openssl rand -hex 16)" -extfile "$temp_dir/extensions.cnf" \
        -out "$temp_dir/new.crt" 2>"$temp_dir/errors" || fail
    mv "$temp_dir/new.key" "$1.key"
    mv "$temp_dir/new.crt" "$1.crt"
}

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p .certs/pos
cd .certs

umask 077
temp_dir="$(mktemp -d tmp.XXXXXX)"
trap 'rm -rf "$temp_dir"' EXIT

if [ "$RENEW" = "1" ] || ! is_usable ca.key ca.crt; then
    issue_ca
    echo "Wrote .certs/ca.key and .certs/ca.crt"
else
    echo "Keeping .certs/ca.crt"
fi

if [ "$RENEW" = "1" ] || ! is_usable server.key server.crt || ! has_server_names; then
    issue server "/CN=localhost" "basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$SERVER_NAMES"
    echo "Wrote .certs/server.key and .certs/server.crt"
else
    echo "Keeping .certs/server.crt"
fi

issued=""
for pos_id in $TERMINALS; do
    if [ "$RENEW" = "1" ] || ! is_usable "pos/$pos_id.key" "pos/$pos_id.crt" \
            || ! has_common_name "pos/$pos_id.crt" "$pos_id"; then
        issue "pos/$pos_id" "/CN=$pos_id" "basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth"
        issued="$issued $pos_id"
    fi
done

if [ -n "$issued" ]; then
    echo "Wrote client certificates in .certs/pos/ for:$issued"
    echo "Register their fingerprints: see 'POS gateway' in README.md."
else
    echo "Keeping the client certificates in .certs/pos/"
fi
