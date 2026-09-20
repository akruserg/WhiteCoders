import os

# Config читает окружение при импорте; БД в этих тестах не нужна
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/none")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")
os.environ.setdefault("ARM_VOIP_SERVICE_TOKEN", "svc-token")
os.environ.setdefault("VOIP_ENABLED", "1")

import pytest  # noqa: E402

from arm_api import create_app  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()
