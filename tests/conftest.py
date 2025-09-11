import pytest
from sqlmodel import Session, SQLModel, create_engine
from fastapi.testclient import TestClient
from app.main import app
from app.db import get_session

# Create test database
TEST_DATABASE_URL = "sqlite:///./test.db"


@pytest.fixture(scope="function")
def session():
    """Create a test database session"""
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
