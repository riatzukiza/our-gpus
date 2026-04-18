from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/ollama.db"
    redis_url: str = "redis://localhost:6379/0"
    admin_api_key: str = ""
    our_gpus_api_key: str = ""
    proxx_api_key: str = ""
    probe_timeout_secs: int = 5
    probe_concurrency: int = 200
    probe_retries: int = 2
    probe_batch_size: int = 100
    probe_sidecar_url: str = ""
    geocode_timeout_secs: int = 5
    geocode_retries: int = 2
    geocode_data_path: str = "/app/data/geoip2fast-city.dat.gz"
    geocode_data_url: str = (
        "https://github.com/rabuchaim/geoip2fast/releases/download/LATEST/geoip2fast-city.dat.gz"
    )
    upload_max_mb: int = 4096
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,https://our-gpu.shuv.dev"
    log_level: str = "INFO"
    cloudflare_access_enabled: bool = False
    cloudflare_access_team_domain: str = ""
    cloudflare_access_audience: str = ""
    batch_size: int = 1000
    workers: int = 4
    our_gpus_exclude_files: str = "/app/excludes.conf,/app/excludes.generated.conf"
    tor_scan_max_hosts: int = 4096
    tor_scan_concurrency: int = 32
    shodan_api_key: str = ""
    shodan_base_query: str = ""
    shodan_page_limit: int = 3
    shodan_max_matches: int = 1000
    shodan_max_queries: int = 24
    shodan_query_max_length: int = 900
    # OpenPlanner integration
    openplanner_url: str = "http://127.0.0.1:8788/api/openplanner"
    openplanner_api_key: str = ""
    openplanner_sync_enabled: bool = True
    openplanner_batch_size: int = 100
    openplanner_timeout_secs: int = 30

    class Config:
        env_file = ".env"

    def get_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    def get_admin_api_key(self) -> str:
        return self.admin_api_key or self.our_gpus_api_key or self.proxx_api_key


settings = Settings()
