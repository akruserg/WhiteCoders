import os

# Config читает окружение при импорте, поэтому значения задаем до него
os.environ.update(
    {
        "ARM_VOIP_SERVICE_TOKEN": "test-token",
        "ARI_PASSWORD": "ari-pass",
        "VOIP_SIP_SECRET": "sip-secret",
        "VOIP_POOL_SIZE": "3",
        "VOIP_POOL_START": "2001",
        "ARM_API_URL": "http://api.test/api/v1",
        "VOIP_RTT_POLL_SEC": "0",
    }
)

import pytest  # noqa: E402

from arm_voip import app as app_module  # noqa: E402
from arm_voip.ari_client import AriError  # noqa: E402


class FakeAri:
    """Подменяет ARI: запоминает команды и отдает заранее заданные ответы."""

    def __init__(self):
        self.started = []
        self.hangups = []
        self.played = []
        self.rtt = None
        self.alive = True
        self.fail_start = False

    def start_call(self, *, attempt_id, destination, audio=None, caller_number=None):
        if self.fail_start:
            raise AriError("ARI отклонил создание канала (500): boom")
        self.started.append((attempt_id, destination, audio, caller_number))
        from arm_voip.ari_client import CallHandle

        call_id = f"chan{len(self.started)}"
        return CallHandle(call_id, call_id, destination, str(attempt_id))

    def hangup(self, channel_id):
        self.hangups.append(channel_id)
        return {"status": "finished", "channel_id": channel_id}

    def play(self, channel_id, media):
        self.played.append((channel_id, media))
        return "pb1"

    def channel_exists(self, channel_id):
        return self.alive

    def rtt_ms(self, channel_id):
        return self.rtt

    def reload_pjsip(self):
        pass

    def ping(self):
        return {"available": True, "version": "22.0"}


class FakeNotifier:
    def __init__(self):
        self.events = []

    async def send(self, payload):
        self.events.append(payload)
        return True


@pytest.fixture
def rt():
    ari, notifier = FakeAri(), FakeNotifier()
    runtime = app_module.Runtime(ari=ari, notifier=notifier)
    runtime.supervisor.connected = True
    app_module.runtime = runtime
    yield runtime
    app_module.runtime = None
