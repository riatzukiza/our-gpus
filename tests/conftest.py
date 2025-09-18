import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app

# Create test database in memory for speed and CI compatibility
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def session():
    """Create a test database session"""
    # Import all models to ensure they're registered
    from app.db import Host, Model, HostModel, Scan, Probe  # noqa: F401

    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    # Clean up after test
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(session):
    """Create a test client with test database"""

    def get_test_session():
        yield session

    app.dependency_overrides[get_session] = get_test_session

    with TestClient(app) as test_client:
        yield test_client

    # Clear overrides after test
    app.dependency_overrides.clear()
