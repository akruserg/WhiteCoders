from arm_voip.pool import sip_password
from arm_voip.sipconf import render_operators, write_operators


def test_render_contains_endpoint_auth_and_aor_for_each_extension():
    text = render_operators(["2001", "2002"], "secret", "arm112", "webrtc")
    for ext in ("2001", "2002"):
        assert f"[{ext}]\ntype=endpoint" in text
        assert f"[{ext}-auth]" in text
        assert f"password={sip_password('secret', ext)}" in text
    assert text.count("type=aor") == 2
    assert "webrtc=yes" in text


def test_sip_mode_has_no_webrtc():
    text = render_operators(["2001"], "secret", "arm112", "sip")
    assert "webrtc" not in text
    assert "transport-udp" in text


def test_write_is_atomic_and_reports_changes(tmp_path):
    path = str(tmp_path / "gen" / "pjsip_operators.conf")
    assert write_operators(path, "a") is True
    assert write_operators(path, "a") is False
    assert write_operators(path, "b") is True
    assert open(path).read() == "b"
