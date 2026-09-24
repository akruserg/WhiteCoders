"""
POST /tts    - {"text", "voice"?} -> audio/wav (речь заявителя)
POST /stt    - multipart-файл audio -> {"text"}  (распознанная реплика оператора)
GET  /health - доступные голоса, модель распознавания

Служебный сервис: без JWT, доступ по общему токену X-Service-Token (как
между arm_api и arm_voip). Наружу (в интернет) не обращается - все модели
читаются с локального диска (см. download_models.sh).
"""

import hmac
import logging
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from . import stt, tts
from .config import Config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    problems = Config.problems()
    if problems:
        raise RuntimeError("Некорректная конфигурация voice: " + "; ".join(problems))
    if Config.WARM_UP:
        tts.warm_up()
        stt.warm_up()
    yield


app = FastAPI(title="arm_voice", version="1.0.0", lifespan=lifespan)


def _check_token(x_service_token: str | None) -> None:
    expected = Config.SERVICE_TOKEN
    if not expected or not hmac.compare_digest(x_service_token or "", expected):
        raise HTTPException(status_code=401, detail="Invalid service token")


class TtsRequest(BaseModel):
    text: str
    voice: str | None = None


@app.post("/tts")
def synthesize(
    body: TtsRequest, x_service_token: str | None = Header(default=None)
) -> Response:
    _check_token(x_service_token)
    try:
        wav = tts.synthesize(body.text, body.voice)
    except tts.TtsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(content=wav, media_type="audio/wav")


@app.post("/stt")
async def recognize(
    audio: UploadFile, x_service_token: str | None = Header(default=None)
) -> dict:
    _check_token(x_service_token)
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        tmp.write(await audio.read())
        tmp.flush()
        try:
            text = stt.transcribe(tmp.name)
        except stt.SttError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"text": text}


@app.get("/health")
def health() -> dict:
    return {
        "available": True,
        "tts_voices": tts.available_voices(),
        "tts_default_voice": Config.TTS_DEFAULT_VOICE,
        "stt_model": Config.STT_MODEL_SIZE,
    }
