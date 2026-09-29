import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .ari_client import AriClient, AriError
from .calls import ACTIVE, CallRegistry, CallState, CallSupervisor, Notifier
from .config import Config
from .pool import OperatorPool, PoolExhausted, sip_password
from .sipconf import render_operators, write_operators

logger = logging.getLogger(__name__)

OPERATORS_CONF = "pjsip_operators.conf"


class Runtime:
    """Общие объекты сервиса. Создаются при старте, в тестах подменяются."""

    def __init__(self, ari: AriClient | None = None, notifier: Notifier | None = None):
        extensions = [
            str(Config.VOIP_POOL_START + i) for i in range(Config.VOIP_POOL_SIZE)
        ]
        self.ari = ari or AriClient()
        self.pool = OperatorPool(extensions, Config.VOIP_LEASE_TTL_SEC)
        self.registry = CallRegistry()
        self.supervisor = CallSupervisor(
            self.ari, self.registry, self.pool, notifier or Notifier()
        )


runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global runtime
    if runtime is None:
        runtime = Runtime()
    return runtime


async def _publish_sip_config(rt: Runtime) -> None:
    """Пишет конфиг номеров операторов и просит Asterisk его перечитать."""
    content = render_operators(
        rt.pool.extensions,
        Config.VOIP_SIP_SECRET,
        Config.VOIP_DIALPLAN_CONTEXT,
        Config.VOIP_ENDPOINT_MODE,
    )
    path = f"{Config.GENERATED_DIR}/{OPERATORS_CONF}"
    changed = await asyncio.to_thread(write_operators, path, content)

    delay = 1.0
    for _ in range(12):  # Asterisk может подняться позже нас
        try:
            await asyncio.to_thread(rt.ari.reload_pjsip)
            logger.info("SIP-номера операторов опубликованы (изменен: %s)", changed)
            return
        except AriError as exc:
            logger.info("PJSIP пока не перечитан: %s", exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)
    logger.error(
        "Не удалось перечитать PJSIP, номера появятся после перезапуска Asterisk"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    problems = Config.problems()
    if problems:
        raise RuntimeError("Некорректная конфигурация arm_voip: " + "; ".join(problems))

    rt = get_runtime()
    tasks = [
        asyncio.create_task(rt.supervisor.run_events()),
        asyncio.create_task(rt.supervisor.run_sweeper()),
    ]
    if not Config.VOIP_DESTINATION:
        tasks.append(asyncio.create_task(_publish_sip_config(rt)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="arm_voip", version="1.1.0", lifespan=lifespan)


def _check_service_token(x_service_token: str | None) -> None:
    expected = Config.SERVICE_TOKEN
    if not expected or not hmac.compare_digest(x_service_token or "", expected):
        raise HTTPException(status_code=401, detail="Invalid service token")


class StartCallRequest(BaseModel):
    attempt_id: str
    operator: str = ""
    destination: str | None = None
    audio: str | None = None
    caller_number: str | None = None


class SipCredentials(BaseModel):
    extension: str
    password: str
    ws_url: str
    domain: str
    mode: str


class CallResponse(BaseModel):
    call_id: str
    channel_id: str
    destination: str
    attempt_id: str
    ring_timeout_sec: int
    sip: SipCredentials | None = None


def _credentials(extension: str) -> SipCredentials:
    return SipCredentials(
        extension=extension,
        password=sip_password(Config.VOIP_SIP_SECRET, extension),
        ws_url=Config.SIP_WS_URL,
        domain=Config.SIP_DOMAIN,
        mode=Config.VOIP_ENDPOINT_MODE,
    )


def _response(state: CallState) -> CallResponse:
    pooled = state.leased and bool(Config.VOIP_SIP_SECRET)
    return CallResponse(
        call_id=state.call_id,
        channel_id=state.call_id,
        destination=state.extension,
        attempt_id=state.attempt_id,
        ring_timeout_sec=Config.VOIP_RING_TIMEOUT_SEC,
        sip=_credentials(state.extension) if pooled else None,
    )


@app.post("/calls", response_model=CallResponse)
def start_call(
    body: StartCallRequest,
    x_service_token: str | None = Header(default=None),
) -> CallResponse:
    _check_service_token(x_service_token)
    rt = get_runtime()

    existing = rt.registry.find_active(body.attempt_id)
    if existing is not None:  # повторный запрос по той же карточке
        return _response(existing)

    if not rt.supervisor.connected:
        raise HTTPException(
            status_code=503, detail="Asterisk недоступен (нет событий ARI)"
        )

    fixed = body.destination or Config.VOIP_DESTINATION
    leased = not fixed
    try:
        extension = fixed or rt.pool.acquire(body.attempt_id)
    except PoolExhausted as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        handle = rt.ari.start_call(
            attempt_id=body.attempt_id,
            destination=extension,
            audio=body.audio,
            caller_number=body.caller_number,
        )
    except AriError as exc:
        if leased:
            rt.pool.release(extension)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if leased:
        rt.pool.bind(extension, handle.call_id)
    state = CallState(
        call_id=handle.call_id,
        attempt_id=handle.attempt_id,
        extension=extension,
        leased=leased,
        audio=body.audio,
        ring_deadline=time.monotonic() + Config.VOIP_RING_TIMEOUT_SEC,
    )
    rt.registry.add(state)
    return _response(state)


@app.get("/calls/{call_id}")
def get_call(call_id: str, x_service_token: str | None = Header(default=None)) -> dict:
    _check_service_token(x_service_token)
    state = get_runtime().registry.get(call_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    return state.to_dict()


@app.delete("/calls/{call_id}")
def hangup_call(
    call_id: str,
    x_service_token: str | None = Header(default=None),
) -> dict:
    _check_service_token(x_service_token)
    rt = get_runtime()

    try:
        result = rt.ari.hangup(call_id)
    except AriError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    state = rt.registry.get(call_id)
    if state is not None and state.status in ACTIVE:
        state.status = "finished" if state.status == "answered" else "no_answer"
        state.finished_at = time.time()
        if state.leased:
            rt.pool.release(state.extension)
    return result


@app.get("/health")
def health() -> dict:
    rt = get_runtime()
    result = rt.ari.ping()
    result["events_connected"] = rt.supervisor.connected
    result["pool"] = rt.pool.stats()
    result["active_calls"] = len(rt.registry.active())
    result["max_latency_ms"] = Config.VOIP_MAX_LATENCY_MS
    if not (result.get("available") and rt.supervisor.connected):
        raise HTTPException(status_code=503, detail=result)
    return result
