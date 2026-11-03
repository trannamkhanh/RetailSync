#!/usr/bin/env bash
# Write a self-signed development certificate to .certs/. Safe to run again:
# a valid certificate is kept. Set RENEW=1 to replace it.
set -euo pipefail

KEY="server.key"
CERT="server.crt"
SUBJECT_ALT_NAME="DNS:localhost,IP:127.0.0.1,DNS:middleware.retailsync.local"
DAYS=825
ONE_DAY=86400

# Git Bash on Windows would rewrite the /CN= subject as a file path, which is
# also why every path below is relative.
export MSYS_NO_PATHCONV=1

is_usable() {
    [ -s "$KEY" ] && [ -s "$CERT" ] || return 1
    openssl x509 -in "$CERT" -noout -checkend "$ONE_DAY" >/dev/null || return 1
    local key_id cert_id
    key_id="$(openssl pkey -in "$KEY" -pubout | openssl sha256)"
    cert_id="$(openssl x509 -in "$CERT" -noout -pubkey | openssl sha256)"
    [ "$key_id" = "$cert_id" ]
}

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p .certs
cd .certs

if [ "${RENEW:-0}" != "1" ] && is_usable; then
    echo "Keeping the existing certificate in .certs/"
    exit 0
fi

umask 077
temp_dir="$(mktemp -d tmp.XXXXXX)"
trap 'rm -rf "$temp_dir"' EXIT

openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days "$DAYS" \
    -subj "/CN=localhost" \
    -addext "subjectAltName=$SUBJECT_ALT_NAME" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    -keyout "$temp_dir/$KEY" -out "$temp_dir/$CERT" 2>"$temp_dir/errors" \
    || { cat "$temp_dir/errors" >&2; exit 1; }

mv "$temp_dir/$KEY" "$KEY"
mv "$temp_dir/$CERT" "$CERT"
echo "Wrote .certs/$KEY and .certs/$CERT"
