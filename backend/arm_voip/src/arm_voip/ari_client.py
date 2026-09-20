import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Config


class AriError(RuntimeError):
    """Asterisk недоступен или отклонил команду ARI."""


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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or Config.ARI_BASE_URL).rstrip("/")
        self.auth = (
            username or Config.ARI_USERNAME,
            password if password is not None else Config.ARI_PASSWORD,
        )
        self.timeout = Config.ARI_TIMEOUT_SEC if timeout is None else timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            auth=self.auth,
            timeout=self.timeout,
            transport=self._transport,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        with self._client() as client:
            try:
                return client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise AriError(f"Не удалось обратиться к ARI: {exc}") from exc

    @staticmethod
    def _check(response: httpx.Response, action: str, ok=(200, 201, 204)) -> None:
        if response.status_code not in ok:
            raise AriError(
                f"ARI отклонил {action} ({response.status_code}): {response.text}"
            )

    def start_call(
        self,
        *,
        attempt_id: str,
        destination: str,
        audio: str | None = None,
        caller_number: str | None = None,
    ) -> CallHandle:
        """Звонит оператору и после ответа отдает канал приложению Stasis."""
        channel_id = uuid.uuid4().hex
        params = {
            "endpoint": f"PJSIP/{destination}",
            "app": Config.ARI_APP_NAME,
            "appArgs": f"{attempt_id},{audio or ''}",
            "channelId": channel_id,
            "timeout": Config.VOIP_RING_TIMEOUT_SEC,
        }
        if caller_number:
            params["callerId"] = caller_number

        response = self._request("POST", "/channels", params=params)
        self._check(response, "создание канала")

        # События канала до ответа приходят только по явной подписке
        self._request(
            "POST",
            f"/applications/{Config.ARI_APP_NAME}/subscription",
            params={"eventSource": f"channel:{channel_id}"},
        )
        return CallHandle(channel_id, channel_id, destination, str(attempt_id))

    def hangup(self, channel_id: str) -> dict[str, Any]:
        if not channel_id:
            return {"status": "finished", "channel_id": None}

        response = self._request("DELETE", f"/channels/{channel_id}")
        self._check(response, "Hangup", ok=(200, 204, 404))
        return {"status": "finished", "channel_id": channel_id}

    def play(self, channel_id: str, media: str) -> str:
        response = self._request(
            "POST", f"/channels/{channel_id}/play", params={"media": media}
        )
        self._check(response, "воспроизведение")
        return response.json().get("id", "")

    def channel_exists(self, channel_id: str) -> bool:
        response = self._request("GET", f"/channels/{channel_id}")
        if response.status_code == 404:
            return False
        self._check(response, "запрос канала")
        return True

    def rtt_ms(self, channel_id: str) -> float | None:
        """RTT по RTCP в миллисекундах. None, если статистики пока нет."""
        response = self._request(
            "GET",
            f"/channels/{channel_id}/variable",
            params={"variable": "CHANNEL(rtcp,rtt)"},
        )
        if response.status_code != 200:
            return None
        try:
            return round(float(response.json().get("value", "")) * 1000, 1)
        except (TypeError, ValueError):
            return None

    def reload_pjsip(self) -> None:
        response = self._request("PUT", "/asterisk/modules/res_pjsip.so")
        self._check(response, "перезагрузку PJSIP")

    def ping(self) -> dict[str, Any]:
        try:
            response = self._request("GET", "/asterisk/info")
        except AriError as exc:
            return {"available": False, "error": str(exc)}

        if response.status_code >= 400:
            return {"available": False, "error": f"HTTP {response.status_code}"}

        info = response.json()
        return {
            "available": True,
            "version": (info.get("system") or {}).get("version"),
        }
