from datetime import datetime
from unittest.mock import patch
import pytest

from app.db import Host


def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.skip(reason="Requires database setup")
def test_ingest_endpoint(client, session):
    # Import Scan model
    from app.db import Scan

    with patch("worker.tasks.process_ingest") as mock_task:
        mock_task.delay.return_value.id = "task-123"

        response = client.post(
            "/api/ingest", json={"source": "test.json", "field_map": {"ip": "ip", "port": "port"}}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["task_id"] == "task-123"


@pytest.mark.skip(reason="Requires database setup")
def test_list_hosts(client, session):
    # Add test host to database
    test_host = Host(
        ip="1.2.3.4",
        port=11434,
        status="online",
        last_seen=datetime.utcnow(),
        first_seen=datetime.utcnow(),
    )
    session.add(test_host)
    session.commit()

    response = client.get("/api/hosts")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["ip"] == "1.2.3.4"


@pytest.mark.skip(reason="Requires database setup")
def test_get_host_detail(client, session):
    # Add test host to database
    test_host = Host(
        ip="1.2.3.4",
        port=11434,
        status="online",
        last_seen=datetime.utcnow(),
        first_seen=datetime.utcnow(),
    )
    session.add(test_host)
    session.commit()

    response = client.get(f"/api/hosts/{test_host.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["ip"] == "1.2.3.4"


@pytest.mark.skip(reason="Requires database setup")
def test_get_host_not_found(client, session):  # noqa: ARG001
    response = client.get("/api/hosts/999")
    assert response.status_code == 404


@pytest.mark.skip(reason="Requires database setup")
def test_trigger_probe(client):
    with (
        patch("worker.tasks.probe_host") as mock_task,
        patch("app.main.get_session") as mock_session,
    ):
        mock_hosts = [Host(id=1, ip="1.2.3.4", port=11434)]

        mock_session.return_value.exec.return_value.all.return_value = mock_hosts
        mock_task.delay.return_value.id = "task-456"

        response = client.post("/api/probe", json={"host_ids": [1]})

        assert response.status_code == 200
        data = response.json()
        assert "Queued 1 probe tasks" in data["message"]


@pytest.mark.skip(reason="Requires database setup")
def test_export_csv(client):
    with patch("app.main.get_session") as mock_session:
        mock_hosts = [
            Host(
                id=1,
                ip="1.2.3.4",
                port=11434,
                status="online",
                last_seen="2024-01-01T00:00:00",
                models=[],
            )
        ]

        mock_session.return_value.exec.return_value.all.return_value = mock_hosts

        response = client.get("/api/export?format=csv")

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
