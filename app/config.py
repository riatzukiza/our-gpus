
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/ollama.db"
    redis_url: str = "redis://localhost:6379/0"
    probe_timeout_secs: int = 5
    probe_concurrency: int = 200
    probe_retries: int = 2
    upload_max_mb: int = 4096
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"
    log_level: str = "INFO"
    batch_size: int = 1000
    workers: int = 4

    class Config:
        env_file = ".env"

    def get_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]


settings = Settings()
