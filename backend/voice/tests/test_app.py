import os

os.environ.setdefault("VOICE_SERVICE_TOKEN", "test-token")
os.environ.setdefault("VOICE_WARM_UP", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from voice import app as app_module  # noqa: E402
from voice import stt, tts  # noqa: E402

TOKEN = {"X-Service-Token": "test-token"}


@pytest.fixture
def client():
    with TestClient(app_module.app) as c:
        yield c


def test_tts_requires_token(client):
    r = client.post("/tts", json={"text": "привет"})
    assert r.status_code == 401


def test_tts_returns_wav(client, monkeypatch):
    monkeypatch.setattr(tts, "synthesize", lambda text, voice=None: b"RIFF....WAVE")
    r = client.post("/tts", json={"text": "привет"}, headers=TOKEN)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == b"RIFF....WAVE"


def test_tts_bad_request_is_422(client, monkeypatch):
    def boom(text, voice=None):
        raise tts.TtsError("голос не найден")

    monkeypatch.setattr(tts, "synthesize", boom)
    r = client.post("/tts", json={"text": "привет"}, headers=TOKEN)
    assert r.status_code == 422


def test_stt_returns_text(client, monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "transcribe", lambda path: "сообщение принято")
    f = tmp_path / "a.wav"
    f.write_bytes(b"\x00\x00")
    with open(f, "rb") as fh:
        r = client.post(
            "/stt", files={"audio": ("a.wav", fh, "audio/wav")}, headers=TOKEN
        )
    assert r.status_code == 200
    assert r.json() == {"text": "сообщение принято"}


def test_health_lists_voices(client, monkeypatch):
    monkeypatch.setattr(tts, "available_voices", lambda: ["ru_RU-irina-medium"])
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["tts_voices"] == ["ru_RU-irina-medium"]
