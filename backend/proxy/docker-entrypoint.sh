#!/bin/sh
# Если своего сертификата в /certs нет, создаем самоподписанный (для стенда).
set -eu

CERT_DIR=/certs
HOST="${TLS_HOST:-localhost}"
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/server.crt" ] || [ ! -f "$CERT_DIR/server.key" ]; then
    echo "[proxy] создаем самоподписанный сертификат для $HOST"
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
        -keyout "$CERT_DIR/server.key" -out "$CERT_DIR/server.crt" \
        -subj "/CN=$HOST" \
        -addext "subjectAltName=DNS:$HOST,DNS:localhost,IP:127.0.0.1"
fi
