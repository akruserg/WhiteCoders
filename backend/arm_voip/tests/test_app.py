from fastapi.testclient import TestClient

from arm_voip.app import app

HEADERS = {"X-Service-Token": "test-token"}


def post_call(client, attempt="att-1", **extra):
    return client.post("/calls", json={"attempt_id": attempt, **extra}, headers=HEADERS)


def test_token_is_required(rt):
    client = TestClient(app)
    assert client.post("/calls", json={"attempt_id": "a"}).status_code == 401
    bad = client.post(
        "/calls", json={"attempt_id": "a"}, headers={"X-Service-Token": "x"}
    )
    assert bad.status_code == 401


def test_start_call_returns_sip_credentials_and_uses_pool(rt):
    client = TestClient(app)
    response = post_call(client, audio="fire.wav", caller_number="+74950000001")
    assert response.status_code == 200
    body = response.json()
    assert body["destination"] == "2001"
    assert body["sip"]["extension"] == "2001"
    assert body["sip"]["password"]
    assert rt.ari.started[0] == ("att-1", "2001", "fire.wav", "+74950000001")


def test_same_attempt_reuses_active_call(rt):
    client = TestClient(app)
    first = post_call(client).json()
    second = post_call(client).json()
    assert first["call_id"] == second["call_id"]
    assert len(rt.ari.started) == 1


def test_parallel_attempts_get_different_numbers(rt):
    client = TestClient(app)
    numbers = {
        post_call(client, attempt=f"a{i}").json()["destination"] for i in range(3)
    }
    assert numbers == {"2001", "2002", "2003"}


def test_pool_exhaustion_is_503(rt):
    client = TestClient(app)
    for i in range(3):
        post_call(client, attempt=f"a{i}")
    assert post_call(client, attempt="extra").status_code == 503


def test_ari_failure_releases_the_number(rt):
    client = TestClient(app)
    rt.ari.fail_start = True
    assert post_call(client).status_code == 502
    assert rt.pool.stats()["busy"] == 0


def test_refuses_calls_while_events_are_down(rt):
    rt.supervisor.connected = False
    assert post_call(TestClient(app)).status_code == 503


def test_hangup_releases_number(rt):
    client = TestClient(app)
    call_id = post_call(client).json()["call_id"]
    response = client.delete(f"/calls/{call_id}", headers=HEADERS)
    assert response.status_code == 200
    assert rt.ari.hangups == [call_id]
    assert rt.pool.stats()["busy"] == 0
    assert (
        client.get(f"/calls/{call_id}", headers=HEADERS).json()["status"] == "no_answer"
    )


def test_explicit_destination_skips_pool_and_credentials(rt):
    client = TestClient(app)
    body = post_call(client, destination="1001").json()
    assert body["destination"] == "1001"
    assert body["sip"] is None
    assert rt.pool.stats()["busy"] == 0


def test_health_reflects_events_connection(rt):
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    rt.supervisor.connected = False
    assert client.get("/health").status_code == 503
