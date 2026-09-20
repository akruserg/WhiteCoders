import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config


class AriError(RuntimeError):
    # астериск пал
    pass


@dataclass
class CallHandle:
    call_id: str
    channel_id: str
    destination: str
    attempt_id: str


class AriClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or Config.ARI_BASE_URL).rstrip("/")
        self.auth = (
            username or Config.ARI_USERNAME,
            password or Config.ARI_PASSWORD,
        )
        self.timeout = timeout or Config.ARI_TIMEOUT_SEC

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            auth=self.auth,
            timeout=self.timeout,
        )

    def start_call(
        self,
        *,
        attempt_id: str,
        operator: str = "",
        destination: str | None = None,
    ) -> CallHandle:
        destination = destination or Config.VOIP_DESTINATION
        channel_id = uuid.uuid4().hex

        payload = {
            "endpoint": f"PJSIP/{destination}",
            "context": Config.VOIP_DIALPLAN_CONTEXT,
            "extension": "s",
            "priority": 1,
            "channelId": channel_id,
            "timeout": Config.VOIP_RING_TIMEOUT_SEC,
            "variables": {
                "ARM112_ATTEMPT_ID": str(attempt_id),
                "ARM112_OPERATOR": operator or "",
            },
        }

        with self._client() as client:
            try:
                response = client.post("/channels", json=payload)
            except httpx.HTTPError as exc:
                raise AriError(f"Не удалось обратиться к ARI: {exc}") from exc

        if response.status_code >= 400:
            raise AriError(
                f"ARI отклонил создание канала "
                f"({response.status_code}): {response.text}"
            )

        return CallHandle(
            call_id=channel_id,
            channel_id=channel_id,
            destination=destination,
            attempt_id=str(attempt_id),
        )

    def hangup(self, channel_id: str) -> dict[str, Any]:
        if not channel_id:
            return {"status": "finished", "channel_id": None}

        with self._client() as client:
            try:
                response = client.delete(f"/channels/{channel_id}")
            except httpx.HTTPError as exc:
                raise AriError(f"Не удалось обратиться к ARI: {exc}") from exc

        if response.status_code not in (204, 404):
            raise AriError(
                f"ARI отклонил Hangup " f"({response.status_code}): {response.text}"
            )

        return {"status": "finished", "channel_id": channel_id}

    def ping(self) -> dict[str, Any]:
        with self._client() as client:
            try:
                response = client.get("/asterisk/info")
            except httpx.HTTPError as exc:
                return {"available": False, "error": str(exc)}

        if response.status_code >= 400:
            return {
                "available": False,
                "error": f"HTTP {response.status_code}",
            }

        return {"available": True, "info": response.json()}
