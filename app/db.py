import json
from datetime import datetime

from sqlalchemy import Column, Index, Text, inspect, text
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
    geo_lat: float | None = None
    geo_lon: float | None = None
    status: str = Field(default="unknown")  # online, offline, error, rate_limited
    last_error: str | None = None

    __table_args__ = (Index("idx_ip_port", "ip", "port"),)


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


class HostGroup(SQLModel, table=True):
    __tablename__ = "host_groups"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = None
    country_filter: str | None = Field(default=None, index=True)
    system_filter: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HostGroupMember(SQLModel, table=True):
    __tablename__ = "host_group_members"

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="host_groups.id", index=True)
    host_id: int = Field(foreign_key="hosts.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


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


class TaskJob(SQLModel, table=True):
    __tablename__ = "task_jobs"

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(sa_column=Column(Text, unique=True, index=True))
    kind: str = Field(index=True)
    label: str | None = None
    status: str = Field(default="queued", index=True)
    total_items: int = 0
    processed_items: int = 0
    success_items: int = 0
    failed_items: int = 0
    message: str | None = None
    error: str | None = None
    payload_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json) if self.payload_json else {}

    @payload.setter
    def payload(self, value: dict):
        self.payload_json = json.dumps(value)


class Workflow(SQLModel, table=True):
    __tablename__ = "workflows"

    workflow_id: str = Field(primary_key=True)
    scan_id: int | None = Field(default=None, index=True)
    workflow_kind: str = Field(default="one-off", index=True)
    target: str
    port: str
    strategy: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    current_stage: str | None = Field(default=None, index=True)
    operator_id: str | None = None
    exclude_snapshot_hash: str
    policy_snapshot_hash: str
    parent_workflow_id: str | None = None
    requested_config_json: str = Field(default="{}", sa_column=Column(Text))
    summary_json: str = Field(default="{}", sa_column=Column(Text))
    last_error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def requested_config(self) -> dict:
        return json.loads(self.requested_config_json) if self.requested_config_json else {}

    @requested_config.setter
    def requested_config(self, value: dict):
        self.requested_config_json = json.dumps(value)

    @property
    def summary(self) -> dict:
        return json.loads(self.summary_json) if self.summary_json else {}

    @summary.setter
    def summary(self, value: dict):
        self.summary_json = json.dumps(value)


class WorkflowStageReceipt(SQLModel, table=True):
    __tablename__ = "workflow_stage_receipts"

    receipt_id: str = Field(primary_key=True)
    workflow_id: str = Field(foreign_key="workflows.workflow_id", index=True)
    stage_name: str = Field(index=True)
    status: str = Field(index=True)
    operator_id: str | None = None
    input_refs_json: str = Field(default="[]", sa_column=Column(Text))
    output_refs_json: str = Field(default="[]", sa_column=Column(Text))
    metrics_json: str = Field(default="{}", sa_column=Column(Text))
    evidence_refs_json: str = Field(default="[]", sa_column=Column(Text))
    policy_decisions_json: str = Field(default="[]", sa_column=Column(Text))
    error: str | None = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None

    @property
    def input_refs(self) -> list:
        return json.loads(self.input_refs_json) if self.input_refs_json else []

    @input_refs.setter
    def input_refs(self, value: list):
        self.input_refs_json = json.dumps(value)

    @property
    def output_refs(self) -> list:
        return json.loads(self.output_refs_json) if self.output_refs_json else []

    @output_refs.setter
    def output_refs(self, value: list):
        self.output_refs_json = json.dumps(value)

    @property
    def metrics(self) -> dict:
        return json.loads(self.metrics_json) if self.metrics_json else {}

    @metrics.setter
    def metrics(self, value: dict):
        self.metrics_json = json.dumps(value)

    @property
    def evidence_refs(self) -> list:
        return json.loads(self.evidence_refs_json) if self.evidence_refs_json else []

    @evidence_refs.setter
    def evidence_refs(self, value: list):
        self.evidence_refs_json = json.dumps(value)

    @property
    def policy_decisions(self) -> list:
        return json.loads(self.policy_decisions_json) if self.policy_decisions_json else []

    @policy_decisions.setter
    def policy_decisions(self, value: list):
        self.policy_decisions_json = json.dumps(value)


engine = None
SessionLocal = None


def _ensure_legacy_sqlite_columns(engine) -> None:
    inspector = inspect(engine)
    if "hosts" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("hosts")}
    required_columns = {
        "geo_lat": "REAL",
        "geo_lon": "REAL",
    }

    missing = [
        (name, ddl_type)
        for name, ddl_type in required_columns.items()
        if name not in existing_columns
    ]
    if not missing:
        return

    with engine.begin() as connection:
        for name, ddl_type in missing:
            connection.execute(text(f"ALTER TABLE hosts ADD COLUMN {name} {ddl_type}"))


def _ensure_legacy_sqlite_tables(engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "host_groups" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE host_groups (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR NOT NULL UNIQUE,
                        description VARCHAR,
                        country_filter VARCHAR,
                        system_filter VARCHAR,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                    """
                )
            )
        if "host_group_members" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE host_group_members (
                        id INTEGER PRIMARY KEY,
                        group_id INTEGER NOT NULL,
                        host_id INTEGER NOT NULL,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )


def init_db(database_url: str = None):
    global engine, SessionLocal
    from app.config import settings

    db_url = database_url or settings.database_url
    engine_kwargs = {"echo": False, "pool_pre_ping": True}
    if "sqlite" in db_url:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(db_url, **engine_kwargs)
    SQLModel.metadata.create_all(engine)
    if "sqlite" in db_url:
        _ensure_legacy_sqlite_columns(engine)
        _ensure_legacy_sqlite_tables(engine)

    from sqlmodel import Session

    SessionLocal = Session


def get_session():
    with Session(engine) as session:
        yield session
