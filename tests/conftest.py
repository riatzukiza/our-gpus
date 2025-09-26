import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app

# Use file-based SQLite for better CI compatibility and shared access
TEST_DATABASE_URL = "sqlite:///./test_ci.db"


@pytest.fixture(scope="session")
def test_engine():
    """Create a test database engine for the session"""
    # Remove existing test database
    if os.path.exists("./test_ci.db"):
        os.unlink("./test_ci.db")

    # Import all models to ensure they're registered
    from app.db import Host, HostModel, Model, Probe, Scan  # noqa: F401

    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, echo=False)

    # Create all tables
    SQLModel.metadata.create_all(engine)

    yield engine

    # Cleanup after all tests
    if os.path.exists("./test_ci.db"):
        os.unlink("./test_ci.db")


@pytest.fixture(scope="function")
def session(test_engine):
    """Create a test database session"""
    with Session(test_engine) as session:
        # Clean up all data before each test
        from app.db import Host, HostModel, Model, Probe, Scan  # noqa: F401

        # Delete all data in correct order to respect foreign keys
        session.exec(Probe.__table__.delete())
        session.exec(HostModel.__table__.delete())
        session.exec(Scan.__table__.delete())
        session.exec(Host.__table__.delete())
        session.exec(Model.__table__.delete())
        session.commit()

        yield session


@pytest.fixture(scope="function")
def client(test_engine, session):  # noqa: ARG001
    """Create a test client with test database"""

    def get_test_session():
        yield session

    # Override the session dependency to use the same session as the test
    app.dependency_overrides[get_session] = get_test_session

    # Disable the startup event to prevent production DB initialization
    with patch("app.main.init_db") as mock_init_db:
        mock_init_db.return_value = None

        with TestClient(app) as test_client:
            yield test_client

    # Clear overrides after test
    app.dependency_overrides.clear()
