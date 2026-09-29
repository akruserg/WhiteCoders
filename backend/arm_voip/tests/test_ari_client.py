import httpx
import pytest

from arm_voip.ari_client import AriClient, AriError


def make(handler):
    return AriClient(
        base_url="http://ari.test/ari",
        username="u",
        password="p",
        transport=httpx.MockTransport(handler),
    )


def test_start_call_originates_into_stasis_and_subscribes():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={})

    handle = make(handler).start_call(
        attempt_id="att-1",
        destination="2001",
        audio="fire.wav",
        caller_number="+74951234567",
    )
    method, path, params = seen[0]
    assert (method, path) == ("POST", "/ari/channels")
    assert params["endpoint"] == "PJSIP/2001"
    assert params["app"] == "arm_voip"
    assert params["appArgs"] == "att-1,fire.wav"
    assert params["channelId"] == handle.channel_id
    assert params["callerId"] == "+74951234567"
    assert seen[1][1] == "/ari/applications/arm_voip/subscription"


def test_start_call_error_is_ari_error():
    client = make(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(AriError):
        client.start_call(attempt_id="a", destination="2001")


def test_hangup_treats_404_as_finished():
    client = make(lambda request: httpx.Response(404))
    assert client.hangup("abc")["status"] == "finished"


def test_connection_error_is_wrapped():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(AriError):
        make(handler).hangup("abc")


def test_rtt_is_converted_to_milliseconds():
    client = make(lambda r: httpx.Response(200, json={"value": "0.0421"}))
    assert client.rtt_ms("abc") == 42.1
    empty = make(lambda r: httpx.Response(200, json={"value": ""}))
    assert empty.rtt_ms("abc") is None


def test_ping_reports_unavailable():
    assert make(lambda r: httpx.Response(503)).ping()["available"] is False
    ok = make(lambda r: httpx.Response(200, json={"system": {"version": "22.0"}}))
    assert ok.ping() == {"available": True, "version": "22.0"}
