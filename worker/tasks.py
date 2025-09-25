import asyncio
import json
import logging
from datetime import datetime

from celery import current_task
from sqlmodel import Session, create_engine, select

from app.config import settings
from app.db import Host, HostModel, Model, Scan
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
                    success, failed = service.process_batch(batch, scan_id)
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
                success, failed = service.process_batch(batch, scan_id)
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
        with Session(engine) as session:
            host = session.get(Host, host_id)
            if not host:
                return {"error": "Host not found"}

            service = ProbeService()
            probe = loop.run_until_complete(service.probe_host(host))

            # Save probe result and updated host information
            session.add(probe)
            session.add(host)  # Save the modified host object!

            # Update models if successful
            if probe.status == "success":
                try:
                    payload = json.loads(probe.raw_payload)
                    tags_data = payload.get("tags", {})
                    ps_data = payload.get("ps", {})

                    # Clear existing host models
                    existing_host_models = session.exec(
                        select(HostModel).where(HostModel.host_id == host.id)
                    ).all()
                    for hm in existing_host_models:
                        session.delete(hm)

                    # Process available models
                    models = service.extract_models(tags_data)
                    for model_data in models:
                        # Get or create model
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

                        # Create host-model association
                        host_model = HostModel(host_id=host.id, model_id=model.id, loaded=False)

                        # Check if model is loaded (from ps endpoint)
                        for loaded_model in ps_data.get("models", []):
                            if loaded_model.get("name") == model_data["name"]:
                                host_model.loaded = True
                                host_model.vram_usage_mb = loaded_model.get("size_vram", 0) // (
                                    1024 * 1024
                                )
                                break

                        session.add(host_model)

                except Exception as e:
                    logger.error(f"Error processing models: {str(e)}")

            session.commit()

            return {
                "status": probe.status,
                "duration_ms": probe.duration_ms,
                "host": f"{host.ip}:{host.port}",
            }

    finally:
        loop.close()


@celery_app.task(bind=True, name="worker.tasks.batch_probe")
def batch_probe(self, host_ids: list):  # noqa: ARG001
    """Probe multiple hosts"""
    results = []
    for host_id in host_ids:
        try:
            result = probe_host.delay(host_id)
            results.append(result.id)
        except Exception as e:
            logger.error(f"Failed to queue probe for host {host_id}: {str(e)}")

    return {"queued": len(results), "task_ids": results}
