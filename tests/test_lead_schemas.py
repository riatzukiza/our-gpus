from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.lead_schemas import (
    AssetImportRecord,
    ContactResponse,
    ContactType,
    EvidenceStepResponse,
    EvidenceSupport,
    EvidenceType,
    LeadContactCandidateResponse,
    LeadRecordResponse,
    LeadScoreBreakdown,
    LeadStatus,
    RecommendedRoute,
    SourceType,
)


def test_asset_import_record_requires_identity() -> None:
    with pytest.raises(ValidationError):
        AssetImportRecord()


def test_lead_record_response_supports_ranked_contact_routes() -> None:
    now = datetime.now(UTC)
    asset_id = uuid4()
    lead_id = uuid4()
    contact_id = uuid4()
    evidence_id = uuid4()

    lead = LeadRecordResponse(
        id=lead_id,
        asset_id=asset_id,
        status=LeadStatus.APPROVED,
        recommended_route=RecommendedRoute.SECURITY_TXT,
        created_at=now,
        updated_at=now,
        scores=LeadScoreBreakdown(
            confidence_score=91,
            org_confidence=84,
            contact_quality=95,
            route_legitimacy=100,
            org_conflict_penalty=0,
        ),
        primary_contact=ContactResponse(
            id=contact_id,
            contact_type=ContactType.SECURITY,
            value="mailto:security@example.com",
            source_type=SourceType.SECURITY_TXT,
            source_url="https://example.com/.well-known/security.txt",
            confidence=98,
        ),
        contact_candidates=[
            LeadContactCandidateResponse(
                id=uuid4(),
                contact_id=contact_id,
                route=RecommendedRoute.SECURITY_TXT,
                rank=1,
                score=91,
                org_confidence=84,
                contact_quality=95,
                route_legitimacy=100,
                org_conflict_penalty=0,
                last_evaluated_at=now,
            )
        ],
        evidence_steps=[
            EvidenceStepResponse(
                id=evidence_id,
                kind=EvidenceType.SECURITY_TXT_CONTACT,
                source_type=SourceType.SECURITY_TXT,
                source_url="https://example.com/.well-known/security.txt",
                raw_value="Contact: mailto:security@example.com",
                normalized_value="mailto:security@example.com",
                confidence=0.98,
                weight=55,
                observed_at=now,
                supports=EvidenceSupport(asset_id=asset_id, contact_id=contact_id),
                metadata={"route_legitimacy": 100},
            )
        ],
    )

    assert lead.recommended_route == RecommendedRoute.SECURITY_TXT
    assert lead.scores.route_legitimacy == 100
    assert lead.primary_contact is not None
    assert lead.primary_contact.source_type == SourceType.SECURITY_TXT
    assert lead.contact_candidates[0].rank == 1
