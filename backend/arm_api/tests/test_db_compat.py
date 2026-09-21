import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.engine.url import make_url

from arm_api.models.mixins import UTCDateTime
from arm_api.services import dbtools

PG = SimpleNamespace(name="postgresql")
SQLITE = SimpleNamespace(name="sqlite")
MSK = timezone(timedelta(hours=3))


def test_datetime_is_stored_in_utc_and_always_read_back_aware():
    kind = UTCDateTime()
    moment = datetime(2026, 9, 21, 12, 0, tzinfo=MSK)
    assert kind.process_bind_param(moment, PG) == datetime(
        2026, 9, 21, 9, 0, tzinfo=timezone.utc
    )
    assert kind.process_bind_param(moment, SQLITE) == datetime(
        2026, 9, 21, 9, 0
    )  # без пояса
    naive_from_db = datetime(2026, 9, 21, 9, 0)
    assert kind.process_result_value(naive_from_db, SQLITE) == datetime(
        2026, 9, 21, 9, 0, tzinfo=timezone.utc
    )
    assert kind.process_result_value(moment, PG) == datetime(
        2026, 9, 21, 9, 0, tzinfo=timezone.utc
    )
    assert (
        kind.process_bind_param(None, PG) is None
        and kind.process_result_value(None, PG) is None
    )


def test_naive_datetime_is_treated_as_utc():
    assert UTCDateTime().process_bind_param(
        datetime(2026, 1, 1, 5), PG
    ).utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("postgresql://u:p@db1:5433/arm", "postgresql://u@db1:5433/arm"),
        (
            "postgresql://u@/arm?host=a,b&port=5432,5433",
            "postgresql://u@a:5432,b:5433/arm",
        ),
        (
            "postgresql://u@/arm?host=a,b&port=5432&target_session_attrs=read-write",
            "postgresql://u@a:5432,b:5432/arm?target_session_attrs=read-write",
        ),
    ],
)
def test_libpq_uri_supports_cluster_nodes(url, expected):
    assert dbtools.libpq_uri(make_url(url)) == expected


def test_sqlite_dump_and_restore_roundtrip(app, tmp_path, monkeypatch):
    db_file = tmp_path / "live.db"
    conn = sqlite3.connect(db_file)
    conn.execute("create table t(x text)")
    conn.execute("insert into t values ('до бэкапа')")
    conn.commit()
    conn.close()
    monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_file}")
    with app.app_context():
        assert (
            dbtools.dialect_name() == "sqlite"
            and dbtools.backup_extension() == "sqlite3"
        )
        copy = tmp_path / "copy.sqlite3"
        dbtools.dump(str(copy))
        conn = sqlite3.connect(db_file)
        conn.execute("delete from t")
        conn.commit()
        conn.close()
        dbtools.restore(str(copy))
    assert sqlite3.connect(db_file).execute("select x from t").fetchall() == [
        ("до бэкапа",)
    ]


def test_unsupported_dialect_is_reported(app, monkeypatch):
    monkeypatch.setitem(
        app.config, "SQLALCHEMY_DATABASE_URI", "oracle+oracledb://u:p@h/db"
    )
    with app.app_context(), pytest.raises(RuntimeError, match="не поддерживается"):
        dbtools.dump("/tmp/x")


def test_mysql_tools_missing_gives_clear_error(app, monkeypatch):
    monkeypatch.setitem(
        app.config, "SQLALCHEMY_DATABASE_URI", "mysql+pymysql://u:p@h/db"
    )
    monkeypatch.setattr(dbtools.shutil, "which", lambda name: None)
    with app.app_context(), pytest.raises(RuntimeError, match="mysqldump недоступен"):
        dbtools.dump("/tmp/x")


def test_uuid_defaults_are_generated_in_python_not_by_the_database():
    from arm_api.models import User

    assert (
        User.__table__.c.id.default is not None
        and User.__table__.c.id.server_default is None
    )
