"""Offline tests (no database or LLM needed):  python -m pytest -q"""
import pytest

from teambrain import ingest, risk, tools

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
    assert plan["meeting"]["id"].startswith("m-") and len(plan["meeting"]["id"]) == 8
    # same notes -> same ids, so re-applying is idempotent
    assert ingest._validate(raw, CTX)["decisions"][0]["id"] == plan["decisions"][0]["id"]


def test_validate_requires_date():
    with pytest.raises(ValueError):
        ingest._validate({"meeting": {"title": "x"}, "project_id": "proj-autopay"}, CTX)


def test_risk_level_is_monotonic_and_explainable():
    low = risk._risk_level(sole_bridges=0, exclusive=0, leads_alone=0, broker_rank=9)
    lead = risk._risk_level(sole_bridges=0, exclusive=0, leads_alone=1, broker_rank=9)
    broker = risk._risk_level(sole_bridges=2, exclusive=1, leads_alone=0, broker_rank=1, brokered_pairs=12)
    assert (low, lead, broker) == ("low", "medium", "high")
    # a top broker who leads nothing is still at least medium: that is the point of the feature
    assert risk._risk_level(0, 0, 0, broker_rank=1) == "medium"


def test_connection_query_ignores_derived_projection():
    assert "COLLABORATES_WITH" not in tools.CONNECTION
    assert "COLLABORATES_WITH" in risk.BUILD_COLLABORATION


def test_apply_rejects_bad_ids():
    plan = {"meeting": {"id": "m-1; DROP", "title": "", "date": "", "notes": ""},
            "project_id": "proj-autopay", "attendees": [], "decisions": [], "new_people": []}
    with pytest.raises(ValueError):
        ingest.apply(plan)
