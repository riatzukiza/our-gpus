import asyncio
import json
import logging
from datetime import datetime

from celery import current_task
from sqlalchemy import or_
from sqlmodel import Session, create_engine, select

from app.config import settings
from app.db import Host, HostModel, Model, Scan
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


def queue_host_probes(host_ids: list[int], batch_size: int | None = None) -> list[str]:
    """Queue probe work in bounded batches."""
    unique_host_ids = list(dict.fromkeys(host_id for host_id in host_ids if host_id))
    if not unique_host_ids:
        return []

    effective_batch_size = batch_size or settings.probe_batch_size
    if len(unique_host_ids) == 1:
        return [probe_host.delay(unique_host_ids[0]).id]

    task_ids = []
    for index in range(0, len(unique_host_ids), effective_batch_size):
        task = batch_probe.delay(unique_host_ids[index : index + effective_batch_size])
        task_ids.append(task.id)
    return task_ids


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
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if not scan:
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
            raise


@celery_app.task(bind=True, name="worker.tasks.probe_host")
def probe_host(self, host_id: int):  # noqa: ARG001
    """Probe a single Ollama host"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        service = ProbeService()
        geo_service = GeoService()
        return _probe_single_host(host_id, service, loop, geo_service=geo_service)

    finally:
        loop.close()


@celery_app.task(bind=True, name="worker.tasks.batch_probe")
def batch_probe(self, host_ids: list):  # noqa: ARG001
    """Probe multiple hosts"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        service = ProbeService()
        geo_service = GeoService()
        results = []
        status_counts: dict[str, int] = {}
        geocode_counts: dict[str, int] = {}

        for host_id in host_ids:
            result = _probe_single_host(host_id, service, loop, geo_service=geo_service)
            results.append(result)
            status = result.get("status", "error")
            status_counts[status] = status_counts.get(status, 0) + 1
            geocode_status = result.get("geocode_status", "skipped")
            geocode_counts[geocode_status] = geocode_counts.get(geocode_status, 0) + 1

        return {
            "processed": len(results),
            "status_counts": status_counts,
            "geocode_counts": geocode_counts,
            "results": results,
        }
    finally:
        loop.close()


@celery_app.task(bind=True, name="worker.tasks.queue_discovered_hosts")
def queue_discovered_hosts(self, limit: int | None = None, batch_size: int | None = None):  # noqa: ARG001
    """Queue probe batches for hosts that are still only discovered."""
    with Session(engine) as session:
        query = select(Host.id).where(Host.status == "discovered").order_by(Host.id.asc())
        if limit is not None:
            query = query.limit(limit)
        host_ids = list(session.exec(query).all())

    task_ids = queue_host_probes(host_ids, batch_size=batch_size)
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
    return {
        "queued_hosts": len(host_ids),
        "batch_tasks": len(task_ids),
        "task_ids": task_ids,
        "include_discovered": include_discovered,
    }
