from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime


class IngestRequest(BaseModel):
    source: str = Field(description="upload or file path")
    field_map: Dict[str, str] = Field(default_factory=lambda: {"ip": "ip", "port": "port"})
    scan_label: Optional[str] = None


class IngestResponse(BaseModel):
    scan_id: int
    status: str
    task_id: str


class ScanResponse(BaseModel):
    id: int
    source_file: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_rows: int
    processed_rows: int
    mapping: Dict[str, Any]
    stats: Dict[str, Any]
    error_message: Optional[str]


class ProbeRequest(BaseModel):
    host_ids: Optional[List[int]] = None
    filter: Optional[Dict[str, Any]] = None


class HostResponse(BaseModel):
    id: int
    ip: str
    port: int
    status: str
    last_seen: datetime
    first_seen: Optional[datetime] = None
    latency_ms: Optional[float]
    api_version: Optional[str]
    os: Optional[str] = None
    arch: Optional[str] = None
    ram_gb: Optional[float] = None
    gpu: Optional[str]
    gpu_vram_mb: Optional[int]
    geo_country: Optional[str] = None
    geo_city: Optional[str] = None
    models: List[Any]
    last_probe: Optional[Dict[str, Any]] = None


class ModelResponse(BaseModel):
    id: int
    name: str
    family: Optional[str]
    parameters: Optional[str]
    host_count: int


class ExportRequest(BaseModel):
    format: str = "csv"
    filters: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


class PaginatedHostResponse(BaseModel):
    items: List[HostResponse]
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
    response: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_duration: Optional[int] = None
    eval_count: Optional[int] = None