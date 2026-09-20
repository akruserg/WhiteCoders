from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .ari_client import AriClient, AriError
from .config import Config

app = FastAPI(title="arm_voip", version="1.0.0")


def _check_service_token(x_service_token: str | None) -> None:
    if Config.SERVICE_TOKEN and x_service_token != Config.SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid service token")


class StartCallRequest(BaseModel):
    attempt_id: str
    operator: str = ""
    destination: str | None = None


class CallResponse(BaseModel):
    call_id: str
    channel_id: str
    destination: str
    attempt_id: str


@app.post("/calls", response_model=CallResponse)
def start_call(
    body: StartCallRequest,
    x_service_token: str | None = Header(default=None),
) -> CallResponse:
    _check_service_token(x_service_token)

    client = AriClient()
    try:
        handle = client.start_call(
            attempt_id=body.attempt_id,
            operator=body.operator,
            destination=body.destination,
        )
    except AriError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return CallResponse(
        call_id=handle.call_id,
        channel_id=handle.channel_id,
        destination=handle.destination,
        attempt_id=handle.attempt_id,
    )


@app.delete("/calls/{call_id}")
def hangup_call(
    call_id: str,
    x_service_token: str | None = Header(default=None),
) -> dict:
    _check_service_token(x_service_token)

    client = AriClient()
    try:
        return client.hangup(call_id)
    except AriError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    client = AriClient()
    result = client.ping()
    if not result.get("available"):
        raise HTTPException(status_code=503, detail=result)
    return result
