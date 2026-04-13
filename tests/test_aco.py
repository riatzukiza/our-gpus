from datetime import datetime

from app.cidr_split import optimal_prefix_for_target_duration
from app.db import Host, Scan


def test_optimal_prefix_for_target_duration_uses_bounded_blocks():
    prefix = optimal_prefix_for_target_duration(target_seconds=300, rate=100_000)

    assert prefix == 8


def test_aco_dashboard_returns_history_and_geography(client, session):
    session.add_all(
        [
            Host(
                ip="1.1.1.1",
                port=11434,
                status="online",
                last_seen=datetime.utcnow(),
                first_seen=datetime.utcnow(),
                geo_country="US",
            ),
            Host(
                ip="2.2.2.2",
                port=11434,
                status="online",
                last_seen=datetime.utcnow(),
                first_seen=datetime.utcnow(),
                geo_country="GB",
            ),
            Host(
                ip="3.3.3.3",
                port=11434,
                status="unknown",
                last_seen=datetime.utcnow(),
                first_seen=datetime.utcnow(),
            ),
            Scan(
                source_file="aco-block:1.0.0.0/24",
                mapping_json="{}",
                stats_json='{"cidr":"1.0.0.0/24","success":4,"failed":1}',
                status="completed",
                total_rows=5,
                processed_rows=4,
            ),
        ]
    )
    session.commit()

    response = client.get("/api/aco/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_running"
    assert data["geography"]["known_hosts"] == 2
    assert data["geography"]["unknown_hosts"] == 1
    assert data["history"][0]["cidr"] == "1.0.0.0/24"
    assert data["history"][0]["hosts_found"] == 4
