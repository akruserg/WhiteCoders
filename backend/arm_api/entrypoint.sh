#!/bin/sh
# Точка входа узла API. Каждый узел кластера запускается одним и тем же образом,
# роли переключаются переменными (все по умолчанию включены):
#   RUN_INIT=0       не выполнять миграции и начальные данные (см. cluster init)
#   RUN_SCHEDULER=0  не запускать ежедневные задания (на кластере их выполняет один узел)
#   RUN_SPOOL=0      не запускать службу буфера
set -e

export FLASK_APP="arm_api.app:app"

if [ "${RUN_INIT:-1}" = "1" ]; then
    echo "* entrypoint [arm_api] - миграции БД и начальные данные (один раз на кластер)"
    if [ "${SEED_DEMO:-0}" = "1" ]; then
        python -m arm_api.services.cluster init --demo
    else
        python -m arm_api.services.cluster init
    fi
fi

if [ "${RUN_SPOOL:-1}" = "1" ]; then
    echo "* entrypoint [arm_api] - служба буфера (повторная обработка ответов после сбоя БД)"
    python -m arm_api.services.spool run &
fi

if [ "${RUN_SCHEDULER:-1}" = "1" ]; then
    echo "* entrypoint [arm_api] - ежедневный бэкап и очистка журнала (лидер выбирается через БД)"
    python -c "from arm_api.services.backup import run_loop; run_loop()" &
fi

# параметры производительности, измененные администратором через /system/settings
eval "$(python -m arm_api.services.settings perf-env 2>/dev/null || true)"

echo "* entrypoint [arm_api] - запускаем gunicorn (узел ${NODE_ID:-$(hostname)})"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "${GUNICORN_WORKERS:-4}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    --graceful-timeout 30 \
    arm_api.app:app
