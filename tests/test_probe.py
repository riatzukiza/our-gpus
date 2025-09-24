from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import Host
from app.probe import ProbeService


@pytest.fixture
def probe_service():
    return ProbeService()


@pytest.fixture
def mock_host():
    host = Host(
        id=1,
        ip="127.0.0.1",
        port=11434,
        status="unknown"
    )
    return host


@pytest.mark.asyncio
async def test_probe_success(probe_service, mock_host):
    with patch('httpx.AsyncClient') as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama2:7b", "size": 3825819648}
            ]
        }

        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        probe = await probe_service.probe_host(mock_host)

        assert probe.status == "success"
        assert probe.host_id == 1
        assert mock_host.status == "online"


@pytest.mark.asyncio
async def test_probe_timeout(probe_service, mock_host):
    with patch('httpx.AsyncClient') as mock_client:
        import httpx
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.TimeoutException("timeout")
        )

        probe = await probe_service.probe_host(mock_host)

        assert probe.status == "timeout"
        assert probe.error == "Connection timeout"
        assert mock_host.status == "timeout"


@pytest.mark.asyncio
async def test_probe_non_ollama(probe_service, mock_host):
    with patch('httpx.AsyncClient') as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        probe = await probe_service.probe_host(mock_host)

        assert probe.status == "non_ollama"
        assert mock_host.status == "non_ollama"


def test_extract_models(probe_service):
    tags_data = {
        "models": [
            {
                "name": "llama2:7b",
                "size": 3825819648,
                "digest": "abc123"
            },
            {
                "name": "mistral:7b-instruct",
                "size": 4113895424,
                "digest": "def456"
            }
        ]
    }

    models = probe_service.extract_models(tags_data)

    assert len(models) == 2
    assert models[0]["name"] == "llama2:7b"
    assert models[0]["family"] == "llama"
    assert models[1]["name"] == "mistral:7b-instruct"
    assert models[1]["family"] == "mistral"


def test_extract_family(probe_service):
    assert probe_service._extract_family("llama2:7b") == "llama"
    assert probe_service._extract_family("mistral:7b-instruct") == "mistral"
    assert probe_service._extract_family("codellama:13b") == "codellama"
    assert probe_service._extract_family("unknown-model") == "other"


def test_extract_parameters(probe_service):
    model_data = {
        "name": "llama2:7b",
        "details": {
            "parameter_size": "7B"
        }
    }

    params = probe_service._extract_parameters(model_data)
    assert params == "7B"

    # Test extraction from name
    model_data = {"name": "llama2:13b-chat"}
    params = probe_service._extract_parameters(model_data)
    assert params == "13b"
