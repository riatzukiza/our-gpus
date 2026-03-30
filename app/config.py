from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/ollama.db"
    redis_url: str = "redis://localhost:6379/0"
    probe_timeout_secs: int = 5
    probe_concurrency: int = 200
    probe_retries: int = 2
    probe_batch_size: int = 100
    geocode_timeout_secs: int = 5
    geocode_retries: int = 2
    geocode_provider_url: str = "https://ipwho.is"
    upload_max_mb: int = 4096
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,https://our-gpu.shuv.dev"
    log_level: str = "INFO"
    cloudflare_access_enabled: bool = False
    cloudflare_access_team_domain: str = ""
    cloudflare_access_audience: str = ""
    batch_size: int = 1000
    workers: int = 4

    class Config:
        env_file = ".env"

    def get_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]


settings = Settings()
