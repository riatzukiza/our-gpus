from sqlmodel import Session

from app.db import Host, HostGroup, HostGroupMember, init_db


def test_group_tables_exist_in_legacy_sqlite(tmp_path):
    db_path = tmp_path / "groups.sqlite"
    init_db(f"sqlite:///{db_path}")

    import app.db as db_module

    with Session(db_module.engine) as session:
        group = HostGroup(name="safe-core", description="safe hosts")
        session.add(group)
        session.commit()
        session.refresh(group)

        host = Host(ip="198.51.100.2", port=11434, status="online", geo_country="US")
        session.add(host)
        session.commit()
        session.refresh(host)

        session.add(HostGroupMember(group_id=group.id, host_id=host.id))
        session.commit()

        assert group.id is not None
        assert host.id is not None
