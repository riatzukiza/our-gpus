from datetime import datetime
from types import SimpleNamespace

from sqlmodel import Session, select

import app.db as db_module
import app.main as main_module
from app.aco import BlockState
from app.cidr_split import optimal_prefix_for_target_duration
from app.db import Host, Scan, Workflow
from app.masscan import TOR_CONNECT_STRATEGY, TOR_SAMPLE_MODE_SPREAD, ScanExecutionResult
from app.masscan_aco import ACOMasscanScheduler, BlockScanResult, SchedulerConfig


def test_optimal_prefix_for_target_duration_uses_bounded_blocks():
    prefix = optimal_prefix_for_target_duration(target_seconds=300, rate=100_000)

    assert prefix == 12


def test_aco_dashboard_returns_history_and_geography(client, session, admin_headers):
    session.add_all(
        [
            Host(
                ip="1.1.1.1",
                port=11434,
                status="online",
                last_seen=datetime.utcnow(),
                first_seen=datetime.utcnow(),
                geo_country="US",
                geo_city="Seattle",
                geo_lat=47.6062,
                geo_lon=-122.3321,
            ),
            Host(
                ip="1.1.2.2",
                port=11434,
                status="online",
                last_seen=datetime.utcnow(),
                first_seen=datetime.utcnow(),
                geo_country="US",
                geo_city="Portland",
                geo_lat=45.5152,
                geo_lon=-122.6784,
            ),
            Host(
                ip="3.3.3.3",
                port=11434,
                status="unknown",
                last_seen=datetime.utcnow(),
                first_seen=datetime.utcnow(),
                geo_country="GB",
                geo_city="London",
                geo_lat=51.5072,
                geo_lon=-0.1276,
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

    response = client.get("/api/aco/dashboard", headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_running"
    assert data["geography"]["known_hosts"] == 3
    assert data["geography"]["unknown_hosts"] == 0
    assert data["history"][0]["cidr"] == "1.0.0.0/24"
    assert data["history"][0]["hosts_found"] == 4
    assert data["geography"]["block_prefix_len"] == 24
    assert {block["cidr"] for block in data["geography"]["blocks"]} == {
        "1.1.1.0/24",
        "1.1.2.0/24",
        "3.3.3.0/24",
    }
    assert data["geography"]["country_details"][0]["country"] == "US"
    assert data["geography"]["country_details"][0]["block_count"] >= 1
    assert data["geography"]["country_details"][0]["ip_ranges"]


def test_aco_dashboard_counts_country_only_hosts_without_coordinates(
    client, session, admin_headers
):
    session.add(
        Host(
            ip="146.59.18.127",
            port=11434,
            status="online",
            last_seen=datetime.utcnow(),
            first_seen=datetime.utcnow(),
            geo_country="France",
            geo_city=None,
            geo_lat=None,
            geo_lon=None,
        )
    )
    session.commit()

    response = client.get("/api/aco/dashboard", headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    france = next(
        detail for detail in data["geography"]["country_details"] if detail["country"] == "France"
    )
    france_block = next(
        block for block in data["geography"]["blocks"] if block["cidr"] == "146.59.0.0/16"
    )

    assert data["geography"]["known_hosts"] == 1
    assert france["host_count"] == 1
    assert france["online_host_count"] == 1
    assert france["discovered_ip_count"] == 1
    assert france_block["host_count"] == 1
    assert france_block["discovered_ip_count"] == 1
    assert france_block["avg_lat"] is None
    assert france_block["avg_lon"] is None


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


def test_scheduler_config_defaults_to_tor_connect():
    assert SchedulerConfig().strategy == TOR_CONNECT_STRATEGY


def test_start_aco_scan_respects_requested_strategy(client, admin_headers, monkeypatch):
    main_module._aco_scheduler = None
    monkeypatch.setattr(ACOMasscanScheduler, "start", lambda _self: None)

    response = client.post(
        "/api/aco/scan/start",
        headers=admin_headers,
        json={
            "strategy": TOR_CONNECT_STRATEGY,
            "tor_max_hosts": 128,
            "tor_concurrency": 8,
        },
    )

    assert response.status_code == 200
    assert main_module._aco_scheduler is not None
    assert main_module._aco_scheduler.config.strategy == TOR_CONNECT_STRATEGY
    assert main_module._aco_scheduler.config.tor_max_hosts == 128
    assert main_module._aco_scheduler.config.tor_concurrency == 8

    main_module._aco_scheduler = None


def test_admin_scanner_config_reflects_scheduler_strategy(client, admin_headers):
    main_module._aco_scheduler = SimpleNamespace(
        config=SchedulerConfig(strategy="masscan", tor_max_hosts=64, tor_concurrency=4, rate=2500)
    )

    response = client.get("/api/admin/scanner/config", headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["scan"]["strategy"] == "masscan"
    assert data["scan"]["rate"] == 2500
    assert data["tor"]["max_hosts"] == 64
    assert data["tor"]["concurrency"] == 4

    main_module._aco_scheduler = None


def test_failed_aco_block_preserves_original_scan_error(tmp_path, session, monkeypatch):
    def fake_get_session():
        with Session(session.get_bind()) as scoped_session:
            yield scoped_session

    monkeypatch.setattr(db_module, "get_session", fake_get_session)
    monkeypatch.setattr(main_module, "load_exclude_list", lambda _exclude_file: ["192.0.2.0/24"])

    result = BlockScanResult(
        cidr="143.144.0.0/13",
        scan_uuid="eb728d7c",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        output_file=str(tmp_path / "missing.txt"),
        log_file=str(tmp_path / "block.log"),
        hosts_found=0,
        duration_ms=1000,
        success=False,
        error="Client error '403 Forbidden' for url 'https://api.shodan.io/shodan/host/search'",
    )

    main_module._on_aco_block_result(result)

    with Session(session.get_bind()) as verify_session:
        scan = verify_session.exec(
            select(Scan).where(Scan.source_file == "aco-block:143.144.0.0/13")
        ).first()
        assert scan is not None
        assert scan.status == "failed"
        assert scan.error_message == result.error

        workflow = verify_session.exec(select(Workflow).where(Workflow.scan_id == scan.id)).first()
        assert workflow is not None
        assert workflow.strategy == TOR_CONNECT_STRATEGY
        assert workflow.status == "failed"
        assert workflow.last_error == result.error


def test_aco_tor_blocks_use_spread_sampling(tmp_path, monkeypatch):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    scheduler = ACOMasscanScheduler(
        config=SchedulerConfig(
            strategy=TOR_CONNECT_STRATEGY,
            results_dir=str(tmp_path / "results"),
            state_file=str(tmp_path / "aco-state.json"),
            exclude_file=str(exclude_file),
        )
    )

    captured: list[dict[str, object]] = []
    sampled_runs = [
        ["146.59.5.119", "146.59.27.77"],
        ["146.59.43.82", "146.59.76.108"],
    ]

    def fake_execute(_self, context):
        captured.append(
            {
                "sample_mode": context.request.tor_sample_mode,
                "sample_seed": context.request.tor_sample_seed,
                "seen_hosts": tuple(context.request.tor_seen_hosts or ()),
            }
        )
        sampled_hosts = sampled_runs[len(captured) - 1]
        return ScanExecutionResult(
            attempted_hosts=8,
            discovered_hosts=0,
            stats={"strategy": TOR_CONNECT_STRATEGY},
            sampled_hosts=sampled_hosts,
        )

    monkeypatch.setattr("app.masscan.TorScanStrategy.execute", fake_execute)

    first_result = scheduler._run_scan_block("146.59.0.0/16")
    second_result = scheduler._run_scan_block("146.59.0.0/16")

    assert first_result.success is True
    assert second_result.success is True
    assert captured[0]["sample_mode"] == TOR_SAMPLE_MODE_SPREAD
    assert str(captured[0]["sample_seed"]).startswith("146.59.0.0/16:")
    assert captured[0]["seen_hosts"] == ()
    assert set(captured[1]["seen_hosts"]) == set(sampled_runs[0])
    assert scheduler.block_sampled_hosts["146.59.0.0/16"] == set(sampled_runs[0] + sampled_runs[1])


def test_geo_proximity_weights_prefer_nearby_blocks(tmp_path, monkeypatch):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    scheduler = ACOMasscanScheduler(
        config=SchedulerConfig(
            strategy=TOR_CONNECT_STRATEGY,
            results_dir=str(tmp_path / "results"),
            state_file=str(tmp_path / "aco-state.json"),
            exclude_file=str(exclude_file),
        )
    )

    monkeypatch.setattr(
        scheduler,
        "_get_geo_proximity_anchors",
        lambda: [{"ip": "146.59.18.127", "country": "France", "lat": 48.8566, "lon": 2.3522}],
    )
    monkeypatch.setattr(
        scheduler,
        "_get_block_geo_hint",
        lambda cidr: {
            "near": {"country": "France", "lat": 48.9, "lon": 2.3},
            "far": {"country": "United States", "lat": 37.7749, "lon": -122.4194},
        }[cidr],
    )

    weights = scheduler._geo_proximity_weights(["near", "far"])

    assert weights is not None
    assert weights["near"] > weights["far"]
    assert weights["near"] > 1.0


def test_aco_dashboard_includes_scan_sampled_blocks_without_hits(
    client, admin_headers, tmp_path, monkeypatch
):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    scheduler = ACOMasscanScheduler(
        config=SchedulerConfig(
            strategy=TOR_CONNECT_STRATEGY,
            results_dir=str(tmp_path / "results"),
            state_file=str(tmp_path / "aco-state.json"),
            exclude_file=str(exclude_file),
        )
    )
    scheduler.block_sampled_hosts = {"146.59.0.0/16": {"146.59.14.13", "146.59.54.33"}}
    scheduler.block_discovered_hosts = {"146.59.0.0/16": {"146.59.14.13"}}
    main_module._aco_scheduler = scheduler

    geo_map = {
        "146.59.14.13": {
            "status": "resolved",
            "country": "France",
            "city": "Paris",
            "lat": 48.8566,
            "lon": 2.3522,
        },
        "146.59.54.33": {
            "status": "resolved",
            "country": "France",
            "city": "Lyon",
            "lat": 45.764,
            "lon": 4.8357,
        },
    }
    monkeypatch.setattr(main_module, "_lookup_geo_cached", lambda _service, ip: geo_map[ip])

    response = client.get("/api/aco/dashboard", headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["geography"]["known_hosts"] == 0
    assert data["geography"]["countries"][0]["country"] == "France"
    assert data["geography"]["blocks"][0]["cidr"] == "146.59.0.0/16"
    assert data["geography"]["blocks"][0]["source"] == "scan-sampled"
    assert data["geography"]["blocks"][0]["sampled_ip_count"] == 2
    assert data["geography"]["blocks"][0]["discovered_ip_count"] == 1
    assert any(point["kind"] == "sampled" for point in data["geography"]["points"])

    main_module._aco_scheduler = None
