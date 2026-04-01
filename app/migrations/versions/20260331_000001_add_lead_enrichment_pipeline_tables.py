"""Add lead enrichment pipeline tables.

Revision ID: 20260331_000001
Revises:
Create Date: 2026-03-31 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260331_000001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_column(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.String(length=36), nullable=nullable)


def _json_object_default() -> sa.TextClause:
    return sa.text("'{}'")


def _json_array_default() -> sa.TextClause:
    return sa.text("'[]'")


def upgrade() -> None:
    op.create_table(
        "organizations",
        _uuid_column("id"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("confidence_baseline", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", "country_code", name="uq_organizations_name_country"),
    )
    op.create_index(
        "ix_organizations_normalized_name", "organizations", ["normalized_name"], unique=False
    )

    op.create_table(
        "asns",
        _uuid_column("id"),
        sa.Column("asn", sa.BigInteger(), nullable=False),
        sa.Column("org_name", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("rir", sa.String(length=32), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("rdap_handle", sa.String(length=255), nullable=True),
        sa.Column("rdap_url", sa.Text(), nullable=True),
        sa.Column("raw_last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("asn > 0", name="ck_asns_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asn", name="uq_asns_asn"),
    )
    op.create_index("ix_asns_organization_id", "asns", ["organization_id"], unique=False)

    op.create_table(
        "domains",
        _uuid_column("id"),
        sa.Column("fqdn", sa.String(length=255), nullable=False),
        sa.Column("root_domain", sa.String(length=255), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fqdn", name="uq_domains_fqdn"),
    )
    op.create_index("ix_domains_root_domain", "domains", ["root_domain"], unique=False)
    op.create_index("ix_domains_organization_id", "domains", ["organization_id"], unique=False)

    op.create_table(
        "assets",
        _uuid_column("id"),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("protocol", sa.String(length=32), nullable=True),
        sa.Column("service", sa.String(length=64), nullable=True),
        sa.Column("asn_id", sa.String(length=36), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("observed_banner_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "ip IS NOT NULL OR hostname IS NOT NULL OR domain IS NOT NULL",
            name="ck_assets_identity_present",
        ),
        sa.CheckConstraint(
            "port IS NULL OR (port >= 1 AND port <= 65535)",
            name="ck_assets_port_range",
        ),
        sa.ForeignKeyConstraint(["asn_id"], ["asns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ip", "port", "protocol", name="uq_assets_ip_port_protocol"),
        sa.UniqueConstraint(
            "hostname", "port", "protocol", name="uq_assets_hostname_port_protocol"
        ),
    )
    op.create_index("ix_assets_asn_id", "assets", ["asn_id"], unique=False)
    op.create_index("ix_assets_country_region", "assets", ["country_code", "region"], unique=False)

    op.create_table(
        "asset_domains",
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("domain_id", sa.String(length=36), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id", "domain_id", "relationship"),
    )
    op.create_index("ix_asset_domains_domain_id", "asset_domains", ["domain_id"], unique=False)

    op.create_table(
        "raw_fetches",
        _uuid_column("id"),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("fetch_kind", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("domain_id", sa.String(length=36), nullable=True),
        sa.Column("asn_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("request_key", sa.String(length=255), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetch_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("transport_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parse_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extraction_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=255), nullable=True),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.CheckConstraint(
            "asset_id IS NOT NULL OR domain_id IS NOT NULL OR asn_id IS NOT NULL OR organization_id IS NOT NULL",
            name="ck_raw_fetches_subject_present",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asn_id"], ["asns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_raw_fetches_source_status_fetched_at",
        "raw_fetches",
        ["source_type", "fetch_status", "fetched_at"],
        unique=False,
    )
    op.create_index("ix_raw_fetches_asset_id", "raw_fetches", ["asset_id"], unique=False)
    op.create_index("ix_raw_fetches_domain_id", "raw_fetches", ["domain_id"], unique=False)
    op.create_index(
        "uq_raw_fetches_source_request_hash",
        "raw_fetches",
        ["source_type", "request_key", "content_hash"],
        unique=True,
    )

    op.create_table(
        "contacts",
        _uuid_column("id"),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("domain_id", sa.String(length=36), nullable=True),
        sa.Column("contact_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_normalized", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("is_role_account", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_organization_id", "contacts", ["organization_id"], unique=False)
    op.create_index("ix_contacts_domain_id", "contacts", ["domain_id"], unique=False)
    op.create_index(
        "ix_contacts_type_confidence", "contacts", ["contact_type", "confidence"], unique=False
    )
    op.create_index(
        "ix_contacts_value_normalized", "contacts", ["value_normalized"], unique=False
    )

    op.create_table(
        "source_observations",
        _uuid_column("id"),
        sa.Column("raw_fetch_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("domain_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("asn_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("weight", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asn_id"], ["asns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_fetch_id"], ["raw_fetches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_observations_fetch_evidence_type",
        "source_observations",
        ["raw_fetch_id", "evidence_type"],
        unique=False,
    )
    op.create_index(
        "ix_source_observations_asset_id_observed_at",
        "source_observations",
        ["asset_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_source_observations_domain_id_observed_at",
        "source_observations",
        ["domain_id", "observed_at"],
        unique=False,
    )

    op.create_table(
        "org_candidates",
        _uuid_column("id"),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("org_conflict_penalty", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("rationale", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "normalized_name", name="uq_org_candidates_asset_name"),
    )
    op.create_index(
        "ix_org_candidates_asset_score", "org_candidates", ["asset_id", "score"], unique=False
    )

    op.create_table(
        "org_resolutions",
        _uuid_column("id"),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("winning_org_candidate_id", sa.String(length=36), nullable=True),
        sa.Column("resolution_mode", sa.String(length=16), nullable=False, server_default="auto"),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("rationale", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["winning_org_candidate_id"], ["org_candidates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_org_resolutions_asset_id"),
    )
    op.create_index(
        "ix_org_resolutions_organization_id", "org_resolutions", ["organization_id"], unique=False
    )

    op.create_table(
        "lead_records",
        _uuid_column("id"),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("org_resolution_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("primary_contact_id", sa.String(length=36), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("org_confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("contact_quality", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("route_legitimacy", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("org_conflict_penalty", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("recommended_route", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("scorer_version", sa.String(length=64), nullable=True),
        sa.Column("resolver_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_resolution_id"], ["org_resolutions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["primary_contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_lead_records_asset_id"),
    )
    op.create_index(
        "ix_lead_records_status_confidence",
        "lead_records",
        ["status", "confidence_score"],
        unique=False,
    )
    op.create_index(
        "ix_lead_records_organization_id", "lead_records", ["organization_id"], unique=False
    )

    op.create_table(
        "lead_contact_candidates",
        _uuid_column("id"),
        sa.Column("lead_record_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("org_confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("contact_quality", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("route_legitimacy", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("org_conflict_penalty", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("rationale", sa.JSON(), nullable=False, server_default=_json_array_default()),
        sa.Column(
            "last_evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("rank > 0", name="ck_lead_contact_candidates_rank_positive"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_record_id"], ["lead_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lead_record_id", "contact_id", "route", name="uq_lead_contact_candidates"
        ),
    )
    op.create_index(
        "ix_lead_contact_candidates_lead_rank",
        "lead_contact_candidates",
        ["lead_record_id", "rank"],
        unique=False,
    )

    op.create_table(
        "campaign_clusters",
        _uuid_column("id"),
        sa.Column("cluster_type", sa.String(length=64), nullable=False),
        sa.Column("cluster_key", sa.String(length=255), nullable=False),
        sa.Column("geo_region", sa.String(length=255), nullable=True),
        sa.Column("org_density", sa.Numeric(8, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_type", "cluster_key", name="uq_campaign_clusters_key"),
    )

    op.create_table(
        "campaign_cluster_members",
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("lead_record_id", sa.String(length=36), nullable=False),
        sa.Column("membership_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["cluster_id"], ["campaign_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_record_id"], ["lead_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("cluster_id", "lead_record_id"),
    )

    op.create_table(
        "enrichment_runs",
        _uuid_column("id"),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("rdap_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("ptr_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("tls_ct_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "security_txt_status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "contact_page_status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "last_error_by_source", sa.JSON(), nullable=False, server_default=_json_object_default()
        ),
        sa.Column("source_versions", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_enrichment_runs_asset_id"),
    )

    op.create_table(
        "enrichment_jobs",
        _uuid_column("id"),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("lead_record_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=_json_object_default()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_hint", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_record_id"], ["lead_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enrichment_jobs_status_scheduled_at",
        "enrichment_jobs",
        ["status", "scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("enrichment_jobs")
    op.drop_table("enrichment_runs")
    op.drop_table("campaign_cluster_members")
    op.drop_table("campaign_clusters")
    op.drop_table("lead_contact_candidates")
    op.drop_table("lead_records")
    op.drop_table("org_resolutions")
    op.drop_table("org_candidates")
    op.drop_table("source_observations")
    op.drop_table("contacts")
    op.drop_table("raw_fetches")
    op.drop_table("asset_domains")
    op.drop_table("assets")
    op.drop_table("domains")
    op.drop_table("asns")
    op.drop_table("organizations")
