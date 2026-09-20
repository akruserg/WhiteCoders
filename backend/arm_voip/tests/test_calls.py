import asyncio
import json
import time

import httpx
import pytest
from websockets.asyncio.server import serve

from arm_voip import audio
from arm_voip.calls import CallState, Notifier
from arm_voip.config import Config


def new_state(rt, attempt="att", audio_name=None, ring=30):
    ext = rt.pool.acquire(attempt)
    state = CallState(
        call_id=f"ch-{attempt}",
        attempt_id=attempt,
        extension=ext,
        leased=True,
        audio=audio_name,
        ring_deadline=time.monotonic() + ring,
    )
    rt.registry.add(state)
    return state


def events(rt):
    return [e["event"] for e in rt.supervisor.notifier.events]


async def test_answer_plays_audio_and_notifies(rt, tmp_path, monkeypatch):
    (tmp_path / "fire.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(Config, "AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)  # без ffmpeg
    state = new_state(rt, audio_name="fire.wav")

    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": state.call_id}}
    )

    assert state.status == "answered"
    assert rt.ari.played == [(state.call_id, "sound:arm112/fire")]
    assert events(rt) == ["answered"]


async def test_call_without_audio_still_answers(rt):
    state = new_state(rt)
    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": state.call_id}}
    )
    assert state.status == "answered" and rt.ari.played == []


async def test_hangup_after_answer_finishes_and_releases_number(rt):
    state = new_state(rt)
    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": state.call_id}}
    )
    state.rtt_samples = [40.0, 60.0]
    await rt.supervisor.handle_event(
        {
            "type": "ChannelDestroyed",
            "channel": {"id": state.call_id},
            "cause_txt": "Normal Clearing",
        }
    )
    assert state.status == "finished"
    assert rt.pool.stats()["busy"] == 0
    last = rt.supervisor.notifier.events[-1]
    assert (
        last["event"] == "finished"
        and last["rtt_ms"] == 50.0
        and last["latency_ok"] is True
    )


async def test_destroy_without_answer_is_no_answer(rt):
    state = new_state(rt)
    await rt.supervisor.handle_event(
        {"type": "ChannelDestroyed", "channel": {"id": state.call_id}, "cause": 19}
    )
    assert state.status == "no_answer"
    assert events(rt) == ["no_answer"]


async def test_duplicate_destroy_notifies_once(rt):
    state = new_state(rt)
    event = {"type": "ChannelDestroyed", "channel": {"id": state.call_id}}
    await rt.supervisor.handle_event(event)
    await rt.supervisor.handle_event(event)
    assert events(rt) == ["no_answer"]


async def test_unknown_channel_is_ignored(rt):
    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": "foreign"}}
    )
    assert events(rt) == []


async def test_sweeper_closes_unanswered_call_when_channel_is_gone(rt):
    state = new_state(rt, ring=-10)
    rt.ari.alive = False
    await rt.supervisor.sweep()
    assert state.status == "no_answer"


async def test_sweeper_keeps_ringing_call_if_channel_alive(rt):
    state = new_state(rt, ring=-10)
    await rt.supervisor.sweep()
    assert state.status == "ringing"


async def test_sweeper_collects_rtt_and_flags_high_latency(rt):
    state = new_state(rt)
    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": state.call_id}}
    )
    rt.ari.rtt = 400.0  # односторонняя задержка ~200 мс, больше нормы 150
    await rt.supervisor.sweep()
    assert state.rtt_samples == [400.0]
    assert state.rtt_summary()["latency_ok"] is False


async def test_sweeper_hangs_up_overlong_call(rt, monkeypatch):
    monkeypatch.setattr(Config, "VOIP_MAX_CALL_SEC", 1)
    state = new_state(rt)
    await rt.supervisor.handle_event(
        {"type": "StasisStart", "channel": {"id": state.call_id}}
    )
    state.answered_at = time.time() - 5
    await rt.supervisor.sweep()
    assert state.status == "finished" and rt.ari.hangups == [state.call_id]


async def test_notifier_retries_then_succeeds(monkeypatch):
    attempts = []

    def handler(request: httpx.Request):
        attempts.append(request.headers["x-service-token"])
        return httpx.Response(500 if len(attempts) < 3 else 200)

    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    notifier = Notifier(transport=httpx.MockTransport(handler))
    assert await notifier.send({"event": "answered"}) is True
    assert attempts == ["test-token"] * 3


async def test_event_stream_over_websocket(rt):
    state = new_state(rt)

    async def server(socket):
        await socket.send(
            json.dumps({"type": "StasisStart", "channel": {"id": state.call_id}})
        )
        await asyncio.sleep(0.3)

    async with serve(server, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        original = Config.ARI_WS_URL
        Config.ARI_WS_URL = f"ws://127.0.0.1:{port}/ari/events"
        task = asyncio.create_task(rt.supervisor.run_events())
        try:
            for _ in range(50):
                if state.status == "answered":
                    break
                await asyncio.sleep(0.05)
            assert state.status == "answered"
            assert rt.supervisor.connected is True
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            Config.ARI_WS_URL = original


@pytest.mark.parametrize(
    "name", ["../etc/passwd", "a/b.wav", ".hidden.wav", "x y.wav", ""]
)
def test_audio_rejects_unsafe_names(name):
    assert audio.resolve_media(name) is None


def test_audio_missing_file_gives_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "AUDIO_DIR", str(tmp_path))
    assert audio.resolve_media("nothing.wav") is None
