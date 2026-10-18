"""TeamBrain web app.  Run:  uvicorn main:app --reload"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from teambrain import agent, ingest, risk
from teambrain.db import read
from teambrain.seed import seed_graph
from teambrain.seed_data import SAMPLE_NOTES

STATIC = Path(__file__).parent / "static"
ALLOW_RESET = os.getenv("ALLOW_RESET", "true").lower() == "true"

app = FastAPI(title="TeamBrain")


class AskRequest(BaseModel):
    question: str
    history: list[dict] = []


class IngestRequest(BaseModel):
    notes: str


class ApplyRequest(BaseModel):
    plan: dict


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    count = read("MATCH (n) RETURN count(n) AS n")[0]["n"]
    return {"ok": True, "nodes": count}


@app.get("/api/graph")
def graph():
    nodes = read(
        "MATCH (n) RETURN n.id AS id, labels(n)[0] AS label, "
        "coalesce(n.name, n.title) AS name, properties(n) AS props"
    )
    # The derived COLLABORATES_WITH projection is left out of the picture; it is dense
    # (every pair of collaborators) and would hide the source relationships.
    edges = read(
        "MATCH (a)-[r]->(b) WHERE type(r) <> 'COLLABORATES_WITH' "
        "RETURN a.id AS source, type(r) AS type, b.id AS target"
    )
    return {"nodes": nodes, "edges": edges}


@app.get("/api/risk")
def risk_overview():
    return {"people": risk.key_people(), "projects": risk.bus_factor()}


@app.get("/api/risk/person/{person_id}")
def risk_person(person_id: str):
    try:
        return risk.person_impact(person_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/ask")
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question is empty.")
    try:
        return agent.ask(req.question.strip(), req.history)
    except Exception as exc:
        raise HTTPException(502, f"Agent error: {exc}") from exc


@app.get("/api/sample-notes")
def sample_notes():
    return {"notes": SAMPLE_NOTES}


@app.post("/api/ingest/preview")
def ingest_preview(req: IngestRequest):
    if not req.notes.strip():
        raise HTTPException(400, "Notes are empty.")
    try:
        return {"plan": ingest.extract(req.notes)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Extraction error: {exc}") from exc


@app.post("/api/ingest/apply")
def ingest_apply(req: ApplyRequest):
    try:
        return ingest.apply(req.plan)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"Bad plan: {exc}") from exc


@app.post("/api/reset")
def reset():
    if not ALLOW_RESET:
        raise HTTPException(403, "Reset is disabled.")
    return seed_graph()
