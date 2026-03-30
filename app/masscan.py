import json
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.db import Scan


def _get_engine():
    from app import db as db_module

    return db_module.engine


class MasscanService:
    def __init__(self, session: Session):
        self.session = session
        self.exclude_file = "/app/excludes.conf"
        self.results_dir = "/workspace/imports/masscan"

    def run_scan(
        self,
        target: str = "0.0.0.0/0",
        port: str = "11434",
        rate: int = 100000,
        router_mac: str = "00:21:59:a0:cf:c1",
    ) -> dict:
        Path(self.results_dir).mkdir(parents=True, exist_ok=True)

        scan_uuid = str(uuid.uuid4())[:8]
        output_file = f"{self.results_dir}/scan-{scan_uuid}.json"
        log_file = f"{self.results_dir}/scan-{scan_uuid}.log"

        scan = Scan(
            source_file=f"masscan:{target}:{port}",
            mapping_json=json.dumps(
                {
                    "target": target,
                    "port": port,
                    "rate": rate,
                    "router_mac": router_mac,
                }
            ),
            status="queued",
            started_at=datetime.utcnow(),
        )
        self.session.add(scan)
        self.session.commit()
        self.session.refresh(scan)

        thread = threading.Thread(
            target=self._run_masscan_background,
            args=(scan.id, scan_uuid, target, port, rate, router_mac),
            daemon=True,
        )
        thread.start()

        return {
            "scan_id": scan.id,
            "output_file": output_file,
            "log_file": log_file,
            "status": "queued",
        }

    def _run_masscan_background(
        self,
        scan_id: int,
        scan_uuid: str,
        target: str,
        port: str,
        rate: int,
        router_mac: str,
    ) -> None:
        output_file = f"{self.results_dir}/scan-{scan_uuid}.json"
        log_file = f"{self.results_dir}/scan-{scan_uuid}.log"

        engine = _get_engine()
        with Session(engine) as session:
            scan = session.get(Scan, scan_id)
            if scan:
                scan.status = "running"
                session.add(scan)
                session.commit()

        cmd = [
            "masscan",
            target,
            "-p",
            port,
            "--rate",
            str(rate),
            "--router-mac",
            router_mac,
            "-oJ",
            output_file,
            "--wait",
            "15",
            "--retries",
            "3",
        ]

        if Path(self.exclude_file).exists():
            cmd[6:6] = ["--exclude-file", self.exclude_file]

        with open(log_file, "w") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            process.wait()

        with Session(engine) as session:
            scan = session.get(Scan, scan_id)
            if scan:
                scan.status = "completed"
                scan.completed_at = datetime.utcnow()
                session.add(scan)
                session.commit()

    def get_progress(self, scan_id: int) -> dict:
        scan = self.session.get(Scan, scan_id)
        if not scan:
            return {"error": "Scan not found"}

        log_file = f"{self.results_dir}/scan-{scan_id}.log"
        try:
            with open(log_file) as f:
                logs = f.read()
        except FileNotFoundError:
            logs = ""

        output_file = f"{self.results_dir}/scan-{scan_id}.json"
        hosts_found = 0
        try:
            with open(output_file) as f:
                for line in f:
                    if '"ip":' in line:
                        hosts_found += 1
        except FileNotFoundError:
            pass

        return {
            "scan_id": scan.id,
            "status": scan.status,
            "hosts_found": hosts_found,
            "logs": logs[-5000:] if len(logs) > 5000 else logs,
        }

    def get_results_file(self, scan_id: int) -> str | None:
        output_file = f"{self.results_dir}/scan-{scan_id}.json"
        if Path(output_file).exists():
            return output_file
        return None
