from pathlib import Path

import pytest

from app.cidr_split import load_exclude_list, write_combined_exclude_file
from app.db import Scan
from app.masscan import (
    TOR_CONNECT_STRATEGY,
    TOR_SAMPLE_MODE_SPREAD,
    MasscanScanStrategy,
    ScanContext,
    ScanPaths,
    ScanRequest,
    ScanService,
    TorScanStrategy,
    build_allowed_host_targets,
)


def test_build_allowed_host_targets_respects_excludes(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("1.1.1.2/32\n")

    allowed = build_allowed_host_targets("1.1.1.0/30", str(exclude_file), max_hosts=16)

    assert allowed == ["1.1.1.1"]


def test_layered_exclude_files_are_merged(tmp_path: Path):
    static_file = tmp_path / "excludes.conf"
    generated_file = tmp_path / "excludes.generated.conf"
    static_file.write_text("1.1.1.0/32\n")
    generated_file.write_text("1.1.1.1/32\n")

    excludes = load_exclude_list(f"{static_file},{generated_file}")

    assert excludes == ["1.1.1.0/32", "1.1.1.1/32"]


def test_write_combined_exclude_file_emits_merged_ranges(tmp_path: Path):
    static_file = tmp_path / "excludes.conf"
    generated_file = tmp_path / "excludes.generated.conf"
    merged_file = tmp_path / "combined.conf"
    static_file.write_text("1.1.1.0/32\n")
    generated_file.write_text("1.1.1.1/32\n")

    write_combined_exclude_file(str(merged_file), f"{static_file},{generated_file}")

    assert merged_file.read_text().splitlines() == ["1.1.1.0/32", "1.1.1.1/32"]


def test_build_allowed_host_targets_rejects_fully_excluded_target(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("11.0.0.0/8\n")

    with pytest.raises(RuntimeError, match="excluded"):
        build_allowed_host_targets("11.1.1.0/30", str(exclude_file), max_hosts=16)


def test_build_allowed_host_targets_caps_oversized_tor_scan(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    allowed = build_allowed_host_targets("1.1.0.0/29", str(exclude_file), max_hosts=4)

    assert allowed == ["1.1.0.1", "1.1.0.2", "1.1.0.3", "1.1.0.4"]


def test_build_allowed_host_targets_supports_spread_sampling(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    allowed = build_allowed_host_targets(
        "146.59.0.0/16",
        str(exclude_file),
        max_hosts=8,
        sample_mode=TOR_SAMPLE_MODE_SPREAD,
        sample_seed="scan-aco-001",
    )

    third_octets = [int(host.split(".")[2]) for host in allowed]

    assert len(allowed) == 8
    assert max(third_octets) - min(third_octets) >= 200
    assert len(set(third_octets)) == 8


def test_build_allowed_host_targets_spread_biases_away_from_seen_hosts(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    first = build_allowed_host_targets(
        "146.59.0.0/16",
        str(exclude_file),
        max_hosts=8,
        sample_mode=TOR_SAMPLE_MODE_SPREAD,
        sample_seed="scan-aco-001",
    )
    second = build_allowed_host_targets(
        "146.59.0.0/16",
        str(exclude_file),
        max_hosts=8,
        sample_mode=TOR_SAMPLE_MODE_SPREAD,
        sample_seed="scan-aco-001",
        avoid_hosts=first,
    )

    assert len(second) == 8
    assert set(first).isdisjoint(second)


def test_masscan_strategy_requires_exclude_file(tmp_path: Path):
    strategy = MasscanScanStrategy()
    context = ScanContext(
        scan_id=1,
        scan_uuid="scan0001",
        request=ScanRequest(
            target="1.1.1.0/24",
            port="11434",
            rate=1000,
            router_mac="00:00:00:00:00:00",
            strategy="masscan",
        ),
        paths=ScanPaths(
            output_file=str(tmp_path / "scan.json"),
            log_file=str(tmp_path / "scan.log"),
        ),
        exclude_file=str(tmp_path / "missing-excludes.conf"),
    )

    with pytest.raises(RuntimeError, match="Exclude files are missing or empty"):
        strategy.execute(context)


def test_tor_strategy_requires_exclude_file(tmp_path: Path):
    strategy = TorScanStrategy()
    context = ScanContext(
        scan_id=1,
        scan_uuid="scan0001",
        request=ScanRequest(
            target="1.1.1.0/30",
            port="11434",
            rate=1000,
            router_mac="00:00:00:00:00:00",
            strategy=TOR_CONNECT_STRATEGY,
        ),
        paths=ScanPaths(
            output_file=str(tmp_path / "scan.txt"),
            log_file=str(tmp_path / "scan.log"),
        ),
        exclude_file=str(tmp_path / "missing-excludes.conf"),
    )

    with pytest.raises(RuntimeError, match="Exclude files are missing or empty"):
        strategy.execute(context)


def test_scan_service_canonicalizes_legacy_tor_strategy(tmp_path: Path, session, monkeypatch):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    service = ScanService(session)
    service.exclude_file = str(exclude_file)
    monkeypatch.setattr(service, "results_dir", tmp_path)

    context = service._build_context(
        ScanRequest(
            target="1.1.1.0/30",
            port="11434",
            rate=1000,
            router_mac="00:00:00:00:00:00",
            strategy="tor",
        )
    )

    assert context.request.strategy == TOR_CONNECT_STRATEGY

    scan = session.get(Scan, context.scan_id)
    assert scan is not None
    assert scan.mapping["strategy"] == TOR_CONNECT_STRATEGY
    assert scan.source_file.startswith(f"{TOR_CONNECT_STRATEGY}:")
