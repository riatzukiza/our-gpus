from pathlib import Path

from app.shodan_queries import build_shodan_query_plan, filter_shodan_matches


def test_build_shodan_query_plan_chunks_excludes(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("\n".join([f"10.0.{index}.0/24" for index in range(6)]) + "\n")

    plan = build_shodan_query_plan(
        target="203.0.113.0/24",
        port="11434",
        exclude_files=str(exclude_file),
        base_query="product:Ollama",
        max_query_length=80,
        max_queries=10,
    )

    assert len(plan.queries) > 1
    assert plan.total_excludes == 6
    assert plan.applied_excludes == 6
    assert all(len(query) <= 80 for query in plan.queries)
    assert all("product:Ollama" in query for query in plan.queries)
    assert all("net:203.0.113.0/24" in query for query in plan.queries)


def test_filter_shodan_matches_respects_target_and_excludes(tmp_path: Path):
    exclude_file = tmp_path / "excludes.conf"
    exclude_file.write_text("198.51.100.3/32\n")

    matches = [
        {"ip_str": "198.51.100.2", "port": 11434},
        {"ip_str": "198.51.100.3", "port": 11434},
        {"ip_str": "203.0.113.5", "port": 11434},
        {"ip_str": "198.51.100.2", "port": 11434},
    ]

    filtered = filter_shodan_matches(
        matches=matches,
        target="198.51.100.0/24",
        port="11434",
        exclude_files=str(exclude_file),
    )

    assert filtered == ["198.51.100.2:11434"]
