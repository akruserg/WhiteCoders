import httpx
import pytest

from arm_api.services import integrations


@pytest.fixture
def ctx(app, monkeypatch):
    monkeypatch.setattr(integrations, "voip_available", lambda: True)
    with app.app_context():
        yield


def voip_client(monkeypatch, handler):
    monkeypatch.setattr(
        integrations,
        "_client",
        lambda: httpx.Client(
            base_url="http://voip.test", transport=httpx.MockTransport(handler)
        ),
    )


def test_text_channel_never_calls_voip(ctx, monkeypatch):
    voip_client(monkeypatch, lambda r: pytest.fail("не должно быть запроса"))
    info = integrations.start_call("att-1", "text")
    assert info["channel"] == "text" and info["degraded"] is False


def test_voip_call_passes_audio_and_returns_sip_credentials(ctx, monkeypatch):
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.read() and __import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "call_id": "chan1",
                "ring_timeout_sec": 30,
                "sip": {"extension": "2001", "password": "p", "ws_url": "ws://pbx/ws"},
            },
        )

    voip_client(monkeypatch, handler)
    info = integrations.start_call("att-1", "voip", "student1", audio="fire.wav")
    assert seen["audio"] == "fire.wav" and seen["attempt_id"] == "att-1"
    assert seen["caller_number"] == info["caller_number"]
    assert info["channel"] == "voip" and info["sip_call_id"] == "chan1"
    assert info["sip"]["extension"] == "2001"
    assert (
        info["sip_server"] == "ws://pbx/ws"
    )  # адрес для браузера, а не внутренний URL


@pytest.mark.parametrize("status", [502, 503])
def test_voip_failure_degrades_to_text(ctx, monkeypatch, status):
    voip_client(monkeypatch, lambda r: httpx.Response(status, text="busy"))
    info = integrations.start_call("att-1", "voip")
    assert (
        info["channel"] == "text" and info["degraded"] is True and info["sip"] is None
    )


def test_voip_unreachable_degrades_to_text(ctx, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")

    voip_client(monkeypatch, handler)
    assert integrations.start_call("att-1", "voip")["degraded"] is True


def test_hangup_survives_voip_errors(ctx, monkeypatch):
    voip_client(monkeypatch, lambda r: httpx.Response(500))
    assert integrations.hangup("chan1")["status"] == "finished"


def test_caller_reply_starts_with_first_followup():
    legend = {"dialog": ["Пожар!"], "followups": ["Пятый этаж", "Есть ребенок"]}
    assert integrations.caller_reply(legend, "Адрес?", 0) == "Пятый этаж"
    assert integrations.caller_reply(legend, "Кто в квартире?", 1) == "Есть ребенок"


def test_internal_endpoint_rejects_bad_or_missing_token(client):
    url = "/api/v1/internal/voip/events"
    payload = {"event": "answered", "call_id": "c1"}
    assert client.post(url, json=payload).status_code == 401
    assert (
        client.post(url, json=payload, headers={"X-Service-Token": "nope"}).status_code
        == 401
    )
