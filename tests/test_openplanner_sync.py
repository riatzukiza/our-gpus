"""Tests for OpenPlanner event sync module."""

import pytest
from datetime import datetime

from app.openplanner_sync import (
    host_to_event,
    host_to_graph_node_event,
    host_to_model_edge_events,
)
from app.db import Host


def test_host_to_event_basic():
    """Test basic event generation from host."""
    host = Host(
        id=1,
        ip="192.168.1.1",
        port=11434,
        status="online",
        gpu="NVIDIA RTX 4090",
        gpu_vram_mb=24576,
        geo_country="US",
        geo_city="San Francisco",
        latency_ms=42.5,
        api_version="0.1.26",
    )

    event = host_to_event(host)

    assert event["schema"] == "openplanner.event.v1"
    assert event["id"] == "our-gpus:host:1"
    assert event["source"] == "our-gpus"
    assert event["kind"] == "gpu_node_discovered"
    assert "192.168.1.1:11434" in event["text"]
    assert "RTX 4090" in event["text"]

    # Check meta fields
    assert event["meta"]["gpu_available"] is True
    assert event["meta"]["gpu_name"] == "NVIDIA RTX 4090"
    assert event["meta"]["gpu_vram_mb"] == 24576
    assert event["meta"]["gpu_vram_gb"] == 24.0
    assert event["meta"]["status"] == "online"
    assert event["meta"]["geo_country"] == "US"

    # Check extra fields
    assert event["extra"]["ip"] == "192.168.1.1"
    assert event["extra"]["port"] == 11434


def test_host_to_event_no_gpu():
    """Test event generation for host without GPU."""
    host = Host(
        id=2,
        ip="10.0.0.1",
        port=11434,
        status="online",
        gpu=None,
        geo_country="DE",
    )

    event = host_to_event(host)

    assert event["meta"]["gpu_available"] is False
    assert event["meta"]["gpu_name"] is None
    assert "no GPU detected" in event["text"]


def test_host_to_graph_node_event():
    """Test graph node event generation."""
    host = Host(
        id=3,
        ip="172.16.0.1",
        port=11434,
        status="online",
        gpu="NVIDIA A100",
        geo_country="JP",
    )

    event = host_to_graph_node_event(host)

    assert event["schema"] == "openplanner.event.v1"
    assert event["kind"] == "graph.node"
    assert event["source"] == "our-gpus"
    assert event["extra"]["node_id"] == "gpu-node:172.16.0.1:11434"
    assert event["source_ref"]["project"] == "our-gpus"
    assert event["meta"]["node_type"] == "gpu_node"


def test_host_to_model_edge_events():
    """Test graph edge event generation for models."""
    host = Host(
        id=4,
        ip="192.168.2.1",
        port=11434,
    )

    models = [
        {"name": "llama3:70b", "family": "llama", "loaded": True, "vram_usage_mb": 40000},
        {"name": "mixtral:8x7b", "family": "mixtral", "loaded": False, "vram_usage_mb": None},
    ]

    events = host_to_model_edge_events(host, models)

    assert len(events) == 2

    # Check first edge
    edge1 = events[0]
    assert edge1["kind"] == "graph.edge"
    assert edge1["meta"]["edge_type"] == "hosts_model"
    assert edge1["extra"]["source_node_id"] == "gpu-node:192.168.2.1:11434"
    assert edge1["extra"]["target_node_id"] == "model:llama3:70b"
    assert edge1["meta"]["loaded"] is True

    # Check second edge
    edge2 = events[1]
    assert edge2["extra"]["target_node_id"] == "model:mixtral:8x7b"


def test_host_to_model_edge_events_empty():
    """Test edge event generation with no models."""
    host = Host(id=5, ip="10.0.0.2", port=11434)

    events = host_to_model_edge_events(host, [])
    assert len(events) == 0

    events = host_to_model_edge_events(host, None)
    assert len(events) == 0


def test_host_to_event_with_models():
    """Test event generation with model information."""
    host = Host(
        id=6,
        ip="192.168.3.1",
        port=11434,
        status="online",
        gpu="NVIDIA H100",
    )

    models = [
        {"name": "codellama:34b", "family": "llama"},
        {"name": "mistral:7b", "family": "mistral"},
    ]

    event = host_to_event(host, models)

    assert event["meta"]["model_count"] == 2
    assert "codellama:34b" in event["text"]
    assert "mistral:7b" in event["text"]
    assert len(event["extra"]["models"]) == 2
