from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import threading
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import httpx
from sqlmodel import Session, select

from app.cidr_split import load_exclude_list, write_combined_exclude_file
from app.config import settings
from app.db import Scan, Workflow, WorkflowStageReceipt
from app.shodan_queries import build_shodan_query_plan, filter_shodan_matches

DEFAULT_TOR_SCAN_MAX_HOSTS = 4096
DEFAULT_TOR_SCAN_CONCURRENCY = 32
TOR_CONNECT_STRATEGY = "tor-connect"
DEFAULT_POLICY_SNAPSHOT_HASH = hashlib.sha256(b"policy:implicit-default-v1").hexdigest()


def normalize_scan_strategy_name(strategy: str) -> str:
    normalized = strategy.strip().lower()
    if normalized == "tor":
        return TOR_CONNECT_STRATEGY
    return normalized


def build_exclude_snapshot_hash(exclude_file: str | Sequence[str]) -> str:
    excludes = load_exclude_list(exclude_file)
    if not excludes:
        raise RuntimeError(
            f"Exclude files are missing or empty: {exclude_file}. Refusing to scan without exclusions."
        )
    payload = "\n".join(excludes).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_workflow_for_scan(
    session: Session,
    scan: Scan,
    *,
    workflow_kind: str = "one-off",
    target: str,
    port: str,
    strategy: str,
    exclude_snapshot_hash: str,
    requested_config: dict,
) -> Workflow:
    workflow_id = str(uuid.uuid4())
    workflow = Workflow(
        workflow_id=workflow_id,
        scan_id=scan.id,
        workflow_kind=workflow_kind,
        target=target,
        port=port,
        strategy=strategy,
        status="pending",
        exclude_snapshot_hash=exclude_snapshot_hash,
        policy_snapshot_hash=DEFAULT_POLICY_SNAPSHOT_HASH,
        requested_config_json=json.dumps(requested_config),
        summary_json=json.dumps({}),
        created_at=scan.started_at or datetime.utcnow(),
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    return workflow


def create_workflow_for_aco_block(
    session: Session,
    scan: Scan,
    *,
    cidr: str,
    port: str,
    exclude_snapshot_hash: str,
) -> Workflow:
    workflow_id = str(uuid.uuid4())
    workflow = Workflow(
        workflow_id=workflow_id,
        scan_id=scan.id,
        workflow_kind="continuous-block",
        target=cidr,
        port=port,
        strategy="masscan",
        status="pending",
        exclude_snapshot_hash=exclude_snapshot_hash,
        policy_snapshot_hash=DEFAULT_POLICY_SNAPSHOT_HASH,
        requested_config_json=json.dumps({"cidr": cidr, "port": port, "strategy": "masscan"}),
        summary_json=json.dumps({}),
        created_at=scan.started_at or datetime.utcnow(),
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    return workflow


def create_stage_receipt_for_workflow(
    session: Session,
    workflow_id: str,
    *,
    stage_name: str,
    status: str,
    input_refs: list[str],
    output_refs: list[str],
    metrics: dict[str, object] | None = None,
    evidence_refs: list[str] | None = None,
    error: str | None = None,
) -> WorkflowStageReceipt:
    now = datetime.utcnow()
    receipt = WorkflowStageReceipt(
        receipt_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        stage_name=stage_name,
        status=status,
        input_refs_json=json.dumps(input_refs),
        output_refs_json=json.dumps(output_refs),
        metrics_json=json.dumps(metrics or {}),
        evidence_refs_json=json.dumps(evidence_refs or []),
        policy_decisions_json=json.dumps([]),
        error=error,
        started_at=now,
        finished_at=None if status == "started" else now,
    )
    session.add(receipt)
    session.commit()
    session.refresh(receipt)
    return receipt


def _get_engine():
    from app import db as db_module

    return db_module.engine


def _parse_target_segments(target: str) -> list[ipaddress.IPv4Network]:
    segments = [segment.strip() for segment in target.split(",") if segment.strip()]
    if not segments:
        raise RuntimeError("Scan target is required")

    networks: list[ipaddress.IPv4Network] = []
    for segment in segments:
        if "-" in segment:
            start_raw, end_raw = [part.strip() for part in segment.split("-", 1)]
            try:
                start_ip = ipaddress.IPv4Address(start_raw)
                end_ip = ipaddress.IPv4Address(end_raw)
            except ipaddress.AddressValueError as error:
                raise RuntimeError(f"Invalid IP range target: {segment}") from error
            if int(start_ip) > int(end_ip):
                raise RuntimeError(f"Invalid IP range target: {segment}")
            networks.extend(ipaddress.summarize_address_range(start_ip, end_ip))
            continue

        try:
            network = ipaddress.ip_network(segment, strict=False)
        except ValueError as error:
            raise RuntimeError(f"Invalid scan target: {segment}") from error

        if network.version != 4:
            raise RuntimeError(f"IPv6 targets are not supported: {segment}")
        networks.append(network)

    return networks


def _load_required_exclude_networks(
    exclude_file: str | Sequence[str],
) -> list[ipaddress.IPv4Network]:
    excludes = [
        ipaddress.ip_network(entry, strict=False)
        for entry in load_exclude_list(exclude_file)
        if ipaddress.ip_network(entry, strict=False).version == 4
    ]
    if not excludes:
        raise RuntimeError(
            f"Exclude files are missing or empty: {exclude_file}. Refusing to scan without exclusions."
        )
    return excludes


def _iter_network_hosts(network: ipaddress.IPv4Network):
    if network.prefixlen >= 31:
        yield from network
        return

    yield from network.hosts()


def build_allowed_host_targets(
    target: str,
    exclude_file: str | Sequence[str],
    max_hosts: int | None = None,
) -> list[str]:
    target_networks = _parse_target_segments(target)
    exclude_networks = _load_required_exclude_networks(exclude_file)
    limit = max_hosts or DEFAULT_TOR_SCAN_MAX_HOSTS

    allowed_hosts: list[str] = []
    for target_network in target_networks:
        if any(target_network.subnet_of(exclude) for exclude in exclude_networks):
            continue

        for address in _iter_network_hosts(target_network):
            if any(address in exclude for exclude in exclude_networks):
                continue
            allowed_hosts.append(str(address))
            if len(allowed_hosts) > limit:
                raise RuntimeError(
                    f"Tor scan target expands to more than {limit} allowed hosts after exclusions. "
                    "Use smaller CIDR blocks or raise TOR_SCAN_MAX_HOSTS deliberately."
                )

    if not allowed_hosts:
        raise RuntimeError(
            "All target addresses are excluded by excludes.conf. Refusing to send scan traffic."
        )

    return allowed_hosts


def _count_result_lines(file_path: Path) -> int:
    if not file_path.exists():
        return 0

    with file_path.open() as handle:
        if file_path.suffix == ".json":
            return sum(1 for line in handle if '"ip":' in line)
        return sum(1 for line in handle if line.strip())


def _extract_masscan_hosts(content: str) -> list[str]:
    hosts: list[str] = []
    for line in content.splitlines():
        if '"ip":' not in line:
            continue
        ip_match = re.search(r'"ip":\s*"([^"]+)"', line)
        if ip_match:
            hosts.append(f"{ip_match.group(1)}:11434")
    return hosts


@dataclass(frozen=True)
class ScanRequest:
    target: str
    port: str
    rate: int
    router_mac: str
    strategy: str
    tor_max_hosts: int | None = None
    tor_concurrency: int | None = None
    shodan_query: str | None = None
    shodan_page_limit: int | None = None
    shodan_max_matches: int | None = None
    shodan_max_queries: int | None = None
    shodan_query_max_length: int | None = None


@dataclass(frozen=True)
class ScanPaths:
    output_file: str
    log_file: str


@dataclass(frozen=True)
class ScanContext:
    scan_id: int
    scan_uuid: str
    request: ScanRequest
    paths: ScanPaths
    exclude_file: str


@dataclass(frozen=True)
class ScanExecutionResult:
    attempted_hosts: int
    discovered_hosts: int
    stats: dict[str, object]


class ScanStrategy(ABC):
    name: str
    output_suffix: str

    @abstractmethod
    def execute(self, context: ScanContext) -> ScanExecutionResult:
        raise NotImplementedError

    def prepare_ingest_file(self, context: ScanContext) -> str:
        return context.paths.output_file


class MasscanScanStrategy(ScanStrategy):
    name = "masscan"
    output_suffix = ".json"

    def execute(self, context: ScanContext) -> ScanExecutionResult:
        if (
            os.environ.get("OUR_GPUS_TOR_REQUIRED", "false").lower() == "true"
            or os.environ.get("MASSCAN_ALLOW_DIRECT_EGRESS", "true").lower() == "false"
        ):
            raise RuntimeError(
                "Raw masscan is blocked while Tor mode is required. Use the tor-connect scan strategy instead."
            )

        _load_required_exclude_networks(context.exclude_file)
        merged_exclude_file = write_combined_exclude_file(
            str(Path(context.paths.log_file).with_suffix(".excludes.conf")),
            context.exclude_file,
        )
        cmd = [
            "masscan",
            context.request.target,
            "-p",
            context.request.port,
            "--rate",
            str(context.request.rate),
            "--router-mac",
            context.request.router_mac,
            "--exclude-file",
            merged_exclude_file,
            "-oJ",
            context.paths.output_file,
            "--wait",
            "15",
            "--retries",
            "3",
        ]

        with Path(context.paths.log_file).open("w") as log_handle:
            process = subprocess.Popen(
                cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            return_code = process.wait()

        if return_code != 0:
            raise RuntimeError(f"masscan exited with status {return_code}")

        discovered_hosts = _count_result_lines(Path(context.paths.output_file))
        return ScanExecutionResult(
            attempted_hosts=0,
            discovered_hosts=discovered_hosts,
            stats={
                "strategy": self.name,
                "target": context.request.target,
                "port": context.request.port,
                "rate": context.request.rate,
                "router_mac": context.request.router_mac,
                "discovered_hosts": discovered_hosts,
            },
        )

    def prepare_ingest_file(self, context: ScanContext) -> str:
        source_path = Path(context.paths.output_file)
        output_path = source_path.with_suffix(".txt")
        if not source_path.exists():
            raise RuntimeError("Scan results not found")

        hosts = _extract_masscan_hosts(source_path.read_text())
        output_path.write_text("\n".join(hosts) + ("\n" if hosts else ""))
        return str(output_path)


class TorScanStrategy(ScanStrategy):
    name = TOR_CONNECT_STRATEGY
    output_suffix = ".txt"

    def execute(self, context: ScanContext) -> ScanExecutionResult:
        allowed_hosts = build_allowed_host_targets(
            context.request.target,
            context.exclude_file,
            max_hosts=(
                context.request.tor_max_hosts
                or settings.tor_scan_max_hosts
                or int(os.environ.get("TOR_SCAN_MAX_HOSTS", DEFAULT_TOR_SCAN_MAX_HOSTS))
            ),
        )
        discovered_hosts = asyncio.run(self._run_probe_scan(context, allowed_hosts))
        return ScanExecutionResult(
            attempted_hosts=len(allowed_hosts),
            discovered_hosts=discovered_hosts,
            stats={
                "strategy": self.name,
                "target": context.request.target,
                "port": context.request.port,
                "attempted_hosts": len(allowed_hosts),
                "discovered_hosts": discovered_hosts,
            },
        )

    async def _run_probe_scan(self, context: ScanContext, allowed_hosts: list[str]) -> int:
        output_path = Path(context.paths.output_file)
        log_path = Path(context.paths.log_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        timeout_seconds = int(os.environ.get("PROBE_TIMEOUT_SECS", "5"))
        retries = int(os.environ.get("PROBE_RETRIES", "2"))
        concurrency = min(
            context.request.tor_concurrency
            or settings.tor_scan_concurrency
            or int(os.environ.get("TOR_SCAN_CONCURRENCY", DEFAULT_TOR_SCAN_CONCURRENCY)),
            int(os.environ.get("PROBE_CONCURRENCY", "200")),
            len(allowed_hosts),
        )
        concurrency = max(concurrency, 1)

        log_path.write_text(
            "\n".join(
                [
                    f"strategy={self.name}",
                    f"target={context.request.target}",
                    f"port={context.request.port}",
                    f"allowed_hosts={len(allowed_hosts)}",
                    f"concurrency={concurrency}",
                ]
            )
            + "\n"
        )

        semaphore = asyncio.Semaphore(concurrency)
        found_hosts: list[str] = []

        async with httpx.AsyncClient(
            verify=False,
            trust_env=True,
            timeout=httpx.Timeout(timeout_seconds, connect=timeout_seconds),
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        ) as client:

            async def probe(ip: str) -> None:
                url = f"http://{ip}:{context.request.port}/api/tags"
                async with semaphore:
                    for attempt in range(retries):
                        try:
                            response = await client.get(url, headers={"Accept": "application/json"})
                            if response.status_code == 200:
                                found_hosts.append(f"{ip}:{context.request.port}")
                                return
                            if 400 <= response.status_code < 500:
                                return
                        except httpx.HTTPError:
                            if attempt == retries - 1:
                                return
                        await asyncio.sleep(min(1 * (2**attempt), 4))

            await asyncio.gather(*(probe(ip) for ip in allowed_hosts))

        output_path.write_text("\n".join(found_hosts) + ("\n" if found_hosts else ""))
        with log_path.open("a") as log_handle:
            log_handle.write(f"discovered_hosts={len(found_hosts)}\n")
        return len(found_hosts)


class ShodanScanStrategy(ScanStrategy):
    name = "shodan"
    output_suffix = ".txt"

    def execute(self, context: ScanContext) -> ScanExecutionResult:
        api_key = settings.shodan_api_key.strip()
        if not api_key:
            raise RuntimeError("SHODAN_API_KEY is not configured")

        page_limit = context.request.shodan_page_limit or settings.shodan_page_limit
        max_matches = context.request.shodan_max_matches or settings.shodan_max_matches
        max_queries = context.request.shodan_max_queries or settings.shodan_max_queries
        max_query_length = (
            context.request.shodan_query_max_length or settings.shodan_query_max_length
        )
        base_query = context.request.shodan_query or settings.shodan_base_query

        plan = build_shodan_query_plan(
            target=context.request.target,
            port=context.request.port,
            exclude_files=context.exclude_file,
            base_query=base_query,
            max_query_length=max_query_length,
            max_queries=max_queries,
        )

        output_path = Path(context.paths.output_file)
        log_path = Path(context.paths.log_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        all_matches: list[dict[str, object]] = []
        pages_scanned = 0

        with httpx.Client(timeout=30.0, trust_env=True, follow_redirects=True) as client:
            for query_index, query in enumerate(plan.queries, start=1):
                with log_path.open("a") as log_handle:
                    log_handle.write(f"query[{query_index}]={query}\n")

                for page in range(1, page_limit + 1):
                    response = client.get(
                        "https://api.shodan.io/shodan/host/search",
                        params={
                            "key": api_key,
                            "query": query,
                            "page": page,
                            "minify": "true",
                        },
                    )
                    if response.status_code == 401:
                        raise RuntimeError(
                            "Shodan API rejected the key. It may be invalid or not authorized for search."
                        )
                    if response.status_code == 402:
                        raise RuntimeError(
                            "Shodan account lacks the credits or subscription required for search."
                        )
                    response.raise_for_status()

                    payload = response.json()
                    matches = payload.get("matches")
                    if not isinstance(matches, list) or len(matches) == 0:
                        break

                    all_matches.extend(entry for entry in matches if isinstance(entry, dict))
                    pages_scanned += 1

                    filtered_hosts = filter_shodan_matches(
                        matches=[entry for entry in all_matches if isinstance(entry, dict)],
                        target=context.request.target,
                        port=context.request.port,
                        exclude_files=context.exclude_file,
                    )
                    if len(filtered_hosts) >= max_matches:
                        output_path.write_text("\n".join(filtered_hosts[:max_matches]) + "\n")
                        with log_path.open("a") as log_handle:
                            log_handle.write(f"max_matches_reached={max_matches}\n")
                        return ScanExecutionResult(
                            attempted_hosts=len(all_matches),
                            discovered_hosts=max_matches,
                            stats={
                                "strategy": self.name,
                                "query_count": len(plan.queries),
                                "pages_scanned": pages_scanned,
                                "applied_excludes": plan.applied_excludes,
                                "omitted_excludes": plan.omitted_excludes,
                                "discovered_hosts": max_matches,
                            },
                        )

        filtered_hosts = filter_shodan_matches(
            matches=[entry for entry in all_matches if isinstance(entry, dict)],
            target=context.request.target,
            port=context.request.port,
            exclude_files=context.exclude_file,
        )
        output_path.write_text("\n".join(filtered_hosts) + ("\n" if filtered_hosts else ""))
        with log_path.open("a") as log_handle:
            log_handle.write(f"raw_matches={len(all_matches)}\n")
            log_handle.write(f"filtered_hosts={len(filtered_hosts)}\n")

        return ScanExecutionResult(
            attempted_hosts=len(all_matches),
            discovered_hosts=len(filtered_hosts),
            stats={
                "strategy": self.name,
                "query_count": len(plan.queries),
                "pages_scanned": pages_scanned,
                "applied_excludes": plan.applied_excludes,
                "omitted_excludes": plan.omitted_excludes,
                "discovered_hosts": len(filtered_hosts),
            },
        )


class ScanService:
    def __init__(self, session: Session):
        self.session = session
        self.exclude_file = os.environ.get(
            "OUR_GPUS_EXCLUDE_FILES",
            "/app/excludes.conf,/app/excludes.generated.conf",
        )
        self.results_dir = Path("/workspace/imports/masscan")
        self._strategies: dict[str, ScanStrategy] = {
            MasscanScanStrategy.name: MasscanScanStrategy(),
            TorScanStrategy.name: TorScanStrategy(),
            ShodanScanStrategy.name: ShodanScanStrategy(),
        }

    def _build_context(self, request: ScanRequest) -> ScanContext:
        request = replace(request, strategy=normalize_scan_strategy_name(request.strategy))
        strategy = self._strategies.get(request.strategy)
        if strategy is None:
            raise RuntimeError(f"Unsupported scan strategy: {request.strategy}")

        self.results_dir.mkdir(parents=True, exist_ok=True)
        scan_uuid = str(uuid.uuid4())[:8]
        workflow_id = str(uuid.uuid4())
        exclude_snapshot_hash = build_exclude_snapshot_hash(self.exclude_file)
        paths = ScanPaths(
            output_file=str(self.results_dir / f"scan-{scan_uuid}{strategy.output_suffix}"),
            log_file=str(self.results_dir / f"scan-{scan_uuid}.log"),
        )
        requested_config = {
            "target": request.target,
            "port": request.port,
            "rate": request.rate,
            "router_mac": request.router_mac,
            "strategy": strategy.name,
            "tor_max_hosts": request.tor_max_hosts,
            "tor_concurrency": request.tor_concurrency,
            "shodan_query": request.shodan_query,
            "shodan_page_limit": request.shodan_page_limit,
            "shodan_max_matches": request.shodan_max_matches,
            "shodan_max_queries": request.shodan_max_queries,
            "shodan_query_max_length": request.shodan_query_max_length,
        }
        scan = Scan(
            source_file=f"{strategy.name}:{request.target}:{request.port}",
            mapping_json=json.dumps(
                {
                    "scan_uuid": scan_uuid,
                    "workflow_id": workflow_id,
                    "strategy": strategy.name,
                    "target": request.target,
                    "port": request.port,
                    "rate": request.rate,
                    "router_mac": request.router_mac,
                    "exclude_snapshot_hash": exclude_snapshot_hash,
                    "policy_snapshot_hash": DEFAULT_POLICY_SNAPSHOT_HASH,
                    "tor_max_hosts": request.tor_max_hosts,
                    "tor_concurrency": request.tor_concurrency,
                    "shodan_query": request.shodan_query,
                    "shodan_page_limit": request.shodan_page_limit,
                    "shodan_max_matches": request.shodan_max_matches,
                    "shodan_max_queries": request.shodan_max_queries,
                    "shodan_query_max_length": request.shodan_query_max_length,
                    "output_file": paths.output_file,
                    "log_file": paths.log_file,
                }
            ),
            stats_json=json.dumps({"strategy": strategy.name, "workflow_id": workflow_id}),
            status="queued",
            started_at=datetime.utcnow(),
        )
        self.session.add(scan)
        self.session.commit()
        self.session.refresh(scan)

        workflow = Workflow(
            workflow_id=workflow_id,
            scan_id=scan.id,
            workflow_kind="one-off",
            target=request.target,
            port=request.port,
            strategy=strategy.name,
            status="pending",
            exclude_snapshot_hash=exclude_snapshot_hash,
            policy_snapshot_hash=DEFAULT_POLICY_SNAPSHOT_HASH,
            requested_config_json=json.dumps(requested_config),
            summary_json=json.dumps({}),
            created_at=scan.started_at,
        )
        self.session.add(workflow)
        self.session.commit()

        return ScanContext(
            scan_id=scan.id,
            scan_uuid=scan_uuid,
            request=request,
            paths=paths,
            exclude_file=self.exclude_file,
        )

    def run_scan(
        self,
        target: str = "0.0.0.0/0",
        port: str = "11434",
        rate: int = 100000,
        router_mac: str = "00:21:59:a0:cf:c1",
        strategy: str = TOR_CONNECT_STRATEGY,
        tor_max_hosts: int | None = None,
        tor_concurrency: int | None = None,
        shodan_query: str | None = None,
        shodan_page_limit: int | None = None,
        shodan_max_matches: int | None = None,
        shodan_max_queries: int | None = None,
        shodan_query_max_length: int | None = None,
    ) -> dict:
        request = ScanRequest(
            target=target,
            port=port,
            rate=rate,
            router_mac=router_mac,
            strategy=strategy,
            tor_max_hosts=tor_max_hosts,
            tor_concurrency=tor_concurrency,
            shodan_query=shodan_query,
            shodan_page_limit=shodan_page_limit,
            shodan_max_matches=shodan_max_matches,
            shodan_max_queries=shodan_max_queries,
            shodan_query_max_length=shodan_query_max_length,
        )
        context = self._build_context(request)

        thread = threading.Thread(
            target=self._run_background,
            args=(context,),
            daemon=True,
        )
        thread.start()

        return {
            "scan_id": context.scan_id,
            "output_file": context.paths.output_file,
            "log_file": context.paths.log_file,
            "status": "queued",
            "strategy": context.request.strategy,
        }

    def _get_workflow(self, session: Session, scan_id: int) -> Workflow | None:
        return session.exec(select(Workflow).where(Workflow.scan_id == scan_id)).first()

    def _create_stage_receipt(
        self,
        session: Session,
        workflow_id: str,
        context: ScanContext,
        *,
        status: str,
        metrics: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.utcnow()
        receipt = WorkflowStageReceipt(
            receipt_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            stage_name="discover",
            status=status,
            input_refs_json=json.dumps([context.request.target, context.request.port]),
            output_refs_json=json.dumps([context.paths.output_file]),
            metrics_json=json.dumps(metrics or {}),
            evidence_refs_json=json.dumps([context.paths.log_file, context.paths.output_file]),
            policy_decisions_json=json.dumps([]),
            error=error,
            started_at=now,
            finished_at=None if status == "started" else now,
        )
        session.add(receipt)

    def _run_background(self, context: ScanContext) -> None:
        engine = _get_engine()
        strategy = self._strategies[context.request.strategy]

        with Session(engine) as session:
            scan = session.get(Scan, context.scan_id)
            workflow = self._get_workflow(session, context.scan_id)
            if scan:
                scan.status = "running"
                session.add(scan)
            if workflow:
                workflow.status = "running"
                workflow.current_stage = "discover"
                workflow.started_at = workflow.started_at or datetime.utcnow()
                session.add(workflow)
                self._create_stage_receipt(session, workflow.workflow_id, context, status="started")
            session.commit()

        try:
            result = strategy.execute(context)
        except Exception as error:  # noqa: BLE001
            with Session(engine) as session:
                scan = session.get(Scan, context.scan_id)
                workflow = self._get_workflow(session, context.scan_id)
                if scan:
                    scan.status = "failed"
                    scan.completed_at = datetime.utcnow()
                    scan.error_message = str(error)
                    scan.stats_json = json.dumps(
                        {
                            "strategy": context.request.strategy,
                            "error": str(error),
                        }
                    )
                    session.add(scan)
                if workflow:
                    workflow.status = "failed"
                    workflow.current_stage = "discover"
                    workflow.completed_at = datetime.utcnow()
                    workflow.last_error = str(error)
                    session.add(workflow)
                    self._create_stage_receipt(
                        session,
                        workflow.workflow_id,
                        context,
                        status="failed",
                        metrics={"attempted_hosts": 0, "discovered_hosts": 0},
                        error=str(error),
                    )
                session.commit()
            return

        with Session(engine) as session:
            scan = session.get(Scan, context.scan_id)
            workflow = self._get_workflow(session, context.scan_id)
            if scan:
                scan.status = "completed"
                scan.completed_at = datetime.utcnow()
                scan.total_rows = result.attempted_hosts
                scan.processed_rows = result.discovered_hosts
                scan.stats_json = json.dumps(result.stats)
                session.add(scan)
            if workflow:
                workflow.status = "completed"
                workflow.current_stage = "discover"
                workflow.completed_at = datetime.utcnow()
                workflow.summary_json = json.dumps(
                    {
                        "attempted_hosts": result.attempted_hosts,
                        "discovered_hosts": result.discovered_hosts,
                        "verified_hosts": 0,
                        "geocoded_hosts": 0,
                        "emitted_nodes": 0,
                        "emitted_edges": 0,
                        "classified_hosts": 0,
                        "alerts_created": 0,
                    }
                )
                session.add(workflow)
                self._create_stage_receipt(
                    session,
                    workflow.workflow_id,
                    context,
                    status="completed",
                    metrics={
                        "attempted_hosts": result.attempted_hosts,
                        "discovered_hosts": result.discovered_hosts,
                    },
                )
            session.commit()

    def _get_scan_context(self, scan_id: int) -> tuple[Scan, ScanContext] | tuple[None, None]:
        scan = self.session.get(Scan, scan_id)
        if not scan:
            return None, None

        mapping = scan.mapping if scan.mapping_json else {}
        strategy_name = normalize_scan_strategy_name(str(mapping.get("strategy", "masscan")))
        context = ScanContext(
            scan_id=scan.id,
            scan_uuid=str(mapping.get("scan_uuid", scan.id)),
            request=ScanRequest(
                target=str(mapping.get("target", "0.0.0.0/0")),
                port=str(mapping.get("port", "11434")),
                rate=int(mapping.get("rate", 100000)),
                router_mac=str(mapping.get("router_mac", "00:21:59:a0:cf:c1")),
                strategy=strategy_name,
                tor_max_hosts=(
                    int(mapping.get("tor_max_hosts"))
                    if mapping.get("tor_max_hosts") is not None
                    else None
                ),
                tor_concurrency=(
                    int(mapping.get("tor_concurrency"))
                    if mapping.get("tor_concurrency") is not None
                    else None
                ),
                shodan_query=(
                    str(mapping.get("shodan_query"))
                    if mapping.get("shodan_query") is not None
                    else None
                ),
                shodan_page_limit=(
                    int(mapping.get("shodan_page_limit"))
                    if mapping.get("shodan_page_limit") is not None
                    else None
                ),
                shodan_max_matches=(
                    int(mapping.get("shodan_max_matches"))
                    if mapping.get("shodan_max_matches") is not None
                    else None
                ),
                shodan_max_queries=(
                    int(mapping.get("shodan_max_queries"))
                    if mapping.get("shodan_max_queries") is not None
                    else None
                ),
                shodan_query_max_length=(
                    int(mapping.get("shodan_query_max_length"))
                    if mapping.get("shodan_query_max_length") is not None
                    else None
                ),
            ),
            paths=ScanPaths(
                output_file=str(mapping.get("output_file", "")),
                log_file=str(mapping.get("log_file", "")),
            ),
            exclude_file=self.exclude_file,
        )
        return scan, context

    def get_progress(self, scan_id: int) -> dict:
        scan, context = self._get_scan_context(scan_id)
        if not scan or not context:
            return {"error": "Scan not found"}

        log_path = Path(context.paths.log_file)
        logs = log_path.read_text() if log_path.exists() else ""
        output_path = Path(context.paths.output_file)
        hosts_found = _count_result_lines(output_path)

        return {
            "scan_id": scan.id,
            "status": scan.status,
            "strategy": context.request.strategy,
            "hosts_found": hosts_found,
            "logs": logs[-5000:] if len(logs) > 5000 else logs,
        }

    def get_results_file(self, scan_id: int) -> str | None:
        _scan, context = self._get_scan_context(scan_id)
        if not context:
            return None
        output_path = Path(context.paths.output_file)
        if output_path.exists():
            return str(output_path)
        return None

    def prepare_ingest_file(self, scan_id: int) -> str:
        scan, context = self._get_scan_context(scan_id)
        if not scan or not context:
            raise RuntimeError("Scan not found")
        strategy = self._strategies.get(context.request.strategy)
        if strategy is None:
            raise RuntimeError(f"Unsupported scan strategy: {context.request.strategy}")
        return strategy.prepare_ingest_file(context)
