from sqlmodel import select

from app.db import (
    Asset,
    CampaignCluster,
    CampaignClusterMember,
    ContactEndpoint,
    EnrichmentJob,
    EnrichmentRun,
    LeadRecord,
    RawFetch,
    SourceObservation,
)
from app.lead_services import LeadEnrichmentService


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


def test_enrich_and_status_routes_queue_jobs_and_update_leads(
    client, session, admin_headers, monkeypatch
):
    rdap_ip_payload = {
        "objectClassName": "ip network",
        "name": "Example Corp Network",
        "entities": [
            {
                "roles": ["abuse"],
                "vcardArray": [
                    "vcard",
                    [
                        ["fn", {}, "text", "Example Corp"],
                        ["email", {}, "text", "abuse@example.org"],
                    ],
                ],
            }
        ],
    }
    rdap_domain_payload = {
        "objectClassName": "domain",
        "ldhName": "example.org",
        "entities": [
            {
                "roles": ["technical"],
                "vcardArray": [
                    "vcard",
                    [
                        ["fn", {}, "text", "Example Corp"],
                        ["email", {}, "text", "tech@example.org"],
                    ],
                ],
            }
        ],
    }

    def fake_fetch_json(_service, url):
        if url == "https://rdap.org/ip/198.51.100.5":
            return 200, "rdap-ip", rdap_ip_payload
        if url == "https://rdap.org/domain/example.org":
            return 200, "rdap-domain", rdap_domain_payload
        return 404, "not found", None

    def fake_fetch_text(_service, url):
        if url == "https://example.org/.well-known/security.txt":
            return (
                200,
                "Contact: mailto:security@example.org\n"
                "Policy: https://example.org/security\n"
                "Expires: 2026-12-31T00:00:00Z\n",
            )
        if url == "https://api.example.org/.well-known/security.txt":
            return 404, "missing"
        if url.endswith("/contact"):
            return 200, '<a href="mailto:hello@example.org">Contact</a>'
        if url.endswith("/"):
            return 200, "<html><body>Example Corp</body></html>"
        return 404, "missing"

    monkeypatch.setattr(LeadEnrichmentService, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(LeadEnrichmentService, "_fetch_text", fake_fetch_text)
    monkeypatch.setattr(LeadEnrichmentService, "_reverse_dns", lambda _service, _ip: "api.example.org")

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
            "requested_sources": ["rdap", "ptr", "security_txt", "website"],
            "candidate_domains": ["example.org"],
            "fetch_versions": {"rdap": "v1"},
        },
    )
    assert enrich_response.status_code == 200
    assert enrich_response.json()["job_type"] == "enrich_asset"
    assert enrich_response.json()["status"] == "completed"

    resolve_response = client.post(
        f"/api/resolve/{lead_id}",
        headers=admin_headers,
        json={"resolver_version": "resolver-v0.2", "scorer_version": "score-v0.2"},
    )
    assert resolve_response.status_code == 200
    assert resolve_response.json()["job_type"] == "resolve_lead"
    assert resolve_response.json()["status"] == "completed"

    rescore_response = client.post(
        f"/api/re-score/{lead_id}",
        headers=admin_headers,
        json={"scorer_version": "score-v0.2", "reason": "test"},
    )
    assert rescore_response.status_code == 200
    assert rescore_response.json()["job_type"] == "rescore_lead"
    assert rescore_response.json()["status"] == "completed"

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
    assert enrichment_run.rdap_status == "ok"
    assert enrichment_run.ptr_status == "ok"
    assert enrichment_run.security_txt_status == "ok"
    assert enrichment_run.contact_page_status == "ok"

    jobs = session.exec(select(EnrichmentJob).order_by(EnrichmentJob.job_type)).all()
    assert [job.job_type for job in jobs] == ["enrich_asset", "rescore_lead", "resolve_lead"]
    assert all(job.status == "completed" for job in jobs)

    contacts = session.exec(select(ContactEndpoint)).all()
    assert len(contacts) >= 2

    lead_detail = client.get(f"/api/lead-records/{lead_id}", headers=admin_headers)
    assert lead_detail.status_code == 200
    lead_payload = lead_detail.json()
    assert lead_payload["recommended_route"] == "security_txt"
    assert lead_payload["primary_contact"]["value"] == "mailto:security@example.org"
    assert lead_payload["scores"]["route_legitimacy"] == 100
    assert lead_payload["organization"] is not None
    assert lead_payload["organization"]["org_candidates"]
    assert any(step["kind"] == "security_txt_contact" for step in lead_payload["evidence_steps"])


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
