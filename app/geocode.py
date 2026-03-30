import asyncio
import ipaddress
import logging

import httpx

from app.config import settings
from app.db import Host

logger = logging.getLogger(__name__)


class GeoService:
    def __init__(self):
        self.timeout = settings.geocode_timeout_secs
        self.retries = settings.geocode_retries
        self.base_url = settings.geocode_provider_url.rstrip("/")

    def should_geocode(self, host: Host) -> bool:
        if host.geo_country and host.geo_lat is not None and host.geo_lon is not None:
            return False

        try:
            ip = ipaddress.ip_address(host.ip)
        except ValueError:
            return False

        return ip.is_global

    async def geocode_host(self, host: Host) -> dict[str, str]:
        if not self.should_geocode(host):
            return {"status": "skipped", "reason": "host does not need geocoding"}

        url = f"{self.base_url}/{host.ip}"

        for attempt in range(self.retries):
            try:
                async with httpx.AsyncClient(
                    verify=False, timeout=httpx.Timeout(self.timeout, connect=self.timeout)
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()

                payload = response.json()
                if payload.get("success") is False:
                    message = str(payload.get("message", "lookup failed"))
                    status = "skipped" if "private" in message.lower() else "failed"
                    return {"status": status, "reason": message}

                country = payload.get("country")
                city = payload.get("city")
                latitude = payload.get("latitude")
                longitude = payload.get("longitude")

                if country:
                    host.geo_country = country
                if city:
                    host.geo_city = city
                if isinstance(latitude, (int, float)):
                    host.geo_lat = float(latitude)
                if isinstance(longitude, (int, float)):
                    host.geo_lon = float(longitude)

                if not host.geo_country and host.geo_lat is None and host.geo_lon is None:
                    return {"status": "failed", "reason": "provider returned no usable geography"}

                return {"status": "resolved", "reason": "ok"}
            except Exception as exc:
                if attempt == self.retries - 1:
                    logger.warning("Geocoding failed for %s: %s", host.ip, str(exc))
                    return {"status": "failed", "reason": str(exc)}
                await asyncio.sleep(0.5 * (2**attempt))

        return {"status": "failed", "reason": "all retries exhausted"}
