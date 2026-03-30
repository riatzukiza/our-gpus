from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import Host
from app.geocode import GeoService


@pytest.fixture
def geo_service():
    return GeoService()


def test_should_geocode_public_host(geo_service):
    host = Host(ip="8.8.8.8", port=11434, status="online")

    assert geo_service.should_geocode(host) is True


def test_should_not_geocode_private_host(geo_service):
    host = Host(ip="10.0.0.1", port=11434, status="online")

    assert geo_service.should_geocode(host) is False


@pytest.mark.asyncio
async def test_geocode_host_success(geo_service):
    host = Host(ip="8.8.8.8", port=11434, status="online")

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "country": "United States",
            "city": "Mountain View",
            "latitude": 37.4056,
            "longitude": -122.0775,
        }
        mock_response.raise_for_status.return_value = None
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        result = await geo_service.geocode_host(host)

    assert result["status"] == "resolved"
    assert host.geo_country == "United States"
    assert host.geo_city == "Mountain View"
    assert host.geo_lat == 37.4056
    assert host.geo_lon == -122.0775
