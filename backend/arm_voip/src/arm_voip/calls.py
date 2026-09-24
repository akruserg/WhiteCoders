import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect

from . import stt, tts
from .ari_client import AriClient, AriError
from .audio import resolve_media
from .config import Config
from .pool import OperatorPool

logger = logging.getLogger(__name__)

ACTIVE = {"ringing", "answered"}
KEEP_FINISHED_SEC = 600
SWEEP_INTERVAL_SEC = 2.0


@dataclass
class CallState:
    call_id: str
    attempt_id: str
    extension: str
    leased: bool
    audio: str | None
    ring_deadline: float
    status: str = "ringing"
    started_at: float = field(default_factory=time.time)
    answered_at: float | None = None
    finished_at: float | None = None
    hangup_cause: str | None = None
    playback_id: str | None = None
    rtt_samples: list[float] = field(default_factory=list)
    last_rtt_poll: float = 0.0
    turn: int = 0
    listening: bool = False

    def rtt_summary(self) -> dict:
        if not self.rtt_samples:
            return {"rtt_ms": None, "rtt_max_ms": None, "latency_ok": None}
        average = sum(self.rtt_samples) / len(self.rtt_samples)
        peak = max(self.rtt_samples)
        # односторонняя задержка приблизительно равна половине RTT
        return {
            "rtt_ms": round(average, 1),
            "rtt_max_ms": round(peak, 1),
            "latency_ok": peak / 2 <= Config.VOIP_MAX_LATENCY_MS,
        }

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "attempt_id": self.attempt_id,
            "extension": self.extension,
            "status": self.status,
            "audio": self.audio,
            "started_at": self.started_at,
            "answered_at": self.answered_at,
            "finished_at": self.finished_at,
            "hangup_cause": self.hangup_cause,
            "voice_turns": self.turn,
            **self.rtt_summary(),
        }


class CallRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, CallState] = {}

    def add(self, state: CallState) -> None:
        with self._lock:
            self._calls[state.call_id] = state

    def get(self, call_id: str) -> CallState | None:
        with self._lock:
            return self._calls.get(call_id)

    def find_active(self, attempt_id: str) -> CallState | None:
        with self._lock:
            for state in self._calls.values():
                if state.attempt_id == attempt_id and state.status in ACTIVE:
                    return state
        return None

    def active(self) -> list[CallState]:
        with self._lock:
            return [s for s in self._calls.values() if s.status in ACTIVE]

    def prune(self) -> None:
        limit = time.time() - KEEP_FINISHED_SEC
        with self._lock:
            for call_id in [
                c for c, s in self._calls.items()
                if s.finished_at and s.finished_at < limit
            ]:  # fmt: skip
                del self._calls[call_id]


class Notifier:
    """Сообщает arm_api о ходе звонка: ответ, завершение, неответ."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def send(self, payload: dict) -> bool:
        url = f"{Config.ARM_API_URL}/internal/voip/events"
        headers = {"X-Service-Token": Config.SERVICE_TOKEN}
        delay = 0.5
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(
                    timeout=Config.ARM_API_TIMEOUT_SEC, transport=self._transport
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code < 400:
                    return True
                logger.warning(
                    "arm_api ответил %s на %s", response.status_code, payload["event"]
                )
            except httpx.HTTPError as exc:
                logger.warning("arm_api недоступен (попытка %s): %s", attempt, exc)
            await asyncio.sleep(delay)
            delay *= 2
        return False


class CallSupervisor:
    """Слушает события Asterisk и ведет звонки: звук, задержка, завершение."""

    def __init__(
        self,
        ari: AriClient,
        registry: CallRegistry,
        pool: OperatorPool,
        notifier: Notifier,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.ari = ari
        self.registry = registry
        self.pool = pool
        self.notifier = notifier
        self.connected = False
        self._transport = transport
        self._background: set[asyncio.Task] = set()

    def _spawn(self, coro) -> None:
        """Фоновая задача (обработка реплики): не блокирует цикл событий ARI
        и не теряется в GC, пока выполняется."""
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # -- события ARI ---------------------------------------------------------

    async def handle_event(self, event: dict) -> None:
        kind = event.get("type")

        if kind in {"RecordingFinished", "RecordingFailed"}:
            await self._on_recording(kind, event.get("recording") or {})
            return

        channel_id = (event.get("channel") or {}).get("id")
        state = self.registry.get(channel_id) if channel_id else None
        if state is None:
            return

        if kind == "StasisStart":
            await self._answered(state)
        elif kind in {"ChannelDestroyed", "StasisEnd"}:
            cause = event.get("cause_txt") or event.get("cause")
            await self.finish(state, cause=str(cause) if cause is not None else None)
        elif kind == "PlaybackFinished":
            await self._playback_finished(state, event)

    async def _answered(self, state: CallState) -> None:
        if state.status != "ringing":
            return
        state.status = "answered"
        state.answered_at = time.time()

        media = await asyncio.to_thread(resolve_media, state.audio)
        if media:
            try:
                state.playback_id = await asyncio.to_thread(
                    self.ari.play, state.call_id, media
                )
            except AriError as exc:
                logger.warning("Не удалось запустить запись %s: %s", media, exc)
                await self._start_listening(state)
        else:
            logger.info("Звонок %s идет без звука (записи нет)", state.call_id)
            await self._start_listening(state)

        await self.notifier.send(self._payload("answered", state))

    async def _playback_finished(self, state: CallState, event: dict) -> None:
        logger.info("Звонок %s: запись воспроизведена", state.call_id)
        playback_id = (event.get("playback") or {}).get("id")
        # слушаем следующую реплику оператора только после того, как
        # доиграла именно та реплика заявителя, что мы сами запустили
        # (приветствие или ответ ИИ) - а не случайное чужое событие
        if playback_id and playback_id == state.playback_id:
            await self._start_listening(state)

    # -- голосовой диалог: запись реплики -> STT -> ИИ -> TTS -> playback ----

    async def _start_listening(self, state: CallState) -> None:
        if not Config.VOICE_DIALOG_ENABLED or state.status != "answered":
            return
        if state.turn >= Config.VOICE_DIALOG_MAX_TURNS:
            logger.info(
                "Звонок %s: лимит реплик диалога исчерпан (%s), дальше без ИИ",
                state.call_id,
                state.turn,
            )
            return
        name = f"turn-{state.call_id}-{state.turn}"
        try:
            await asyncio.to_thread(
                self.ari.record,
                state.call_id,
                name,
                max_duration_sec=Config.VOICE_MAX_UTTERANCE_SEC,
                max_silence_sec=Config.VOICE_MAX_SILENCE_SEC,
                fmt=Config.RECORDING_FORMAT,
            )
            state.listening = True
        except AriError as exc:
            logger.warning(
                "Не удалось начать запись реплики (звонок %s): %s", state.call_id, exc
            )

    async def _on_recording(self, kind: str, recording: dict) -> None:
        name = recording.get("name") or ""
        target = recording.get("target_uri") or ""
        if not target.startswith("channel:"):
            return
        state = self.registry.get(target.split(":", 1)[1])
        if state is None:
            return
        state.listening = False
        if kind == "RecordingFailed":
            logger.warning(
                "Запись реплики %s не удалась (звонок %s)", name, state.call_id
            )
            if state.status == "answered":
                await self._start_listening(state)
            return
        self._spawn(self._process_turn(state, name))

    async def _process_turn(self, state: CallState, recording_name: str) -> None:
        path = os.path.join(
            Config.RECORDING_DIR, f"{recording_name}.{Config.RECORDING_FORMAT}"
        )
        text = await asyncio.to_thread(stt.transcribe, path)
        if not text:
            # тишина или STT недоступен: пробуем еще раз, не тратя реплику ИИ
            if state.status == "answered":
                await self._start_listening(state)
            return

        reply = await asyncio.to_thread(self._voice_turn_request, state.call_id, text)
        state.turn += 1
        if not reply or state.status != "answered":
            if state.status == "answered":
                await self._start_listening(state)
            return

        media = await asyncio.to_thread(tts.synthesize, reply)
        if not media:
            await self._start_listening(state)
            return
        try:
            state.playback_id = await asyncio.to_thread(
                self.ari.play, state.call_id, media
            )
        except AriError as exc:
            logger.warning(
                "Не удалось озвучить ответ (звонок %s): %s", state.call_id, exc
            )
            await self._start_listening(state)

    def _voice_turn_request(self, call_id: str, text: str) -> str | None:
        """Синхронный запрос к arm_api за репликой заявителя (выполняется в
        отдельном потоке - httpx.Client там безопаснее async-клиента)."""
        url = f"{Config.ARM_API_URL}/internal/calls/{call_id}/voice-turn"
        headers = {"X-Service-Token": Config.SERVICE_TOKEN}
        try:
            with httpx.Client(
                timeout=Config.ARM_API_TIMEOUT_SEC,
                transport=self._transport,
            ) as client:
                response = client.post(url, json={"text": text}, headers=headers)
            if response.status_code >= 400:
                logger.warning(
                    "arm_api отклонил voice-turn (%s): %s",
                    response.status_code,
                    response.text[:200],
                )
                return None
            return (response.json().get("reply") or "").strip() or None
        except httpx.HTTPError as exc:
            logger.warning("arm_api недоступен для voice-turn: %s", exc)
            return None

    async def finish(self, state: CallState, cause: str | None = None) -> None:
        if state.status not in ACTIVE:
            return
        event = "finished" if state.status == "answered" else "no_answer"
        state.status = "finished" if event == "finished" else "no_answer"
        state.finished_at = time.time()
        state.hangup_cause = cause
        if state.leased:
            self.pool.release(state.extension)
        await self.notifier.send(self._payload(event, state))

    @staticmethod
    def _payload(event: str, state: CallState) -> dict:
        return {
            "event": event,
            "call_id": state.call_id,
            "attempt_id": state.attempt_id,
            "extension": state.extension,
            "at": time.time(),
            "hangup_cause": state.hangup_cause,
            **state.rtt_summary(),
        }

    # -- фоновые циклы -------------------------------------------------------

    async def run_events(self) -> None:
        backoff = 1.0
        query = urlencode(
            {
                "app": Config.ARI_APP_NAME,
                "api_key": f"{Config.ARI_USERNAME}:{Config.ARI_PASSWORD}",
                "subscribeAll": "false",
            }
        )
        url = f"{Config.ARI_WS_URL}?{query}"
        while True:
            try:
                async with connect(url, open_timeout=Config.ARI_TIMEOUT_SEC) as socket:
                    self.connected = True
                    backoff = 1.0
                    logger.info("Подключено к событиям ARI")
                    async for raw in socket:
                        await self.handle_event(json.loads(raw))
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as exc:  # обрыв связи с Asterisk - переподключаемся
                logger.warning("События ARI недоступны: %s", exc)
            self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def run_sweeper(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SEC)
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка обхода активных звонков")

    async def sweep(self) -> None:
        now = time.monotonic()
        wall = time.time()
        for state in self.registry.active():
            if state.status == "ringing" and now > state.ring_deadline + 3:
                # неответ: Asterisk мог не прислать событие, сверяемся с каналом
                if not await asyncio.to_thread(self._alive, state.call_id):
                    await self.finish(state, cause="no answer")
            elif state.status == "answered":
                if wall - (state.answered_at or wall) > Config.VOIP_MAX_CALL_SEC:
                    await asyncio.to_thread(self._hangup_quietly, state.call_id)
                    await self.finish(state, cause="max call duration")
                elif now - state.last_rtt_poll >= Config.VOIP_RTT_POLL_SEC:
                    state.last_rtt_poll = now
                    await self._sample_rtt(state)
        self.registry.prune()

    async def _sample_rtt(self, state: CallState) -> None:
        try:
            rtt = await asyncio.to_thread(self.ari.rtt_ms, state.call_id)
            if rtt is not None:
                state.rtt_samples.append(rtt)
            elif not await asyncio.to_thread(self._alive, state.call_id):
                await self.finish(state, cause="channel lost")
        except AriError as exc:
            logger.warning("RTT звонка %s недоступен: %s", state.call_id, exc)

    def _alive(self, call_id: str) -> bool:
        try:
            return self.ari.channel_exists(call_id)
        except AriError:
            return True  # Asterisk не ответил - не считаем звонок потерянным

    def _hangup_quietly(self, call_id: str) -> None:
        try:
            self.ari.hangup(call_id)
        except AriError as exc:
            logger.warning("Hangup %s не удался: %s", call_id, exc)
