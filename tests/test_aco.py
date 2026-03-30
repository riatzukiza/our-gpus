from datetime import datetime

from app.aco import BlockState
from app.cidr_split import optimal_prefix_for_target_duration
from app.db import Host, Scan
from app.masscan_aco import ACOMasscanScheduler, SchedulerConfig


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


def test_aco_dashboard_ignores_stale_non_block_state(tmp_path):
    config = SchedulerConfig(
        results_dir=str(tmp_path / "results"),
        state_file=str(tmp_path / "aco-state.json"),
        exclude_file=str(tmp_path / "excludes.conf"),
    )
    scheduler = ACOMasscanScheduler(config=config)
    scheduler.prefix_len = 13
    scheduler.blocks = ["1.0.0.0/13", "1.8.0.0/13"]
    scheduler._blocks_loaded = True
    scheduler.aco.blocks = {
        "1.0.0.0/13": BlockState(
            key="1.0.0.0/13",
            pheromone=0.4,
            scan_count=1,
            last_scan_at=datetime.utcnow(),
            cumulative_yield=3,
        ),
        "130.61.172.128/32": BlockState(
            key="130.61.172.128/32",
            pheromone=0.9,
            scan_count=0,
        ),
    }

    snapshot = scheduler.dashboard_snapshot(block_limit=5)

    assert snapshot["stats"]["total_blocks"] == 2
    assert snapshot["stats"]["scanned_blocks"] == 1
    assert snapshot["stats"]["unscanned_blocks"] == 1
    assert [block["cidr"] for block in snapshot["top_blocks"]] == ["1.8.0.0/13", "1.0.0.0/13"]
