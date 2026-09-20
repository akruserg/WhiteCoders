import hashlib
import hmac
import threading
import time
from dataclasses import dataclass
from typing import Callable


class PoolExhausted(RuntimeError):
    """Все SIP-номера заняты: одновременных звонков больше, чем номеров в пуле."""


@dataclass
class Lease:
    extension: str
    attempt_id: str
    expires_at: float
    call_id: str | None = None


def sip_password(secret: str, extension: str) -> str:
    """Пароль номера выводится из общего секрета: отдельный для каждого номера."""
    digest = hmac.new(secret.encode(), extension.encode(), hashlib.sha256)
    return digest.hexdigest()[:32]


class OperatorPool:
    """Выдает свободный SIP-номер под каждую карточку (попытку).

    Один номер - один одновременный звонок, поэтому 20 обучающихся не делят
    единственный телефон. Состояние живет в памяти процесса, сервис работает
    в одном процессе uvicorn.
    """

    def __init__(
        self,
        extensions: list[str],
        ttl_sec: int = 900,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._extensions = list(extensions)
        self._ttl = ttl_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._leases: dict[str, Lease] = {}  # extension -> lease

    @property
    def extensions(self) -> list[str]:
        return list(self._extensions)

    def _drop_expired(self) -> None:
        now = self._clock()
        for extension in [e for e, l in self._leases.items() if l.expires_at <= now]:
            del self._leases[extension]

    def acquire(self, attempt_id: str) -> str:
        with self._lock:
            self._drop_expired()
            for lease in self._leases.values():
                if lease.attempt_id == attempt_id:
                    return lease.extension
            for extension in self._extensions:
                if extension not in self._leases:
                    self._leases[extension] = Lease(
                        extension, attempt_id, self._clock() + self._ttl
                    )
                    return extension
        raise PoolExhausted(
            f"Свободных SIP-номеров нет (всего {len(self._extensions)})"
        )

    def bind(self, extension: str, call_id: str) -> None:
        with self._lock:
            lease = self._leases.get(extension)
            if lease is not None:
                lease.call_id = call_id

    def release(self, extension: str | None) -> None:
        if not extension:
            return
        with self._lock:
            self._leases.pop(extension, None)

    def stats(self) -> dict:
        with self._lock:
            self._drop_expired()
            busy = len(self._leases)
        return {
            "size": len(self._extensions),
            "busy": busy,
            "free": len(self._extensions) - busy,
        }
