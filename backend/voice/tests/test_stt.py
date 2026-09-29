import os

os.environ.setdefault("VOICE_SERVICE_TOKEN", "test-token")

from voice import stt  # noqa: E402


class Segment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return [Segment(s) for s in self.segments], object()


def test_transcribe_joins_segments(monkeypatch):
    fake = FakeModel([" Пожар ", "в квартире."])
    monkeypatch.setattr(stt, "_load", lambda: fake)
    assert stt.transcribe("/tmp/x.wav") == "Пожар в квартире."


def test_transcribe_empty_on_silence(monkeypatch):
    fake = FakeModel([])
    monkeypatch.setattr(stt, "_load", lambda: fake)
    assert stt.transcribe("/tmp/silence.wav") == ""


def test_transcribe_wraps_errors(monkeypatch):
    class Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr(stt, "_load", lambda: Boom())
    try:
        stt.transcribe("/tmp/x.wav")
    except stt.SttError:
        pass
    else:
        raise AssertionError("SttError expected")
