"""Offline tests (no database or LLM needed):  python -m pytest -q"""
import pytest

from teambrain import ingest, tools

CTX = {
    "people": [{"id": "p-kabir", "name": "Kabir Shah", "role": "Compliance Officer", "team": "team-risk"},
               {"id": "p-neha", "name": "Neha Kapoor", "role": "PM", "team": "team-payments"}],
    "teams": [{"id": "team-payments", "name": "Payments"}, {"id": "team-risk", "name": "Risk"}],
    "projects": [{"id": "proj-autopay", "name": "UPI Autopay"}],
    "decisions": [{"id": "d-2", "title": "Cap at 15,000", "project": "proj-autopay"}],
}


@pytest.mark.parametrize("query", [
    "MATCH (n) DETACH DELETE n",
    "CREATE (:Person {name: 'x'})",
    "MATCH (n) SET n.name = 'x'",
    "MERGE (n:Team {id: 'x'})",
])
def test_run_cypher_blocks_writes(query):
    with pytest.raises(ValueError):
        tools.run_cypher(query)


def test_validate_resolves_names_and_new_people():
    raw = {
        "meeting": {"title": "Autopay limit review", "date": "2026-10-14", "summary": "s"},
        "project_id": "proj-autopay",
        "attendees": [{"person_id": None, "name": "kabir shah"},
                      {"person_id": "p-neha", "name": "Neha Kapoor"},
                      {"person_id": None, "name": "Ishaan Verma", "role": "Designer", "team_id": "team-payments"}],
        "decisions": [{"title": "Raise cap", "rationale": "r", "decided_by": "Kabir Shah", "supersedes_id": "d-2"},
                      {"title": "Bogus", "decided_by": "Nobody", "supersedes_id": "d-999"}],
    }
    plan = ingest._validate(raw, CTX)
    assert plan["attendees"] == ["p-kabir", "p-neha", "p-ishaan-verma"]
    assert plan["new_people"][0]["team_id"] == "team-payments"
    assert plan["decisions"][0]["decided_by"] == "p-kabir"
    assert plan["decisions"][0]["supersedes"] == "d-2"
    assert plan["decisions"][1]["decided_by"] is None
    assert plan["decisions"][1]["supersedes"] is None  # unknown ids are dropped
    assert plan["meeting"]["id"] == "m-2026-10-14-autopay-limit-review"


def test_validate_requires_date():
    with pytest.raises(ValueError):
        ingest._validate({"meeting": {"title": "x"}, "project_id": "proj-autopay"}, CTX)


def test_apply_rejects_bad_ids():
    plan = {"meeting": {"id": "m-1; DROP", "title": "", "date": "", "notes": ""},
            "project_id": "proj-autopay", "attendees": [], "decisions": [], "new_people": []}
    with pytest.raises(ValueError):
        ingest.apply(plan)
