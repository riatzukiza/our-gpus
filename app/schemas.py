from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    source: str = Field(description="upload or file path")
    field_map: dict[str, str] = Field(default_factory=lambda: {"ip": "ip", "port": "port"})
    scan_label: str | None = None


class IngestResponse(BaseModel):
    scan_id: int
    status: str
    task_id: str


class ScanResponse(BaseModel):
    id: int
    workflow_id: str | None = None
    source_file: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    total_rows: int
    processed_rows: int
    mapping: dict[str, Any]
    stats: dict[str, Any]
    error_message: str | None


class ProbeRequest(BaseModel):
    host_ids: list[int] | None = None
    filter: dict[str, Any] | None = None
    probe_all: bool = False


class HostResponse(BaseModel):
    id: int
    ip: str
    port: int
    status: str
    last_seen: datetime
    first_seen: datetime | None = None
    latency_ms: float | None
    api_version: str | None
    os: str | None = None
    arch: str | None = None
    ram_gb: float | None = None
    gpu: str | None
    gpu_vram_mb: int | None
    geo_country: str | None = None
    geo_city: str | None = None
    groups: list[str] | None = None
    models: list[Any]
    last_probe: dict[str, Any] | None = None
    # Enrichment fields
    isp: str | None = None
    org: str | None = None
    asn: str | None = None
    cloud_provider: str | None = None
    abuse_email: str | None = None
    enriched_at: datetime | None = None


class HostGroupCreateRequest(BaseModel):
    name: str
    description: str | None = None
    country_filter: str | None = None
    system_filter: str | None = None
    host_ids: list[int] = Field(default_factory=list)


class HostGroupUpdateRequest(BaseModel):
    description: str | None = None
    country_filter: str | None = None
    system_filter: str | None = None
    host_ids: list[int] | None = None


class HostGroupResponse(BaseModel):
    id: int
    name: str
    description: str | None
    country_filter: str | None
    system_filter: str | None
    host_count: int
    created_at: datetime
    updated_at: datetime


class ModelResponse(BaseModel):
    id: int
    name: str
    family: str | None
    parameters: str | None
    host_count: int


class ExportRequest(BaseModel):
    format: str = "csv"
    filters: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


class PaginatedHostResponse(BaseModel):
    items: list[HostResponse]
    total: int
    page: int
    size: int
    pages: int


class PromptRequest(BaseModel):
    host_id: int
    model: str
    prompt: str
    stream: bool = False


class PromptResponse(BaseModel):
    success: bool
    response: str | None = None
    error: str | None = None
    model: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_duration: int | None = None
    eval_duration: int | None = None
    eval_count: int | None = None


class WorkflowReceiptResponse(BaseModel):
    receipt_id: str
    workflow_id: str
    stage_name: str
    status: str
    operator_id: str | None = None
    input_refs: list[str]
    output_refs: list[str]
    metrics: dict[str, Any]
    evidence_refs: list[str]
    policy_decisions: list[str]
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class WorkflowResponse(BaseModel):
    workflow_id: str
    scan_id: int | None = None
    workflow_kind: str
    target: str
    port: str
    strategy: str
    status: str
    current_stage: str | None = None
    operator_id: str | None = None
    exclude_snapshot_hash: str
    policy_snapshot_hash: str
    parent_workflow_id: str | None = None
    requested_config: dict[str, Any]
    summary: dict[str, Any]
    last_error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowDetailResponse(WorkflowResponse):
    receipts: list[WorkflowReceiptResponse]
