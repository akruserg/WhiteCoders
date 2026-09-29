"""Голосовой диалог: реплика оператора -> STT -> ИИ (arm_api) -> TTS -> playback.

conftest.rt дает VOICE_DIALOG_ENABLED=0 по умолчанию (как в проде), поэтому
здесь конфигурация включается точечно через monkeypatch на время теста.
"""

import json
import time

import httpx

from arm_voip import stt, tts
from arm_voip.calls import CallState
from arm_voip.config import Config


def new_state(rt, attempt="att", audio_name=None):
    ext = rt.pool.acquire(attempt)
    state = CallState(
        call_id=f"ch-{attempt}",
        attempt_id=attempt,
        extension=ext,
        leased=True,
        audio=audio_name,
        ring_deadline=time.monotonic() + 30,
    )
    rt.registry.add(state)
    return state


async def _answer(rt, state):
    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": state.call_id}}
    )


def _recording_event(kind, state, name):
    return {
        "type": kind,
        "recording": {"name": name, "target_uri": f"channel:{state.call_id}"},
    }


async def test_call_without_audio_starts_listening_when_dialog_enabled(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    state = new_state(rt)
    await _answer(rt, state)
    assert rt.ari.recorded == [(state.call_id, f"turn-{state.call_id}-0")]
    assert state.listening is True


async def test_listening_starts_after_intro_playback_finishes(
    rt, tmp_path, monkeypatch
):
    (tmp_path / "fire.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(Config, "AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    state = new_state(rt, audio_name="fire.wav")

    await _answer(rt, state)
    assert rt.ari.recorded == []  # интро еще играет, слушать рано

    await rt.supervisor.handle_event(
        {
            "type": "PlaybackFinished",
            "channel": {"id": state.call_id},
            "playback": {"id": state.playback_id},
        }
    )
    assert rt.ari.recorded == [(state.call_id, f"turn-{state.call_id}-0")]


async def test_unrelated_playback_finished_does_not_start_listening(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    state = new_state(rt)
    await _answer(rt, state)
    rt.ari.recorded.clear()  # уже начали слушать после ответа без интро

    await rt.supervisor.handle_event(
        {
            "type": "PlaybackFinished",
            "channel": {"id": state.call_id},
            "playback": {"id": "какой-то-чужой-id"},
        }
    )
    assert rt.ari.recorded == []


async def test_recording_finished_runs_full_turn(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    monkeypatch.setattr(stt, "transcribe", lambda path: "Пожар в квартире")
    monkeypatch.setattr(
        tts, "synthesize", lambda text, voice=None: "sound:arm112/reply"
    )

    def handler(request: httpx.Request):
        assert json.loads(request.content) == {"text": "Пожар в квартире"}
        return httpx.Response(200, json={"reply": "Адрес назовите, пожалуйста"})

    rt.supervisor._transport = httpx.MockTransport(handler)
    state = new_state(rt)
    await _answer(rt, state)
    rt.ari.recorded.clear()

    await rt.supervisor.handle_event(
        _recording_event("RecordingFinished", state, f"turn-{state.call_id}-0")
    )
    await _drain(rt)

    assert state.turn == 1
    assert rt.ari.played[-1] == (state.call_id, "sound:arm112/reply")


async def test_silence_retries_without_spending_a_turn(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    monkeypatch.setattr(stt, "transcribe", lambda path: None)
    state = new_state(rt)
    await _answer(rt, state)
    rt.ari.recorded.clear()

    await rt.supervisor.handle_event(
        _recording_event("RecordingFinished", state, f"turn-{state.call_id}-0")
    )
    await _drain(rt)

    assert state.turn == 0
    assert rt.ari.recorded == [(state.call_id, f"turn-{state.call_id}-0")]


async def test_recording_failed_retries_listening(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    state = new_state(rt)
    await _answer(rt, state)
    rt.ari.recorded.clear()

    await rt.supervisor.handle_event(
        _recording_event("RecordingFailed", state, f"turn-{state.call_id}-0")
    )
    assert rt.ari.recorded == [(state.call_id, f"turn-{state.call_id}-0")]


async def test_dialog_stops_after_max_turns(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    monkeypatch.setattr(Config, "VOICE_DIALOG_MAX_TURNS", 1)
    monkeypatch.setattr(stt, "transcribe", lambda path: "Пожар в квартире")
    monkeypatch.setattr(
        tts, "synthesize", lambda text, voice=None: "sound:arm112/reply"
    )
    rt.supervisor._transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"reply": "Хорошо"})
    )
    state = new_state(rt)
    await _answer(rt, state)
    rt.ari.recorded.clear()

    await rt.supervisor.handle_event(
        _recording_event("RecordingFinished", state, f"turn-{state.call_id}-0")
    )
    await _drain(rt)
    assert state.turn == 1

    # плейбек ответа доигрался - лимит уже исчерпан, новой записи не будет
    await rt.supervisor.handle_event(
        {
            "type": "PlaybackFinished",
            "channel": {"id": state.call_id},
            "playback": {"id": state.playback_id},
        }
    )
    assert rt.ari.recorded == []


async def test_voice_turn_ignored_for_unknown_channel(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOICE_DIALOG_ENABLED", True)
    await rt.supervisor.handle_event(
        {
            "type": "RecordingFinished",
            "recording": {"name": "x", "target_uri": "channel:foreign"},
        }
    )
    # не падает и никого не трогает


async def _drain(rt):
    """Ждет фоновые задачи, запущенные handle_event (_spawn)."""
    tasks = list(rt.supervisor._background)
    if tasks:
        import asyncio

        await asyncio.gather(*tasks, return_exceptions=True)
