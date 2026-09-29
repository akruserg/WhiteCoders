"""Резервное копирование и восстановление на разных СУБД.

PostgreSQL - pg_dump/pg_restore (основная СУБД), MySQL и MariaDB - mysqldump и
клиент mysql, SQLite - встроенный механизм backup. Адрес БД может содержать
несколько узлов PostgreSQL для отказоустойчивости:
    postgresql://user:pass@/db?host=node1,node2&port=5432,5432&target_session_attrs=read-write
"""

import os
import shutil
import sqlite3
import subprocess

from flask import current_app
from sqlalchemy.engine.url import make_url

TIMEOUT_SEC = 3600


def _url():
    return make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])


def dialect_name():
    return _url().get_backend_name()  # postgresql, mysql, mariadb, sqlite


def backup_extension():
    return {"postgresql": "dump", "sqlite": "sqlite3"}.get(dialect_name(), "sql")


def libpq_uri(url=None):
    """Адрес для pg_dump/pg_restore. Узлы кластера берутся из ?host=a,b&port=1,2."""
    url = url or _url()
    hosts = url.query.get("host") or url.host or "localhost"
    ports = url.query.get("port") or (str(url.port) if url.port else "5432")
    host_list = str(hosts).split(",")
    port_list = str(ports).split(",")
    if len(port_list) == 1:
        port_list = port_list * len(host_list)
    nodes = ",".join(f"{h}:{p}" for h, p in zip(host_list, port_list))
    user = f"{url.username}@" if url.username else ""
    attrs = url.query.get("target_session_attrs")
    tail = f"?target_session_attrs={attrs}" if attrs else ""
    return f"postgresql://{user}{nodes}/{url.database}{tail}"


def _run(command, env=None, stdin=None, stdout=None):
    completed = subprocess.run(
        command,
        check=False,
        capture_output=stdout is None,
        timeout=TIMEOUT_SEC,
        env=env,
        stdin=stdin,
        stdout=stdout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            detail or f"{command[0]} завершился с кодом {completed.returncode}"
        )


def _require(tool):
    if shutil.which(tool) is None:
        raise RuntimeError(f"{tool} недоступен в контейнере API")


def _mysql_args(url):
    args = ["--host", url.host or "localhost", "--port", str(url.port or 3306)]
    if url.username:
        args += ["--user", url.username]
    return args


def _env(url):
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
        env["MYSQL_PWD"] = url.password
    return env


def dump(file_path):
    url, name = _url(), dialect_name()
    if name == "postgresql":
        _require("pg_dump")
        _run(
            [
                "pg_dump",
                "--format=custom",
                "--file",
                file_path,
                "--dbname",
                libpq_uri(url),
            ],
            _env(url),
        )
    elif name in {"mysql", "mariadb"}:
        _require("mysqldump")
        with open(file_path, "wb") as handle:
            _run(
                [
                    "mysqldump",
                    *_mysql_args(url),
                    "--single-transaction",
                    "--routines",
                    url.database,
                ],
                _env(url),
                stdout=handle,
            )
    elif name == "sqlite":
        source = sqlite3.connect(url.database)
        try:
            target = sqlite3.connect(file_path)
            with target:
                source.backup(target)
            target.close()
        finally:
            source.close()
    else:
        raise RuntimeError(f"Резервное копирование для {name} не поддерживается")


def restore(file_path):
    url, name = _url(), dialect_name()
    if name == "postgresql":
        _require("pg_restore")
        _run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--dbname",
                libpq_uri(url),
                file_path,
            ],
            _env(url),
        )
    elif name in {"mysql", "mariadb"}:
        _require("mysql")
        with open(file_path, "rb") as handle:
            _run(["mysql", *_mysql_args(url), url.database], _env(url), stdin=handle)
    elif name == "sqlite":
        shutil.copyfile(file_path, url.database)
    else:
        raise RuntimeError(f"Восстановление для {name} не поддерживается")
