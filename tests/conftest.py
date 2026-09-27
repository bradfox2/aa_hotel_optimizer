import pytest
from fastapi.testclient import TestClient

from aa_hotel_optimizer.service.app import create_app
from aa_hotel_optimizer.service.config import Settings

ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def app(tmp_path):
    return create_app(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path}/test.sqlite3",
            public_url=ORIGIN,
            provider_enabled=True,
            free_searches=2,
        )
    )


@pytest.fixture
def client(app):
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        yield client
