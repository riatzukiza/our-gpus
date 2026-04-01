from sqlmodel import select

from app.db import (
    Asset,
    CampaignCluster,
    CampaignClusterMember,
    EnrichmentJob,
    EnrichmentRun,
    LeadRecord,
    RawFetch,
    SourceObservation,
)


def test_import_assets_creates_leads_and_provenance(client, session, admin_headers):
    response = client.post(
        "/api/assets/import",
        headers=admin_headers,
        json={
            "source": "import",
            "import_batch_id": "batch-test-1",
            "rows": [
                {
                    "ip": "203.0.113.10",
                    "domain": "Example.COM",
                    "port": 443,
                    "protocol": "tcp",
                    "service": "https",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["created_count"] == 1
    assert payload["updated_count"] == 0

    assert session.exec(select(Asset)).all()
    assert session.exec(select(LeadRecord)).all()
    assert session.exec(select(RawFetch)).all()
    observations = session.exec(select(SourceObservation)).all()
    assert len(observations) == 1
    assert observations[0].evidence_type == "asset_observation"


def test_enrich_and_status_routes_queue_jobs_and_update_leads(client, session, admin_headers):
    import_response = client.post(
        "/api/assets/import",
        headers=admin_headers,
        json={
            "source": "import",
            "rows": [{"ip": "198.51.100.5", "port": 11434, "protocol": "tcp"}],
        },
    )
    lead_id = import_response.json()["lead_record_ids"][0]
    asset_id = import_response.json()["asset_ids"][0]

    enrich_response = client.post(
        f"/api/enrich/{asset_id}",
        headers=admin_headers,
        json={
            "requested_sources": ["rdap", "security_txt"],
            "candidate_domains": ["example.org"],
            "fetch_versions": {"rdap": "v1"},
        },
    )
    assert enrich_response.status_code == 200
    assert enrich_response.json()["job_type"] == "enrich_asset"

    resolve_response = client.post(
        f"/api/resolve/{lead_id}",
        headers=admin_headers,
        json={"resolver_version": "resolver-v0.2", "scorer_version": "score-v0.2"},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["job_type"] == "resolve_lead"

    rescore_response = client.post(
        f"/api/re-score/{lead_id}",
        headers=admin_headers,
        json={"scorer_version": "score-v0.2", "reason": "test"},
    )
    assert rescore_response.status_code == 200
    assert rescore_response.json()["job_type"] == "rescore_lead"

    status_response = client.post(
        f"/api/lead-records/{lead_id}/status",
        headers=admin_headers,
        json={"status": "reviewed", "notes": "triaged"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "reviewed"
    assert status_response.json()["notes"] == "triaged"

    enrichment_run = session.exec(select(EnrichmentRun).where(EnrichmentRun.asset_id == asset_id)).first()
    assert enrichment_run is not None
    assert enrichment_run.rdap_status == "pending"
    assert enrichment_run.security_txt_status == "pending"

    jobs = session.exec(select(EnrichmentJob).order_by(EnrichmentJob.job_type)).all()
    assert [job.job_type for job in jobs] == ["enrich_asset", "rescore_lead", "resolve_lead"]


def test_list_leads_and_clusters(client, session, admin_headers):
    import_response = client.post(
        "/api/assets/manual",
        headers=admin_headers,
        json={"hostname": "api.example.net", "port": 443, "protocol": "tcp"},
    )
    assert import_response.status_code == 200
    lead_id = import_response.json()["id"]

    lead_list_response = client.get("/api/lead-records", headers=admin_headers)
    assert lead_list_response.status_code == 200
    lead_list = lead_list_response.json()
    assert lead_list["total"] == 1
    assert lead_list["items"][0]["id"] == lead_id
    assert lead_list["items"][0]["asset"]["hostname"] == "api.example.net"

    cluster = CampaignCluster(cluster_type="asn", cluster_key="AS64500")
    session.add(cluster)
    session.flush()
    session.add(CampaignClusterMember(cluster_id=cluster.id, lead_record_id=lead_id, membership_score=87))
    session.commit()

    clusters_response = client.get("/api/clusters", headers=admin_headers)
    assert clusters_response.status_code == 200
    clusters = clusters_response.json()
    assert len(clusters) == 1
    assert clusters[0]["cluster_type"] == "asn"
    assert clusters[0]["cluster_key"] == "AS64500"
    assert clusters[0]["lead_count"] == 1
