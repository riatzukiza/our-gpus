import asyncio
import json
import logging
from datetime import datetime, timezone

from celery import current_task
import httpx
from sqlalchemy import or_
from sqlmodel import Session, create_engine, select

from app.config import settings
from app.db import Host, HostModel, Model, Probe, Scan, TaskJob
from app.geocode import GeoService
from app.ingest import IngestService
from app.probe import ProbeService
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Initialize database engine for worker
engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)


def _upsert_task_job(
    task_id: str,
    *,
    kind: str,
    label: str | None = None,
    status: str | None = None,
    total_items: int | None = None,
    processed_items: int | None = None,
    success_items: int | None = None,
    failed_items: int | None = None,
    message: str | None = None,
    error: str | None = None,
    payload: dict | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job:
            job = TaskJob(task_id=task_id, kind=kind, label=label)

        if label is not None:
            job.label = label
        if status is not None:
            job.status = status
        if total_items is not None:
            job.total_items = total_items
        if processed_items is not None:
            job.processed_items = processed_items
        if success_items is not None:
            job.success_items = success_items
        if failed_items is not None:
            job.failed_items = failed_items
        if message is not None:
            job.message = message
        if error is not None:
            job.error = error
        if payload is not None:
            job.payload = payload
        if started and job.started_at is None:
            job.started_at = datetime.utcnow()
        if finished:
            job.finished_at = datetime.utcnow()

        session.add(job)
        session.commit()


def register_task_job(
    task_id: str,
    *,
    kind: str,
    label: str,
    total_items: int = 0,
    payload: dict | None = None,
) -> None:
    _upsert_task_job(
        task_id,
        kind=kind,
        label=label,
        status="queued",
        total_items=total_items,
        payload=payload or {},
    )


def _mark_task_started(task_id: str, *, kind: str, label: str, total_items: int = 0) -> None:
    _upsert_task_job(
        task_id,
        kind=kind,
        label=label,
        status="started",
        total_items=total_items,
        message="Task started",
        started=True,
    )


def _mark_task_progress(
    task_id: str,
    *,
    kind: str,
    label: str,
    total_items: int,
    processed_items: int,
    success_items: int,
    failed_items: int,
    payload: dict | None = None,
    message: str | None = None,
) -> None:
    _upsert_task_job(
        task_id,
        kind=kind,
        label=label,
        status="running",
        total_items=total_items,
        processed_items=processed_items,
        success_items=success_items,
        failed_items=failed_items,
        payload=payload,
        message=message,
        started=True,
    )


def _mark_task_finished(
    task_id: str,
    *,
    kind: str,
    label: str,
    status: str,
    total_items: int,
    processed_items: int,
    success_items: int,
    failed_items: int,
    payload: dict | None = None,
    message: str | None = None,
    error: str | None = None,
) -> None:
    _upsert_task_job(
        task_id,
        kind=kind,
        label=label,
        status=status,
        total_items=total_items,
        processed_items=processed_items,
        success_items=success_items,
        failed_items=failed_items,
        payload=payload,
        message=message,
        error=error,
        started=True,
        finished=True,
    )


def queue_host_probes(host_ids: list[int], batch_size: int | None = None) -> list[str]:
    """Queue probe work in bounded batches."""
    unique_host_ids = list(dict.fromkeys(host_id for host_id in host_ids if host_id))
    if not unique_host_ids:
        return []

    effective_batch_size = batch_size or settings.probe_batch_size
    if len(unique_host_ids) == 1:
        task = probe_host.delay(unique_host_ids[0])
        register_task_job(
            task.id,
            kind="probe_host",
            label=f"Probe host {unique_host_ids[0]}",
            total_items=1,
            payload={"host_ids": unique_host_ids},
        )
        return [task.id]

    task_ids = []
    for index in range(0, len(unique_host_ids), effective_batch_size):
        batch = unique_host_ids[index : index + effective_batch_size]
        task = batch_probe.delay(batch)
        register_task_job(
            task.id,
            kind="probe_batch",
            label=f"Probe batch {index // effective_batch_size + 1}",
            total_items=len(batch),
            payload={"host_ids": batch},
        )
        task_ids.append(task.id)
    return task_ids


def _persist_sidecar_probe_result(
    host_id: int,
    result: dict,
    service: ProbeService,
    geo_service: GeoService,
    loop: asyncio.AbstractEventLoop,
) -> dict:
    with Session(engine) as session:
        host = session.get(Host, host_id)
        if not host:
            return {"error": "Host not found", "host_id": host_id}

        host_update = result.get("hostUpdate", {})
        host.status = host_update.get("status", host.status)
        host.last_seen = datetime.utcnow()
        host.latency_ms = host_update.get("latencyMs")
        host.api_version = host_update.get("apiVersion")
        host.gpu = host_update.get("gpu")
        host.gpu_vram_mb = host_update.get("gpuVramMb")
        host.last_error = host_update.get("lastError")

        geocode_result = loop.run_until_complete(geo_service.geocode_host(host))

        probe = Probe(
            host_id=host.id,
            status=result.get("status", "error"),
            duration_ms=result.get("durationMs", 0),
            raw_payload=json.dumps(
                {
                    "tags": result.get("tagsData", {}),
                    "ps": result.get("psData", {}),
                    "version": result.get("versionData", {}),
                }
            )
            if result.get("status") == "success"
            else "",
            error=result.get("error"),
        )
        session.add(probe)
        session.add(host)

        if result.get("status") == "success":
            try:
                tags_data = result.get("tagsData", {})
                ps_data = result.get("psData", {})

                existing_host_models = session.exec(
                    select(HostModel).where(HostModel.host_id == host.id)
                ).all()
                for host_model in existing_host_models:
                    session.delete(host_model)

                models = service.extract_models(tags_data)
                for model_data in models:
                    model = session.exec(
                        select(Model).where(Model.name == model_data["name"])
                    ).first()

                    if not model:
                        model = Model(
                            name=model_data["name"],
                            family=model_data["family"],
                            parameters=model_data["parameters"],
                        )
                        session.add(model)
                        session.flush()

                    host_model = HostModel(host_id=host.id, model_id=model.id, loaded=False)

                    for loaded_model in ps_data.get("models", []):
                        if loaded_model.get("name") == model_data["name"]:
                            host_model.loaded = True
                            host_model.vram_usage_mb = loaded_model.get("size_vram", 0) // (
                                1024 * 1024
                            )
                            break

                    session.add(host_model)
            except Exception as exc:
                logger.error(f"Error processing sidecar models for host {host_id}: {str(exc)}")

        session.commit()

        return {
            "status": probe.status,
            "duration_ms": probe.duration_ms,
            "host": f"{host.ip}:{host.port}",
            "host_id": host_id,
            "geocode_status": geocode_result["status"],
        }


def _probe_batch_via_sidecar(host_ids: list[int]) -> list[dict] | None:
    if not settings.probe_sidecar_url:
        return None

    with Session(engine) as session:
        hosts = [session.get(Host, host_id) for host_id in host_ids]
        payload = {
            "hosts": [
                {"hostId": host.id, "ip": host.ip, "port": host.port}
                for host in hosts
                if host is not None and host.id is not None
            ],
            "timeoutSeconds": settings.probe_timeout_secs,
            "retries": settings.probe_retries,
            "concurrency": settings.probe_concurrency,
        }

    if not payload["hosts"]:
        return []

    response = httpx.post(
        f"{settings.probe_sidecar_url.rstrip('/')}/probe-batch",
        json=payload,
        timeout=httpx.Timeout(max(60.0, settings.probe_timeout_secs * len(payload["hosts"]))),
    )
    response.raise_for_status()
    data = response.json()
    return data.get("results", [])


def _probe_single_host(
    host_id: int,
    service: ProbeService,
    loop: asyncio.AbstractEventLoop,
    geo_service: GeoService | None = None,
) -> dict:
    """Probe one host and persist the result."""
    with Session(engine) as session:
        host = session.get(Host, host_id)
        if not host:
            return {"error": "Host not found", "host_id": host_id}

        probe = loop.run_until_complete(service.probe_host(host))
        geocode_result = {"status": "skipped", "reason": "geocoder unavailable"}

        session.add(probe)
        session.add(host)

        if probe.status == "success":
            try:
                payload = json.loads(probe.raw_payload)
                tags_data = payload.get("tags", {})
                ps_data = payload.get("ps", {})

                existing_host_models = session.exec(
                    select(HostModel).where(HostModel.host_id == host.id)
                ).all()
                for host_model in existing_host_models:
                    session.delete(host_model)

                models = service.extract_models(tags_data)
                for model_data in models:
                    model = session.exec(
                        select(Model).where(Model.name == model_data["name"])
                    ).first()

                    if not model:
                        model = Model(
                            name=model_data["name"],
                            family=model_data["family"],
                            parameters=model_data["parameters"],
                        )
                        session.add(model)
                        session.flush()

                    host_model = HostModel(host_id=host.id, model_id=model.id, loaded=False)

                    for loaded_model in ps_data.get("models", []):
                        if loaded_model.get("name") == model_data["name"]:
                            host_model.loaded = True
                            host_model.vram_usage_mb = loaded_model.get("size_vram", 0) // (
                                1024 * 1024
                            )
                            break

                    session.add(host_model)
            except Exception as exc:
                logger.error(f"Error processing models for host {host_id}: {str(exc)}")

        if geo_service is not None:
            geocode_result = loop.run_until_complete(geo_service.geocode_host(host))

        session.commit()

        return {
            "status": probe.status,
            "duration_ms": probe.duration_ms,
            "host": f"{host.ip}:{host.port}",
            "host_id": host_id,
            "geocode_status": geocode_result["status"],
        }


@celery_app.task(bind=True, name="worker.tasks.process_ingest")
def process_ingest(self, scan_id: int, file_data: bytes = None):  # noqa: ARG001
    """Process data ingestion job"""
    task_id = self.request.id
    if task_id:
        _mark_task_started(task_id, kind="process_ingest", label=f"Ingest scan {scan_id}")

    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
            if task_id:
                _mark_task_finished(
                    task_id,
                    kind="process_ingest",
                    label=f"Ingest scan {scan_id}",
                    status="failure",
                    total_items=0,
                    processed_items=0,
                    success_items=0,
                    failed_items=0,
                    error="Scan not found",
                )
            return {"error": "Scan not found"}

        try:
            scan.status = "processing"
            scan.started_at = datetime.utcnow()
            session.commit()

            # Initialize service
            service = IngestService(session)

            # Read file data if not provided
            if not file_data and scan.source_file:
                with open(scan.source_file, "rb") as f:
                    file_data = f.read()

            if not file_data:
                raise ValueError("No data to process")

            # Infer schema
            schema = service.infer_schema(file_data)
            scan.stats = {"schema": schema}

            # Process records in batches
            mapping = scan.mapping
            total_success = 0
            total_failed = 0
            batch = []

            for i, record in enumerate(service.parse_stream(file_data, mapping)):
                batch.append(record)

                if len(batch) >= service.batch_size:
                    success, failed = service.process_batch(
                        batch, scan_id, auto_probe_new_hosts=True
                    )
                    total_success += success
                    total_failed += failed
                    batch = []

                    # Update progress
                    scan.processed_rows = i + 1
                    current_task.update_state(
                        state="PROGRESS", meta={"current": i + 1, "total": scan.total_rows}
                    )
                    if task_id:
                        _mark_task_progress(
                            task_id,
                            kind="process_ingest",
                            label=f"Ingest scan {scan_id}",
                            total_items=scan.total_rows,
                            processed_items=i + 1,
                            success_items=total_success,
                            failed_items=total_failed,
                            message=f"Processed {i + 1}/{scan.total_rows} rows",
                        )

                    if i % 1000 == 0:
                        session.commit()

            # Process remaining batch
            if batch:
                success, failed = service.process_batch(batch, scan_id, auto_probe_new_hosts=True)
                total_success += success
                total_failed += failed

            # Complete scan
            scan.status = "completed"
            scan.completed_at = datetime.utcnow()
            scan.processed_rows = total_success + total_failed
            scan.stats = {**scan.stats, "success": total_success, "failed": total_failed}
            session.commit()

            if task_id:
                _mark_task_finished(
                    task_id,
                    kind="process_ingest",
                    label=f"Ingest scan {scan_id}",
                    status="success",
                    total_items=scan.total_rows,
                    processed_items=total_success + total_failed,
                    success_items=total_success,
                    failed_items=total_failed,
                    payload={"scan_id": scan_id},
                    message="Ingest completed",
                )

            return {
                "status": "completed",
                "processed": total_success + total_failed,
                "success": total_success,
                "failed": total_failed,
            }

        except Exception as e:
            logger.error(f"Ingest error: {str(e)}")
            scan.status = "failed"
            scan.error_message = str(e)[:500]
            session.commit()
            if task_id:
                _mark_task_finished(
                    task_id,
                    kind="process_ingest",
                    label=f"Ingest scan {scan_id}",
                    status="failure",
                    total_items=scan.total_rows,
                    processed_items=scan.processed_rows,
                    success_items=total_success,
                    failed_items=total_failed,
                    payload={"scan_id": scan_id},
                    message="Ingest failed",
                    error=str(e)[:500],
                )
            raise


@celery_app.task(bind=True, name="worker.tasks.probe_host")
def probe_host(self, host_id: int):  # noqa: ARG001
    """Probe a single Ollama host"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task_id = self.request.id
    label = f"Probe host {host_id}"

    try:
        if task_id:
            _mark_task_started(task_id, kind="probe_host", label=label, total_items=1)
        service = ProbeService()
        geo_service = GeoService()
        result = _probe_single_host(host_id, service, loop, geo_service=geo_service)
        if task_id:
            status = result.get("status", "error")
            failure_count = 1 if status in {"error", "timeout"} else 0
            _mark_task_finished(
                task_id,
                kind="probe_host",
                label=label,
                status="success" if status != "error" else "failure",
                total_items=1,
                processed_items=1,
                success_items=1 if status == "success" else 0,
                failed_items=failure_count,
                payload=result,
                message=f"Probe finished with status {status}",
                error=result.get("error"),
            )
        return result
    except Exception as exc:
        if task_id:
            _mark_task_finished(
                task_id,
                kind="probe_host",
                label=label,
                status="failure",
                total_items=1,
                processed_items=0,
                success_items=0,
                failed_items=1,
                message="Probe task crashed",
                error=str(exc)[:500],
            )
        raise

    finally:
        loop.close()


@celery_app.task(bind=True, name="worker.tasks.batch_probe")
def batch_probe(self, host_ids: list):  # noqa: ARG001
    """Probe multiple hosts"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task_id = self.request.id
    label = f"Probe batch ({len(host_ids)} hosts)"

    try:
        if task_id:
            _mark_task_started(task_id, kind="probe_batch", label=label, total_items=len(host_ids))
        service = ProbeService()
        geo_service = GeoService()
        results = []
        status_counts: dict[str, int] = {}
        geocode_counts: dict[str, int] = {}

        sidecar_results = _probe_batch_via_sidecar(host_ids)
        if sidecar_results is not None:
            sidecar_by_host_id = {result.get("hostId"): result for result in sidecar_results}
            iterable = [
                _persist_sidecar_probe_result(
                    host_id,
                    sidecar_by_host_id.get(
                        host_id, {"status": "error", "error": "Missing sidecar result"}
                    ),
                    service,
                    geo_service,
                    loop,
                )
                for host_id in host_ids
            ]
        else:
            iterable = [
                _probe_single_host(host_id, service, loop, geo_service=geo_service)
                for host_id in host_ids
            ]

        for index, result in enumerate(iterable, start=1):
            results.append(result)
            status = result.get("status", "error")
            status_counts[status] = status_counts.get(status, 0) + 1
            geocode_status = result.get("geocode_status", "skipped")
            geocode_counts[geocode_status] = geocode_counts.get(geocode_status, 0) + 1
            if task_id:
                _mark_task_progress(
                    task_id,
                    kind="probe_batch",
                    label=label,
                    total_items=len(host_ids),
                    processed_items=index,
                    success_items=status_counts.get("success", 0),
                    failed_items=status_counts.get("error", 0) + status_counts.get("timeout", 0),
                    payload={
                        "status_counts": status_counts,
                        "geocode_counts": geocode_counts,
                    },
                    message=f"Processed {index}/{len(host_ids)} hosts",
                )

        if task_id:
            _mark_task_finished(
                task_id,
                kind="probe_batch",
                label=label,
                status="success",
                total_items=len(host_ids),
                processed_items=len(results),
                success_items=status_counts.get("success", 0),
                failed_items=status_counts.get("error", 0) + status_counts.get("timeout", 0),
                payload={
                    "status_counts": status_counts,
                    "geocode_counts": geocode_counts,
                },
                message="Probe batch completed",
            )
        return {
            "processed": len(results),
            "status_counts": status_counts,
            "geocode_counts": geocode_counts,
            "results": results,
        }
    except Exception as exc:
        if task_id:
            _mark_task_finished(
                task_id,
                kind="probe_batch",
                label=label,
                status="failure",
                total_items=len(host_ids),
                processed_items=len(results) if "results" in locals() else 0,
                success_items=status_counts.get("success", 0) if "status_counts" in locals() else 0,
                failed_items=(status_counts.get("error", 0) + status_counts.get("timeout", 0))
                if "status_counts" in locals()
                else 0,
                payload={
                    "status_counts": status_counts if "status_counts" in locals() else {},
                    "geocode_counts": geocode_counts if "geocode_counts" in locals() else {},
                },
                message="Probe batch failed",
                error=str(exc)[:500],
            )
        raise
    finally:
        loop.close()


@celery_app.task(bind=True, name="worker.tasks.queue_discovered_hosts")
def queue_discovered_hosts(self, limit: int | None = None, batch_size: int | None = None):  # noqa: ARG001
    """Queue probe batches for hosts that are still only discovered."""
    task_id = self.request.id
    label = "Queue discovered probe backlog"
    if task_id:
        _mark_task_started(task_id, kind="queue_discovered_hosts", label=label)

    with Session(engine) as session:
        query = select(Host.id).where(Host.status == "discovered").order_by(Host.id.asc())
        if limit is not None:
            query = query.limit(limit)
        host_ids = list(session.exec(query).all())

    task_ids = queue_host_probes(host_ids, batch_size=batch_size)
    if task_id:
        _mark_task_finished(
            task_id,
            kind="queue_discovered_hosts",
            label=label,
            status="success",
            total_items=len(host_ids),
            processed_items=len(host_ids),
            success_items=len(task_ids),
            failed_items=0,
            payload={"task_ids": task_ids},
            message=f"Queued {len(task_ids)} probe tasks",
        )
    return {
        "queued_hosts": len(host_ids),
        "batch_tasks": len(task_ids),
        "task_ids": task_ids,
    }


@celery_app.task(bind=True, name="worker.tasks.queue_ungeocoded_hosts")
def queue_ungeocoded_hosts(
    self,
    limit: int | None = None,
    batch_size: int | None = None,
    include_discovered: bool = False,
):  # noqa: ARG001
    """Queue probes for hosts missing geography so probe-time geocoding can fill them in."""
    task_id = self.request.id
    label = "Queue ungeocoded host backlog"
    if task_id:
        _mark_task_started(task_id, kind="queue_ungeocoded_hosts", label=label)

    with Session(engine) as session:
        query = (
            select(Host.id)
            .where(
                or_(
                    Host.geo_country.is_(None),
                    Host.geo_country == "",
                    Host.geo_lat.is_(None),
                    Host.geo_lon.is_(None),
                )
            )
            .order_by(Host.last_seen.desc(), Host.id.asc())
        )
        if not include_discovered:
            query = query.where(Host.status != "discovered")
        if limit is not None:
            query = query.limit(limit)
        host_ids = list(session.exec(query).all())

    task_ids = queue_host_probes(host_ids, batch_size=batch_size)
    if task_id:
        _mark_task_finished(
            task_id,
            kind="queue_ungeocoded_hosts",
            label=label,
            status="success",
            total_items=len(host_ids),
            processed_items=len(host_ids),
            success_items=len(task_ids),
            failed_items=0,
            payload={"task_ids": task_ids, "include_discovered": include_discovered},
            message=f"Queued {len(task_ids)} probe tasks",
        )
    return {
        "queued_hosts": len(host_ids),
        "batch_tasks": len(task_ids),
        "task_ids": task_ids,
        "include_discovered": include_discovered,
    }


@celery_app.task(bind=True, name="worker.tasks.sync_to_openplanner")
def sync_to_openplanner(
    self,
    status: str | None = None,
    has_gpu: bool | None = None,
    limit: int | None = None,
    include_graph_nodes: bool = True,
):  # noqa: ARG001
    """Sync discovered GPU hosts to OpenPlanner event lake.

    Args:
        status: Filter hosts by status (e.g., "online", "discovered"). None = all.
        has_gpu: Filter hosts with GPU detected. None = all.
        limit: Maximum number of hosts to sync. None = all.
        include_graph_nodes: Also emit graph.node and graph.edge events.

    Returns:
        Dict with sync statistics.
    """
    from app.openplanner_sync import sync_hosts_to_openplanner_sync

    task_id = self.request.id
    label = f"Sync to OpenPlanner (status={status or 'all'}, gpu={has_gpu})"

    if task_id:
        _mark_task_started(task_id, kind="sync_to_openplanner", label=label)

    with Session(engine) as session:
        # Build query for hosts to sync
        query = select(Host).order_by(Host.last_seen.desc())

        if status is not None:
            query = query.where(Host.status == status)

        if has_gpu is True:
            query = query.where(Host.gpu != None)  # noqa: E711
        elif has_gpu is False:
            query = query.where(Host.gpu == None)  # noqa: E711

        if limit is not None:
            query = query.limit(limit)

        hosts = list(session.exec(query).all())

        # Fetch models for each host
        host_models: dict[int, list[dict]] = {}
        for host in hosts:
            if host.id is None:
                continue
            host_model_records = session.exec(
                select(HostModel, Model)
                .join(Model, HostModel.model_id == Model.id)
                .where(HostModel.host_id == host.id)
            ).all()

            host_models[host.id] = [
                {
                    "name": model.name,
                    "family": model.family,
                    "parameters": model.parameters,
                    "loaded": hm.loaded,
                    "vram_usage_mb": hm.vram_usage_mb,
                }
                for hm, model in host_model_records
            ]

    # Sync to OpenPlanner
    result = sync_hosts_to_openplanner_sync(
        hosts, host_models=host_models, include_graph_nodes=include_graph_nodes
    )

    if task_id:
        _mark_task_finished(
            task_id,
            kind="sync_to_openplanner",
            label=label,
            status=result.get("status", "unknown"),
            total_items=result.get("hosts_count", 0),
            processed_items=result.get("events_sent", 0),
            success_items=result.get("events_sent", 0),
            failed_items=result.get("events_total", 0) - result.get("events_sent", 0),
            payload=result,
            message=f"Synced {result.get('events_sent', 0)} events for {result.get('hosts_count', 0)} hosts",
            error=result.get("errors", [None])[0] if result.get("errors") else None,
        )

    return result


@celery_app.task(bind=True, name="worker.tasks.enrich_leads")
def enrich_leads(self, limit: int | None = None):  # noqa: ARG001
    """Enrich probed Ollama hosts with RDAP, ISP, and cloud provider data."""
    import asyncio
    import json

    import httpx

    import app.db as db_module

    db_module.init_db()

    task_id = self.request.id
    label = f"Enrich leads (limit={limit or 'all'})"

    def _classify_cloud(as_str: str, isp: str, org: str) -> str:
        s = f"{as_str} {isp} {org}".lower()
        if "amazon" in s or "aws" in s:
            return "AWS"
        if "microsoft" in s or "azure" in s:
            return "Azure"
        if "google" in s or "gcp" in s:
            return "GCP"
        if "hetzner" in s:
            return "Hetzner"
        if "ovh" in s:
            return "OVH"
        if "digitalocean" in s:
            return "DigitalOcean"
        if "vultr" in s:
            return "Vultr"
        if "linode" in s or "akamai" in s:
            return "Linode/Akamai"
        if "oracle" in s:
            return "Oracle"
        if "alibaba" in s:
            return "Alibaba"
        if "tencent" in s:
            return "Tencent"
        if "contabo" in s:
            return "Contabo"
        return "unknown"

    async def _resolve_rdap(client: httpx.AsyncClient, ip: str) -> dict:
        try:
            resp = await client.get(
                f"https://rdap.arin.net/registry/ip/{ip}",
                timeout=8,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                rdap = resp.json()
                org_name = None
                abuse_email = None
                for entity in rdap.get("entities", []):
                    vcard = entity.get("vcardArray", [])
                    roles = entity.get("roles", [])
                    if len(vcard) > 1:
                        for prop in vcard[1]:
                            if prop[0] == "fn" and not org_name:
                                org_name = prop[3]
                            if prop[0] == "email" and "abuse" in roles:
                                abuse_email = prop[3]
                return {"org": org_name, "abuse_email": abuse_email}
        except Exception:
            pass
        return {"org": None, "abuse_email": None}

    async def _resolve_ipinfo(client: httpx.AsyncClient, ip: str) -> dict:
        try:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,isp,org,as",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return {
                        "isp": data.get("isp"),
                        "org_name": data.get("org"),
                        "asn": data.get("as"),
                    }
        except Exception:
            pass
        return {}

    async def _enrich_all(hosts: list) -> list:
        async with httpx.AsyncClient() as client:
            rdap_tasks = [_resolve_rdap(client, h.ip) for h in hosts]
            ipinfo_tasks = [_resolve_ipinfo(client, h.ip) for h in hosts]
            rdap_results = await asyncio.gather(*rdap_tasks)
            ipinfo_results = await asyncio.gather(*ipinfo_tasks)

        results = []
        for host, rdap, ipinfo in zip(hosts, rdap_results, ipinfo_results):
            cloud = _classify_cloud(
                ipinfo.get("asn") or "",
                ipinfo.get("isp") or "",
                ipinfo.get("org_name") or "",
            )
            results.append(
                {
                    "host_id": host.id,
                    "ip": host.ip,
                    "port": host.port,
                    "country": host.geo_country,
                    "org": rdap.get("org") or ipinfo.get("org_name"),
                    "abuse_email": rdap.get("abuse_email"),
                    "isp": ipinfo.get("isp"),
                    "asn": ipinfo.get("asn"),
                    "cloud": cloud,
                    "ollama_version": host.api_version,
                    "gpu": host.gpu,
                    "gpu_vram_mb": host.gpu_vram_mb,
                }
            )
        return results

    with Session(db_module.engine) as session:
        # Get probed hosts that haven't been enriched yet
        query = (
            select(db_module.Host)
            .where(db_module.Host.api_version != None)  # noqa: E711
            .where(db_module.Host.enriched_at == None)  # noqa: E711
            .order_by(db_module.Host.id)
        )
        if limit:
            query = query.limit(limit)
        hosts = list(session.exec(query).all())

        _mark_task_started(task_id, kind="enrich_leads", label=label, total_items=len(hosts))

        results = asyncio.run(_enrich_all(hosts))

        # Write enrichment data directly to Host records
        success = 0
        for r in results:
            host = session.get(db_module.Host, r["host_id"])
            if host:
                host.isp = r.get("isp")
                host.org = r.get("org")
                host.asn = r.get("asn")
                host.cloud_provider = r.get("cloud")
                host.abuse_email = r.get("abuse_email")
                host.enriched_at = datetime.now(timezone.utc)
                success += 1

        session.commit()

        _mark_task_finished(
            task_id,
            kind="enrich_leads",
            label=label,
            status="success",
            total_items=len(hosts),
            processed_items=len(results),
            success_items=success,
            failed_items=len(hosts) - success,
            message=f"Enriched {success} hosts ({sum(1 for r in results if r['abuse_email'])} with email)",
        )

    return {"enriched": success, "total": len(hosts)}
