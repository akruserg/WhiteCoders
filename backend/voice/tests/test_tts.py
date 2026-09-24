import os

os.environ.setdefault("VOICE_SERVICE_TOKEN", "test-token")

import pytest  # noqa: E402

from voice import tts  # noqa: E402


class FakeVoice:
    def __init__(self):
        self.calls = []

    def synthesize_wav(self, text, wav_file):
        self.calls.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 10)


@pytest.fixture(autouse=True)
def _clear_cache():
    tts._voices.clear()
    yield
    tts._voices.clear()


def test_synthesize_returns_wav_bytes(monkeypatch, tmp_path):
    (tmp_path / "ru_RU-irina-medium.onnx").write_bytes(b"stub")
    monkeypatch.setattr(tts.Config, "TTS_VOICES_DIR", str(tmp_path))
    fake = FakeVoice()
    monkeypatch.setattr(
        "piper.PiperVoice.load", staticmethod(lambda path: fake), raising=False
    )
    import sys
    import types

    piper_stub = types.SimpleNamespace(PiperVoice=types.SimpleNamespace(load=lambda p: fake))
    monkeypatch.setitem(sys.modules, "piper", piper_stub)

    audio = tts.synthesize("Пожар в квартире", "ru_RU-irina-medium")
    assert audio[:4] == b"RIFF"
    assert fake.calls == ["Пожар в квартире"]


def test_synthesize_empty_text_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(tts.Config, "TTS_VOICES_DIR", str(tmp_path))
    with pytest.raises(tts.TtsError):
        tts.synthesize("   ")


def test_synthesize_missing_voice_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.Config, "TTS_VOICES_DIR", str(tmp_path))
    with pytest.raises(tts.TtsError):
        tts.synthesize("текст", "no-such-voice")


def test_synthesize_rejects_unsafe_voice_name(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.Config, "TTS_VOICES_DIR", str(tmp_path))
    with pytest.raises(tts.TtsError):
        tts.synthesize("текст", "../../etc/passwd")


def test_available_voices_lists_onnx_files(tmp_path, monkeypatch):
    (tmp_path / "ru_RU-denis-medium.onnx").write_bytes(b"stub")
    (tmp_path / "ru_RU-denis-medium.onnx.json").write_text("{}")
    (tmp_path / "ru_RU-irina-medium.onnx").write_bytes(b"stub")
    monkeypatch.setattr(tts.Config, "TTS_VOICES_DIR", str(tmp_path))
    assert tts.available_voices() == ["ru_RU-denis-medium", "ru_RU-irina-medium"]
