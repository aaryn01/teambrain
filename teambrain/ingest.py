"""Keep the brain current: turn free-text meeting notes into graph updates.

Two steps so a human can review before anything is written:
  extract(notes) -> plan   (LLM reads the notes against what the graph already knows)
  apply(plan)    -> summary (deterministic Cypher MERGEs)
"""
import hashlib
import json
import re

from .db import read, write
from .llm import chat, parse_json

EXTRACT_PROMPT = """You turn meeting notes into updates for a company knowledge graph.

What the graph already contains:
PEOPLE: {people}
TEAMS: {teams}
PROJECTS: {projects}
ACTIVE DECISIONS: {decisions}

Read the meeting notes and return ONLY a JSON object of this shape:
{{
  "meeting": {{"title": str, "date": "YYYY-MM-DD", "summary": "1-2 sentence summary"}},
  "project_id": existing project id this meeting is about, or null,
  "new_project": {{"name": str, "summary": str, "team_id": str}} or null (only if no existing project fits),
  "attendees": [{{"person_id": existing id or null, "name": str, "role": str or null, "team_id": str or null}}],
  "decisions": [{{"title": short imperative title, "rationale": why, "decided_by": person id or name or null,
                 "supersedes_id": id of an ACTIVE DECISION above that this one replaces, or null}}]
}}
Rules: reuse existing ids whenever a person or project already exists. Only mark
supersedes_id when the notes clearly replace or change that earlier decision.

MEETING NOTES:
{notes}
"""


def _slug(text: str, n: int = 32) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].strip("-")


def _short_id(prefix: str, *parts: str) -> str:
    """Short, stable id: re-applying the same notes MERGEs instead of duplicating."""
    digest = hashlib.sha1("|".join(parts).lower().encode()).hexdigest()[:6]
    return f"{prefix}-{digest}"


def _context() -> dict:
    return {
        "people": read("MATCH (p:Person)-[:MEMBER_OF]->(t:Team) "
                       "RETURN p.id AS id, p.name AS name, p.role AS role, t.id AS team"),
        "teams": read("MATCH (t:Team) RETURN t.id AS id, t.name AS name"),
        "projects": read("MATCH (p:Project) RETURN p.id AS id, p.name AS name"),
        "decisions": read("MATCH (d:Decision {status: 'active'})-[:ABOUT]->(p:Project) "
                          "RETURN d.id AS id, d.title AS title, p.id AS project"),
    }


def extract(notes: str) -> dict:
    ctx = _context()
    prompt = EXTRACT_PROMPT.format(
        people=json.dumps(ctx["people"]), teams=json.dumps(ctx["teams"]),
        projects=json.dumps(ctx["projects"]), decisions=json.dumps(ctx["decisions"]),
        notes=notes,
    )
    raw = parse_json(chat([{"role": "user", "content": prompt}], json_mode=True).content)
    return _validate(raw, ctx)


def _validate(raw: dict, ctx: dict) -> dict:
    """Resolve everything the LLM proposed against real graph ids."""
    people_by_id = {p["id"]: p for p in ctx["people"]}
    people_by_name = {p["name"].lower(): p for p in ctx["people"]}
    team_ids = {t["id"] for t in ctx["teams"]}
    project_ids = {p["id"] for p in ctx["projects"]}
    active_ids = {d["id"] for d in ctx["decisions"]}

    meeting = raw.get("meeting") or {}
    date = str(meeting.get("date") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("Couldn't find a meeting date (YYYY-MM-DD) in the notes.")
    title = (meeting.get("title") or "Meeting").strip()

    project, new_project = raw.get("project_id"), None
    if project not in project_ids:
        np = raw.get("new_project") or {}
        if not np.get("name"):
            raise ValueError("Couldn't tell which project these notes are about.")
        project = "proj-" + _slug(np["name"])
        new_project = {"id": project, "name": np["name"], "summary": np.get("summary", ""),
                       "team_id": np.get("team_id") if np.get("team_id") in team_ids else None}

    def resolve(ref):
        if not ref:
            return None
        if ref in people_by_id:
            return ref
        hit = people_by_name.get(str(ref).lower())
        return hit["id"] if hit else None

    attendees, new_people = [], []
    for a in raw.get("attendees") or []:
        pid = resolve(a.get("person_id")) or resolve(a.get("name"))
        if not pid:
            if not a.get("name"):
                continue
            pid = "p-" + _slug(a["name"])
            if pid not in {p["id"] for p in new_people}:
                new_people.append({"id": pid, "name": a["name"].strip(), "role": a.get("role") or "",
                                   "team_id": a.get("team_id") if a.get("team_id") in team_ids else None})
            people_by_name[a["name"].lower()] = {"id": pid}
        if pid not in attendees:
            attendees.append(pid)

    decisions = []
    for d in raw.get("decisions") or []:
        if not d.get("title"):
            continue
        sup = d.get("supersedes_id")
        decisions.append({
            "id": _short_id("d", date, d["title"]),
            "title": d["title"].strip(),
            "rationale": (d.get("rationale") or "").strip(),
            "decided_by": resolve(d.get("decided_by")),
            "supersedes": sup if sup in active_ids else None,
        })

    return {
        "meeting": {"id": _short_id("m", date, title), "title": title, "date": date,
                    "notes": (meeting.get("summary") or "").strip()},
        "project_id": project,
        "new_project": new_project,
        "new_people": new_people,
        "attendees": attendees,
        "decisions": decisions,
    }


# Cypher used to write an approved plan.
WRITE_PROJECT = """
MERGE (pr:Project {id: $p.id})
  ON CREATE SET pr.name = $p.name, pr.summary = $p.summary, pr.status = 'in_progress'
WITH pr
OPTIONAL MATCH (t:Team {id: $p.team_id})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (t)-[:OWNS]->(pr))
"""

WRITE_PEOPLE = """
UNWIND $rows AS r
MERGE (p:Person {id: r.id}) ON CREATE SET p.name = r.name, p.role = r.role
WITH p, r
OPTIONAL MATCH (t:Team {id: r.team_id})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (p)-[:MEMBER_OF]->(t))
"""

WRITE_MEETING = """
MATCH (pr:Project {id: $project_id})
MERGE (m:Meeting {id: $m.id})
  SET m.title = $m.title, m.date = $m.date, m.notes = $m.notes
MERGE (m)-[:ABOUT]->(pr)
WITH m
UNWIND $attendees AS aid
MATCH (a:Person {id: aid})
MERGE (a)-[:ATTENDED]->(m)
"""

WRITE_DECISIONS = """
UNWIND $rows AS r
MATCH (m:Meeting {id: $meeting_id}), (pr:Project {id: $project_id})
MERGE (d:Decision {id: r.id})
  SET d.title = r.title, d.rationale = r.rationale, d.date = $date, d.status = 'active'
MERGE (d)-[:DECIDED_IN]->(m)
MERGE (d)-[:ABOUT]->(pr)
WITH d, r
OPTIONAL MATCH (by:Person {id: r.decided_by})
FOREACH (_ IN CASE WHEN by IS NULL THEN [] ELSE [1] END | MERGE (by)-[:DECIDED]->(d))
WITH d, r
OPTIONAL MATCH (old:Decision {id: r.supersedes})
FOREACH (_ IN CASE WHEN old IS NULL THEN [] ELSE [1] END |
  SET old.status = 'superseded'
  MERGE (d)-[:SUPERSEDES]->(old))
"""


_ID_RE = re.compile(r"^[a-z]+-[a-z0-9-]+$")


def _check_ids(plan: dict):
    ids = [plan["meeting"]["id"], plan["project_id"], *plan["attendees"],
           *[d["id"] for d in plan["decisions"]], *[p["id"] for p in plan["new_people"]]]
    bad = [i for i in ids if not isinstance(i, str) or not _ID_RE.match(i)]
    if bad:
        raise ValueError(f"Invalid ids in plan: {bad}")


def apply(plan: dict) -> dict:
    _check_ids(plan)
    if plan.get("new_project"):
        write(WRITE_PROJECT, {"p": plan["new_project"]})
    if plan.get("new_people"):
        write(WRITE_PEOPLE, {"rows": plan["new_people"]})
    write(WRITE_MEETING, {"m": plan["meeting"], "project_id": plan["project_id"],
                          "attendees": plan["attendees"]})
    if plan.get("decisions"):
        write(WRITE_DECISIONS, {"rows": plan["decisions"], "meeting_id": plan["meeting"]["id"],
                                "project_id": plan["project_id"], "date": plan["meeting"]["date"]})
    from .risk import rebuild_collaboration

    rebuild_collaboration()  # keep the people-to-people projection current
    touched = ([plan["meeting"]["id"]] + [d["id"] for d in plan["decisions"]]
               + [p["id"] for p in plan["new_people"]]
               + ([plan["new_project"]["id"]] if plan.get("new_project") else []))
    return {
        "written": touched,
        "superseded": [d["supersedes"] for d in plan["decisions"] if d["supersedes"]],
    }
