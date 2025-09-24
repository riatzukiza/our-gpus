"""Test configuration settings."""

from app.config import Settings


class TestSettings(Settings):
    """Test-specific configuration."""

    # Use a file-based SQLite database for tests (more reliable than memory)
    database_url: str = "sqlite:///./test_ci.db"

    # Disable external services in tests
    redis_url: str = "redis://localhost:6379/15"  # Use different Redis DB for tests

    # Test-specific settings
    batch_size: int = 100  # Smaller batches for faster tests


def get_test_settings() -> TestSettings:
    """Get test settings."""
    return TestSettings()


# Create a global test settings instance
test_settings = get_test_settings()
