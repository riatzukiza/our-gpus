from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeadSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SourceType(StrEnum):
    SCANNER = "scanner"
    IMPORT = "import"
    MANUAL = "manual"
    RDAP = "rdap"
    WHOIS = "whois"
    PTR = "ptr"
    TLS = "tls"
    CT = "ct"
    SECURITY_TXT = "security_txt"
    WEBSITE = "website"


class ContactType(StrEnum):
    SECURITY = "security"
    ABUSE = "abuse"
    BUSINESS = "business"
    PROVIDER = "provider"
    OTHER = "other"


class EvidenceType(StrEnum):
    ASSET_OBSERVATION = "asset_observation"
    RDAP_NETWORK = "rdap_network"
    RDAP_ASN = "rdap_asn"
    RDAP_ENTITY = "rdap_entity"
    RDAP_CONTACT = "rdap_contact"
    PTR = "ptr"
    HOSTNAME_OBSERVED = "hostname_observed"
    TLS_CN = "tls_cn"
    TLS_SAN = "tls_san"
    CT_DOMAIN = "ct_domain"
    DOMAIN_REGISTRATION = "domain_registration"
    SECURITY_TXT_CONTACT = "security_txt_contact"
    SECURITY_TXT_POLICY = "security_txt_policy"
    WEBSITE_CONTACT = "website_contact"
    ORG_MATCH = "org_match"
    PROVIDER_MATCH = "provider_match"
    GEO_MATCH = "geo_match"
    MANUAL_NOTE = "manual_note"


class LeadStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    SUPPRESSED = "suppressed"
    EXPORTED = "exported"


class RecommendedRoute(StrEnum):
    SECURITY_TXT = "security_txt"
    RDAP_ABUSE = "rdap_abuse"
    WEBSITE_SECURITY = "website_security"
    WEBSITE_GENERAL = "website_general"
    PROVIDER_ABUSE = "provider_abuse"
    MANUAL_REVIEW = "manual_review"


class FetchStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    NOT_FOUND = "not_found"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    SKIPPED = "skipped"


class ResolutionMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class AssetImportRecord(LeadSchema):
    ip: str | None = None
    hostname: str | None = None
    domain: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    protocol: str | None = None
    service: str | None = None
    timestamp_seen: datetime | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "AssetImportRecord":
        if not any((self.ip, self.hostname, self.domain)):
            raise ValueError("at least one of ip, hostname, or domain must be provided")
        return self


class AssetImportRequest(LeadSchema):
    source: SourceType = SourceType.IMPORT
    rows: list[AssetImportRecord] = Field(default_factory=list)
    dedupe_key_mode: str = "ip-port-protocol"
    import_batch_id: str | None = None


class AssetImportResponse(LeadSchema):
    imported_count: int
    created_count: int
    updated_count: int
    asset_ids: list[UUID] = Field(default_factory=list)
    lead_record_ids: list[UUID] = Field(default_factory=list)


class ManualAssetCreateRequest(AssetImportRecord):
    source: SourceType = SourceType.MANUAL


class JobQueuedResponse(LeadSchema):
    job_id: UUID
    job_type: str
    status: str
    scheduled_at: datetime | None = None
    worker_hint: str | None = None


class EnrichAssetRequest(LeadSchema):
    requested_sources: list[SourceType] = Field(
        default_factory=lambda: [
            SourceType.RDAP,
            SourceType.PTR,
            SourceType.TLS,
            SourceType.CT,
            SourceType.SECURITY_TXT,
            SourceType.WEBSITE,
        ]
    )
    candidate_domains: list[str] = Field(default_factory=list)
    force_refresh: bool = False
    fetch_versions: dict[str, str] = Field(default_factory=dict)


class ResolveLeadRequest(LeadSchema):
    resolver_version: str | None = None
    scorer_version: str | None = None
    recompute_org_candidates: bool = True
    recompute_contact_routes: bool = True


class RescoreLeadRequest(LeadSchema):
    scorer_version: str | None = None
    reason: str | None = None


class LeadStatusUpdateRequest(LeadSchema):
    status: LeadStatus
    notes: str | None = None


class ContactResponse(LeadSchema):
    id: UUID
    organization_id: UUID | None = None
    domain_id: UUID | None = None
    contact_type: ContactType
    value: str
    source_type: SourceType
    source_url: str | None = None
    is_role_account: bool = False
    confidence: float = 0
    last_verified_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawFetchResponse(LeadSchema):
    id: UUID
    source_type: SourceType
    fetch_kind: str
    asset_id: UUID | None = None
    domain_id: UUID | None = None
    asn_id: UUID | None = None
    organization_id: UUID | None = None
    request_url: str
    canonical_url: str | None = None
    request_key: str
    http_status: int | None = None
    fetch_status: FetchStatus
    transport_ok: bool = False
    parse_ok: bool = False
    extraction_ok: bool = False
    content_type: str | None = None
    content_hash: str | None = None
    etag: str | None = None
    artifact_uri: str | None = None
    parser_version: str | None = None
    fetched_at: datetime | None = None
    last_verified_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSupport(LeadSchema):
    asset_id: UUID | None = None
    domain_id: UUID | None = None
    organization_id: UUID | None = None
    asn_id: UUID | None = None
    contact_id: UUID | None = None


class EvidenceStepResponse(LeadSchema):
    id: UUID
    raw_fetch_id: UUID | None = None
    kind: EvidenceType
    source_type: SourceType
    source_url: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    confidence: float = 0
    weight: float = 0
    observed_at: datetime
    supports: EvidenceSupport = Field(default_factory=EvidenceSupport)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetResponse(LeadSchema):
    id: UUID
    ip: str | None = None
    hostname: str | None = None
    domain: str | None = None
    port: int | None = None
    protocol: str | None = None
    service: str | None = None
    country_code: str | None = None
    region: str | None = None
    city: str | None = None
    last_seen: datetime | None = None


class OrgCandidateResponse(LeadSchema):
    id: UUID
    organization_id: UUID | None = None
    name: str
    normalized_name: str
    score: float = 0
    org_conflict_penalty: float = 0
    rationale: list[dict[str, Any]] = Field(default_factory=list)
    last_evaluated_at: datetime | None = None


class OrgResolutionResponse(LeadSchema):
    id: UUID
    organization_id: UUID | None = None
    winning_org_candidate_id: UUID | None = None
    resolution_mode: ResolutionMode = ResolutionMode.AUTO
    confidence: float = 0
    rationale: list[dict[str, Any]] = Field(default_factory=list)
    resolved_at: datetime
    reviewed_at: datetime | None = None
    reviewer_note: str | None = None
    org_candidates: list[OrgCandidateResponse] = Field(default_factory=list)


class LeadScoreBreakdown(LeadSchema):
    confidence_score: float = 0
    org_confidence: float = 0
    contact_quality: float = 0
    route_legitimacy: float = 0
    org_conflict_penalty: float = 0


class LeadContactCandidateResponse(LeadSchema):
    id: UUID
    contact_id: UUID
    route: RecommendedRoute
    rank: int
    score: float
    org_confidence: float = 0
    contact_quality: float = 0
    route_legitimacy: float = 0
    org_conflict_penalty: float = 0
    rationale: list[dict[str, Any]] = Field(default_factory=list)
    last_evaluated_at: datetime
    contact: ContactResponse | None = None


class LeadRecordResponse(LeadSchema):
    id: UUID
    asset_id: UUID
    organization_id: UUID | None = None
    org_resolution_id: UUID | None = None
    primary_contact_id: UUID | None = None
    status: LeadStatus = LeadStatus.NEW
    recommended_route: RecommendedRoute | None = None
    notes: str | None = None
    scorer_version: str | None = None
    resolver_version: str | None = None
    created_at: datetime
    updated_at: datetime
    last_resolved_at: datetime | None = None
    asset: AssetResponse | None = None
    organization: OrgResolutionResponse | None = None
    primary_contact: ContactResponse | None = None
    scores: LeadScoreBreakdown = Field(default_factory=LeadScoreBreakdown)
    contact_candidates: list[LeadContactCandidateResponse] = Field(default_factory=list)
    evidence_steps: list[EvidenceStepResponse] = Field(default_factory=list)


class PaginatedLeadRecordResponse(LeadSchema):
    items: list[LeadRecordResponse]
    total: int
    page: int
    size: int
    pages: int


class CampaignClusterResponse(LeadSchema):
    id: UUID
    cluster_type: str
    cluster_key: str
    geo_region: str | None = None
    org_density: float | None = None
    lead_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EnrichmentRunResponse(LeadSchema):
    asset_id: UUID
    rdap_status: FetchStatus = FetchStatus.PENDING
    ptr_status: FetchStatus = FetchStatus.PENDING
    tls_ct_status: FetchStatus = FetchStatus.PENDING
    security_txt_status: FetchStatus = FetchStatus.PENDING
    contact_page_status: FetchStatus = FetchStatus.PENDING
    last_error_by_source: dict[str, Any] = Field(default_factory=dict)
    source_versions: dict[str, str] = Field(default_factory=dict)
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    updated_at: datetime | None = None
