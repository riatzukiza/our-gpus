import hashlib
import json
import re
import socket
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from app.db import (
    Asset,
    AssetDomain,
    AutonomousSystem,
    ContactEndpoint,
    DomainRecord,
    EnrichmentRun,
    LeadContactCandidate,
    LeadRecord,
    Organization,
    OrgCandidate,
    OrgResolution,
    RawFetch,
    SourceObservation,
)

EMAIL_RE = re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.+)$")
ROLE_LOCALPARTS = (
    "security",
    "abuse",
    "noc",
    "soc",
    "cert",
    "csirt",
    "contact",
    "support",
    "info",
    "admin",
)
IGNORED_ORG_NAMES = {
    "redacted for privacy",
    "privacy service provided by withheld for privacy ehf",
    "not disclosed",
    "private registrant",
    "private person",
}
SOURCE_WEIGHT = {
    "rdap_network": 40.0,
    "rdap_entity": 25.0,
    "domain_registration": 20.0,
    "ptr": 15.0,
    "security_txt_contact": 15.0,
    "website_contact": 10.0,
}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_domain(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def root_domain(value: str) -> str:
    parts = [part for part in value.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return value


def normalize_org_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def infer_display_name_from_domain(value: str) -> str:
    label = root_domain(value).split(".")[0]
    return label.replace("-", " ").replace("_", " ").title()


def route_legitimacy_for_contact(contact: ContactEndpoint) -> float:
    if contact.source_type == "security_txt":
        return 100.0
    if contact.source_type in {"rdap", "whois"} and contact.contact_type in {"abuse", "security"}:
        return 80.0
    if contact.source_type == "website" and contact.contact_type == "security":
        return 60.0
    if contact.source_type == "website" and contact.contact_type == "business":
        return 40.0
    return 20.0


def contact_quality_for_contact(contact: ContactEndpoint) -> float:
    value = contact.value.lower()
    email = value.removeprefix("mailto:") if value.startswith("mailto:") else value
    local_part = email.split("@", 1)[0]

    if contact.is_role_account and any(role in local_part for role in ROLE_LOCALPARTS):
        return 95.0
    if contact.is_role_account:
        return 80.0
    if value.startswith("http"):
        return 55.0
    if "@" in email:
        return 35.0
    return 20.0


def route_name_for_contact(contact: ContactEndpoint) -> str:
    if contact.source_type == "security_txt":
        return "security_txt"
    if contact.source_type in {"rdap", "whois"} and contact.contact_type == "abuse":
        return "rdap_abuse"
    if contact.source_type == "website" and contact.contact_type == "security":
        return "website_security"
    if contact.source_type == "website":
        return "website_general"
    return "manual_review"


class LeadEvidenceStore:
    def __init__(self, session: Session):
        self.session = session

    def ensure_domain_record(self, fqdn: str, source_type: str) -> DomainRecord:
        normalized = normalize_domain(fqdn)
        if normalized is None:
            raise ValueError("domain is required")
        existing = self.session.exec(
            select(DomainRecord).where(DomainRecord.fqdn == normalized)
        ).first()
        now = utcnow()
        if existing is not None:
            existing.last_seen = now
            existing.updated_at = now
            existing.source_type = existing.source_type or source_type
            return existing

        domain = DomainRecord(
            fqdn=normalized,
            root_domain=root_domain(normalized),
            source_type=source_type,
            first_seen=now,
            last_seen=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(domain)
        self.session.flush()
        return domain

    def ensure_asset_domain_link(
        self,
        asset_id: str,
        domain_id: str,
        relationship: str,
        confidence: float,
    ) -> None:
        link = self.session.exec(
            select(AssetDomain).where(
                AssetDomain.asset_id == asset_id,
                AssetDomain.domain_id == domain_id,
                AssetDomain.relationship == relationship,
            )
        ).first()
        now = utcnow()
        if link is not None:
            link.last_seen = now
            link.confidence = max(float(link.confidence or 0), confidence)
            return

        self.session.add(
            AssetDomain(
                asset_id=asset_id,
                domain_id=domain_id,
                relationship=relationship,
                confidence=confidence,
                first_seen=now,
                last_seen=now,
            )
        )

    def ensure_organization(self, name: str | None, country_code: str | None = None) -> Organization | None:
        normalized = normalize_org_name(name)
        if not normalized or normalized in IGNORED_ORG_NAMES:
            return None

        organization = self.session.exec(
            select(Organization).where(
                Organization.normalized_name == normalized,
                Organization.country_code == country_code,
            )
        ).first()
        now = utcnow()
        if organization is not None:
            organization.updated_at = now
            return organization

        organization = Organization(
            name=name.strip(),
            normalized_name=normalized,
            country_code=country_code,
            created_at=now,
            updated_at=now,
        )
        self.session.add(organization)
        self.session.flush()
        return organization

    def ensure_contact(
        self,
        *,
        organization_id: str | None,
        domain_id: str | None,
        contact_type: str,
        value: str,
        source_type: str,
        source_url: str | None,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> ContactEndpoint:
        normalized_value = value.strip().lower()
        existing = self.session.exec(
            select(ContactEndpoint).where(
                ContactEndpoint.organization_id == organization_id,
                ContactEndpoint.domain_id == domain_id,
                ContactEndpoint.contact_type == contact_type,
                ContactEndpoint.value_normalized == normalized_value,
                ContactEndpoint.source_type == source_type,
            )
        ).first()
        now = utcnow()
        is_role_account = any(role in normalized_value for role in ROLE_LOCALPARTS)

        if existing is not None:
            existing.last_seen = now
            existing.last_verified_at = now
            existing.confidence = max(float(existing.confidence or 0), confidence)
            existing.source_url = source_url or existing.source_url
            existing.metadata_json = {**(existing.metadata_json or {}), **(metadata or {})}
            return existing

        contact = ContactEndpoint(
            organization_id=organization_id,
            domain_id=domain_id,
            contact_type=contact_type,
            value=value,
            value_normalized=normalized_value,
            source_type=source_type,
            source_url=source_url,
            is_role_account=is_role_account,
            confidence=confidence,
            first_seen=now,
            last_seen=now,
            last_verified_at=now,
            metadata_json=metadata or {},
        )
        self.session.add(contact)
        self.session.flush()
        return contact

    def ensure_fetch(
        self,
        *,
        source_type: str,
        fetch_kind: str,
        request_url: str,
        request_key: str,
        subject: dict[str, str | None],
        http_status: int | None,
        fetch_status: str,
        response_body: str | None,
        metadata: dict[str, Any] | None = None,
        parser_version: str | None = None,
    ) -> RawFetch:
        content_hash = None
        if response_body is not None:
            content_hash = hashlib.sha256(response_body.encode("utf-8")).hexdigest()

        if content_hash is not None:
            existing = self.session.exec(
                select(RawFetch).where(
                    RawFetch.source_type == source_type,
                    RawFetch.request_key == request_key,
                    RawFetch.content_hash == content_hash,
                )
            ).first()
            if existing is not None:
                existing.fetch_status = fetch_status
                existing.http_status = http_status
                existing.transport_ok = http_status is not None
                existing.parse_ok = http_status == 200
                existing.extraction_ok = existing.extraction_ok or fetch_status == "ok"
                existing.last_verified_at = utcnow()
                existing.metadata_json = {**(existing.metadata_json or {}), **(metadata or {})}
                return existing

        fetch = RawFetch(
            source_type=source_type,
            fetch_kind=fetch_kind,
            asset_id=subject.get("asset_id"),
            domain_id=subject.get("domain_id"),
            asn_id=subject.get("asn_id"),
            organization_id=subject.get("organization_id"),
            request_url=request_url,
            canonical_url=request_url,
            request_key=request_key,
            http_status=http_status,
            fetch_status=fetch_status,
            transport_ok=http_status is not None,
            parse_ok=http_status == 200,
            extraction_ok=fetch_status == "ok",
            content_hash=content_hash,
            parser_version=parser_version,
            fetched_at=utcnow(),
            last_verified_at=utcnow(),
            metadata_json=metadata or {},
        )
        self.session.add(fetch)
        self.session.flush()
        return fetch

    def add_observation(
        self,
        *,
        raw_fetch_id: str,
        evidence_type: str,
        raw_value: str | None,
        normalized_value: str | None,
        subject: dict[str, str | None],
        confidence: float,
        weight: float,
        metadata: dict[str, Any] | None = None,
    ) -> SourceObservation:
        observation = SourceObservation(
            raw_fetch_id=raw_fetch_id,
            asset_id=subject.get("asset_id"),
            domain_id=subject.get("domain_id"),
            organization_id=subject.get("organization_id"),
            asn_id=subject.get("asn_id"),
            contact_id=subject.get("contact_id"),
            evidence_type=evidence_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            observed_at=utcnow(),
            last_seen_at=utcnow(),
            weight=weight,
            confidence=confidence,
            metadata_json=metadata or {},
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def ensure_enrichment_run(self, asset_id: str) -> EnrichmentRun:
        run = self.session.exec(select(EnrichmentRun).where(EnrichmentRun.asset_id == asset_id)).first()
        if run is not None:
            return run

        run = EnrichmentRun(asset_id=asset_id)
        self.session.add(run)
        self.session.flush()
        return run


class LeadEnrichmentService:
    def __init__(self, session: Session, http_client: httpx.Client | None = None):
        self.session = session
        self.store = LeadEvidenceStore(session)
        self.http_client = http_client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "our-gpus-lead-enrichment/0.1"},
        )
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def _fetch_json(self, url: str) -> tuple[int | None, str | None, dict[str, Any] | None]:
        try:
            response = self.http_client.get(url)
            text = response.text
            payload = response.json() if response.is_success else None
            return response.status_code, text, payload
        except Exception as exc:  # noqa: BLE001
            return None, str(exc), None

    def _fetch_text(self, url: str) -> tuple[int | None, str]:
        try:
            response = self.http_client.get(url)
            return response.status_code, response.text
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    def _reverse_dns(self, ip: str) -> str | None:
        try:
            hostname, _aliases, _ips = socket.gethostbyaddr(ip)
            return hostname.lower()
        except Exception:  # noqa: BLE001
            return None

    def enrich_asset(
        self,
        *,
        asset_id: str,
        requested_sources: list[str],
        candidate_domains: list[str],
        force_refresh: bool,
        fetch_versions: dict[str, str],
    ) -> dict[str, Any]:
        asset = self.session.exec(select(Asset).where(Asset.id == asset_id)).first()
        if asset is None:
            raise ValueError("Asset not found")

        run = self.store.ensure_enrichment_run(asset.id)
        run.last_started_at = utcnow()
        run.updated_at = utcnow()
        run.source_versions = fetch_versions
        summary: dict[str, Any] = {}

        domains = self._collect_candidate_domains(asset, candidate_domains)

        if "rdap" in requested_sources:
            summary["rdap"] = self._enrich_rdap(asset, domains, force_refresh)
            run.rdap_status = summary["rdap"]["status"]

        if "ptr" in requested_sources:
            summary["ptr"] = self._enrich_ptr(asset)
            run.ptr_status = summary["ptr"]["status"]
            ptr_domain = summary["ptr"].get("hostname")
            if ptr_domain:
                domains.update(self._domain_variants(ptr_domain))

        if "tls" in requested_sources or "ct" in requested_sources:
            summary["tls_ct"] = {"status": "skipped", "reason": "not yet implemented"}
            run.tls_ct_status = "skipped"

        if "security_txt" in requested_sources:
            summary["security_txt"] = self._enrich_security_txt(asset, sorted(domains), force_refresh)
            run.security_txt_status = summary["security_txt"]["status"]

        if "website" in requested_sources:
            summary["website"] = self._enrich_website_contacts(asset, sorted(domains), force_refresh)
            run.contact_page_status = summary["website"]["status"]

        run.last_finished_at = utcnow()
        run.updated_at = utcnow()
        self.session.add(run)
        return summary

    def _collect_candidate_domains(self, asset: Asset, candidate_domains: list[str]) -> set[str]:
        domains: set[str] = set()
        for value in candidate_domains:
            domains.update(self._domain_variants(value))
        if asset.domain:
            domains.update(self._domain_variants(asset.domain))
        if asset.hostname and "." in asset.hostname:
            domains.update(self._domain_variants(asset.hostname))

        linked_domain_ids = self.session.exec(
            select(AssetDomain.domain_id).where(AssetDomain.asset_id == asset.id)
        ).all()
        if linked_domain_ids:
            linked_domains = self.session.exec(
                select(DomainRecord).where(DomainRecord.id.in_(linked_domain_ids))
            ).all()
            for domain in linked_domains:
                domains.update(self._domain_variants(domain.fqdn))
        return {domain for domain in domains if domain}

    def _domain_variants(self, value: str | None) -> set[str]:
        normalized = normalize_domain(value)
        if not normalized or "." not in normalized:
            return set()
        return {normalized, root_domain(normalized)}

    def _classify_contact_value(self, value: str) -> str:
        lower_value = value.lower()
        if "abuse" in lower_value:
            return "abuse"
        if any(token in lower_value for token in ("security", "csirt", "cert", "soc")):
            return "security"
        return "business"

    def _extract_rdap_asn(self, payload: Any) -> int | None:
        if isinstance(payload, dict):
            if payload.get("objectClassName") == "autnum" and isinstance(payload.get("handle"), str):
                handle = payload["handle"].upper().removeprefix("AS")
                if handle.isdigit():
                    return int(handle)
            for key, value in payload.items():
                if "autnum" in key.lower() and isinstance(value, list):
                    for item in value:
                        if isinstance(item, int):
                            return item
                        if isinstance(item, str) and item.upper().removeprefix("AS").isdigit():
                            return int(item.upper().removeprefix("AS"))
                nested = self._extract_rdap_asn(value)
                if nested is not None:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._extract_rdap_asn(item)
                if nested is not None:
                    return nested
        return None

    def _extract_vcard_properties(self, entity: dict[str, Any]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        vcard = entity.get("vcardArray")
        if not (isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list)):
            return result
        for item in vcard[1]:
            if not (isinstance(item, list) and len(item) >= 4):
                continue
            key = str(item[0]).lower()
            value = item[3]
            if isinstance(value, list):
                value = " ".join(str(part) for part in value if part)
            if value is None:
                continue
            result[key].append(str(value))
        return result

    def _upsert_rdap_entity(
        self,
        *,
        asset: Asset,
        payload: dict[str, Any],
        fetch: RawFetch,
        evidence_type: str,
        domain: DomainRecord | None = None,
    ) -> dict[str, Any]:
        top_name = payload.get("name") or payload.get("ldhName") or payload.get("unicodeName")
        organization = self.store.ensure_organization(top_name)
        subject = {
            "asset_id": asset.id,
            "domain_id": domain.id if domain else None,
            "organization_id": organization.id if organization else None,
            "asn_id": None,
            "contact_id": None,
        }

        if top_name:
            self.store.add_observation(
                raw_fetch_id=fetch.id,
                evidence_type=evidence_type,
                raw_value=json.dumps({"name": top_name}, sort_keys=True),
                normalized_value=str(top_name),
                subject=subject,
                confidence=80,
                weight=SOURCE_WEIGHT.get(evidence_type, 20.0),
                metadata={"source": "rdap-top-level"},
            )

        entities = payload.get("entities", []) if isinstance(payload.get("entities"), list) else []
        contacts_created = 0
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            roles = [str(role).lower() for role in entity.get("roles", []) if role]
            properties = self._extract_vcard_properties(entity)
            org_name = next(iter(properties.get("org", [])), None) or next(
                iter(properties.get("fn", [])), None
            )
            entity_org = self.store.ensure_organization(org_name)
            entity_subject = {
                "asset_id": asset.id,
                "domain_id": domain.id if domain else None,
                "organization_id": entity_org.id if entity_org else subject["organization_id"],
                "asn_id": None,
                "contact_id": None,
            }
            if org_name:
                self.store.add_observation(
                    raw_fetch_id=fetch.id,
                    evidence_type="rdap_entity",
                    raw_value=json.dumps({"roles": roles, "name": org_name}, sort_keys=True),
                    normalized_value=org_name,
                    subject=entity_subject,
                    confidence=75,
                    weight=SOURCE_WEIGHT["rdap_entity"],
                    metadata={"roles": roles},
                )

            for email in properties.get("email", []):
                contact_type = "abuse" if "abuse" in roles else self._classify_contact_value(email)
                contact = self.store.ensure_contact(
                    organization_id=entity_subject["organization_id"],
                    domain_id=domain.id if domain else None,
                    contact_type=contact_type,
                    value=email if email.startswith("mailto:") else f"mailto:{email}",
                    source_type="rdap",
                    source_url=fetch.request_url,
                    confidence=85,
                    metadata={"roles": roles},
                )
                self.store.add_observation(
                    raw_fetch_id=fetch.id,
                    evidence_type="rdap_contact",
                    raw_value=email,
                    normalized_value=email.lower(),
                    subject={**entity_subject, "contact_id": contact.id},
                    confidence=90,
                    weight=20,
                    metadata={"roles": roles, "contact_type": contact_type},
                )
                contacts_created += 1

        asn_value = self._extract_rdap_asn(payload)
        if asn_value is not None:
            asn = self.session.exec(
                select(AutonomousSystem).where(AutonomousSystem.asn == asn_value)
            ).first()
            if asn is None:
                asn = AutonomousSystem(
                    asn=asn_value,
                    org_name=top_name,
                    organization_id=subject["organization_id"],
                )
                self.session.add(asn)
                self.session.flush()
            asset.asn_id = asn.id
            self.store.add_observation(
                raw_fetch_id=fetch.id,
                evidence_type="rdap_asn",
                raw_value=str(asn_value),
                normalized_value=str(asn_value),
                subject={**subject, "asn_id": asn.id},
                confidence=80,
                weight=25,
                metadata={"asn": asn_value},
            )

        return {
            "organization_id": subject["organization_id"],
            "contacts_created": contacts_created,
            "asn": asn_value,
        }

    def _enrich_rdap(self, asset: Asset, domains: set[str], force_refresh: bool) -> dict[str, Any]:
        del force_refresh
        results: dict[str, Any] = {"status": "skipped", "lookups": 0, "contacts_created": 0}

        if asset.ip:
            url = f"https://rdap.org/ip/{asset.ip}"
            status_code, body, payload = self._fetch_json(url)
            fetch_status = "ok" if status_code == 200 and payload else "error"
            fetch = self.store.ensure_fetch(
                source_type="rdap",
                fetch_kind="ip_rdap",
                request_url=url,
                request_key=f"rdap:ip:{asset.ip}",
                subject={"asset_id": asset.id, "domain_id": None, "asn_id": None, "organization_id": None},
                http_status=status_code,
                fetch_status=fetch_status if status_code != 404 else "not_found",
                response_body=body,
                metadata={"asset_ip": asset.ip},
                parser_version="rdap-v1",
            )
            results["lookups"] += 1
            if payload:
                parsed = self._upsert_rdap_entity(
                    asset=asset,
                    payload=payload,
                    fetch=fetch,
                    evidence_type="rdap_network",
                )
                results["status"] = "ok"
                results["contacts_created"] += parsed["contacts_created"]
            elif status_code == 404:
                results["status"] = "not_found"
            else:
                results["status"] = "error"

        for domain_value in sorted(domains):
            domain = self.store.ensure_domain_record(domain_value, "rdap")
            rdap_domain = root_domain(domain.fqdn)
            url = f"https://rdap.org/domain/{rdap_domain}"
            status_code, body, payload = self._fetch_json(url)
            fetch = self.store.ensure_fetch(
                source_type="rdap",
                fetch_kind="domain_rdap",
                request_url=url,
                request_key=f"rdap:domain:{rdap_domain}",
                subject={"asset_id": asset.id, "domain_id": domain.id, "asn_id": None, "organization_id": None},
                http_status=status_code,
                fetch_status=(
                    "ok"
                    if status_code == 200 and payload
                    else "not_found"
                    if status_code == 404
                    else "error"
                ),
                response_body=body,
                metadata={"domain": rdap_domain},
                parser_version="rdap-v1",
            )
            results["lookups"] += 1
            if payload:
                parsed = self._upsert_rdap_entity(
                    asset=asset,
                    payload=payload,
                    fetch=fetch,
                    evidence_type="domain_registration",
                    domain=domain,
                )
                results["status"] = "ok"
                results["contacts_created"] += parsed["contacts_created"]
                self.store.ensure_asset_domain_link(asset.id, domain.id, "domain_registration", 80)

        return results

    def _enrich_ptr(self, asset: Asset) -> dict[str, Any]:
        if not asset.ip:
            return {"status": "skipped", "reason": "asset has no ip"}

        hostname = self._reverse_dns(asset.ip)
        fetch = self.store.ensure_fetch(
            source_type="ptr",
            fetch_kind="reverse_dns",
            request_url=f"ptr://{asset.ip}",
            request_key=f"ptr:{asset.ip}",
            subject={"asset_id": asset.id, "domain_id": None, "asn_id": None, "organization_id": None},
            http_status=200 if hostname else 404,
            fetch_status="ok" if hostname else "not_found",
            response_body=hostname,
            metadata={"ip": asset.ip},
            parser_version="ptr-v1",
        )
        if not hostname:
            return {"status": "not_found"}

        asset.hostname = asset.hostname or hostname
        domain = self.store.ensure_domain_record(hostname, "ptr")
        self.store.ensure_asset_domain_link(asset.id, domain.id, "ptr", 65)
        self.store.add_observation(
            raw_fetch_id=fetch.id,
            evidence_type="ptr",
            raw_value=hostname,
            normalized_value=hostname,
            subject={"asset_id": asset.id, "domain_id": domain.id, "organization_id": None, "asn_id": None, "contact_id": None},
            confidence=70,
            weight=SOURCE_WEIGHT["ptr"],
            metadata={"ip": asset.ip},
        )
        return {"status": "ok", "hostname": hostname}

    def _parse_security_txt(self, text: str) -> dict[str, Any]:
        fields: dict[str, list[str]] = defaultdict(list)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = FIELD_RE.match(stripped)
            if not match:
                continue
            key, value = match.groups()
            fields[key.lower()].append(value.strip())
        return {
            "contacts": fields.get("contact", []),
            "policies": fields.get("policy", []),
            "expires": fields.get("expires", []),
            "canonical": fields.get("canonical", []),
            "valid": bool(fields.get("contact")),
        }

    def _enrich_security_txt(
        self, asset: Asset, domains: list[str], force_refresh: bool
    ) -> dict[str, Any]:
        del force_refresh
        contacts_created = 0
        lookups = 0
        had_valid = False
        for domain_value in domains:
            domain = self.store.ensure_domain_record(domain_value, "security_txt")
            for url in (
                f"https://{domain.fqdn}/.well-known/security.txt",
                f"https://{domain.fqdn}/security.txt",
            ):
                status_code, body = self._fetch_text(url)
                fetch_status = "ok" if status_code == 200 else "not_found" if status_code == 404 else "error"
                fetch = self.store.ensure_fetch(
                    source_type="security_txt",
                    fetch_kind="security_txt",
                    request_url=url,
                    request_key=f"security_txt:{domain.fqdn}:{urlparse(url).path}",
                    subject={"asset_id": asset.id, "domain_id": domain.id, "asn_id": None, "organization_id": None},
                    http_status=status_code,
                    fetch_status=fetch_status,
                    response_body=body,
                    metadata={"domain": domain.fqdn},
                    parser_version="securitytxt-rfc9116-v1",
                )
                lookups += 1
                if status_code != 200:
                    continue

                parsed = self._parse_security_txt(body)
                fetch.extraction_ok = parsed["valid"]
                fetch.metadata_json = {**(fetch.metadata_json or {}), **parsed}
                self.store.ensure_asset_domain_link(asset.id, domain.id, "security_txt", 85)

                for contact_value in parsed["contacts"]:
                    contact_type = self._classify_contact_value(contact_value)
                    contact = self.store.ensure_contact(
                        organization_id=None,
                        domain_id=domain.id,
                        contact_type=contact_type,
                        value=contact_value,
                        source_type="security_txt",
                        source_url=url,
                        confidence=98,
                        metadata={"valid": parsed["valid"]},
                    )
                    self.store.add_observation(
                        raw_fetch_id=fetch.id,
                        evidence_type="security_txt_contact",
                        raw_value=contact_value,
                        normalized_value=contact_value.lower(),
                        subject={"asset_id": asset.id, "domain_id": domain.id, "organization_id": None, "asn_id": None, "contact_id": contact.id},
                        confidence=98,
                        weight=SOURCE_WEIGHT["security_txt_contact"],
                        metadata={"valid": parsed["valid"], "url": url},
                    )
                    contacts_created += 1

                for policy in parsed["policies"]:
                    self.store.add_observation(
                        raw_fetch_id=fetch.id,
                        evidence_type="security_txt_policy",
                        raw_value=policy,
                        normalized_value=policy,
                        subject={"asset_id": asset.id, "domain_id": domain.id, "organization_id": None, "asn_id": None, "contact_id": None},
                        confidence=80,
                        weight=10,
                        metadata={"url": url},
                    )

                had_valid = had_valid or parsed["valid"]
                if parsed["valid"]:
                    break
        return {
            "status": "ok" if had_valid else ("not_found" if lookups else "skipped"),
            "lookups": lookups,
            "contacts_created": contacts_created,
        }

    def _extract_emails(self, text: str) -> list[str]:
        return sorted({match.lower() for match in EMAIL_RE.findall(text or "")})

    def _enrich_website_contacts(
        self, asset: Asset, domains: list[str], force_refresh: bool
    ) -> dict[str, Any]:
        del force_refresh
        contacts_created = 0
        lookups = 0
        any_success = False
        for domain_value in domains:
            domain = self.store.ensure_domain_record(domain_value, "website")
            pages = [
                f"https://{domain.fqdn}/",
                f"https://{domain.fqdn}/security",
                f"https://{domain.fqdn}/contact",
            ]
            for url in pages:
                status_code, body = self._fetch_text(url)
                fetch = self.store.ensure_fetch(
                    source_type="website",
                    fetch_kind="website_contact",
                    request_url=url,
                    request_key=f"website:{domain.fqdn}:{urlparse(url).path or '/'}",
                    subject={"asset_id": asset.id, "domain_id": domain.id, "asn_id": None, "organization_id": None},
                    http_status=status_code,
                    fetch_status=(
                        "ok"
                        if status_code == 200
                        else "not_found"
                        if status_code == 404
                        else "error"
                    ),
                    response_body=body,
                    metadata={"domain": domain.fqdn, "path": urlparse(url).path or "/"},
                    parser_version="website-contact-v1",
                )
                lookups += 1
                if status_code != 200:
                    continue

                emails = self._extract_emails(body)
                if not emails and urlparse(url).path in {"/security", "/contact"}:
                    contact_type = "security" if urlparse(url).path == "/security" else "business"
                    contact = self.store.ensure_contact(
                        organization_id=None,
                        domain_id=domain.id,
                        contact_type=contact_type,
                        value=url,
                        source_type="website",
                        source_url=url,
                        confidence=45,
                        metadata={"page_url": url},
                    )
                    self.store.add_observation(
                        raw_fetch_id=fetch.id,
                        evidence_type="website_contact",
                        raw_value=url,
                        normalized_value=url,
                        subject={"asset_id": asset.id, "domain_id": domain.id, "organization_id": None, "asn_id": None, "contact_id": contact.id},
                        confidence=55,
                        weight=SOURCE_WEIGHT["website_contact"],
                        metadata={"page_url": url},
                    )
                    contacts_created += 1
                    any_success = True

                for email in emails:
                    contact_type = self._classify_contact_value(email)
                    contact = self.store.ensure_contact(
                        organization_id=None,
                        domain_id=domain.id,
                        contact_type=contact_type,
                        value=f"mailto:{email}",
                        source_type="website",
                        source_url=url,
                        confidence=70,
                        metadata={"page_url": url},
                    )
                    self.store.add_observation(
                        raw_fetch_id=fetch.id,
                        evidence_type="website_contact",
                        raw_value=email,
                        normalized_value=email,
                        subject={"asset_id": asset.id, "domain_id": domain.id, "organization_id": None, "asn_id": None, "contact_id": contact.id},
                        confidence=70,
                        weight=SOURCE_WEIGHT["website_contact"],
                        metadata={"page_url": url, "contact_type": contact_type},
                    )
                    contacts_created += 1
                    any_success = True
                if emails:
                    self.store.ensure_asset_domain_link(asset.id, domain.id, "website_contact", 60)
        return {
            "status": "ok" if any_success else ("not_found" if lookups else "skipped"),
            "lookups": lookups,
            "contacts_created": contacts_created,
        }


class LeadResolveScoreService:
    def __init__(self, session: Session):
        self.session = session
        self.store = LeadEvidenceStore(session)

    def resolve_lead(
        self,
        *,
        lead_record_id: str,
        resolver_version: str | None,
        scorer_version: str | None,
        recompute_org_candidates: bool,
        recompute_contact_routes: bool,
    ) -> dict[str, Any]:
        record = self.session.exec(select(LeadRecord).where(LeadRecord.id == lead_record_id)).first()
        if record is None:
            raise ValueError("Lead record not found")
        asset = self.session.exec(select(Asset).where(Asset.id == record.asset_id)).first()
        if asset is None:
            raise ValueError("Asset not found")

        domain_records = self._collect_asset_domains(asset)
        if recompute_org_candidates:
            self._recompute_org_candidates(asset, domain_records)
        resolution, conflict_penalty = self._apply_org_resolution(asset)
        if recompute_contact_routes:
            top_contact = self._recompute_contact_candidates(
                record, resolution, domain_records, conflict_penalty
            )
        else:
            top_contact = self._top_contact_candidate(record.id)

        record.org_resolution_id = resolution.id if resolution else None
        record.organization_id = resolution.organization_id if resolution else None
        record.primary_contact_id = top_contact.contact_id if top_contact else None
        record.recommended_route = top_contact.route if top_contact else "manual_review"
        record.org_conflict_penalty = conflict_penalty
        record.org_confidence = float(resolution.confidence or 0) if resolution else 0.0
        if top_contact:
            record.contact_quality = float(top_contact.contact_quality or 0)
            record.route_legitimacy = float(top_contact.route_legitimacy or 0)
            record.confidence_score = max(0.0, min(100.0, float(top_contact.score or 0)))
        else:
            record.contact_quality = 0.0
            record.route_legitimacy = 0.0
            record.confidence_score = max(0.0, min(100.0, record.org_confidence - conflict_penalty))
        record.resolver_version = resolver_version or record.resolver_version or "resolver-v0.1"
        record.scorer_version = scorer_version or record.scorer_version or "score-v0.1"
        record.last_resolved_at = utcnow()
        record.updated_at = utcnow()
        self.session.add(record)
        return {
            "lead_record_id": record.id,
            "organization_id": record.organization_id,
            "primary_contact_id": record.primary_contact_id,
            "recommended_route": record.recommended_route,
            "confidence_score": float(record.confidence_score or 0),
        }

    def rescore_lead(self, *, lead_record_id: str, scorer_version: str | None) -> dict[str, Any]:
        return self.resolve_lead(
            lead_record_id=lead_record_id,
            resolver_version=None,
            scorer_version=scorer_version,
            recompute_org_candidates=False,
            recompute_contact_routes=True,
        )

    def _collect_asset_domains(self, asset: Asset) -> list[DomainRecord]:
        domains: dict[str, DomainRecord] = {}
        if asset.domain:
            domain = self.store.ensure_domain_record(asset.domain, "manual")
            domains[domain.id] = domain
        if asset.hostname and "." in asset.hostname:
            domain = self.store.ensure_domain_record(asset.hostname, "manual")
            domains[domain.id] = domain
        linked_domain_ids = self.session.exec(
            select(AssetDomain.domain_id).where(AssetDomain.asset_id == asset.id)
        ).all()
        if linked_domain_ids:
            for domain in self.session.exec(select(DomainRecord).where(DomainRecord.id.in_(linked_domain_ids))).all():
                domains[domain.id] = domain
        return list(domains.values())

    def _recompute_org_candidates(self, asset: Asset, domains: list[DomainRecord]) -> None:
        existing = self.session.exec(select(OrgCandidate).where(OrgCandidate.asset_id == asset.id)).all()
        for row in existing:
            self.session.delete(row)
        self.session.flush()

        bucket: dict[str, dict[str, Any]] = {}

        observations = self.session.exec(
            select(SourceObservation).where(SourceObservation.asset_id == asset.id)
        ).all()
        organizations = {}
        organization_ids = {ob.organization_id for ob in observations if ob.organization_id}
        if organization_ids:
            organizations = {
                org.id: org
                for org in self.session.exec(
                    select(Organization).where(Organization.id.in_(organization_ids))
                ).all()
            }

        def add_candidate(
            name: str | None,
            *,
            score: float,
            source: str,
            organization_id: str | None = None,
            reason: str | None = None,
        ) -> None:
            normalized = normalize_org_name(name)
            if not normalized:
                return
            entry = bucket.setdefault(
                normalized,
                {
                    "name": name.strip() if name else normalized,
                    "organization_id": organization_id,
                    "score": 0.0,
                    "reasons": [],
                    "sources": set(),
                },
            )
            entry["score"] += score
            entry["sources"].add(source)
            entry["reasons"].append({"source": source, "score": score, "reason": reason or source})
            if entry["organization_id"] is None and organization_id is not None:
                entry["organization_id"] = organization_id

        for observation in observations:
            if observation.organization_id and observation.organization_id in organizations:
                org = organizations[observation.organization_id]
                add_candidate(
                    org.name,
                    score=SOURCE_WEIGHT.get(observation.evidence_type, float(observation.weight or 5)),
                    source=observation.evidence_type,
                    organization_id=org.id,
                    reason=f"observation:{observation.evidence_type}",
                )
            elif observation.evidence_type in {"rdap_network", "rdap_entity", "domain_registration"}:
                add_candidate(
                    observation.normalized_value,
                    score=SOURCE_WEIGHT.get(observation.evidence_type, 15),
                    source=observation.evidence_type,
                    reason="text-derived candidate",
                )

        if asset.asn_id:
            asn = self.session.exec(select(AutonomousSystem).where(AutonomousSystem.id == asset.asn_id)).first()
            if asn and asn.org_name:
                add_candidate(asn.org_name, score=20, source="rdap_asn", organization_id=asn.organization_id)

        for domain in domains:
            display_name = infer_display_name_from_domain(domain.fqdn)
            add_candidate(display_name, score=25, source="domain", reason=f"domain:{domain.fqdn}")

        items = list(bucket.items())
        for normalized_a, entry_a in items:
            tokens_a = set(normalized_a.split())
            if not tokens_a:
                continue
            for normalized_b, entry_b in items:
                if normalized_a == normalized_b:
                    continue
                tokens_b = set(normalized_b.split())
                if not tokens_a & tokens_b:
                    continue
                if "domain" in entry_a["sources"] and any(
                    source.startswith("rdap") for source in entry_b["sources"]
                ):
                    entry_b["score"] += 15
                    entry_b["reasons"].append(
                        {"source": "signal_overlap", "score": 15, "reason": f"domain overlap:{entry_a['name']}"}
                    )

        now = utcnow()
        for normalized, entry in bucket.items():
            organization_id = entry["organization_id"]
            if organization_id is None:
                organization = self.store.ensure_organization(entry["name"])
                organization_id = organization.id if organization else None
            self.session.add(
                OrgCandidate(
                    asset_id=asset.id,
                    organization_id=organization_id,
                    name=entry["name"],
                    normalized_name=normalized,
                    score=min(100.0, entry["score"]),
                    org_conflict_penalty=0.0,
                    rationale=entry["reasons"],
                    created_at=now,
                    last_evaluated_at=now,
                )
            )
        self.session.flush()

    def _apply_org_resolution(self, asset: Asset) -> tuple[OrgResolution | None, float]:
        candidates = self.session.exec(
            select(OrgCandidate)
            .where(OrgCandidate.asset_id == asset.id)
            .order_by(OrgCandidate.score.desc(), OrgCandidate.last_evaluated_at.desc())
        ).all()
        if not candidates:
            existing = self.session.exec(select(OrgResolution).where(OrgResolution.asset_id == asset.id)).first()
            if existing is not None:
                existing.organization_id = None
                existing.winning_org_candidate_id = None
                existing.confidence = 0.0
                existing.rationale = []
                existing.resolved_at = utcnow()
            return existing, 0.0

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        conflict_penalty = 0.0
        if second is not None and second.normalized_name != top.normalized_name:
            if float(second.score or 0) >= float(top.score or 0) - 10:
                conflict_penalty = 25.0
            elif float(second.score or 0) >= float(top.score or 0) - 20:
                conflict_penalty = 10.0

        top.org_conflict_penalty = conflict_penalty
        resolution = self.session.exec(select(OrgResolution).where(OrgResolution.asset_id == asset.id)).first()
        if resolution is None:
            resolution = OrgResolution(asset_id=asset.id)
        resolution.organization_id = top.organization_id
        resolution.winning_org_candidate_id = top.id
        resolution.resolution_mode = "auto"
        resolution.confidence = max(0.0, min(100.0, float(top.score or 0) - conflict_penalty))
        resolution.rationale = top.rationale or []
        resolution.resolved_at = utcnow()
        self.session.add(resolution)
        self.session.flush()
        return resolution, conflict_penalty

    def _top_contact_candidate(self, lead_record_id: str) -> LeadContactCandidate | None:
        return self.session.exec(
            select(LeadContactCandidate)
            .where(LeadContactCandidate.lead_record_id == lead_record_id)
            .order_by(LeadContactCandidate.rank.asc())
        ).first()

    def _recompute_contact_candidates(
        self,
        record: LeadRecord,
        resolution: OrgResolution | None,
        domains: list[DomainRecord],
        conflict_penalty: float,
    ) -> LeadContactCandidate | None:
        existing = self.session.exec(
            select(LeadContactCandidate).where(LeadContactCandidate.lead_record_id == record.id)
        ).all()
        for row in existing:
            self.session.delete(row)
        self.session.flush()

        contacts_query = select(ContactEndpoint)
        domain_ids = [domain.id for domain in domains]
        contacts = []
        if resolution and resolution.organization_id and domain_ids:
            contacts = self.session.exec(
                contacts_query.where(
                    (ContactEndpoint.organization_id == resolution.organization_id)
                    | (ContactEndpoint.domain_id.in_(domain_ids))
                )
            ).all()
        elif resolution and resolution.organization_id:
            contacts = self.session.exec(
                contacts_query.where(ContactEndpoint.organization_id == resolution.organization_id)
            ).all()
        elif domain_ids:
            contacts = self.session.exec(
                contacts_query.where(ContactEndpoint.domain_id.in_(domain_ids))
            ).all()

        org_confidence = float(resolution.confidence or 0) if resolution else 0.0
        ranked: list[tuple[float, ContactEndpoint, float, float, str]] = []
        seen_ids = set()
        for contact in contacts:
            if contact.id in seen_ids:
                continue
            seen_ids.add(contact.id)
            route_legitimacy = route_legitimacy_for_contact(contact)
            contact_quality = contact_quality_for_contact(contact)
            total = max(
                0.0,
                min(
                    100.0,
                    org_confidence * 0.4 + contact_quality * 0.3 + route_legitimacy * 0.3 - conflict_penalty,
                ),
            )
            ranked.append((total, contact, contact_quality, route_legitimacy, route_name_for_contact(contact)))

        ranked.sort(key=lambda item: item[0], reverse=True)
        now = utcnow()
        top_row = None
        for rank, (score, contact, contact_quality, route_legitimacy, route_name) in enumerate(ranked, start=1):
            row = LeadContactCandidate(
                lead_record_id=record.id,
                contact_id=contact.id,
                route=route_name,
                rank=rank,
                score=score,
                org_confidence=org_confidence,
                contact_quality=contact_quality,
                route_legitimacy=route_legitimacy,
                org_conflict_penalty=conflict_penalty,
                rationale=[
                    {
                        "source_type": contact.source_type,
                        "contact_type": contact.contact_type,
                        "org_confidence": org_confidence,
                        "contact_quality": contact_quality,
                        "route_legitimacy": route_legitimacy,
                    }
                ],
                last_evaluated_at=now,
            )
            self.session.add(row)
            if top_row is None:
                top_row = row
        self.session.flush()
        return top_row
