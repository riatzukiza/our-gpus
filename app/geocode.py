import asyncio
import ipaddress
import logging
import os
import shutil
import urllib.request
from pathlib import Path

from geoip2fast import GeoIP2Fast

from app.config import settings
from app.db import Host

logger = logging.getLogger(__name__)


class GeoService:
    _geoip: GeoIP2Fast | None = None
    _data_path: str | None = None

    def __init__(self):
        self.timeout = settings.geocode_timeout_secs
        self.retries = settings.geocode_retries
        self.data_path = Path(settings.geocode_data_path)
        self.data_url = settings.geocode_data_url
        self.lock_path = self.data_path.with_suffix(self.data_path.suffix + ".lock")

    def should_geocode(self, host: Host) -> bool:
        if host.geo_country and host.geo_lat is not None and host.geo_lon is not None:
            return False

        try:
            ip = ipaddress.ip_address(host.ip)
        except ValueError:
            return False

        return ip.is_global

    def _ensure_data_file(self) -> None:
        if self.data_path.exists():
            return

        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        with self.lock_path.open("w") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass

            if self.data_path.exists():
                return

            tmp_path = self.data_path.with_suffix(self.data_path.suffix + ".part")
            logger.info("Downloading local GeoIP database to %s", self.data_path)
            with urllib.request.urlopen(self.data_url, timeout=self.timeout) as response:
                with tmp_path.open("wb") as output:
                    shutil.copyfileobj(response, output)
            os.replace(tmp_path, self.data_path)

    def _get_geoip(self) -> GeoIP2Fast:
        data_path = str(self.data_path)
        if GeoService._geoip is None or GeoService._data_path != data_path:
            self._ensure_data_file()
            GeoService._geoip = GeoIP2Fast(geoip2fast_data_file=data_path)
            GeoService._data_path = data_path
        return GeoService._geoip

    @staticmethod
    def _coerce_float(value) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                return None
        return None

    async def geocode_host(self, host: Host) -> dict[str, str]:
        if not self.should_geocode(host):
            return {"status": "skipped", "reason": "host does not need geocoding"}

        for attempt in range(self.retries):
            try:
                geoip = self._get_geoip()
                result = geoip.lookup(host.ip)

                if getattr(result, "is_private", False):
                    return {"status": "skipped", "reason": "private or reserved network"}

                country = getattr(result, "country_name", "") or ""
                city = getattr(result, "city", None)
                city_name = getattr(city, "name", "") if city is not None else ""
                latitude = self._coerce_float(
                    getattr(city, "latitude", None) if city is not None else None
                )
                longitude = self._coerce_float(
                    getattr(city, "longitude", None) if city is not None else None
                )

                if country.startswith("<") or country in {"", "--"}:
                    return {"status": "failed", "reason": "host not found in local geo database"}

                host.geo_country = country
                host.geo_city = city_name or host.geo_city
                host.geo_lat = latitude
                host.geo_lon = longitude

                if not host.geo_country:
                    return {"status": "failed", "reason": "lookup returned no usable geography"}

                return {"status": "resolved", "reason": "ok"}
            except Exception as exc:
                if attempt == self.retries - 1:
                    logger.warning("Geocoding failed for %s: %s", host.ip, str(exc))
                    return {"status": "failed", "reason": str(exc)}
                await asyncio.sleep(0.5 * (2**attempt))

        return {"status": "failed", "reason": "all retries exhausted"}
