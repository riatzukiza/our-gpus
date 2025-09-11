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
    models: list[Any]
    last_probe: dict[str, Any] | None = None


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
