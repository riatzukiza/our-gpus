"""Test database utilities."""

import os

from sqlmodel import Session, SQLModel, create_engine

from app.config_test import test_settings


def create_test_engine():
    """Create a test database engine."""
    # Remove existing test database
    if os.path.exists("./test_ci.db"):
        os.unlink("./test_ci.db")

    engine = create_engine(
        test_settings.database_url, connect_args={"check_same_thread": False}, echo=False
    )

    # Import all models to ensure they're registered with SQLModel.metadata
    from app.db import Host, HostModel, Model, Probe, Scan  # noqa: F401

    # Create all tables
    SQLModel.metadata.create_all(engine)

    return engine


def get_test_session(engine):
    """Get a test database session."""
    with Session(engine) as session:
        yield session


def cleanup_test_db():
    """Clean up test database."""
    if os.path.exists("./test_ci.db"):
        os.unlink("./test_ci.db")
