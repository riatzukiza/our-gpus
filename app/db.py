from sqlmodel import Field, SQLModel, Session, create_engine
from typing import Optional
from datetime import datetime
from sqlalchemy import Column, Index, Float, Text
import json


class Host(SQLModel, table=True):
    __tablename__ = "hosts"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    port: int
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: Optional[float] = None
    api_version: Optional[str] = None
    os: Optional[str] = None
    arch: Optional[str] = None
    ram_gb: Optional[float] = None
    gpu: Optional[str] = None
    gpu_vram_mb: Optional[int] = None
    geo_country: Optional[str] = None
    geo_city: Optional[str] = None
    status: str = Field(default="unknown")  # online, offline, error, rate_limited
    last_error: Optional[str] = None
    
    __table_args__ = (
        Index("idx_ip_port", "ip", "port"),
    )


class Model(SQLModel, table=True):
    __tablename__ = "models"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    family: Optional[str] = Field(index=True)
    size_mb: Optional[int] = None
    parameters: Optional[str] = None
    sha256: Optional[str] = None


class HostModel(SQLModel, table=True):
    __tablename__ = "host_models"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    host_id: int = Field(foreign_key="hosts.id")
    model_id: int = Field(foreign_key="models.id")
    quantization: Optional[str] = None
    size_mb: Optional[int] = None
    loaded: bool = Field(default=False)
    vram_usage_mb: Optional[int] = None


class Scan(SQLModel, table=True):
    __tablename__ = "scans"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    source_file: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    mapping_json: str = Field(sa_column=Column(Text))  # JSON field mapping
    stats_json: str = Field(sa_column=Column(Text))  # JSON stats
    status: str = Field(default="pending")  # pending, processing, completed, failed
    total_rows: int = 0
    processed_rows: int = 0
    error_message: Optional[str] = None
    
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
    
    id: Optional[int] = Field(default=None, primary_key=True)
    host_id: int = Field(foreign_key="hosts.id", index=True)
    status: str  # success, timeout, error, non_ollama
    duration_ms: float
    raw_payload: str = Field(sa_column=Column(Text))  # JSON response, capped
    error: Optional[str] = None
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