import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
from app.db import Host, Model, Scan


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_ingest_endpoint(client):
    with patch('app.main.process_ingest') as mock_task:
        mock_task.delay.return_value.id = "task-123"
        
        response = client.post(
            "/api/ingest",
            json={
                "source": "test.json",
                "field_map": {"ip": "ip", "port": "port"}
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["task_id"] == "task-123"


def test_list_hosts(client):
    with patch('app.main.get_session') as mock_session:
        mock_hosts = [
            Host(
                id=1,
                ip="1.2.3.4",
                port=11434,
                status="online",
                last_seen="2024-01-01T00:00:00"
            )
        ]
        
        mock_session.return_value.exec.return_value.all.return_value = mock_hosts
        
        response = client.get("/api/hosts")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["ip"] == "1.2.3.4"


def test_get_host_detail(client):
    with patch('app.main.get_session') as mock_session:
        mock_host = Host(
            id=1,
            ip="1.2.3.4",
            port=11434,
            status="online",
            last_seen="2024-01-01T00:00:00",
            models=[]
        )
        
        mock_session.return_value.get.return_value = mock_host
        mock_session.return_value.exec.return_value.first.return_value = None
        
        response = client.get("/api/hosts/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["ip"] == "1.2.3.4"


def test_get_host_not_found(client):
    with patch('app.main.get_session') as mock_session:
        mock_session.return_value.get.return_value = None
        
        response = client.get("/api/hosts/999")
        
        assert response.status_code == 404


def test_trigger_probe(client):
    with patch('app.main.probe_host') as mock_task:
        with patch('app.main.get_session') as mock_session:
            mock_hosts = [
                Host(id=1, ip="1.2.3.4", port=11434)
            ]
            
            mock_session.return_value.exec.return_value.all.return_value = mock_hosts
            mock_task.delay.return_value.id = "task-456"
            
            response = client.post(
                "/api/probe",
                json={"host_ids": [1]}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "Queued 1 probe tasks" in data["message"]


def test_export_csv(client):
    with patch('app.main.get_session') as mock_session:
        mock_hosts = [
            Host(
                id=1,
                ip="1.2.3.4",
                port=11434,
                status="online",
                last_seen="2024-01-01T00:00:00",
                models=[]
            )
        ]
        
        mock_session.return_value.exec.return_value.all.return_value = mock_hosts
        
        response = client.get("/api/export?format=csv")
        
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]