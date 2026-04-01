import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Column, Index, Text, UniqueConstraint, inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine


def _uuid_str() -> str:
    return str(uuid4())


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


class Organization(SQLModel, table=True):
    __tablename__ = "organizations"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    name: str
    normalized_name: str = Field(index=True)
    country_code: str | None = Field(default=None, max_length=2)
    confidence_baseline: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("normalized_name", "country_code", name="uq_organizations_name_country"),
    )


class AutonomousSystem(SQLModel, table=True):
    __tablename__ = "asns"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    asn: int = Field(index=True)
    org_name: str | None = None
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    rir: str | None = None
    country_code: str | None = Field(default=None, max_length=2)
    rdap_handle: str | None = None
    rdap_url: str | None = None
    raw_last_verified_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DomainRecord(SQLModel, table=True):
    __tablename__ = "domains"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    fqdn: str = Field(index=True)
    root_domain: str | None = Field(default=None, index=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    source_type: str
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (UniqueConstraint("fqdn", name="uq_domains_fqdn"),)


class Asset(SQLModel, table=True):
    __tablename__ = "assets"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    ip: str | None = Field(default=None, index=True)
    hostname: str | None = Field(default=None, index=True)
    domain: str | None = Field(default=None, index=True)
    port: int | None = None
    protocol: str | None = None
    service: str | None = None
    asn_id: str | None = Field(default=None, foreign_key="asns.id", index=True)
    country_code: str | None = Field(default=None, max_length=2)
    region: str | None = None
    city: str | None = None
    observed_banner_hash: str | None = None
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ip", "port", "protocol", name="uq_assets_ip_port_protocol"),
        UniqueConstraint("hostname", "port", "protocol", name="uq_assets_hostname_port_protocol"),
        CheckConstraint(
            "ip IS NOT NULL OR hostname IS NOT NULL OR domain IS NOT NULL",
            name="ck_assets_identity_present",
        ),
    )


class AssetDomain(SQLModel, table=True):
    __tablename__ = "asset_domains"

    asset_id: str = Field(foreign_key="assets.id", primary_key=True)
    domain_id: str = Field(foreign_key="domains.id", primary_key=True)
    relationship: str = Field(primary_key=True)
    confidence: float = 0.0
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class RawFetch(SQLModel, table=True):
    __tablename__ = "raw_fetches"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    source_type: str = Field(index=True)
    fetch_kind: str
    asset_id: str | None = Field(default=None, foreign_key="assets.id", index=True)
    domain_id: str | None = Field(default=None, foreign_key="domains.id", index=True)
    asn_id: str | None = Field(default=None, foreign_key="asns.id")
    organization_id: str | None = Field(default=None, foreign_key="organizations.id")
    request_url: str
    canonical_url: str | None = None
    request_key: str
    http_status: int | None = None
    fetch_status: str = Field(default="pending", index=True)
    transport_ok: bool = False
    parse_ok: bool = False
    extraction_ok: bool = False
    content_type: str | None = None
    content_hash: str | None = None
    etag: str | None = None
    artifact_uri: str | None = None
    parser_version: str | None = None
    fetched_at: datetime | None = None
    last_verified_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )


class ContactEndpoint(SQLModel, table=True):
    __tablename__ = "contacts"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    domain_id: str | None = Field(default=None, foreign_key="domains.id", index=True)
    contact_type: str = Field(index=True)
    value: str
    value_normalized: str = Field(index=True)
    source_type: str
    source_url: str | None = None
    is_role_account: bool = False
    confidence: float = 0.0
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    last_verified_at: datetime | None = None
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )


class SourceObservation(SQLModel, table=True):
    __tablename__ = "source_observations"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    raw_fetch_id: str = Field(foreign_key="raw_fetches.id", index=True)
    asset_id: str | None = Field(default=None, foreign_key="assets.id", index=True)
    domain_id: str | None = Field(default=None, foreign_key="domains.id", index=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id")
    asn_id: str | None = Field(default=None, foreign_key="asns.id")
    contact_id: str | None = Field(default=None, foreign_key="contacts.id")
    evidence_type: str = Field(index=True)
    raw_value: str | None = None
    normalized_value: str | None = None
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    weight: float = 0.0
    confidence: float = 0.0
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )


class OrgCandidate(SQLModel, table=True):
    __tablename__ = "org_candidates"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    asset_id: str = Field(foreign_key="assets.id", index=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id")
    name: str
    normalized_name: str
    score: float = 0.0
    org_conflict_penalty: float = 0.0
    rationale: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_evaluated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("asset_id", "normalized_name", name="uq_org_candidates_asset_name"),
    )


class OrgResolution(SQLModel, table=True):
    __tablename__ = "org_resolutions"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    asset_id: str = Field(foreign_key="assets.id", unique=True, index=True)
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    winning_org_candidate_id: str | None = Field(default=None, foreign_key="org_candidates.id")
    resolution_mode: str = "auto"
    confidence: float = 0.0
    rationale: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    resolved_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: datetime | None = None
    reviewer_note: str | None = None


class LeadRecord(SQLModel, table=True):
    __tablename__ = "lead_records"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    asset_id: str = Field(foreign_key="assets.id", unique=True, index=True)
    org_resolution_id: str | None = Field(default=None, foreign_key="org_resolutions.id")
    organization_id: str | None = Field(default=None, foreign_key="organizations.id", index=True)
    primary_contact_id: str | None = Field(default=None, foreign_key="contacts.id")
    confidence_score: float = 0.0
    org_confidence: float = 0.0
    contact_quality: float = 0.0
    route_legitimacy: float = 0.0
    org_conflict_penalty: float = 0.0
    status: str = Field(default="new", index=True)
    recommended_route: str | None = None
    notes: str | None = None
    scorer_version: str | None = None
    resolver_version: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_resolved_at: datetime | None = None


class LeadContactCandidate(SQLModel, table=True):
    __tablename__ = "lead_contact_candidates"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    lead_record_id: str = Field(foreign_key="lead_records.id", index=True)
    contact_id: str = Field(foreign_key="contacts.id")
    route: str
    rank: int
    score: float = 0.0
    org_confidence: float = 0.0
    contact_quality: float = 0.0
    route_legitimacy: float = 0.0
    org_conflict_penalty: float = 0.0
    rationale: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    last_evaluated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("lead_record_id", "contact_id", "route", name="uq_lead_contact_candidates"),
        CheckConstraint("rank > 0", name="ck_lead_contact_candidates_rank_positive"),
    )


class CampaignCluster(SQLModel, table=True):
    __tablename__ = "campaign_clusters"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    cluster_type: str
    cluster_key: str
    geo_region: str | None = None
    org_density: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("cluster_type", "cluster_key", name="uq_campaign_clusters_key"),
    )


class CampaignClusterMember(SQLModel, table=True):
    __tablename__ = "campaign_cluster_members"

    cluster_id: str = Field(foreign_key="campaign_clusters.id", primary_key=True)
    lead_record_id: str = Field(foreign_key="lead_records.id", primary_key=True)
    membership_score: float = 0.0


class EnrichmentRun(SQLModel, table=True):
    __tablename__ = "enrichment_runs"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    asset_id: str = Field(foreign_key="assets.id", unique=True, index=True)
    rdap_status: str = "pending"
    ptr_status: str = "pending"
    tls_ct_status: str = "pending"
    security_txt_status: str = "pending"
    contact_page_status: str = "pending"
    last_error_by_source: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source_versions: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EnrichmentJob(SQLModel, table=True):
    __tablename__ = "enrichment_jobs"

    id: str = Field(default_factory=_uuid_str, primary_key=True)
    job_type: str = Field(index=True)
    status: str = Field(index=True)
    asset_id: str | None = Field(default=None, foreign_key="assets.id", index=True)
    lead_record_id: str | None = Field(default=None, foreign_key="lead_records.id", index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    attempts: int = 0
    scheduled_at: datetime = Field(default_factory=datetime.utcnow)
    run_after: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    worker_hint: str | None = None
    last_error: str | None = None


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
