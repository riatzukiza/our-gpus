import csv
import io
import json
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from prometheus_client import Counter, Histogram, generate_latest
from sqlmodel import Session, func, select

from app.config import settings
from app.db import Host, HostModel, Model, Probe, Scan, get_session, init_db
from app.ingest import IngestService
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
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()


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
            success, failed = ingest_service.process_batch(records, scan.id or 0)

            # Update scan status
            scan.status = "completed"
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
        
        success, failed = ingest_service.process_batch(records, scan.id or 0)

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
        raise HTTPException(500, f"Processing failed: {str(e)}")


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
async def trigger_probe(request: ProbeRequest, session: Session = Depends(get_session)):
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
    elif not getattr(request, 'probe_all', False):
        # Only apply default limit if probe_all is not explicitly set to True
        query = query.limit(100)  # Default limit

    hosts = session.exec(query).all()

    # Queue probe tasks
    total_hosts = len(hosts)
    
    if total_hosts == 0:
        return {"message": "No hosts found to probe", "task_ids": []}
    
    # Store start time for progress tracking
    probe_start_time = datetime.now()
    
    tasks = []
    
    # Use batch processing for large requests to reduce Redis load
    if total_hosts > 100:
        from worker.tasks import batch_probe
        host_ids = [host.id for host in hosts]
        
        # Split into smaller batches of 100 to avoid overwhelming the worker
        batch_size = 100
        
        for i in range(0, len(host_ids), batch_size):
            batch = host_ids[i:i + batch_size]
            task = batch_probe.delay(batch)
            tasks.append(task.id)
            # Increment counter for each host in the batch
            for _ in batch:
                probe_counter.labels(status="queued").inc()
        
        message = f"Queued {total_hosts} probe tasks in {len(tasks)} batches"
    
    else:
        # Use individual tasks for smaller requests
        from worker.tasks import probe_host
        
        for host in hosts:
            task = probe_host.delay(host.id)
            tasks.append(task.id)
            probe_counter.labels(status="queued").inc()

        message = f"Queued {len(tasks)} probe tasks"
        
    # Add descriptive information
    if getattr(request, 'probe_all', False):
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

    # Apply filters
    if model:
        base_query = base_query.join(HostModel).join(Model).where(Model.name.contains(model))
    if family:
        base_query = base_query.join(HostModel).join(Model).where(Model.family == family)
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
        """Generate SSE events"""
        try:
            async for chunk in probe_service.stream_prompt(
                host_ip=host.ip, host_port=host.port, model=request.model, prompt=request.prompt
            ):
                # Format as Server-Sent Event
                if chunk["type"] == "error":
                    yield f"data: {json.dumps({'error': chunk['content']})}\n\n"
                else:
                    yield f"data: {json.dumps(chunk)}\n\n"

                # If done, send final event
                if chunk.get("done", False):
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
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
async def delete_host(host_id: int, session: Session = Depends(get_session)):
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
async def clear_all_hosts(session: Session = Depends(get_session)):
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


@app.get("/api/probe-stats")
async def get_recent_probe_stats(
    minutes: int = Query(5, ge=1, le=60),
    session: Session = Depends(get_session)
):
    """Get probe statistics for the last N minutes"""
    from datetime import timedelta
    
    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
    
    # Get recent probe statistics
    probe_stats = session.exec(
        select(
            Probe.status,
            func.count(Probe.id).label("count"),
            func.avg(Probe.duration_ms).label("avg_duration")
        )
        .where(Probe.created_at >= cutoff_time)
        .group_by(Probe.status)
    ).all()
    
    # Get total counts
    total_recent = session.exec(
        select(func.count(Probe.id))
        .where(Probe.created_at >= cutoff_time)
    ).first() or 0
    
    # Get total hosts and current status breakdown
    total_hosts = session.exec(select(func.count(Host.id))).first() or 0
    
    host_status_counts = session.exec(
        select(Host.status, func.count(Host.id).label("count"))
        .group_by(Host.status)
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
            "avg_duration_ms": round(stat.avg_duration, 2) if stat.avg_duration else 0
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
        "last_updated": datetime.utcnow()
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")
