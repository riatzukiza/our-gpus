import json
from datetime import datetime

from sqlalchemy import Column, Index, Text
from sqlmodel import Field, Session, SQLModel, create_engine


class Host(SQLModel, table=True):
    __tablename__ = "hosts"

    id: int | None = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    port: int
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float | None = None
    api_version: str | None = None
    os: str | None = None
    arch: str | None = None
    ram_gb: float | None = None
    gpu: str | None = None
    gpu_vram_mb: int | None = None
    geo_country: str | None = None
    geo_city: str | None = None
    status: str = Field(default="unknown")  # online, offline, error, rate_limited
    last_error: str | None = None

    __table_args__ = (
        Index("idx_ip_port", "ip", "port"),
    )


class Model(SQLModel, table=True):
    __tablename__ = "models"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    family: str | None = Field(index=True)
    size_mb: int | None = None
    parameters: str | None = None
    sha256: str | None = None


class HostModel(SQLModel, table=True):
    __tablename__ = "host_models"

    id: int | None = Field(default=None, primary_key=True)
    host_id: int = Field(foreign_key="hosts.id")
    model_id: int = Field(foreign_key="models.id")
    quantization: str | None = None
    size_mb: int | None = None
    loaded: bool = Field(default=False)
    vram_usage_mb: int | None = None


class Scan(SQLModel, table=True):
    __tablename__ = "scans"

    id: int | None = Field(default=None, primary_key=True)
    source_file: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    mapping_json: str = Field(sa_column=Column(Text))  # JSON field mapping
    stats_json: str = Field(sa_column=Column(Text))  # JSON stats
    status: str = Field(default="pending")  # pending, processing, completed, failed
    total_rows: int = 0
    processed_rows: int = 0
    error_message: str | None = None

    @property
    def mapping(self) -> dict:
        return json.loads(self.mapping_json) if self.mapping_json else {}

    @mapping.setter
    def mapping(self, value: dict):
        self.mapping_json = json.dumps(value)

    @property
    def stats(self) -> dict:
        return json.loads(self.stats_json) if self.stats_json else {}

    @stats.setter
    def stats(self, value: dict):
        self.stats_json = json.dumps(value)


class Probe(SQLModel, table=True):
    __tablename__ = "probes"

    id: int | None = Field(default=None, primary_key=True)
    host_id: int = Field(foreign_key="hosts.id", index=True)
    status: str  # success, timeout, error, non_ollama
    duration_ms: float
    raw_payload: str = Field(sa_column=Column(Text))  # JSON response, capped
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


engine = None
SessionLocal = None


def init_db(database_url: str = None):
    global engine, SessionLocal
    from app.config import settings

    db_url = database_url or settings.database_url
    engine = create_engine(db_url, echo=False, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
    SQLModel.metadata.create_all(engine)

    from sqlmodel import Session
    SessionLocal = Session


def get_session():
    with Session(engine) as session:
        yield session
