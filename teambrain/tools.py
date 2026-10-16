"""Graph tools the agent can call. Each one is a single Cypher query over FalkorDB.

Every tool returns {"cypher": <query>, "params": <params>, "rows": <rows>} so the
UI can show exactly which graph queries produced an answer.
"""
import re

from .db import read

# ---------------------------------------------------------------------------
# Cypher the product depends on (also documented in QUERIES.md)
# ---------------------------------------------------------------------------

FIND_ENTITIES = """
MATCH (n)
WITH n, toLower(coalesce(n.name, n.title, '') + ' ' +
                coalesce(n.role, n.summary, n.rationale, n.notes, '')) AS text
WITH n, size([t IN $tokens WHERE text CONTAINS t]) AS hits
WHERE hits > 0
RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.title) AS name,
       coalesce(n.role, n.status, n.date, n.kind) AS detail, hits
ORDER BY hits DESC, label
LIMIT 12
"""

PROJECT_OVERVIEW = """
MATCH (p:Project {id: $id})
OPTIONAL MATCH (t:Team)-[:OWNS]->(p)
OPTIONAL MATCH (lead:Person)-[:LEADS]->(p)
OPTIONAL MATCH (m:Person)-[:WORKS_ON]->(p)
OPTIONAL MATCH (d:Decision {status: 'active'})-[:ABOUT]->(p)
OPTIONAL MATCH (doc:Document)-[:ABOUT]->(p)
OPTIONAL MATCH (mt:Meeting)-[:ABOUT]->(p)
RETURN p.id AS id, p.name AS name, p.status AS status, p.summary AS summary,
       t {.id, .name} AS owner_team,
       lead {.id, .name, .role} AS lead,
       collect(DISTINCT m {.id, .name, .role}) AS members,
       collect(DISTINCT d {.id, .title, .date}) AS active_decisions,
       collect(DISTINCT doc {.id, .title, .kind, .url}) AS documents,
       collect(DISTINCT mt {.id, .title, .date}) AS meetings
"""

DECISION_TRAIL = """
MATCH (d:Decision)-[:ABOUT]->(:Project {id: $id})
OPTIONAL MATCH (d)-[:DECIDED_IN]->(m:Meeting)
OPTIONAL MATCH (by:Person)-[:DECIDED]->(d)
OPTIONAL MATCH (a:Person)-[:ATTENDED]->(m)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
OPTIONAL MATCH (doc:Document)-[:REFERENCES]->(d)
RETURN d.id AS id, d.title AS title, d.rationale AS rationale,
       d.date AS date, d.status AS status,
       by {.id, .name, .role} AS decided_by,
       m {.id, .title, .date, .notes} AS meeting,
       collect(DISTINCT a.name) AS attendees,
       old {.id, .title} AS supersedes,
       newer {.id, .title} AS superseded_by,
       collect(DISTINCT doc {.id, .title, .url}) AS documents
ORDER BY date
"""

PERSON_PROFILE = """
MATCH (p:Person {id: $id})
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH (p)-[:LEADS]->(lp:Project)
OPTIONAL MATCH (p)-[:WORKS_ON]->(wp:Project)
OPTIONAL MATCH (p)-[:DECIDED]->(d:Decision)
OPTIONAL MATCH (p)-[:AUTHORED]->(doc:Document)
OPTIONAL MATCH (p)-[:ATTENDED]->(m:Meeting)
RETURN p.id AS id, p.name AS name, p.role AS role,
       t {.id, .name} AS team,
       collect(DISTINCT lp {.id, .name}) AS leads,
       collect(DISTINCT wp {.id, .name}) AS works_on,
       collect(DISTINCT d {.id, .title, .status}) AS decisions_made,
       collect(DISTINCT doc {.id, .title}) AS authored,
       collect(DISTINCT m {.id, .title, .date}) AS meetings
"""

# Rank people by how strongly they are connected to a project.
# Direct links weigh more than links through meetings/decisions/docs.
WHO_KNOWS = """
MATCH (proj:Project {id: $id})
MATCH (p:Person)-[r]->(x)
WHERE (x = proj AND type(r) IN ['LEADS', 'WORKS_ON'])
   OR (type(r) IN ['DECIDED', 'AUTHORED', 'ATTENDED'] AND (x)-[:ABOUT]->(proj))
WITH p, type(r) AS rel, count(*) AS n
WITH p, rel, n,
     CASE rel WHEN 'LEADS' THEN 5 WHEN 'WORKS_ON' THEN 3 WHEN 'DECIDED' THEN 3
              WHEN 'AUTHORED' THEN 2 ELSE 1 END AS weight
RETURN p.id AS id, p.name AS name, p.role AS role,
       sum(weight * n) AS score,
       collect(rel + ' x' + toString(n)) AS evidence
ORDER BY score DESC
LIMIT 5
"""

# Shortest ways two things are connected, in either direction, up to 4 hops.
CONNECTION = """
MATCH path = (a {id: $from_id})-[*1..4]-(b {id: $to_id})
RETURN [n IN nodes(path) | n.id] AS ids,
       [n IN nodes(path) | coalesce(n.name, n.title)] AS names,
       [r IN relationships(path) |
          startNode(r).id + ' -' + type(r) + '-> ' + endNode(r).id] AS hops,
       length(path) AS length
ORDER BY length
LIMIT 3
"""

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_STOPWORDS = {"the", "and", "for", "who", "what", "why", "how", "was", "are", "with", "about"}

_WRITE_PATTERN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH)\b", re.IGNORECASE
)


def _result(cypher: str, params: dict, rows: list) -> dict:
    return {"cypher": cypher.strip(), "params": params, "rows": rows}


def find_entities(query: str) -> dict:
    tokens = [t for t in re.findall(r"[a-z0-9.]+", query.lower())
              if len(t) > 2 and t not in _STOPWORDS] or [query.lower().strip()]
    params = {"tokens": tokens}
    return _result(FIND_ENTITIES, params, read(FIND_ENTITIES, params))


def project_overview(project_id: str) -> dict:
    params = {"id": project_id}
    return _result(PROJECT_OVERVIEW, params, read(PROJECT_OVERVIEW, params))


def decision_trail(project_id: str) -> dict:
    params = {"id": project_id}
    return _result(DECISION_TRAIL, params, read(DECISION_TRAIL, params))


def person_profile(person_id: str) -> dict:
    params = {"id": person_id}
    return _result(PERSON_PROFILE, params, read(PERSON_PROFILE, params))


def who_knows(project_id: str) -> dict:
    params = {"id": project_id}
    return _result(WHO_KNOWS, params, read(WHO_KNOWS, params))


def connection(from_id: str, to_id: str) -> dict:
    params = {"from_id": from_id, "to_id": to_id}
    return _result(CONNECTION, params, read(CONNECTION, params))


def run_cypher(query: str) -> dict:
    """Ad-hoc read-only Cypher. Blocked twice: a keyword check here, and
    FalkorDB's GRAPH.RO_QUERY, which refuses any write server-side."""
    if _WRITE_PATTERN.search(query):
        raise ValueError("Only read-only queries are allowed.")
    rows = read(query)
    return _result(query, {}, rows[:50])


TOOLS = {
    "find_entities": find_entities,
    "project_overview": project_overview,
    "decision_trail": decision_trail,
    "person_profile": person_profile,
    "who_knows": who_knows,
    "connection": connection,
    "run_cypher": run_cypher,
}


def _fn(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_ID = {"type": "string"}

TOOL_SCHEMAS = [
    _fn("find_entities",
        "Fuzzy-search the company graph by name, title or keywords. Use this first "
        "to turn names in the question into node ids.",
        {"query": {"type": "string", "description": "Names or keywords, e.g. 'ledger cutover'"}},
        ["query"]),
    _fn("project_overview",
        "Owner team, lead, members, active decisions, documents and meetings of a project.",
        {"project_id": {**_ID, "description": "e.g. proj-ledger"}}, ["project_id"]),
    _fn("decision_trail",
        "Every decision on a project in date order, with who decided, the meeting, "
        "attendees, the rationale, supporting docs, and which decision replaced which.",
        {"project_id": {**_ID, "description": "e.g. proj-fraud"}}, ["project_id"]),
    _fn("person_profile",
        "A person's team, role, projects, decisions, documents and meetings.",
        {"person_id": {**_ID, "description": "e.g. p-asha"}}, ["person_id"]),
    _fn("who_knows",
        "Rank the people most connected to a project (leads, works on, decided, wrote "
        "docs, attended meetings). Use for 'who should I ask about X'.",
        {"project_id": {**_ID, "description": "e.g. proj-autopay"}}, ["project_id"]),
    _fn("connection",
        "Shortest paths (up to 4 hops) connecting any two nodes, e.g. how a person "
        "is linked to a decision.",
        {"from_id": _ID, "to_id": _ID}, ["from_id", "to_id"]),
    _fn("run_cypher",
        "Run a custom READ-ONLY Cypher query when no other tool fits. "
        "Return properties (n.id, n.name, ...), not whole nodes.",
        {"query": {"type": "string"}}, ["query"]),
]
