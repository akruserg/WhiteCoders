import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from arm_api.core import security
from arm_api.services import spool

ATTEMPT = str(uuid.uuid4())


@pytest.fixture
def spool_dir(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "SPOOL_DIR", str(tmp_path))
    return tmp_path


def token(app, perms=("attempt.submit",), expires=300, typ="access"):
    now = datetime.now(timezone.utc)
    claims = {
        "iss": app.config["JWT_ISSUER"],
        "sub": str(uuid.uuid4()),
        "typ": typ,
        "perms": list(perms),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires)).timestamp()),
    }
    return (
        jwt.encode(claims, app.config["SECRET_KEY"], algorithm="HS256"),
        claims["sub"],
    )


def down(exc_type=OperationalError):
    def fail(*args, **kwargs):
        raise exc_type("SELECT 1", {}, Exception("connection refused"))

    return fail


# ---------------------------------------------------------------- хранение


def test_enqueue_writes_a_durable_file_and_status_counts_it(app, spool_dir):
    with app.app_context():
        info = spool.enqueue(
            "submit", ATTEMPT, "u1", {"a": "б"}, [], {"ip": "10.0.0.1"}
        )
        files = spool.pending_files()
        assert len(files) == 1 and spool.status() == {"pending": 1, "failed": 0}
        saved = json.load(open(files[0], encoding="utf-8"))
    assert (
        saved["id"] == info["id"]
        and saved["answer"] == {"a": "б"}
        and saved["ip"] == "10.0.0.1"
    )
    assert not [
        f for f in os.listdir(spool_dir) if f.endswith(".tmp")
    ]  # временных файлов нет


def test_entries_keep_the_order_of_receipt(app, spool_dir):
    with app.app_context():
        ids = []
        for i in range(4):
            ids.append(spool.enqueue("draft", ATTEMPT, "u1", {"n": i}, [], {})["id"])
            time.sleep(0.003)
        order = [
            json.load(open(p, encoding="utf-8"))["id"] for p in spool.pending_files()
        ]
    assert order == ids


def test_buffer_has_a_size_limit(app, spool_dir, monkeypatch):
    monkeypatch.setitem(app.config, "SPOOL_MAX_FILES", 2)
    with app.app_context():
        spool.enqueue("draft", ATTEMPT, "u1", {}, [], {})
        spool.enqueue("draft", ATTEMPT, "u1", {}, [], {})
        with pytest.raises(spool.SpoolFull):
            spool.enqueue("draft", ATTEMPT, "u1", {}, [], {})


def test_unknown_kind_is_refused(app, spool_dir):
    with app.app_context(), pytest.raises(ValueError):
        spool.enqueue("delete_everything", ATTEMPT, "u1", {}, [], {})


def test_only_connection_failures_count_as_outage():
    assert spool.is_db_outage(OperationalError("s", {}, Exception("x")))
    invalid = DBAPIError("s", {}, Exception("x"), connection_invalidated=True)
    assert spool.is_db_outage(invalid)
    assert not spool.is_db_outage(DBAPIError("s", {}, Exception("x")))
    assert not spool.is_db_outage(ValueError("x"))


# ---------------------------------------------------------------- прием при отказе БД


def test_answers_are_buffered_with_202_when_the_database_is_down(
    app, client, spool_dir, monkeypatch
):
    monkeypatch.setattr(security, "current_user", down())
    bearer, user = token(app)
    payload = {"answer": {"address_street": "Мира"}, "actions": [{"type": "save_card"}]}
    for method, path, kind in [("post", "submit", "submit"), ("put", "draft", "draft")]:
        response = getattr(client, method)(
            f"/api/v1/attempts/{ATTEMPT}/{path}",
            json=payload,
            headers={"Authorization": f"Bearer {bearer}"},
        )
        assert response.status_code == 202, response.get_json()
        body = response.get_json()
        assert (
            body["status"] == "buffered"
            and body["kind"] == kind
            and body["attempt_id"] == ATTEMPT
        )
        assert response.headers["Retry-After"] == str(
            app.config["SPOOL_RETRY_AFTER_SEC"]
        )
    with app.app_context():
        entries = [json.load(open(p, encoding="utf-8")) for p in spool.pending_files()]
    assert {e["kind"] for e in entries} == {"submit", "draft"} and {
        e["user_id"] for e in entries
    } == {user}
    assert entries[0]["answer"] == payload["answer"]


def test_buffering_checks_the_token_and_the_body_without_the_database(
    app, client, spool_dir, monkeypatch
):
    monkeypatch.setattr(security, "current_user", down())
    url = f"/api/v1/attempts/{ATTEMPT}/submit"
    assert client.post(url, json={"answer": {}}).status_code == 401
    assert (
        client.post(
            url, json={"answer": {}}, headers={"Authorization": "Bearer nonsense"}
        ).status_code
        == 401
    )
    forged, _ = token(app)
    forged = forged[:-3] + "abc"
    assert (
        client.post(
            url, json={"answer": {}}, headers={"Authorization": f"Bearer {forged}"}
        ).status_code
        == 401
    )
    weak, _ = token(app, perms=("scenario.read",))
    assert (
        client.post(
            url, json={"answer": {}}, headers={"Authorization": f"Bearer {weak}"}
        ).status_code
        == 403
    )
    ok_token, _ = token(app)
    bad = client.post(
        url, json={"actions": []}, headers={"Authorization": f"Bearer {ok_token}"}
    )
    assert bad.status_code == 422 and "answer" in bad.get_json()["error"]["details"]
    with app.app_context():
        assert spool.status()["pending"] == 0  # ничего лишнего в буфер не попало


def test_other_requests_get_503_with_retry_after_instead_of_500(
    app, client, spool_dir, monkeypatch
):
    monkeypatch.setattr(security, "current_user", down())
    bearer, _ = token(app)
    response = client.get(
        "/api/v1/sessions", headers={"Authorization": f"Bearer {bearer}"}
    )
    assert (
        response.status_code == 503
        and response.get_json()["error"]["code"] == "db_unavailable"
    )
    assert "Retry-After" in response.headers


def test_a_full_buffer_answers_503_so_the_client_keeps_its_data(
    app, client, spool_dir, monkeypatch
):
    monkeypatch.setattr(security, "current_user", down())
    monkeypatch.setitem(app.config, "SPOOL_MAX_FILES", 0)
    bearer, _ = token(app)
    response = client.post(
        f"/api/v1/attempts/{ATTEMPT}/submit",
        json={"answer": {}},
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert response.status_code == 503


def test_xml_answers_are_buffered_too(app, client, spool_dir, monkeypatch):
    monkeypatch.setattr(security, "current_user", down())
    bearer, _ = token(app)
    xml = "<request><answer><address_street>Мира</address_street></answer></request>"
    response = client.post(
        f"/api/v1/attempts/{ATTEMPT}/submit",
        data=xml,
        content_type="application/xml",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert response.status_code == 202
    with app.app_context():
        entry = json.load(open(spool.pending_files()[0], encoding="utf-8"))
    assert entry["answer"] == {"address_street": "Мира"}
