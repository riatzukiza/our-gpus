import csv
import io
import json
import secrets
from collections import deque
from datetime import datetime
from pathlib import Path

from celery.result import AsyncResult
from fastapi import Depends, FastAPI, File, Form, HTTPException, Header, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.config import settings
from app.db import Host, HostModel, Model, Probe, Scan, TaskJob, get_session, init_db
from app.ingest import IngestService
from app.masscan import MasscanService
from app.probe import ProbeService
from app.schemas import (
    HealthResponse,
    HostResponse,
    IngestResponse,
    ModelResponse,
    PaginatedHostResponse,
    ProbeRequest,
    PromptRequest,
    PromptResponse,
    ScanResponse,
)
from worker.celery_app import celery_app
from worker.tasks import register_task_job

app = FastAPI(title="our gpu API", version="1.0.0")

# Metrics
ingest_counter = Counter("ingest_total", "Total ingests started")
probe_counter = Counter("probe_total", "Total probes initiated", ["status"])
request_duration = Histogram("request_duration_seconds", "Request duration", ["endpoint"])

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


@app.get("/api/hosts", response_model=PaginatedHostResponse)
async def list_hosts(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    model: str | None = None,
    family: str | None = None,
    gpu: bool | None = None,
    status: str | None = None,
    sort: str = "last_seen",
    session: Session = Depends(get_session),
):
    # Build base query for counting
    base_query = select(Host)

    # Apply filters - handle joins carefully to avoid duplicates
    needs_model_join = bool(model or family)
    if needs_model_join:
        base_query = base_query.join(HostModel).join(Model)

    if model:
        base_query = base_query.where(Model.name.contains(model))
    if family:
        base_query = base_query.where(Model.family == family)
    if gpu is not None:
        if gpu:
            base_query = base_query.where((Host.gpu == "available") | (Host.gpu_vram_mb > 0))
        else:
            base_query = base_query.where(
                (Host.gpu.is_(None)) & ((Host.gpu_vram_mb == 0) | (Host.gpu_vram_mb.is_(None)))
            )
    if status:
        base_query = base_query.where(Host.status == status)

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
                models=model_names,
            )
        )

    return PaginatedHostResponse(
        items=result,
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,  # Calculate total pages
    )


@app.get("/api/hosts/{host_id}", response_model=HostResponse)
async def get_host(host_id: int, session: Session = Depends(get_session)):
    host = session.get(Host, host_id)
    if not host:
        raise HTTPException(404, "Host not found")

    # Get latest probe
    latest_probe = session.exec(
        select(Probe).where(Probe.host_id == host_id).order_by(Probe.created_at.desc()).limit(1)
    ).first()

    # Get models for this host
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

    # Safely parse probe payload
    last_probe_data = None
    if latest_probe:
        try:
            last_probe_data = json.loads(latest_probe.raw_payload)
        except json.JSONDecodeError:
            # Handle truncated JSON
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
        models=models,
        last_probe=last_probe_data,
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


@app.get("/api/export")
async def export_data(
    format: str = Query("csv", regex="^(csv|json)$"),
    model: str | None = None,
    family: str | None = None,
    gpu: bool | None = None,
    session: Session = Depends(get_session),
):
    # Build query
    query = select(Host)
    if model:
        query = query.join(HostModel).join(Model).where(Model.name.contains(model))
    if family:
        query = query.join(HostModel).join(Model).where(Model.family == family)
    if gpu is not None:
        if gpu:
            query = query.where((Host.gpu == "available") | (Host.gpu_vram_mb > 0))
        else:
            query = query.where(
                (Host.gpu.is_(None)) & ((Host.gpu_vram_mb == 0) | (Host.gpu_vram_mb.is_(None)))
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


@app.post("/api/hosts/clear-filtered")
async def clear_filtered_hosts(
    request: ClearFilteredHostsRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
):
    """Clear hosts that match the specified filters"""
    # Build query to find hosts to delete
    query = select(Host)

    # Apply the same filters as the list_hosts endpoint
    needs_model_join = bool(request.model or request.family)
    if needs_model_join:
        query = query.join(HostModel).join(Model)

    if request.model:
        query = query.where(Model.name.contains(request.model))
    if request.family:
        query = query.where(Model.family == request.family)
    if request.gpu is not None:
        if request.gpu:
            query = query.where((Host.gpu == "available") | (Host.gpu_vram_mb > 0))
        else:
            query = query.where(
                (Host.gpu.is_(None)) & ((Host.gpu_vram_mb == 0) | (Host.gpu_vram_mb.is_(None)))
            )
    if request.status:
        query = query.where(Host.status == request.status)

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
        success, failed = ingest_service.process_batch(records, scan_id, auto_probe_new_hosts=True)

    scan.completed_at = datetime.utcnow()
    scan.total_rows = len(records)
    scan.processed_rows = success
    scan.stats_json = json.dumps({"success": success, "failed": failed})
    session.add(scan)
    session.commit()

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
                    success, failed = ingest.process_batch(
                        records,
                        scan.id or 0,
                        auto_probe_new_hosts=True,
                    )
                    scan.status = "completed"
                    scan.completed_at = datetime.utcnow()
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
    from app.aco import AntColony
    from app.masscan_aco import SchedulerConfig

    config = SchedulerConfig()
    state_file = config.state_file

    try:
        if Path(state_file).exists():
            with open(state_file) as file_handle:
                data = json.load(file_handle)
            aco = AntColony.from_dict(data)
            stats = aco.stats()
            top = aco.top_blocks(20)
            return {
                "status": "not_running",
                "started_at": None,
                "uptime_seconds": None,
                "prefix_len": None,
                "estimated_block_duration_s": None,
                "config": {
                    "port": config.port,
                    "rate": config.rate,
                    "max_block_duration_s": config.max_block_duration_s,
                    "min_scan_interval_s": config.min_scan_interval_s,
                },
                "stats": stats,
                "current_job": None,
                "recent_results": [],
                "top_blocks": [
                    {
                        "cidr": cidr,
                        "pheromone": round(pheromone, 4),
                    }
                    for cidr, pheromone in top
                ],
                "last_error": None,
            }
    except Exception as error:
        print(f"[WARN] Failed to load ACO state for dashboard: {error}")

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

    host_rows = session.exec(
        select(
            Host.ip,
            Host.geo_country,
            Host.geo_city,
            Host.geo_lat,
            Host.geo_lon,
            Host.status,
        ).where(Host.geo_lat.is_not(None), Host.geo_lon.is_not(None))
    ).all()

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
        "points": [
            {
                "ip": ip,
                "country": country or "",
                "city": city or "",
                "lat": lat,
                "lon": lon,
                "status": status or "unknown",
            }
            for ip, country, city, lat, lon, status in host_rows
            if lat is not None and lon is not None
        ],
    }


@app.get("/api/aco/dashboard")
async def get_aco_dashboard(
    history_limit: int = Query(default=20, ge=1, le=100),
    country_limit: int = Query(default=25, ge=1, le=100),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_api_key),
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
async def get_aco_current_logs(
    lines: int = Query(default=200, ge=1, le=2000),
    _: None = Depends(require_admin_api_key),
):
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
async def get_aco_scan_logs(
    scan_uuid: str,
    lines: int = Query(default=200, ge=1, le=2000),
    _: None = Depends(require_admin_api_key),
):
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
async def start_aco_scan(_: None = Depends(require_admin_api_key)):
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
async def stop_aco_scan(_: None = Depends(require_admin_api_key)):
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
async def get_aco_scan_stats(_: None = Depends(require_admin_api_key)):
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
async def get_aco_top_blocks(
    n: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_admin_api_key),
):
    """Get top N blocks by ACO pheromone score."""
    if not _aco_scheduler:
        return {"status": "not_running", "blocks": []}
    snapshot = _aco_scheduler.dashboard_snapshot(result_limit=0, block_limit=n)
    return {"status": snapshot["status"], "blocks": snapshot["top_blocks"]}


@app.post("/api/aco/scan/one")
async def scan_one_block(_: None = Depends(require_admin_api_key)):
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
