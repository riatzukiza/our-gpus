"""OpenPlanner event sync for discovered GPU hosts.

This module syncs discovered Ollama hosts to the OpenPlanner data lake,
enabling semantic search and graph-based discovery of GPU compute resources.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.db import Host

logger = logging.getLogger(__name__)

# OpenPlanner configuration from settings
OPENPLANNER_URL = settings.openplanner_url
OPENPLANNER_API_KEY = settings.openplanner_api_key
OPENPLANNER_SYNC_ENABLED = settings.openplanner_sync_enabled
OPENPLANNER_BATCH_SIZE = settings.openplanner_batch_size
OPENPLANNER_TIMEOUT_SECS = settings.openplanner_timeout_secs


def host_to_event(host: Host, models: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Convert a Host record to an OpenPlanner event.

    Args:
        host: The Host database record
        models: Optional list of model dicts with name, family, loaded, vram_usage_mb

    Returns:
        OpenPlanner EventEnvelopeV1 dict
    """
    event_id = f"our-gpus:host:{host.id}"
    ts = datetime.now(timezone.utc).isoformat()

    # Build human-readable text for semantic search
    gpu_info = f"GPU: {host.gpu}" if host.gpu else "no GPU detected"
    geo_info = f"{host.geo_city}, {host.geo_country}" if host.geo_city and host.geo_country else host.geo_country or "unknown location"
    model_names = [m.get("name", "") for m in (models or [])]
    models_text = f"models: {', '.join(model_names[:5])}" if model_names else "no models"

    text = f"Ollama instance at {host.ip}:{host.port} ({host.status}) with {gpu_info}. Location: {geo_info}. {models_text}."

    return {
        "schema": "openplanner.event.v1",
        "id": event_id,
        "ts": ts,
        "source": "our-gpus",
        "kind": "gpu_node_discovered",
        "text": text,
        "meta": {
            "gpu_available": host.gpu is not None,
            "gpu_name": host.gpu,
            "gpu_vram_mb": host.gpu_vram_mb,
            "gpu_vram_gb": round(host.gpu_vram_mb / 1024, 1) if host.gpu_vram_mb else None,
            "status": host.status,
            "latency_ms": host.latency_ms,
            "api_version": host.api_version,
            "geo_country": host.geo_country,
            "geo_city": host.geo_city,
            "cloud_provider": host.cloud_provider,
            "isp": host.isp,
            "model_count": len(models) if models else 0,
        },
        "extra": {
            "ip": host.ip,
            "port": host.port,
            "host_id": host.id,
            "os": host.os,
            "arch": host.arch,
            "ram_gb": host.ram_gb,
            "geo_lat": host.geo_lat,
            "geo_lon": host.geo_lon,
            "org": host.org,
            "asn": host.asn,
            "abuse_email": host.abuse_email,
            "models": models or [],
            "first_seen": host.first_seen.isoformat() if host.first_seen else None,
            "last_seen": host.last_seen.isoformat() if host.last_seen else None,
            "enriched_at": host.enriched_at.isoformat() if host.enriched_at else None,
        },
    }


def host_to_graph_node_event(host: Host, models: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Convert a Host record to an OpenPlanner graph.node event.

    This creates a graph node that can be linked to other resources.

    Args:
        host: The Host database record
        models: Optional list of model dicts

    Returns:
        OpenPlanner EventEnvelopeV1 dict with kind="graph.node"
    """
    node_id = f"gpu-node:{host.ip}:{host.port}"
    event_id = f"our-gpus:node:{host.id}"
    ts = datetime.now(timezone.utc).isoformat()

    return {
        "schema": "openplanner.event.v1",
        "id": event_id,
        "ts": ts,
        "source": "our-gpus",
        "kind": "graph.node",
        "source_ref": {
            "project": "our-gpus",
            "message": node_id,
        },
        "text": f"{host.ip}:{host.port} - {host.gpu or 'CPU'} - {host.geo_country or 'unknown'}",
        "meta": {
            "node_type": "gpu_node",
            "status": host.status,
            "gpu_available": host.gpu is not None,
        },
        "extra": {
            "node_id": node_id,
            "preview": f"{host.ip}:{host.port} ({host.gpu or 'CPU'})",
            "ip": host.ip,
            "port": host.port,
            "gpu": host.gpu,
            "gpu_vram_mb": host.gpu_vram_mb,
            "geo_country": host.geo_country,
            "geo_city": host.geo_city,
            "cloud_provider": host.cloud_provider,
            "models": models or [],
        },
    }


def host_to_model_edge_events(host: Host, models: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Create graph.edge events linking GPU node to its models.

    Args:
        host: The Host database record
        models: List of model dicts with name, family

    Returns:
        List of OpenPlanner EventEnvelopeV1 dicts with kind="graph.edge"
    """
    if not models:
        return []

    node_id = f"gpu-node:{host.ip}:{host.port}"
    events = []
    ts = datetime.now(timezone.utc).isoformat()

    for model in models:
        model_name = model.get("name", "")
        if not model_name:
            continue

        model_node_id = f"model:{model_name}"
        event_id = f"our-gpus:edge:{host.id}:{model_name}"

        events.append({
            "schema": "openplanner.event.v1",
            "id": event_id,
            "ts": ts,
            "source": "our-gpus",
            "kind": "graph.edge",
            "meta": {
                "edge_type": "hosts_model",
                "loaded": model.get("loaded", False),
            },
            "extra": {
                "source_node_id": node_id,
                "target_node_id": model_node_id,
                "edge_type": "hosts_model",
                "edge_kind": "hosts_model",
                "vram_usage_mb": model.get("vram_usage_mb"),
            },
        })

    return events


async def sync_hosts_to_openplanner(
    hosts: list[Host],
    host_models: dict[int, list[dict[str, Any]]] | None = None,
    include_graph_nodes: bool = True,
) -> dict[str, Any]:
    """Sync discovered hosts to OpenPlanner event lake.

    Args:
        hosts: List of Host records to sync
        host_models: Optional dict mapping host_id to list of model dicts
        include_graph_nodes: Whether to also emit graph.node and graph.edge events

    Returns:
        Dict with sync statistics
    """
    if not OPENPLANNER_SYNC_ENABLED:
        logger.debug("OpenPlanner sync disabled, skipping")
        return {"status": "disabled", "count": 0}

    if not hosts:
        return {"status": "success", "count": 0}

    events = []
    for host in hosts:
        models = host_models.get(host.id, []) if host_models else []
        
        # Primary discovery event
        events.append(host_to_event(host, models))
        
        # Graph node for federation/linking
        if include_graph_nodes:
            events.append(host_to_graph_node_event(host, models))
            events.extend(host_to_model_edge_events(host, models))

    # Batch send to OpenPlanner
    headers = {"Content-Type": "application/json"}
    if OPENPLANNER_API_KEY:
        headers["Authorization"] = f"Bearer {OPENPLANNER_API_KEY}"

    total_sent = 0
    total_events = len(events)
    errors = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(OPENPLANNER_TIMEOUT_SECS)) as client:
        # Send in batches
        for i in range(0, len(events), OPENPLANNER_BATCH_SIZE):
            batch = events[i : i + OPENPLANNER_BATCH_SIZE]
            try:
                resp = await client.post(
                    f"{OPENPLANNER_URL}/v1/events",
                    json={"events": batch},
                    headers=headers,
                )
                resp.raise_for_status()
                total_sent += len(batch)
                logger.debug(f"Synced {len(batch)} events to OpenPlanner")
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                errors.append(error_msg)
                logger.error(f"Failed to sync batch to OpenPlanner: {error_msg}")
            except httpx.RequestError as e:
                error_msg = str(e)
                errors.append(error_msg)
                logger.error(f"Request error syncing to OpenPlanner: {error_msg}")

    result = {
        "status": "success" if total_sent == total_events else "partial" if total_sent > 0 else "failed",
        "hosts_count": len(hosts),
        "events_total": total_events,
        "events_sent": total_sent,
        "include_graph_nodes": include_graph_nodes,
    }
    
    if errors:
        result["errors"] = errors[:5]  # Limit error messages

    return result


def sync_hosts_to_openplanner_sync(
    hosts: list[Host],
    host_models: dict[int, list[dict[str, Any]]] | None = None,
    include_graph_nodes: bool = True,
) -> dict[str, Any]:
    """Synchronous wrapper for sync_hosts_to_openplanner.

    Useful for CLI commands and Celery tasks.
    """
    import asyncio
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're in an async context, create a new loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                sync_hosts_to_openplanner(hosts, host_models, include_graph_nodes)
            )
            return future.result()
    else:
        return asyncio.run(sync_hosts_to_openplanner(hosts, host_models, include_graph_nodes))
