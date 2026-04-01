from pathlib import Path

from sqlmodel import select

import app.masscan as masscan_module
import worker.tasks as worker_tasks
from app.db import Host, Workflow, WorkflowStageReceipt
from app.masscan import TOR_CONNECT_STRATEGY, ScanExecutionResult, ScanRequest, ScanService


def test_scan_service_creates_workflow_record(tmp_path: Path, session, monkeypatch):
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

    workflow = session.exec(select(Workflow).where(Workflow.scan_id == context.scan_id)).first()
    assert workflow is not None
    assert workflow.strategy == TOR_CONNECT_STRATEGY
    assert workflow.status == "pending"
    assert workflow.exclude_snapshot_hash
    assert workflow.policy_snapshot_hash
    assert workflow.requested_config["strategy"] == TOR_CONNECT_STRATEGY


def test_run_background_records_discover_receipts(tmp_path: Path, session, monkeypatch):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("192.0.2.0/24\n")

    service = ScanService(session)
    service.exclude_file = str(exclude_file)
    monkeypatch.setattr(service, "results_dir", tmp_path)
    monkeypatch.setattr(masscan_module, "_get_engine", lambda: session.get_bind())
    monkeypatch.setattr(worker_tasks, "queue_host_probes", lambda *_args, **_kwargs: [])

    context = service._build_context(
        ScanRequest(
            target="1.1.1.0/30",
            port="11434",
            rate=1000,
            router_mac="00:00:00:00:00:00",
            strategy=TOR_CONNECT_STRATEGY,
        )
    )

    class FakeStrategy:
        def execute(self, context):
            Path(context.paths.output_file).write_text("1.1.1.1:11434\n")
            Path(context.paths.log_file).write_text("ok\n")
            return ScanExecutionResult(
                attempted_hosts=4,
                discovered_hosts=1,
                stats={
                    "strategy": context.request.strategy,
                    "attempted_hosts": 4,
                    "discovered_hosts": 1,
                },
            )

        def prepare_ingest_file(self, context):
            return context.paths.output_file

    service._strategies[context.request.strategy] = FakeStrategy()
    service._run_background(context)

    workflow = session.exec(select(Workflow).where(Workflow.scan_id == context.scan_id)).first()
    receipts = session.exec(
        select(WorkflowStageReceipt)
        .where(WorkflowStageReceipt.workflow_id == workflow.workflow_id)
        .order_by(WorkflowStageReceipt.started_at.asc())
    ).all()
    hosts = session.exec(select(Host)).all()

    assert workflow is not None
    assert workflow.status == "completed"
    assert workflow.current_stage == "discover"
    assert workflow.summary["attempted_hosts"] == 4
    assert workflow.summary["discovered_hosts"] == 1
    assert workflow.summary["ingested_hosts"] == 1
    assert len(hosts) == 1
    assert hosts[0].ip == "1.1.1.1"
    assert [receipt.status for receipt in receipts] == ["started", "completed"]
    assert receipts[-1].metrics["ingested_hosts"] == 1


def test_admin_workflow_endpoints_return_workflow_data(client, session, admin_headers):
    workflow = Workflow(
        workflow_id="workflow-1",
        scan_id=7,
        workflow_kind="one-off",
        target="1.1.1.0/30",
        port="11434",
        strategy=TOR_CONNECT_STRATEGY,
        status="completed",
        current_stage="discover",
        exclude_snapshot_hash="exclude-hash",
        policy_snapshot_hash="policy-hash",
        requested_config_json='{"strategy":"tor-connect"}',
        summary_json='{"discovered_hosts":1}',
    )
    receipt = WorkflowStageReceipt(
        receipt_id="receipt-1",
        workflow_id="workflow-1",
        stage_name="discover",
        status="completed",
        input_refs_json='["1.1.1.0/30", "11434"]',
        output_refs_json='["/tmp/scan.txt"]',
        metrics_json='{"discovered_hosts":1}',
        evidence_refs_json='["/tmp/scan.log"]',
        policy_decisions_json="[]",
    )
    session.add(workflow)
    session.add(receipt)
    session.commit()

    list_response = client.get("/api/admin/workflows", headers=admin_headers)
    detail_response = client.get("/api/admin/workflows/workflow-1", headers=admin_headers)

    assert list_response.status_code == 200
    assert list_response.json()[0]["workflow_id"] == "workflow-1"
    assert list_response.json()[0]["strategy"] == TOR_CONNECT_STRATEGY

    assert detail_response.status_code == 200
    assert detail_response.json()["workflow_id"] == "workflow-1"
    assert detail_response.json()["receipts"][0]["receipt_id"] == "receipt-1"
