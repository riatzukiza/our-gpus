import csv
import hashlib
import io
import ipaddress
import json
from collections import deque
from datetime import datetime
from pathlib import Path

from celery.result import AsyncResult
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.cidr_split import load_exclude_list
from app.config import settings
from app.db import (
    Host,
    HostGroup,
    HostGroupMember,
    HostModel,
    Model,
    Probe,
    Scan,
    TaskJob,
    Workflow,
    WorkflowStageReceipt,
    get_session,
    init_db,
)
from app.geocode import GeoService
from app.ingest import IngestService
from app.masscan import MasscanService
from app.probe import ProbeService
from app.schemas import (
    HealthResponse,
    HostGroupCreateRequest,
    HostGroupResponse,
    HostGroupUpdateRequest,
    HostResponse,
    IngestResponse,
    ModelResponse,
    PaginatedHostResponse,
    ProbeRequest,
    PromptRequest,
    PromptResponse,
    ScanResponse,
    WorkflowDetailResponse,
    WorkflowReceiptResponse,
    WorkflowResponse,
)
from app.shodan_queries import build_shodan_query_plan
from worker.celery_app import celery_app
from worker.tasks import register_task_job

app = FastAPI(title="our gpu API", version="1.0.0")
app.include_router(lead_router)

# Metrics
ingest_counter = Counter("ingest_total", "Total ingests started")
probe_counter = Counter("probe_total", "Total probes initiated", ["status"])
request_duration = Histogram("request_duration_seconds", "Request duration", ["endpoint"])

_ACO_GEO_LOOKUP_CACHE: dict[str, dict[str, object]] = {}

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "*",
        "CF-Access-JWT-Assertion",
        "CF-Access-Client-Id",
        "CF-Access-Client-Secret",
        "X-Requested-With",
    ],
)


@app.on_event("startup")
async def startup():
    init_db()


def require_admin_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected_key = settings.get_admin_api_key()
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key is not configured",
        )

    if not x_api_key or not secrets.compare_digest(x_api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin API key",
        )


def _serialize_task_job(job: TaskJob) -> dict:
    celery_state = AsyncResult(job.task_id, app=celery_app).state
    return {
        "task_id": job.task_id,
        "kind": job.kind,
        "label": job.label,
        "status": job.status,
        "celery_state": celery_state,
        "total_items": job.total_items,
        "processed_items": job.processed_items,
        "success_items": job.success_items,
        "failed_items": job.failed_items,
        "message": job.message,
        "error": job.error,
        "payload": job.payload,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _serialize_workflow_receipt(receipt: WorkflowStageReceipt) -> WorkflowReceiptResponse:
    return WorkflowReceiptResponse(
        receipt_id=receipt.receipt_id,
        workflow_id=receipt.workflow_id,
        stage_name=receipt.stage_name,
        status=receipt.status,
        operator_id=receipt.operator_id,
        input_refs=receipt.input_refs,
        output_refs=receipt.output_refs,
        metrics=receipt.metrics,
        evidence_refs=receipt.evidence_refs,
        policy_decisions=receipt.policy_decisions,
        error=receipt.error,
        started_at=receipt.started_at,
        finished_at=receipt.finished_at,
    )


def _serialize_workflow(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=workflow.workflow_id,
        scan_id=workflow.scan_id,
        workflow_kind=workflow.workflow_kind,
        target=workflow.target,
        port=workflow.port,
        strategy=workflow.strategy,
        status=workflow.status,
        current_stage=workflow.current_stage,
        operator_id=workflow.operator_id,
        exclude_snapshot_hash=workflow.exclude_snapshot_hash,
        policy_snapshot_hash=workflow.policy_snapshot_hash,
        parent_workflow_id=workflow.parent_workflow_id,
        requested_config=workflow.requested_config,
        summary=workflow.summary,
        last_error=workflow.last_error,
        created_at=workflow.created_at,
        started_at=workflow.started_at,
        completed_at=workflow.completed_at,
    )


def _apply_host_filters(
    query,
    *,
    model=None,
    family=None,
    gpu=None,
    status=None,
    country=None,
    system=None,
    group_id=None,
):
    needs_model_join = bool(model or family)
    if needs_model_join:
        query = query.join(HostModel).join(Model)

    if model:
        query = query.where(Model.name.contains(model))
    if family:
        query = query.where(Model.family == family)
    if gpu is not None:
        if gpu:
            query = query.where((Host.gpu == "available") | (Host.gpu_vram_mb > 0))
        else:
            query = query.where(
                (Host.gpu.is_(None)) & ((Host.gpu_vram_mb == 0) | (Host.gpu_vram_mb.is_(None)))
            )
    if status:
        query = query.where(Host.status == status)
    if country:
        query = query.where(Host.geo_country == country)
    if system:
        if system == "gpu":
            query = query.where((Host.gpu == "available") | (Host.gpu_vram_mb > 0))
        elif system == "cpu":
            query = query.where(
                (Host.gpu.is_(None)) & ((Host.gpu_vram_mb == 0) | (Host.gpu_vram_mb.is_(None)))
            )
    if group_id is not None:
        query = query.join(HostGroupMember).where(HostGroupMember.group_id == group_id)

    return query


def _inspect_workers() -> dict:
    inspector = celery_app.control.inspect(timeout=1)
    active = inspector.active() or {}
    reserved = inspector.reserved() or {}
    scheduled = inspector.scheduled() or {}
    stats = inspector.stats() or {}

    worker_names = sorted(set(active) | set(reserved) | set(scheduled) | set(stats))
    workers = []
    for worker_name in worker_names:
        workers.append(
            {
                "name": worker_name,
                "online": worker_name in stats,
                "active_count": len(active.get(worker_name, [])),
                "reserved_count": len(reserved.get(worker_name, [])),
                "scheduled_count": len(scheduled.get(worker_name, [])),
            }
        )

    return {
        "workers": workers,
        "totals": {
            "workers": len(workers),
            "active": sum(worker["active_count"] for worker in workers),
            "reserved": sum(worker["reserved_count"] for worker in workers),
            "scheduled": sum(worker["scheduled_count"] for worker in workers),
        },
    }


@app.post("/api/ingest", response_model=IngestResponse)
async def start_ingest(
    file: UploadFile | None = File(None),
    source: str = Form("upload"),
    field_map: str = Form("{}"),
    session: Session = Depends(get_session),
):
    ingest_counter.inc()

    # Handle plain text files with ip:port format
    if file and file.filename and file.filename.endswith(".txt"):
        file_content = await file.read()

        # Create scan record for text file
        scan = Scan(
            source_file=file.filename,
            mapping_json=json.dumps({}),  # No mapping needed for txt files
            status="pending",
        )
        session.add(scan)
        session.commit()
        session.refresh(scan)

        # Process text file directly
        ingest_service = IngestService(session)
        try:
            records = list(ingest_service.parse_stream(file_content, {}))
            success, failed = ingest_service.process_batch(
                records,
                scan.id or 0,
                auto_probe_new_hosts=True,
            )

            # Update scan status
            scan.status = "completed"
            scan.completed_at = datetime.utcnow()
            scan.total_rows = len(records)
            scan.processed_rows = success
            scan.stats_json = json.dumps({"success": success, "failed": failed})
            session.commit()

        except Exception as e:
            scan.status = "failed"
            scan.error_message = str(e)
            session.commit()

        return IngestResponse(scan_id=scan.id, status=scan.status, task_id=f"task-{scan.id}")

    # Original logic for JSON/JSONL files
    if not file:
        raise HTTPException(400, "No file provided")

    field_mapping = json.loads(field_map) if field_map else {}
    scan = Scan(
        source_file=file.filename if file else source,
        mapping_json=json.dumps(field_mapping),
        status="pending",
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)

    # Process synchronously for now (simplified approach)
    try:
        file_content = await file.read()
        ingest_service = IngestService(session)

        # Set scan to processing
        scan.status = "processing"
        scan.started_at = datetime.now()
        session.commit()

        # Process the file
        records = list(ingest_service.parse_stream(file_content, field_mapping))
        scan.total_rows = len(records)
        session.commit()

        success, failed = ingest_service.process_batch(
            records,
            scan.id or 0,
            auto_probe_new_hosts=True,
        )

        # Update scan status
        scan.status = "completed"
        scan.completed_at = datetime.now()
        scan.processed_rows = success + failed
        scan.stats_json = json.dumps({"success": success, "failed": failed})
        session.commit()

        return IngestResponse(scan_id=scan.id, status="completed", task_id=f"sync-{scan.id}")

    except Exception as e:
        scan.status = "failed"
        scan.error_message = str(e)
        session.commit()
        raise HTTPException(500, f"Processing failed: {str(e)}") from None


@app.get("/api/scans/{scan_id}", response_model=ScanResponse)
async def get_scan(scan_id: int, session: Session = Depends(get_session)):
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")

    return ScanResponse(
        id=scan.id,
        workflow_id=scan.mapping.get("workflow_id"),
        source_file=scan.source_file,
        status=scan.status,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        total_rows=scan.total_rows,
        processed_rows=scan.processed_rows,
        mapping=scan.mapping,
        stats=scan.stats,
        error_message=scan.error_message,
    )


@app.get("/api/admin/workflows", response_model=list[WorkflowResponse])
async def list_workflows(
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    workflows = session.exec(
        select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
    ).all()
    return [_serialize_workflow(workflow) for workflow in workflows]


@app.get("/api/admin/workflows/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
    workflow_id: str,
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    receipts = session.exec(
        select(WorkflowStageReceipt)
        .where(WorkflowStageReceipt.workflow_id == workflow_id)
        .order_by(WorkflowStageReceipt.started_at.asc())
    ).all()

    workflow_response = _serialize_workflow(workflow)
    return WorkflowDetailResponse(
        **workflow_response.model_dump(),
        receipts=[_serialize_workflow_receipt(receipt) for receipt in receipts],
    )


@app.post("/api/probe")
async def trigger_probe(
    request: ProbeRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
):
    # Get hosts to probe
    query = select(Host)
    if request.host_ids:
        query = query.where(Host.id.in_(request.host_ids))
    elif request.filter:
        # Apply filters
        if "model" in request.filter:
            query = (
                query.join(HostModel)
                .join(Model)
                .where(Model.name.contains(request.filter["model"]))
            )
        if "family" in request.filter:
            query = (
                query.join(HostModel).join(Model).where(Model.family == request.filter["family"])
            )
        if "gpu" in request.filter:
            gpu_filter = request.filter["gpu"]
            if gpu_filter is True:
                query = query.where((Host.gpu == "available") | (Host.gpu_vram_mb > 0))
            elif gpu_filter is False:
                query = query.where(
                    (Host.gpu.is_(None)) & ((Host.gpu_vram_mb == 0) | (Host.gpu_vram_mb.is_(None)))
                )
        if "status" in request.filter:
            query = query.where(Host.status == request.filter["status"])
    elif not getattr(request, "probe_all", False):
        # Only apply default limit if probe_all is not explicitly set to True
        query = query.limit(100)  # Default limit

    hosts = session.exec(query).all()

    # Queue probe tasks
    total_hosts = len(hosts)

    if total_hosts == 0:
        return {"message": "No hosts found to probe", "task_ids": []}

    # Store start time for progress tracking
    probe_start_time = datetime.now()

    from worker.tasks import queue_host_probes

    host_ids = [host.id for host in hosts if host.id is not None]
    tasks = queue_host_probes(host_ids)
    for _ in host_ids:
        probe_counter.labels(status="queued").inc()

    if len(tasks) == 1 and len(host_ids) == 1:
        message = "Queued 1 probe task"
    else:
        message = f"Queued {len(host_ids)} host probes in {len(tasks)} batch tasks"

    # Add descriptive information
    if getattr(request, "probe_all", False):
        message += f" (probing all {total_hosts} hosts)"
    elif request.filter and len(hosts) < 1000:  # Only show details for reasonable numbers
        filter_desc = []
        if request.filter.get("model"):
            filter_desc.append(f"model: {request.filter['model']}")
        if request.filter.get("family"):
            filter_desc.append(f"family: {request.filter['family']}")
        if request.filter.get("status"):
            filter_desc.append(f"status: {request.filter['status']}")
        if request.filter.get("gpu") is not None:
            gpu_desc = "with GPU" if request.filter["gpu"] else "without GPU"
            filter_desc.append(gpu_desc)

        if filter_desc:
            message += f" ({', '.join(filter_desc)})"

    return {"message": message, "task_ids": tasks, "probe_start_time": probe_start_time.isoformat()}


@app.post("/api/probe/discovered")
async def trigger_discovered_probe_backlog(
    limit: int | None = Query(default=None, ge=1),
    batch_size: int | None = Query(default=None, ge=1, le=1000),
    _: None = Depends(require_admin_api_key),
):
    from worker.tasks import queue_discovered_hosts

    task = queue_discovered_hosts.delay(limit=limit, batch_size=batch_size)
    register_task_job(
        task.id,
        kind="queue_discovered_hosts",
        label="Queue discovered probe backlog",
        payload={"limit": limit, "batch_size": batch_size},
    )
    return {
        "message": "Queued background probe backlog task for discovered hosts",
        "task_id": task.id,
        "limit": limit,
        "batch_size": batch_size or settings.probe_batch_size,
    }


@app.post("/api/geocode/backlog")
async def trigger_geocode_backlog(
    limit: int | None = Query(default=None, ge=1),
    batch_size: int | None = Query(default=None, ge=1, le=1000),
    include_discovered: bool = Query(default=False),
    _: None = Depends(require_admin_api_key),
):
    from worker.tasks import queue_ungeocoded_hosts

    task = queue_ungeocoded_hosts.delay(
        limit=limit,
        batch_size=batch_size,
        include_discovered=include_discovered,
    )
    register_task_job(
        task.id,
        kind="queue_ungeocoded_hosts",
        label="Queue ungeocoded host backlog",
        payload={
            "limit": limit,
            "batch_size": batch_size,
            "include_discovered": include_discovered,
        },
    )
    return {
        "message": "Queued background geocode backlog task for hosts missing geography",
        "task_id": task.id,
        "limit": limit,
        "batch_size": batch_size or settings.probe_batch_size,
        "include_discovered": include_discovered,
    }


@app.get("/api/admin/session")
async def get_admin_session(_: None = Depends(require_admin_api_key)):
    return {"authorized": True}


@app.post("/api/admin/enrich-leads")
async def trigger_enrich_leads(
    limit: int | None = Query(default=None, ge=1),
    _: None = Depends(require_admin_api_key),
):
    from worker.tasks import enrich_leads

    task = enrich_leads.delay(limit=limit)
    return {
        "message": "Queued lead enrichment task",
        "task_id": task.id,
        "limit": limit,
    }


@app.get("/api/admin/enrichment-stats")
async def get_enrichment_stats(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    from app.db import Host

    total_probed = session.exec(
        select(func.count()).select_from(Host).where(Host.api_version != None)  # noqa: E711
    ).one()
    enriched = session.exec(
        select(func.count()).select_from(Host).where(Host.enriched_at != None)  # noqa: E711
    ).one()
    with_email = session.exec(
        select(func.count()).select_from(Host).where(Host.abuse_email != None)  # noqa: E711
    ).one()
    with_org = session.exec(
        select(func.count()).select_from(Host).where(Host.org != None)  # noqa: E711
    ).one()
    with_cloud = session.exec(
        select(func.count()).select_from(Host).where(Host.cloud_provider != None)  # noqa: E711
    ).one()

    # Cloud breakdown
    cloud_rows = session.exec(
        select(Host.cloud_provider, func.count(Host.id))
        .where(Host.cloud_provider != None)  # noqa: E711
        .group_by(Host.cloud_provider)
        .order_by(func.count(Host.id).desc())
    ).all()

    return {
        "total_probed": total_probed,
        "enriched": enriched,
        "pending": total_probed - enriched,
        "with_email": with_email,
        "with_org": with_org,
        "with_cloud": with_cloud,
        "cloud_breakdown": {row[0]: row[1] for row in cloud_rows},
    }


@app.get("/api/admin/jobs")
async def get_admin_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    jobs = session.exec(select(TaskJob).order_by(TaskJob.created_at.desc()).limit(limit)).all()
    summary_rows = session.exec(
        select(TaskJob.kind, TaskJob.status, func.count(TaskJob.id))
        .group_by(TaskJob.kind, TaskJob.status)
        .order_by(TaskJob.kind, TaskJob.status)
    ).all()

    summary: dict[str, dict[str, int]] = {}
    for kind, status_name, count in summary_rows:
        summary.setdefault(kind, {})[status_name] = count

    return {
        "workers": _inspect_workers(),
        "summary": summary,
        "jobs": [_serialize_task_job(job) for job in jobs],
    }


class MasscanRequest(BaseModel):
    target: str = "0.0.0.0/0"
    port: str = "11434"
    rate: int = 100000
    router_mac: str = "00:21:59:a0:cf:c1"
    strategy: str = TOR_CONNECT_STRATEGY
    tor_max_hosts: int | None = None
    tor_concurrency: int | None = None
    shodan_query: str | None = None
    shodan_page_limit: int | None = None
    shodan_max_matches: int | None = None
    shodan_max_queries: int | None = None
    shodan_query_max_length: int | None = None


class MasscanResponse(BaseModel):
    scan_id: int
    status: str
    message: str
    strategy: str


class ACOStartRequest(BaseModel):
    strategy: str | None = None
    port: str | None = None
    rate: int | None = None
    max_block_duration_s: float | None = None
    min_scan_interval_s: float | None = None
    breathing_room_s: float | None = None
    router_mac: str | None = None
    interface: str | None = None
    tor_max_hosts: int | None = None
    tor_concurrency: int | None = None
    aco_alpha: float | None = None
    aco_beta: float | None = None
    aco_decay: float | None = None
    aco_reinforcement: float | None = None
    aco_penalty: float | None = None


class ShodanQueryPlanRequest(BaseModel):
    target: str = "0.0.0.0/0"
    port: str = "11434"
    base_query: str = ""
    max_query_length: int = 900
    max_queries: int = 24


def _serialize_scheduler_config(config) -> dict:
    return {
        "strategy": normalize_scan_strategy_name(config.strategy),
        "port": config.port,
        "rate": config.rate,
        "max_block_duration_s": config.max_block_duration_s,
        "min_scan_interval_s": config.min_scan_interval_s,
        "breathing_room_s": config.breathing_room_s,
        "router_mac": config.router_mac,
        "interface": config.interface,
        "exclude_file": config.exclude_file,
        "aco_alpha": config.aco_alpha,
        "aco_beta": config.aco_beta,
        "aco_decay": config.aco_decay,
        "aco_reinforcement": config.aco_reinforcement,
        "aco_penalty": config.aco_penalty,
    }


@app.get("/api/admin/scanner/config")
async def get_admin_scanner_config(_: None = Depends(require_admin_api_key)):
    from app.masscan_aco import SchedulerConfig

    current = _aco_scheduler.config if _aco_scheduler else SchedulerConfig()
    strategy = normalize_scan_strategy_name(current.strategy)
    return {
        "aco": _serialize_scheduler_config(current),
        "tor": {
            "max_hosts": current.tor_max_hosts,
            "concurrency": current.tor_concurrency,
        },
        "shodan": {
            "api_key_configured": bool(settings.shodan_api_key),
            "base_query": settings.shodan_base_query,
            "page_limit": settings.shodan_page_limit,
            "max_matches": settings.shodan_max_matches,
            "max_queries": settings.shodan_max_queries,
            "query_max_length": settings.shodan_query_max_length,
        },
        "scan": {
            "target": "0.0.0.0/0",
            "port": current.port,
            "rate": current.rate,
            "router_mac": current.router_mac,
            "strategy": strategy,
        },
    }


@app.post("/api/admin/scanner/query-plan")
async def get_admin_shodan_query_plan(
    request: ShodanQueryPlanRequest,
    _: None = Depends(require_admin_api_key),
):
    plan = build_shodan_query_plan(
        target=request.target,
        port=request.port,
        exclude_files=settings.our_gpus_exclude_files,
        base_query=request.base_query,
        max_query_length=request.max_query_length,
        max_queries=request.max_queries,
    )
    return {
        "base_query": plan.base_query,
        "target": plan.target,
        "port": plan.port,
        "query_count": len(plan.queries),
        "queries": plan.queries,
        "total_excludes": plan.total_excludes,
        "applied_excludes": plan.applied_excludes,
        "omitted_excludes": plan.omitted_excludes,
        "max_query_length": plan.max_query_length,
    }


@app.post("/api/admin/scanner/run", response_model=MasscanResponse)
async def run_admin_scan(
    request: MasscanRequest,
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    service = ScanService(session)
    try:
        result = service.run_scan(
            target=request.target,
            port=request.port,
            rate=request.rate,
            router_mac=request.router_mac,
            strategy=request.strategy,
            tor_max_hosts=request.tor_max_hosts,
            tor_concurrency=request.tor_concurrency,
            shodan_query=request.shodan_query,
            shodan_page_limit=request.shodan_page_limit,
            shodan_max_matches=request.shodan_max_matches,
            shodan_max_queries=request.shodan_max_queries,
            shodan_query_max_length=request.shodan_query_max_length,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return MasscanResponse(
        scan_id=result["scan_id"],
        status="started",
        message=f"{result['strategy']} scan started. Output: {result['output_file']}",
        strategy=result["strategy"],
    )


@app.get("/api/hosts", response_model=PaginatedHostResponse)
async def list_hosts(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    model: str | None = None,
    family: str | None = None,
    gpu: bool | None = None,
    status: str | None = None,
    country: str | None = None,
    system: str | None = None,
    group_id: int | None = None,
    enriched: bool | None = None,
    cloud_provider: str | None = None,
    has_email: bool | None = None,
    sort: str = "last_seen",
    session: Session = Depends(get_session),
):
    base_query = _apply_host_filters(
        select(Host),
        model=model,
        family=family,
        gpu=gpu,
        status=status,
        country=country,
        system=system,
        group_id=group_id,
    )

    # Enrichment filters
    if enriched is not None:
        if enriched:
            base_query = base_query.where(Host.enriched_at != None)  # noqa: E711
        else:
            base_query = base_query.where(Host.enriched_at == None)  # noqa: E711
    if cloud_provider:
        base_query = base_query.where(Host.cloud_provider == cloud_provider)
    if has_email:
        base_query = base_query.where(Host.abuse_email != None)  # noqa: E711

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total = session.exec(count_query).one()

    # Sort
    query = base_query
    if sort == "last_seen":
        query = query.order_by(Host.last_seen.desc())
    elif sort == "latency":
        query = query.order_by(Host.latency_ms)

    # Paginate
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)

    hosts = session.exec(query).all()

    # Get models for each host
    result = []
    for h in hosts:
        host_models = session.exec(
            select(HostModel, Model).join(Model).where(HostModel.host_id == h.id)
        ).all()

        model_names = [m.name for hm, m in host_models]
        group_names = session.exec(
            select(HostGroup.name)
            .join(HostGroupMember, HostGroup.id == HostGroupMember.group_id)
            .where(HostGroupMember.host_id == h.id)
            .order_by(HostGroup.name)
        ).all()

        result.append(
            HostResponse(
                id=h.id,
                ip=h.ip,
                port=h.port,
                status=h.status,
                last_seen=h.last_seen,
                latency_ms=h.latency_ms,
                api_version=h.api_version,
                gpu=h.gpu,
                gpu_vram_mb=h.gpu_vram_mb,
                geo_country=h.geo_country,
                geo_city=h.geo_city,
                groups=group_names,
                models=model_names,
                isp=h.isp,
                org=h.org,
                asn=h.asn,
                cloud_provider=h.cloud_provider,
                abuse_email=h.abuse_email,
                enriched_at=h.enriched_at,
            )
        )

    return PaginatedHostResponse(
        items=result,
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,  # Calculate total pages
    )


@app.get("/api/models", response_model=list[ModelResponse])
async def list_models(session: Session = Depends(get_session)):
    models = session.exec(
        select(Model, func.count(HostModel.id).label("host_count"))
        .join(HostModel)
        .group_by(Model.id)
        .order_by(func.count(HostModel.id).desc())
    ).all()

    return [
        ModelResponse(
            id=m[0].id,
            name=m[0].name,
            family=m[0].family,
            parameters=m[0].parameters,
            host_count=m[1],
        )
        for m in models
    ]


@app.get("/api/models/names")
async def list_model_names(session: Session = Depends(get_session)):
    """Get unique model names for filter dropdown"""
    model_names = session.exec(
        select(Model.name).join(HostModel).group_by(Model.name).order_by(Model.name)
    ).all()

    return {"models": model_names}


@app.get("/api/models/families")
async def list_model_families(session: Session = Depends(get_session)):
    """Get unique model families for filter dropdown"""
    families = session.exec(
        select(Model.family).join(HostModel).group_by(Model.family).order_by(Model.family)
    ).all()

    return {"families": families}


@app.get("/api/hosts/countries")
async def list_host_countries(session: Session = Depends(get_session)):
    countries = session.exec(
        select(Host.geo_country)
        .where(Host.geo_country.is_not(None), Host.geo_country != "")
        .group_by(Host.geo_country)
        .order_by(Host.geo_country)
    ).all()
    return {"countries": countries}


@app.get("/api/hosts/{host_id}", response_model=HostResponse)
async def get_host(host_id: int, session: Session = Depends(get_session)):
    host = session.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")

    latest_probe = session.exec(
        select(Probe).where(Probe.host_id == host_id).order_by(Probe.created_at.desc()).limit(1)
    ).first()

    host_models = session.exec(
        select(HostModel, Model).join(Model).where(HostModel.host_id == host_id)
    ).all()

    models = [
        {
            "name": m.name,
            "family": m.family,
            "parameters": m.parameters,
            "loaded": hm.loaded,
            "vram_usage_mb": hm.vram_usage_mb,
        }
        for hm, m in host_models
    ]
    group_names = session.exec(
        select(HostGroup.name)
        .join(HostGroupMember, HostGroup.id == HostGroupMember.group_id)
        .where(HostGroupMember.host_id == host_id)
        .order_by(HostGroup.name)
    ).all()

    last_probe_data = None
    if latest_probe:
        try:
            last_probe_data = json.loads(latest_probe.raw_payload)
        except json.JSONDecodeError:
            last_probe_data = {"error": "Probe data truncated"}

    return HostResponse(
        id=host.id,
        ip=host.ip,
        port=host.port,
        status=host.status,
        last_seen=host.last_seen,
        first_seen=host.first_seen,
        latency_ms=host.latency_ms,
        api_version=host.api_version,
        os=host.os,
        arch=host.arch,
        ram_gb=host.ram_gb,
        gpu=host.gpu,
        gpu_vram_mb=host.gpu_vram_mb,
        geo_country=host.geo_country,
        geo_city=host.geo_city,
        groups=group_names,
        models=models,
        last_probe=last_probe_data,
        isp=host.isp,
        org=host.org,
        asn=host.asn,
        cloud_provider=host.cloud_provider,
        abuse_email=host.abuse_email,
        enriched_at=host.enriched_at,
    )


@app.get("/api/admin/groups", response_model=list[HostGroupResponse])
async def list_host_groups(
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    groups = session.exec(select(HostGroup).order_by(HostGroup.name)).all()
    result: list[HostGroupResponse] = []
    for group in groups:
        host_count = session.exec(
            select(func.count(HostGroupMember.id)).where(HostGroupMember.group_id == group.id)
        ).one()
        result.append(
            HostGroupResponse(
                id=group.id,
                name=group.name,
                description=group.description,
                country_filter=group.country_filter,
                system_filter=group.system_filter,
                host_count=host_count,
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
        )
    return result


@app.post("/api/admin/groups", response_model=HostGroupResponse)
async def create_host_group(
    request: HostGroupCreateRequest,
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    existing = session.exec(select(HostGroup).where(HostGroup.name == request.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Group name already exists")

    group = HostGroup(
        name=request.name.strip(),
        description=request.description,
        country_filter=request.country_filter,
        system_filter=request.system_filter,
    )
    session.add(group)
    session.commit()
    session.refresh(group)

    for host_id in request.host_ids:
        session.add(HostGroupMember(group_id=group.id, host_id=host_id))
    session.commit()

    return HostGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        country_filter=group.country_filter,
        system_filter=group.system_filter,
        host_count=len(request.host_ids),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@app.patch("/api/admin/groups/{group_id}", response_model=HostGroupResponse)
async def update_host_group(
    group_id: int,
    request: HostGroupUpdateRequest,
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    group = session.get(HostGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    group.description = request.description
    group.country_filter = request.country_filter
    group.system_filter = request.system_filter
    group.updated_at = datetime.utcnow()
    session.add(group)
    session.commit()

    if request.host_ids is not None:
        existing_members = session.exec(
            select(HostGroupMember).where(HostGroupMember.group_id == group_id)
        ).all()
        for member in existing_members:
            session.delete(member)
        session.commit()
        for host_id in request.host_ids:
            session.add(HostGroupMember(group_id=group_id, host_id=host_id))
        session.commit()

    host_count = session.exec(
        select(func.count(HostGroupMember.id)).where(HostGroupMember.group_id == group_id)
    ).one()
    session.refresh(group)
    return HostGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        country_filter=group.country_filter,
        system_filter=group.system_filter,
        host_count=host_count,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@app.delete("/api/admin/groups/{group_id}")
async def delete_host_group(
    group_id: int,
    _: None = Depends(require_admin_api_key),
    session: Session = Depends(get_session),
):
    group = session.get(HostGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    members = session.exec(
        select(HostGroupMember).where(HostGroupMember.group_id == group_id)
    ).all()
    for member in members:
        session.delete(member)
    session.delete(group)
    session.commit()
    return {"status": "deleted", "group_id": group_id}


@app.get("/api/export")
async def export_data(
    format: str = Query("csv", regex="^(csv|json)$"),
    model: str | None = None,
    family: str | None = None,
    gpu: bool | None = None,
    country: str | None = None,
    system: str | None = None,
    group_id: int | None = None,
    session: Session = Depends(get_session),
):
    query = _apply_host_filters(
        select(Host),
        model=model,
        family=family,
        gpu=gpu,
        country=country,
        system=system,
        group_id=group_id,
    )

    hosts = session.exec(query).all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "ip",
                "port",
                "status",
                "api_version",
                "gpu",
                "gpu_vram_mb",
                "models",
                "last_seen",
                "latency_ms",
            ],
        )
        writer.writeheader()

        for host in hosts:
            writer.writerow(
                {
                    "ip": host.ip,
                    "port": host.port,
                    "status": host.status,
                    "api_version": host.api_version,
                    "gpu": host.gpu,
                    "gpu_vram_mb": host.gpu_vram_mb,
                    "models": "",  # TODO: get models
                    "last_seen": host.last_seen.isoformat(),
                    "latency_ms": host.latency_ms,
                }
            )

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=ollama_hosts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            },
        )

    else:  # JSON
        data = [
            {
                "ip": host.ip,
                "port": host.port,
                "status": host.status,
                "api_version": host.api_version,
                "gpu": host.gpu,
                "gpu_vram_mb": host.gpu_vram_mb,
                "models": [],  # TODO: get models
                "last_seen": host.last_seen.isoformat(),
                "latency_ms": host.latency_ms,
            }
            for host in hosts
        ]

        return StreamingResponse(
            io.BytesIO(json.dumps(data, indent=2).encode()),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=ollama_hosts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            },
        )


@app.post("/api/hosts/{host_id}/prompt", response_model=PromptResponse)
async def run_prompt(host_id: int, request: PromptRequest, session: Session = Depends(get_session)):
    """Run a prompt against a specific model on an Ollama host"""
    # Get the host
    host = session.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")

    if host.status != "online":
        raise HTTPException(400, f"Host is not online (status: {host.status})")

    # Initialize probe service
    probe_service = ProbeService()

    # Run the prompt
    result = await probe_service.run_prompt(
        host_ip=host.ip,
        host_port=host.port,
        model=request.model,
        prompt=request.prompt,
        stream=request.stream,
    )

    if result["success"]:
        return PromptResponse(
            success=True,
            response=result.get("response"),
            model=result.get("model"),
            total_duration=result.get("total_duration"),
            load_duration=result.get("load_duration"),
            prompt_eval_duration=result.get("prompt_eval_duration"),
            eval_duration=result.get("eval_duration"),
            eval_count=result.get("eval_count"),
        )
    else:
        return PromptResponse(success=False, error=result.get("error", "Unknown error"))


@app.options("/api/hosts/{host_id}/prompt/stream")
async def options_stream_prompt(_host_id: int):
    """Handle preflight OPTIONS requests for streaming endpoint"""
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "CF-Access-JWT-Assertion, CF-Access-Client-Id, CF-Access-Client-Secret, Content-Type, Authorization, X-Requested-With",
            "Access-Control-Max-Age": "86400",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Expose-Headers": "*",
        },
    )


@app.post("/api/hosts/{host_id}/prompt/stream")
async def stream_prompt(
    host_id: int, request: PromptRequest, session: Session = Depends(get_session)
):
    """Stream a prompt response from an Ollama host using Server-Sent Events"""
    # Get the host
    host = session.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")

    if host.status != "online":
        raise HTTPException(400, f"Host is not online (status: {host.status})")

    # Initialize probe service
    probe_service = ProbeService()

    async def generate():
        """Generate SSE events with keep-alive pings"""
        try:
            import asyncio

            # Create a queue for chunks
            chunk_queue = asyncio.Queue()

            async def stream_from_ollama():
                """Stream from Ollama and put chunks in queue"""
                try:
                    async for chunk in probe_service.stream_prompt(
                        host_ip=host.ip,
                        host_port=host.port,
                        model=request.model,
                        prompt=request.prompt,
                    ):
                        await chunk_queue.put(chunk)
                    await chunk_queue.put(None)  # Sentinel to indicate done
                except Exception as e:
                    await chunk_queue.put({"type": "error", "content": str(e)})

            # Start the Ollama streaming task
            stream_task = asyncio.create_task(stream_from_ollama())

            # Stream with keep-alive pings every 15 seconds
            while True:
                try:
                    # Wait for chunk with timeout for keep-alive
                    chunk = await asyncio.wait_for(chunk_queue.get(), timeout=15.0)

                    if chunk is None:  # Stream completed
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break

                    # Format as Server-Sent Event
                    if chunk["type"] == "error":
                        yield f"data: {json.dumps({'error': chunk['content']})}\n\n"
                    else:
                        yield f"data: {json.dumps(chunk)}\n\n"

                    # If done, send final event
                    if chunk.get("done", False):
                        yield f"data: {json.dumps({'done': True})}\n\n"
                        break

                except TimeoutError:
                    # Send keep-alive ping
                    yield f"data: {json.dumps({'ping': True})}\n\n"

            await stream_task

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "CF-Access-JWT-Assertion, CF-Access-Client-Id, CF-Access-Client-Secret, Content-Type, Authorization",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Expose-Headers": "*",
        },
    )


@app.get("/healthz")
async def health_check():
    return HealthResponse(status="healthy", timestamp=datetime.utcnow())


@app.get("/readyz", response_model=HealthResponse)
async def ready_check(session: Session = Depends(get_session)):
    # Check DB connection
    try:
        session.exec(select(func.count(Host.id))).first()
    except Exception as e:
        raise HTTPException(503, f"Database not ready: {str(e)}") from e

    return HealthResponse(status="ready", timestamp=datetime.utcnow())


@app.delete("/api/hosts/{host_id}")
async def delete_host(
    host_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
):
    host = session.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")

    # Delete related records first
    session.exec(select(HostModel).where(HostModel.host_id == host_id)).all()
    for hm in session.exec(select(HostModel).where(HostModel.host_id == host_id)).all():
        session.delete(hm)

    session.exec(select(Probe).where(Probe.host_id == host_id)).all()
    for probe in session.exec(select(Probe).where(Probe.host_id == host_id)).all():
        session.delete(probe)

    session.delete(host)
    session.commit()

    return {"message": "Host deleted successfully"}


@app.delete("/api/hosts")
async def clear_all_hosts(
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
):
    # Delete all host-related records
    session.exec(select(HostModel)).all()
    for hm in session.exec(select(HostModel)).all():
        session.delete(hm)

    session.exec(select(Probe)).all()
    for probe in session.exec(select(Probe)).all():
        session.delete(probe)

    session.exec(select(Host)).all()
    host_count = 0
    for host in session.exec(select(Host)).all():
        session.delete(host)
        host_count += 1

    session.commit()

    return {"message": f"Cleared {host_count} hosts and related data"}


class ClearFilteredHostsRequest(BaseModel):
    model: str | None = None
    family: str | None = None
    gpu: bool | None = None
    status: str | None = None
    country: str | None = None
    system: str | None = None
    group_id: int | None = None


@app.post("/api/hosts/clear-filtered")
async def clear_filtered_hosts(
    request: ClearFilteredHostsRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
):
    """Clear hosts that match the specified filters"""
    query = _apply_host_filters(
        select(Host),
        model=request.model,
        family=request.family,
        gpu=request.gpu,
        status=request.status,
        country=request.country,
        system=request.system,
        group_id=request.group_id,
    )

    # Get hosts to delete
    hosts_to_delete = session.exec(query).all()
    host_ids_to_delete = [host.id for host in hosts_to_delete]

    if not host_ids_to_delete:
        return {"message": "No hosts match the specified filters", "cleared_count": 0}

    # Delete related records first
    if host_ids_to_delete:
        # Delete HostModel records
        host_models = session.exec(
            select(HostModel).where(HostModel.host_id.in_(host_ids_to_delete))
        ).all()
        for hm in host_models:
            session.delete(hm)

        # Delete Probe records
        probes = session.exec(select(Probe).where(Probe.host_id.in_(host_ids_to_delete))).all()
        for probe in probes:
            session.delete(probe)

        memberships = session.exec(
            select(HostGroupMember).where(HostGroupMember.host_id.in_(host_ids_to_delete))
        ).all()
        for membership in memberships:
            session.delete(membership)

    # Delete the hosts
    deleted_count = 0
    for host in hosts_to_delete:
        session.delete(host)
        deleted_count += 1

    session.commit()

    return {
        "message": f"Cleared {deleted_count} hosts matching filters",
        "cleared_count": deleted_count,
    }


@app.get("/api/probe-stats")
async def get_recent_probe_stats(
    minutes: int = Query(5, ge=1, le=60),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
):
    """Get probe statistics for the last N minutes"""
    from datetime import timedelta

    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)

    # Get recent probe statistics
    probe_stats = session.exec(
        select(
            Probe.status,
            func.count(Probe.id).label("count"),
            func.avg(Probe.duration_ms).label("avg_duration"),
        )
        .where(Probe.created_at >= cutoff_time)
        .group_by(Probe.status)
    ).all()

    # Get total counts
    total_recent = (
        session.exec(select(func.count(Probe.id)).where(Probe.created_at >= cutoff_time)).first()
        or 0
    )

    # Get total hosts and current status breakdown
    total_hosts = session.exec(select(func.count(Host.id))).first() or 0

    host_status_counts = session.exec(
        select(Host.status, func.count(Host.id).label("count")).group_by(Host.status)
    ).all()

    # Get sample errors for debugging
    sample_errors = session.exec(
        select(Probe.error)
        .where(Probe.created_at >= cutoff_time, Probe.status == "error", Probe.error.is_not(None))
        .limit(5)
    ).all()

    # Format statistics
    stats = {}
    for stat in probe_stats:
        stats[stat.status] = {
            "count": stat.count,
            "avg_duration_ms": round(stat.avg_duration, 2) if stat.avg_duration else 0,
        }

    host_statuses = {}
    for status_count in host_status_counts:
        host_statuses[status_count.status] = status_count.count

    return {
        "time_window_minutes": minutes,
        "total_hosts": total_hosts,
        "probes_completed": total_recent,
        "success_count": stats.get("success", {}).get("count", 0),
        "error_count": stats.get("error", {}).get("count", 0),
        "timeout_count": stats.get("timeout", {}).get("count", 0),
        "detailed_stats": stats,
        "host_status_breakdown": host_statuses,
        "sample_errors": [err for err in sample_errors if err],
        "last_updated": datetime.utcnow(),
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")


class MasscanRequest(BaseModel):
    target: str = "0.0.0.0/0"
    port: str = "11434"
    rate: int = 100000
    router_mac: str = "00:21:59:a0:cf:c1"


class MasscanResponse(BaseModel):
    scan_id: int
    status: str
    message: str


@app.post("/api/masscan", response_model=MasscanResponse)
async def run_masscan(
    request: MasscanRequest,
    session: Session = Depends(get_session),
):

    service = MasscanService(session)

    def run_in_background():
        service.run_scan(
            target=request.target,
            port=request.port,
            rate=request.rate,
            router_mac=request.router_mac,
        )

    result = service.run_scan(
        target=request.target,
        port=request.port,
        rate=request.rate,
        router_mac=request.router_mac,
    )

    return MasscanResponse(
        scan_id=result["scan_id"],
        status="started",
        message=f"Masscan started. Output: {result['output_file']}",
    )


@app.get("/api/masscan/{scan_id}")
async def get_masscan_status(
    scan_id: int,
    session: Session = Depends(get_session),
):
    service = MasscanService(session)
    return service.get_progress(scan_id)


@app.post("/api/masscan/{scan_id}/ingest")
async def ingest_masscan_results(
    scan_id: int,
    session: Session = Depends(get_session),
):
    service = MasscanService(session)
    results_file = service.get_results_file(scan_id)

    if not results_file:
        raise HTTPException(status_code=404, detail="Scan results not found")

    with open(results_file) as f:
        content = f.read()

    output_file = f"/workspace/imports/masscan-{scan_id}.txt"
    with open(output_file, "w") as f:
        for line in content.split("\n"):
            if '"ip":' in line:
                import re

                ip_match = re.search(r'"ip":\s*"([^"]+)"', line)
                if ip_match:
                    f.write(f"{ip_match.group(1)}:11434\n")

    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    scan.source_file = f"masscan-ingest:{scan_id}"
    session.commit()

    from app.ingest import IngestService

    ingest_service = IngestService(session)

    with open(output_file, "rb") as file_content:
        records = list(ingest_service.parse_stream(file_content.read(), {}))
        success, failed = ingest_service.process_batch(records, scan_id)

    return {
        "scan_id": scan_id,
        "hosts_ingested": success,
        "hosts_failed": failed,
    }


# ── ACO masscan block scheduler ──────────────────────────────────────────────

import logging  # noqa: E402

from app.ingest import IngestService as _IngestService  # noqa: E402
from app.masscan_aco import ACOMasscanScheduler, BlockScanResult  # noqa: E402

_aco_logger = logging.getLogger("aco_scheduler")
_aco_scheduler: ACOMasscanScheduler | None = None


def _on_aco_block_result(result: BlockScanResult) -> None:
    """Ingest ACO block scan results automatically."""
    if not result.success or result.hosts_found == 0:
        return
    try:
        from app.db import get_session as _get_session

        with next(_get_session()) as session:
            ingest = _IngestService(session)
            with open(result.output_file, "rb") as f:
                records = list(ingest.parse_stream(f.read(), {}))
                if records:
                    scan = Scan(
                        source_file=f"aco-block:{result.cidr}",
                        mapping_json="{}",
                        status="processing",
                    )
                    session.add(scan)
                    session.commit()
                    session.refresh(scan)
                    success, failed = ingest.process_batch(records, scan.id or 0)
                    scan.status = "completed"
                    scan.total_rows = len(records)
                    scan.processed_rows = success
                    scan.stats_json = json.dumps(
                        {"success": success, "failed": failed, "cidr": result.cidr}
                    )
                    session.commit()
                    _aco_logger.info("ACO block %s ingested: %d hosts", result.cidr, success)
    except Exception as e:
        _aco_logger.error("ACO block ingest failed for %s: %s", result.cidr, e)


def _aco_not_running_snapshot() -> dict:
    return {
        "status": "not_running",
        "started_at": None,
        "uptime_seconds": None,
        "prefix_len": None,
        "estimated_block_duration_s": None,
        "config": None,
        "stats": {
            "total_blocks": 0,
            "scanned_blocks": 0,
            "unscanned_blocks": 0,
            "total_yield": 0,
            "avg_pheromone": 0,
        },
        "current_job": None,
        "recent_results": [],
        "top_blocks": [],
        "last_error": None,
    }


def _get_aco_history(session: Session, limit: int = 20) -> list[dict]:
    scans = session.exec(
        select(Scan)
        .where(Scan.source_file.like("aco-block:%"))
        .order_by(Scan.started_at.desc())
        .limit(limit)
    ).all()

    history = []
    for scan in scans:
        stats = scan.stats
        cidr = stats.get("cidr")
        if not cidr and scan.source_file.startswith("aco-block:"):
            cidr = scan.source_file.split(":", 1)[1]

        history.append(
            {
                "scan_id": scan.id,
                "cidr": cidr,
                "status": scan.status,
                "started_at": scan.started_at.isoformat() if scan.started_at else None,
                "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
                "hosts_found": stats.get("success", scan.processed_rows),
                "failed_rows": stats.get("failed", 0),
                "processed_rows": scan.processed_rows,
                "error_message": scan.error_message,
            }
        )

    return history


def _get_host_geography(session: Session, limit: int = 20) -> dict:
    country_rows = session.exec(
        select(Host.geo_country, func.count(Host.id))
        .where(Host.geo_country.is_not(None), Host.geo_country != "")
        .group_by(Host.geo_country)
        .order_by(func.count(Host.id).desc())
        .limit(limit)
    ).all()

    known_hosts = session.exec(
        select(func.count())
        .select_from(Host)
        .where(Host.geo_country.is_not(None), Host.geo_country != "")
    ).one()
    unknown_hosts = session.exec(
        select(func.count())
        .select_from(Host)
        .where(or_(Host.geo_country.is_(None), Host.geo_country == ""))
    ).one()

    return {
        "known_hosts": known_hosts,
        "unknown_hosts": unknown_hosts,
        "countries": [
            {
                "country": country,
                "count": count,
            }
            for country, count in country_rows
            if country
        ],
    }


@app.get("/api/aco/dashboard")
async def get_aco_dashboard(
    history_limit: int = Query(default=20, ge=1, le=100),
    country_limit: int = Query(default=25, ge=1, le=100),
    session: Session = Depends(get_session),
):
    scheduler = (
        _aco_scheduler.dashboard_snapshot(result_limit=history_limit, block_limit=20)
        if _aco_scheduler
        else _aco_not_running_snapshot()
    )

    return {
        "status": scheduler["status"],
        "scheduler": scheduler,
        "history": _get_aco_history(session, history_limit),
        "geography": _get_host_geography(session, country_limit),
    }


def _read_log_file(log_path: str, max_lines: int = 200) -> str | None:
    """Read last N lines of a log file safely (most recent progress)."""
    try:
        p = Path(log_path)
        if not p.exists():
            print(f"[DEBUG] log file does not exist: {log_path}")
            return None
        content = p.read_text(errors="replace")
        all_lines = content.splitlines()
        last_lines = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines
        return "\n".join(last_lines)
    except Exception as e:
        print(f"[DEBUG] exception reading log file {log_path}: {e}")
        return None


@app.get("/api/aco/logs/current")
async def get_aco_current_logs(lines: int = Query(default=200, ge=1, le=2000)):
    """Get logs for the currently running scan, if any."""
    if not _aco_scheduler:
        return {"status": "not_running", "logs": None}

    with _aco_scheduler._state_lock:
        current = _aco_scheduler.current_job
        if not current:
            return {
                "status": "idle",
                "message": "No scan currently running",
                "last_error": _aco_scheduler.last_error,
                "logs": None,
            }

        log_path = current.log_file
        scan_info = {
            "cidr": current.cidr,
            "scan_uuid": current.scan_uuid,
            "started_at": current.started_at.isoformat(),
            "port": current.port,
            "rate": current.rate,
            "estimated_duration_s": current.estimated_duration_s,
        }

    content = _read_log_file(log_path, lines)
    return {
        "status": "running",
        "scan": scan_info,
        "log_file": log_path,
        "lines": lines,
        "logs": content,
    }


@app.get("/api/aco/logs/{scan_uuid}")
async def get_aco_scan_logs(scan_uuid: str, lines: int = Query(default=200, ge=1, le=2000)):
    """Get logs for a specific scan by UUID."""
    if not _aco_scheduler:
        raise HTTPException(status_code=503, detail="ACO scheduler not running")

    with _aco_scheduler._state_lock:
        current = _aco_scheduler.current_job
        if current and current.scan_uuid == scan_uuid:
            log_path = current.log_file
        else:
            for result in _aco_scheduler.recent_results:
                if result.scan_uuid == scan_uuid:
                    log_path = result.log_file
                    break
            else:
                log_path = None

    if not log_path:
        raise HTTPException(status_code=404, detail=f"No logs found for scan {scan_uuid}")

    content = _read_log_file(log_path, lines)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_path}")

    return {"scan_uuid": scan_uuid, "log_file": log_path, "lines": lines, "content": content}


@app.post("/api/aco/scan/start")
async def start_aco_scan():
    """Start the ACO-guided masscan block scanner."""
    global _aco_scheduler
    if _aco_scheduler:
        snapshot = _aco_scheduler.dashboard_snapshot(result_limit=10, block_limit=10)
        if snapshot["status"] != "stopped":
            return {"status": "already_running", "scheduler": snapshot}
        _aco_scheduler = None

    _aco_scheduler = ACOMasscanScheduler(
        on_result=_on_aco_block_result,
    )
    _aco_scheduler.start()
    return {
        "status": "started",
        "scheduler": _aco_scheduler.dashboard_snapshot(result_limit=10, block_limit=10),
    }


@app.post("/api/aco/scan/stop")
async def stop_aco_scan():
    """Stop the ACO-guided masscan block scanner."""
    global _aco_scheduler
    if not _aco_scheduler:
        return {"status": "not_running"}

    fully_stopped = _aco_scheduler.stop()
    snapshot = _aco_scheduler.dashboard_snapshot(result_limit=10, block_limit=10)
    if fully_stopped:
        _aco_scheduler = None
        return {"status": "stopped", "scheduler": snapshot}

    return {"status": "stop_requested", "scheduler": snapshot}


@app.get("/api/aco/scan/stats")
async def get_aco_scan_stats():
    """Get ACO scanner stats."""
    if not _aco_scheduler:
        return {"status": "not_running"}
    snapshot = _aco_scheduler.dashboard_snapshot(result_limit=5, block_limit=10)
    return {
        "status": snapshot["status"],
        "stats": snapshot["stats"],
        "current_job": snapshot["current_job"],
        "started_at": snapshot["started_at"],
        "uptime_seconds": snapshot["uptime_seconds"],
        "last_error": snapshot["last_error"],
    }


@app.get("/api/aco/scan/blocks")
async def get_aco_top_blocks(n: int = Query(default=20, ge=1, le=100)):
    """Get top N blocks by ACO pheromone score."""
    if not _aco_scheduler:
        return {"status": "not_running", "blocks": []}
    snapshot = _aco_scheduler.dashboard_snapshot(result_limit=0, block_limit=n)
    return {"status": snapshot["status"], "blocks": snapshot["top_blocks"]}


@app.post("/api/aco/scan/one")
async def scan_one_block():
    """Run a single ACO-selected block scan (manual)."""
    if not _aco_scheduler:
        raise HTTPException(status_code=400, detail="ACO scheduler not running")

    try:
        result = _aco_scheduler.scan_one_block()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not result:
        return {"status": "no_eligible_blocks"}

    return {
        "status": "completed" if result.success else "failed",
        "cidr": result.cidr,
        "hosts_found": result.hosts_found,
        "duration_ms": round(result.duration_ms),
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "error": result.error,
    }
