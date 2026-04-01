import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import settings
from app.db import (
    Asset,
    AssetDomain,
    CampaignCluster,
    CampaignClusterMember,
    ContactEndpoint,
    DomainRecord,
    EnrichmentJob,
    EnrichmentRun,
    LeadContactCandidate,
    LeadRecord,
    OrgCandidate,
    OrgResolution,
    RawFetch,
    SourceObservation,
    get_session,
)
from app.lead_schemas import (
    AssetImportRecord,
    AssetImportRequest,
    AssetImportResponse,
    AssetResponse,
    CampaignClusterResponse,
    ContactResponse,
    EnrichAssetRequest,
    EnrichmentRunResponse,
    EvidenceStepResponse,
    EvidenceSupport,
    JobQueuedResponse,
    LeadContactCandidateResponse,
    LeadRecordResponse,
    LeadScoreBreakdown,
    LeadStatusUpdateRequest,
    ManualAssetCreateRequest,
    OrgCandidateResponse,
    OrgResolutionResponse,
    PaginatedLeadRecordResponse,
    RescoreLeadRequest,
    ResolveLeadRequest,
    SourceType,
)

router = APIRouter(prefix="/api", tags=["lead-enrichment"])


def require_admin_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected_key = settings.get_admin_api_key()
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key is not configured",
        )

    if not x_api_key or not secrets.compare_digest(x_api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin API key",
        )


def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_domain(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def _root_domain(value: str) -> str:
    parts = [part for part in value.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return value


def _find_matching_asset(session: Session, row: AssetImportRecord) -> Asset | None:
    if row.ip:
        stmt = select(Asset).where(Asset.ip == row.ip)
    elif row.hostname:
        stmt = select(Asset).where(Asset.hostname == row.hostname.lower())
    elif row.domain:
        stmt = select(Asset).where(Asset.domain == row.domain.lower())
    else:
        return None

    if row.port is None:
        stmt = stmt.where(Asset.port.is_(None))
    else:
        stmt = stmt.where(Asset.port == row.port)

    if row.protocol is None:
        stmt = stmt.where(Asset.protocol.is_(None))
    else:
        stmt = stmt.where(Asset.protocol == row.protocol)

    return session.exec(stmt).first()


def _ensure_domain_record(session: Session, fqdn: str, source_type: str) -> DomainRecord:
    normalized = fqdn.lower()
    existing = session.exec(select(DomainRecord).where(DomainRecord.fqdn == normalized)).first()
    now = _utcnow()
    if existing is not None:
        existing.last_seen = now
        existing.updated_at = now
        return existing

    domain = DomainRecord(
        fqdn=normalized,
        root_domain=_root_domain(normalized),
        source_type=source_type,
        first_seen=now,
        last_seen=now,
        created_at=now,
        updated_at=now,
    )
    session.add(domain)
    session.flush()
    return domain


def _ensure_asset_domain_link(
    session: Session,
    asset_id: str,
    domain_id: str,
    relationship: str,
    confidence: float = 50.0,
) -> None:
    link = session.exec(
        select(AssetDomain).where(
            AssetDomain.asset_id == asset_id,
            AssetDomain.domain_id == domain_id,
            AssetDomain.relationship == relationship,
        )
    ).first()
    now = _utcnow()
    if link is not None:
        link.last_seen = now
        link.confidence = max(link.confidence, confidence)
        return

    session.add(
        AssetDomain(
            asset_id=asset_id,
            domain_id=domain_id,
            relationship=relationship,
            confidence=confidence,
            first_seen=now,
            last_seen=now,
        )
    )


def _ensure_lead_record(session: Session, asset: Asset) -> LeadRecord:
    record = session.exec(select(LeadRecord).where(LeadRecord.asset_id == asset.id)).first()
    if record is not None:
        return record

    now = _utcnow()
    record = LeadRecord(
        asset_id=asset.id,
        status="new",
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.flush()
    return record


def _import_one_asset(
    session: Session,
    row: AssetImportRecord,
    source_type: str,
    batch_id: str,
    row_index: int,
) -> tuple[Asset, LeadRecord, bool]:
    now = _utcnow()
    asset = _find_matching_asset(session, row)
    created = asset is None

    if asset is None:
        asset = Asset(
            ip=row.ip,
            hostname=_normalize_domain(row.hostname),
            domain=_normalize_domain(row.domain),
            port=row.port,
            protocol=row.protocol,
            service=row.service,
            first_seen=row.timestamp_seen or now,
            last_seen=row.timestamp_seen or now,
            created_at=now,
            updated_at=now,
        )
        session.add(asset)
        session.flush()
    else:
        asset.ip = asset.ip or row.ip
        asset.hostname = asset.hostname or _normalize_domain(row.hostname)
        asset.domain = asset.domain or _normalize_domain(row.domain)
        asset.port = asset.port if asset.port is not None else row.port
        asset.protocol = asset.protocol or row.protocol
        asset.service = asset.service or row.service
        asset.last_seen = row.timestamp_seen or now
        asset.updated_at = now

    domain = None
    if row.domain:
        domain = _ensure_domain_record(session, row.domain, source_type)
        asset.domain = domain.fqdn
        _ensure_asset_domain_link(session, asset.id, domain.id, "hostname_observed")

    fetch = RawFetch(
        source_type=source_type,
        fetch_kind="asset_import",
        asset_id=asset.id,
        domain_id=domain.id if domain else None,
        request_url=f"{source_type}://{batch_id}/{row_index}",
        canonical_url=f"{source_type}://{batch_id}/{row_index}",
        request_key=f"{source_type}:{batch_id}:{row_index}:{asset.id}",
        fetch_status="ok",
        transport_ok=True,
        parse_ok=True,
        extraction_ok=True,
        fetched_at=now,
        last_verified_at=now,
        metadata_json=row.model_dump(exclude_none=True),
    )
    session.add(fetch)
    session.flush()

    session.add(
        SourceObservation(
            raw_fetch_id=fetch.id,
            asset_id=asset.id,
            domain_id=domain.id if domain else None,
            evidence_type="asset_observation",
            raw_value=json.dumps(row.model_dump(exclude_none=True), sort_keys=True),
            normalized_value=row.ip or row.hostname or row.domain,
            observed_at=row.timestamp_seen or now,
            last_seen_at=row.timestamp_seen or now,
            weight=10,
            confidence=100,
            metadata_json={"source_type": source_type},
        )
    )

    lead_record = _ensure_lead_record(session, asset)
    return asset, lead_record, created


def _ensure_enrichment_run(session: Session, asset_id: str) -> EnrichmentRun:
    run = session.exec(select(EnrichmentRun).where(EnrichmentRun.asset_id == asset_id)).first()
    if run is not None:
        return run

    run = EnrichmentRun(asset_id=asset_id)
    session.add(run)
    session.flush()
    return run


def _enqueue_job(
    session: Session,
    *,
    job_type: str,
    payload: dict,
    asset_id: str | None = None,
    lead_record_id: str | None = None,
    worker_hint: str | None = None,
) -> EnrichmentJob:
    job = EnrichmentJob(
        job_type=job_type,
        status="queued",
        asset_id=asset_id,
        lead_record_id=lead_record_id,
        payload=payload,
        worker_hint=worker_hint,
        scheduled_at=_utcnow(),
    )
    session.add(job)
    session.flush()
    return job


def _serialize_contact(contact: ContactEndpoint | None) -> ContactResponse | None:
    if contact is None:
        return None
    return ContactResponse(
        id=contact.id,
        organization_id=contact.organization_id,
        domain_id=contact.domain_id,
        contact_type=contact.contact_type,
        value=contact.value,
        source_type=contact.source_type,
        source_url=contact.source_url,
        is_role_account=contact.is_role_account,
        confidence=float(contact.confidence or 0),
        last_verified_at=contact.last_verified_at,
        metadata=contact.metadata_json or {},
    )


def _serialize_asset(asset: Asset | None) -> AssetResponse | None:
    if asset is None:
        return None
    return AssetResponse(
        id=asset.id,
        ip=asset.ip,
        hostname=asset.hostname,
        domain=asset.domain,
        port=asset.port,
        protocol=asset.protocol,
        service=asset.service,
        country_code=asset.country_code,
        region=asset.region,
        city=asset.city,
        last_seen=asset.last_seen,
    )


def _serialize_org_candidate(candidate: OrgCandidate) -> OrgCandidateResponse:
    return OrgCandidateResponse(
        id=candidate.id,
        organization_id=candidate.organization_id,
        name=candidate.name,
        normalized_name=candidate.normalized_name,
        score=float(candidate.score or 0),
        org_conflict_penalty=float(candidate.org_conflict_penalty or 0),
        rationale=candidate.rationale or [],
        last_evaluated_at=candidate.last_evaluated_at,
    )


def _serialize_org_resolution(session: Session, resolution: OrgResolution | None) -> OrgResolutionResponse | None:
    if resolution is None:
        return None

    candidates = session.exec(
        select(OrgCandidate)
        .where(OrgCandidate.asset_id == resolution.asset_id)
        .order_by(OrgCandidate.score.desc(), OrgCandidate.last_evaluated_at.desc())
    ).all()

    return OrgResolutionResponse(
        id=resolution.id,
        organization_id=resolution.organization_id,
        winning_org_candidate_id=resolution.winning_org_candidate_id,
        resolution_mode=resolution.resolution_mode,
        confidence=float(resolution.confidence or 0),
        rationale=resolution.rationale or [],
        resolved_at=resolution.resolved_at,
        reviewed_at=resolution.reviewed_at,
        reviewer_note=resolution.reviewer_note,
        org_candidates=[_serialize_org_candidate(candidate) for candidate in candidates],
    )


def _serialize_evidence_steps(session: Session, asset_id: str) -> list[EvidenceStepResponse]:
    observations = session.exec(
        select(SourceObservation)
        .where(SourceObservation.asset_id == asset_id)
        .order_by(SourceObservation.observed_at.desc())
    ).all()
    if not observations:
        return []

    fetch_ids = {observation.raw_fetch_id for observation in observations if observation.raw_fetch_id}
    fetches = {
        fetch.id: fetch
        for fetch in session.exec(select(RawFetch).where(RawFetch.id.in_(fetch_ids))).all()
    }

    return [
        EvidenceStepResponse(
            id=observation.id,
            raw_fetch_id=observation.raw_fetch_id,
            kind=observation.evidence_type,
            source_type=(
                fetches[observation.raw_fetch_id].source_type
                if observation.raw_fetch_id in fetches
                else SourceType.MANUAL.value
            ),
            source_url=(
                fetches[observation.raw_fetch_id].request_url
                if observation.raw_fetch_id in fetches
                else None
            ),
            raw_value=observation.raw_value,
            normalized_value=observation.normalized_value,
            confidence=float(observation.confidence or 0),
            weight=float(observation.weight or 0),
            observed_at=observation.observed_at,
            supports=EvidenceSupport(
                asset_id=observation.asset_id,
                domain_id=observation.domain_id,
                organization_id=observation.organization_id,
                asn_id=observation.asn_id,
                contact_id=observation.contact_id,
            ),
            metadata=observation.metadata_json or {},
        )
        for observation in observations
    ]


def _serialize_contact_candidates(
    session: Session, lead_record_id: str
) -> list[LeadContactCandidateResponse]:
    candidates = session.exec(
        select(LeadContactCandidate)
        .where(LeadContactCandidate.lead_record_id == lead_record_id)
        .order_by(LeadContactCandidate.rank.asc(), LeadContactCandidate.score.desc())
    ).all()
    if not candidates:
        return []

    contact_ids = {candidate.contact_id for candidate in candidates}
    contacts = {
        contact.id: contact
        for contact in session.exec(select(ContactEndpoint).where(ContactEndpoint.id.in_(contact_ids))).all()
    }

    return [
        LeadContactCandidateResponse(
            id=candidate.id,
            contact_id=candidate.contact_id,
            route=candidate.route,
            rank=candidate.rank,
            score=float(candidate.score or 0),
            org_confidence=float(candidate.org_confidence or 0),
            contact_quality=float(candidate.contact_quality or 0),
            route_legitimacy=float(candidate.route_legitimacy or 0),
            org_conflict_penalty=float(candidate.org_conflict_penalty or 0),
            rationale=candidate.rationale or [],
            last_evaluated_at=candidate.last_evaluated_at,
            contact=_serialize_contact(contacts.get(candidate.contact_id)),
        )
        for candidate in candidates
    ]


def _assemble_lead_record(session: Session, record: LeadRecord) -> LeadRecordResponse:
    asset = session.exec(select(Asset).where(Asset.id == record.asset_id)).first()
    resolution = None
    if record.org_resolution_id:
        resolution = session.exec(
            select(OrgResolution).where(OrgResolution.id == record.org_resolution_id)
        ).first()
    if resolution is None:
        resolution = session.exec(
            select(OrgResolution).where(OrgResolution.asset_id == record.asset_id)
        ).first()

    primary_contact = None
    if record.primary_contact_id:
        primary_contact = session.exec(
            select(ContactEndpoint).where(ContactEndpoint.id == record.primary_contact_id)
        ).first()

    return LeadRecordResponse(
        id=record.id,
        asset_id=record.asset_id,
        organization_id=record.organization_id,
        org_resolution_id=record.org_resolution_id,
        primary_contact_id=record.primary_contact_id,
        status=record.status,
        recommended_route=record.recommended_route,
        notes=record.notes,
        scorer_version=record.scorer_version,
        resolver_version=record.resolver_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_resolved_at=record.last_resolved_at,
        asset=_serialize_asset(asset),
        organization=_serialize_org_resolution(session, resolution),
        primary_contact=_serialize_contact(primary_contact),
        scores=LeadScoreBreakdown(
            confidence_score=float(record.confidence_score or 0),
            org_confidence=float(record.org_confidence or 0),
            contact_quality=float(record.contact_quality or 0),
            route_legitimacy=float(record.route_legitimacy or 0),
            org_conflict_penalty=float(record.org_conflict_penalty or 0),
        ),
        contact_candidates=_serialize_contact_candidates(session, record.id),
        evidence_steps=_serialize_evidence_steps(session, record.asset_id),
    )


def _serialize_job(job: EnrichmentJob) -> JobQueuedResponse:
    return JobQueuedResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        scheduled_at=job.scheduled_at,
        worker_hint=job.worker_hint,
    )


@router.post(
    "/assets/import",
    response_model=AssetImportResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def import_assets(payload: AssetImportRequest, session: Session = Depends(get_session)) -> AssetImportResponse:
    batch_id = payload.import_batch_id or f"batch-{int(_utcnow().timestamp())}"
    created_count = 0
    updated_count = 0
    asset_ids: list[str] = []
    lead_ids: list[str] = []

    for row_index, row in enumerate(payload.rows, start=1):
        asset, lead_record, created = _import_one_asset(
            session,
            row,
            payload.source.value,
            batch_id,
            row_index,
        )
        if created:
            created_count += 1
        else:
            updated_count += 1
        asset_ids.append(asset.id)
        lead_ids.append(lead_record.id)

    session.commit()
    return AssetImportResponse(
        imported_count=len(payload.rows),
        created_count=created_count,
        updated_count=updated_count,
        asset_ids=asset_ids,
        lead_record_ids=lead_ids,
    )


@router.post(
    "/assets/manual",
    response_model=LeadRecordResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def create_manual_asset(
    payload: ManualAssetCreateRequest, session: Session = Depends(get_session)
) -> LeadRecordResponse:
    _, lead_record, _ = _import_one_asset(
        session,
        AssetImportRecord(
            ip=payload.ip,
            hostname=payload.hostname,
            domain=payload.domain,
            port=payload.port,
            protocol=payload.protocol,
            service=payload.service,
            timestamp_seen=payload.timestamp_seen,
        ),
        payload.source.value,
        batch_id=f"manual-{int(_utcnow().timestamp())}",
        row_index=1,
    )
    session.commit()
    session.refresh(lead_record)
    return _assemble_lead_record(session, lead_record)


@router.post(
    "/enrich/{asset_id}",
    response_model=JobQueuedResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def enqueue_asset_enrichment(
    asset_id: str,
    payload: EnrichAssetRequest,
    session: Session = Depends(get_session),
) -> JobQueuedResponse:
    asset = session.exec(select(Asset).where(Asset.id == asset_id)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    run = _ensure_enrichment_run(session, asset_id)
    now = _utcnow()
    requested_sources = {source.value for source in payload.requested_sources}
    if "rdap" in requested_sources:
        run.rdap_status = "pending"
    if "ptr" in requested_sources:
        run.ptr_status = "pending"
    if {"tls", "ct"} & requested_sources:
        run.tls_ct_status = "pending"
    if "security_txt" in requested_sources:
        run.security_txt_status = "pending"
    if "website" in requested_sources:
        run.contact_page_status = "pending"
    run.source_versions = payload.fetch_versions
    run.last_started_at = now
    run.updated_at = now

    job = _enqueue_job(
        session,
        job_type="enrich_asset",
        asset_id=asset_id,
        worker_hint="enrich",
        payload={
            "asset_id": asset_id,
            "requested_sources": [source.value for source in payload.requested_sources],
            "candidate_domains": payload.candidate_domains,
            "force_refresh": payload.force_refresh,
            "fetch_versions": payload.fetch_versions,
        },
    )
    session.commit()
    return _serialize_job(job)


@router.post(
    "/resolve/{lead_id}",
    response_model=JobQueuedResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def enqueue_lead_resolution(
    lead_id: str,
    payload: ResolveLeadRequest,
    session: Session = Depends(get_session),
) -> JobQueuedResponse:
    lead_record = session.exec(select(LeadRecord).where(LeadRecord.id == lead_id)).first()
    if lead_record is None:
        raise HTTPException(status_code=404, detail="Lead record not found")

    job = _enqueue_job(
        session,
        job_type="resolve_lead",
        lead_record_id=lead_id,
        asset_id=lead_record.asset_id,
        worker_hint="resolve",
        payload={
            "lead_record_id": lead_id,
            "asset_id": lead_record.asset_id,
            "resolver_version": payload.resolver_version,
            "scorer_version": payload.scorer_version,
            "recompute_org_candidates": payload.recompute_org_candidates,
            "recompute_contact_routes": payload.recompute_contact_routes,
        },
    )
    session.commit()
    return _serialize_job(job)


@router.post(
    "/re-score/{lead_id}",
    response_model=JobQueuedResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def enqueue_lead_rescore(
    lead_id: str,
    payload: RescoreLeadRequest,
    session: Session = Depends(get_session),
) -> JobQueuedResponse:
    lead_record = session.exec(select(LeadRecord).where(LeadRecord.id == lead_id)).first()
    if lead_record is None:
        raise HTTPException(status_code=404, detail="Lead record not found")

    job = _enqueue_job(
        session,
        job_type="rescore_lead",
        lead_record_id=lead_id,
        asset_id=lead_record.asset_id,
        worker_hint="resolve",
        payload={
            "lead_record_id": lead_id,
            "scorer_version": payload.scorer_version,
            "reason": payload.reason,
        },
    )
    session.commit()
    return _serialize_job(job)


@router.get(
    "/lead-records",
    response_model=PaginatedLeadRecordResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def list_lead_records(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    minimum_confidence: float | None = Query(default=None, ge=0, le=100),
    session: Session = Depends(get_session),
) -> PaginatedLeadRecordResponse:
    stmt = select(LeadRecord)
    count_stmt = select(func.count()).select_from(LeadRecord)

    if status_filter:
        stmt = stmt.where(LeadRecord.status == status_filter)
        count_stmt = count_stmt.where(LeadRecord.status == status_filter)
    if minimum_confidence is not None:
        stmt = stmt.where(LeadRecord.confidence_score >= minimum_confidence)
        count_stmt = count_stmt.where(LeadRecord.confidence_score >= minimum_confidence)

    total = session.exec(count_stmt).one()
    records = session.exec(
        stmt.order_by(LeadRecord.confidence_score.desc(), LeadRecord.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    pages = (total + size - 1) // size if total else 0

    return PaginatedLeadRecordResponse(
        items=[_assemble_lead_record(session, record) for record in records],
        total=total,
        page=page,
        size=size,
        pages=pages,
    )


@router.get(
    "/lead-records/{lead_id}",
    response_model=LeadRecordResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def get_lead_record(lead_id: str, session: Session = Depends(get_session)) -> LeadRecordResponse:
    record = session.exec(select(LeadRecord).where(LeadRecord.id == lead_id)).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Lead record not found")
    return _assemble_lead_record(session, record)


@router.post(
    "/lead-records/{lead_id}/status",
    response_model=LeadRecordResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def update_lead_status(
    lead_id: str,
    payload: LeadStatusUpdateRequest,
    session: Session = Depends(get_session),
) -> LeadRecordResponse:
    record = session.exec(select(LeadRecord).where(LeadRecord.id == lead_id)).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Lead record not found")

    record.status = payload.status.value
    if payload.notes is not None:
        record.notes = payload.notes
    record.updated_at = _utcnow()
    session.add(record)
    session.commit()
    session.refresh(record)
    return _assemble_lead_record(session, record)


@router.get(
    "/clusters",
    response_model=list[CampaignClusterResponse],
    dependencies=[Depends(require_admin_api_key)],
)
def list_campaign_clusters(session: Session = Depends(get_session)) -> list[CampaignClusterResponse]:
    clusters = session.exec(
        select(CampaignCluster).order_by(CampaignCluster.cluster_type, CampaignCluster.cluster_key)
    ).all()

    results: list[CampaignClusterResponse] = []
    for cluster in clusters:
        lead_count = session.exec(
            select(func.count())
            .select_from(CampaignClusterMember)
            .where(CampaignClusterMember.cluster_id == cluster.id)
        ).one()
        results.append(
            CampaignClusterResponse(
                id=cluster.id,
                cluster_type=cluster.cluster_type,
                cluster_key=cluster.cluster_key,
                geo_region=cluster.geo_region,
                org_density=cluster.org_density,
                lead_count=lead_count,
                created_at=cluster.created_at,
                updated_at=cluster.updated_at,
            )
        )
    return results


@router.get(
    "/enrichment-runs/{asset_id}",
    response_model=EnrichmentRunResponse,
    dependencies=[Depends(require_admin_api_key)],
)
def get_enrichment_run(asset_id: str, session: Session = Depends(get_session)) -> EnrichmentRunResponse:
    run = session.exec(select(EnrichmentRun).where(EnrichmentRun.asset_id == asset_id)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Enrichment run not found")

    return EnrichmentRunResponse(
        asset_id=run.asset_id,
        rdap_status=run.rdap_status,
        ptr_status=run.ptr_status,
        tls_ct_status=run.tls_ct_status,
        security_txt_status=run.security_txt_status,
        contact_page_status=run.contact_page_status,
        last_error_by_source=run.last_error_by_source or {},
        source_versions=run.source_versions or {},
        last_started_at=run.last_started_at,
        last_finished_at=run.last_finished_at,
        updated_at=run.updated_at,
    )
