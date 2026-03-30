import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db import Host
from app.ingest import IngestService


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_infer_schema_jsonl():
    service = IngestService(None)

    data = b'{"ip": "1.2.3.4", "port": 11434, "country": "US"}\n{"ip": "5.6.7.8", "port": 11434, "country": "UK"}'

    schema = service.infer_schema(data)

    assert "ip" in schema["fields"]
    assert "port" in schema["fields"]
    assert "country" in schema["fields"]
    assert len(schema["sample_records"]) == 2


def test_infer_schema_json_array():
    service = IngestService(None)

    data = b'[{"ip": "1.2.3.4", "port": 11434}, {"ip": "5.6.7.8", "port": 11434}]'

    schema = service.infer_schema(data)

    assert "ip" in schema["fields"]
    assert "port" in schema["fields"]
    assert len(schema["sample_records"]) == 2


def test_ip_int_to_str():
    service = IngestService(None)

    # Test IP integer conversion
    ip_int = 16843009  # 1.1.1.1
    ip_str = service._ip_int_to_str(ip_int)

    assert ip_str == "1.1.1.1"


def test_parse_stream_with_mapping():
    service = IngestService(None)

    data = b'{"host": "1.2.3.4", "port_num": 11434, "location": "US"}'
    mapping = {"ip": "host", "port": "port_num", "geo_country": "location"}

    records = list(service.parse_stream(data, mapping))

    assert len(records) == 1
    assert records[0]["ip"] == "1.2.3.4"
    assert records[0]["port"] == 11434
    assert records[0]["geo_country"] == "US"


def test_parse_stream_masscan_json_array_without_mapping():
    service = IngestService(None)

    data = (
        b'[{"ip": "1.2.3.4", "timestamp": "123", '
        b'"ports": [{"port": 11434, "proto": "tcp", "status": "open"}]}]'
    )

    records = list(service.parse_stream(data, {}))

    assert len(records) == 1
    assert records[0]["ip"] == "1.2.3.4"
    assert records[0]["port"] == 11434


def test_process_batch_queues_new_hosts_for_probe(session):
    service = IngestService(session)

    with pytest.MonkeyPatch.context() as mp:
        queued_ids = []

        def fake_queue(host_ids):
            queued_ids.extend(host_ids)
            return ["task-1"]

        mp.setattr("worker.tasks.queue_host_probes", fake_queue)
        success, failed = service.process_batch(
            [{"ip": "9.8.7.6", "port": 11434}],
            1,
            auto_probe_new_hosts=True,
        )

    assert success == 1
    assert failed == 0
    assert queued_ids == [1]


def test_process_batch(session):
    service = IngestService(session)

    records = [
        {"ip": "1.2.3.4", "port": 11434},
        {"ip": "5.6.7.8", "port": 11434},
        {"ip": None, "port": 11434},  # Invalid record
    ]

    success, failed = service.process_batch(records, 1)

    assert success == 2
    assert failed == 1

    # Check database
    hosts = session.query(Host).all()
    assert len(hosts) == 2
