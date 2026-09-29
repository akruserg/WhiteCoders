#!/bin/sh
# Готовит конфиг Asterisk из шаблонов и запускает его в foreground.
set -eu

if [ -z "${ARI_PASSWORD:-}" ]; then
    echo "[asterisk] ARI_PASSWORD не задан, запуск невозможен" >&2
    exit 1
fi

# экранируем символы, которые sed воспринимает в замене особым образом
escaped=$(printf '%s' "$ARI_PASSWORD" | sed -e 's/[\\/&|]/\\&/g')
sed "s|\${ARI_PASSWORD}|${escaped}|g" /etc/asterisk/ari.conf.template > /etc/asterisk/ari.conf
chmod 640 /etc/asterisk/ari.conf

mkdir -p /etc/asterisk/generated

echo "[asterisk] конфигурация готова, запускаем"
exec asterisk -f -vvv
