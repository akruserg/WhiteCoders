from datetime import datetime, timezone
from types import SimpleNamespace

from arm_api.core.security import audit_entry_hash, is_public_path


def test_public_paths():
    assert is_public_path("/api/v1/auth/login")
    assert is_public_path("/api/v1/openapi.json")
    assert is_public_path("/health") and is_public_path("/")
    assert is_public_path("/api/v1/internal/voip/events")
    assert not is_public_path("/api/v1/users")
    assert not is_public_path("/api/v1/auth/me")


def test_protected_route_needs_a_token(client):
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_cors_credentials_only_for_listed_origins(app):
    client = app.test_client()
    listed = client.get("/health", headers={"Origin": "http://localhost"})
    assert listed.headers["Access-Control-Allow-Origin"] == "http://localhost"
    assert listed.headers["Access-Control-Allow-Credentials"] == "true"
    assert (
        "Access-Control-Allow-Origin"
        not in client.get("/health", headers={"Origin": "http://evil.example"}).headers
    )


def entry(prev, action="session.start"):
    e = SimpleNamespace(
        ts=datetime(2026, 9, 21, 12, 0, 0, 123456, tzinfo=timezone.utc),
        user_id="u-1",
        action=action,
        object_type="session",
        object_id="s-1",
        prev_hash=prev,
    )
    e.entry_hash = audit_entry_hash(e)
    return e


def test_audit_hash_detects_changed_content_and_chain_position():
    first = entry(None)
    second = entry(first.entry_hash)
    assert audit_entry_hash(second) == second.entry_hash

    second.action = "session.finish"  # правка записи задним числом
    assert audit_entry_hash(second) != second.entry_hash

    other_zone = entry(first.entry_hash)
    other_zone.ts = other_zone.ts.astimezone(
        timezone(offset=__import__("datetime").timedelta(hours=3))
    )
    assert (
        audit_entry_hash(other_zone) == other_zone.entry_hash
    )  # часовой пояс не важен
