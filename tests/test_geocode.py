from unittest.mock import MagicMock, patch

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

    with patch.object(geo_service, "_get_geoip") as mock_get_geoip:
        mock_result = MagicMock()
        mock_result.is_private = False
        mock_result.country_name = "United States"
        mock_result.city = MagicMock(
            name="Mountain View",
            latitude=37.4056,
            longitude=-122.0775,
        )
        mock_get_geoip.return_value.lookup.return_value = mock_result

        result = await geo_service.geocode_host(host)

    assert result["status"] == "resolved"
    assert host.geo_country == "United States"
    assert host.geo_city == "Mountain View"
    assert host.geo_lat == 37.4056
    assert host.geo_lon == -122.0775
