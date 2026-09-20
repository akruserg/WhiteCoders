import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


class Config:
    ARI_BASE_URL = os.environ.get("ARI_BASE_URL", "http://asterisk:8088/ari")
    ARI_USERNAME = os.environ.get("ARI_USERNAME", "arm_voip")
    ARI_PASSWORD = os.environ.get("ARI_PASSWORD", "")
    ARI_APP_NAME = os.environ.get("ARI_APP_NAME", "arm_voip")

    VOIP_DIALPLAN_CONTEXT = os.environ.get("VOIP_DIALPLAN_CONTEXT", "arm112")
    VOIP_DESTINATION = os.environ.get("VOIP_DESTINATION", "1001")

    ARI_TIMEOUT_SEC = float(os.environ.get("ARI_TIMEOUT_SEC", "5"))
    VOIP_RING_TIMEOUT_SEC = _int("VOIP_RING_TIMEOUT_SEC", 30)

    SERVICE_TOKEN = os.environ.get("ARM_VOIP_SERVICE_TOKEN", "")
