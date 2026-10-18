"""Key-person risk: who holds the company's knowledge together, and what breaks if they leave.

Two graph techniques, both executed by FalkorDB:

1. A *collaboration projection*. People never point at each other in the source data, they
   point at projects, meetings, decisions and documents. `rebuild_collaboration()` derives
   (Person)-[:COLLABORATES_WITH {shared}]->(Person) edges between people who share any of
   those, in both directions, so centrality algorithms have a people-to-people graph to work on.
2. FalkorDB's built-in `algo.betweenness` on that projection. Betweenness counts how many
   shortest paths between other people run through someone: the *brokers* who connect teams.
   Project leads are hubs inside their own project and often score zero here, which is
   exactly why this view is useful. The obvious owners are visible; the brokers are not.
"""
from .db import read, write

# Relationship types that mean "this person is involved in this thing".
INVOLVEMENT = "LEADS|WORKS_ON|ATTENDED|DECIDED|AUTHORED"

# ---------------------------------------------------------------------------
# 1. Collaboration projection (write)
# ---------------------------------------------------------------------------

DROP_COLLABORATION = "MATCH ()-[c:COLLABORATES_WITH]->() DELETE c"

# Two people collaborate when they are involved in the same project, or in the same
# meeting / decision / document (which all point at a project via ABOUT).
BUILD_COLLABORATION = f"""
MATCH (a:Person)-[:{INVOLVEMENT}]->(x)
OPTIONAL MATCH (x)-[:ABOUT]->(pr:Project)
WITH a, CASE WHEN x:Project THEN x ELSE coalesce(pr, x) END AS ctx
WITH a, collect(DISTINCT ctx) AS ctxs
UNWIND ctxs AS ctx
MATCH (b:Person)-[:{INVOLVEMENT}]->(y)
OPTIONAL MATCH (y)-[:ABOUT]->(pr2:Project)
WITH a, b, ctx, CASE WHEN y:Project THEN y ELSE coalesce(pr2, y) END AS ctx2
WHERE a <> b AND ctx = ctx2
WITH a, b, count(DISTINCT ctx) AS shared
MERGE (a)-[c:COLLABORATES_WITH]->(b) SET c.shared = shared
RETURN count(c) AS edges
"""


def rebuild_collaboration() -> int:
    """Recompute the projection from scratch. Idempotent; run after any graph change."""
    write(DROP_COLLABORATION)
    rows = write(BUILD_COLLABORATION)
    return rows[0]["edges"] if rows else 0


def ensure_collaboration():
    if read("MATCH ()-[c:COLLABORATES_WITH]->() RETURN count(c) AS n")[0]["n"] == 0:
        rebuild_collaboration()


# ---------------------------------------------------------------------------
# 2. Read queries
# ---------------------------------------------------------------------------

KEY_PEOPLE = """
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES_WITH'],
                       samplingSize: 100, samplingSeed: 7})
YIELD node AS p, score
MATCH (p)-[:MEMBER_OF]->(t:Team)
OPTIONAL MATCH (p)-[:LEADS]->(lp:Project)
OPTIONAL MATCH (p)-[:COLLABORATES_WITH]->(c:Person)
RETURN p.id AS id, p.name AS name, p.role AS role, t.id AS team_id, t.name AS team,
       round(score * 10) / 10 AS broker_score,
       collect(DISTINCT lp {.id, .name}) AS leads,
       count(DISTINCT c) AS collaborators
ORDER BY broker_score DESC, collaborators DESC
"""

# Projects owned by another team where this person is their own team's ONLY link.
SOLE_BRIDGES = f"""
MATCH (p:Person {{id: $id}})-[:MEMBER_OF]->(t:Team)
MATCH (p)-[:{INVOLVEMENT}]->(x)
OPTIONAL MATCH (x)-[:ABOUT]->(pr1:Project)
WITH p, t, CASE WHEN x:Project THEN x ELSE pr1 END AS pr
WITH DISTINCT p, t, pr
WHERE NOT (t)-[:OWNS]->(pr)
OPTIONAL MATCH (o:Person)-[:MEMBER_OF]->(t) WHERE o <> p
OPTIONAL MATCH (o)-[r1:LEADS|WORKS_ON]->(pr)
OPTIONAL MATCH (o)-[r2:ATTENDED|DECIDED|AUTHORED]->(z)-[:ABOUT]->(pr)
WITH pr, t, collect(DISTINCT CASE WHEN r1 IS NOT NULL OR r2 IS NOT NULL THEN o.id END) AS others
WHERE size(others) = 0
MATCH (owner:Team)-[:OWNS]->(pr)
RETURN pr.id AS id, pr.name AS name, owner.name AS owner_team, t.name AS team
"""

# Meetings, decisions and documents where this person is the only person directly attached.
EXCLUSIVE_KNOWLEDGE = """
MATCH (p:Person {id: $id})-[r]->(x)
WHERE NOT x:Team AND NOT x:Person
OPTIONAL MATCH (o:Person)-[]->(x) WHERE o <> p
WITH x, type(r) AS rel, count(o) AS others
WHERE others = 0
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.name, x.title) AS name, rel
ORDER BY label, name
"""

# Pairs of this person's collaborators who do not collaborate directly with each other:
# today their knowledge flows through this person.
BROKERED_PAIRS = """
MATCH (p:Person {id: $id})-[:COLLABORATES_WITH]->(c:Person)
WITH p, collect(c) AS cs
UNWIND cs AS a
UNWIND cs AS b
WITH a, b WHERE a.id < b.id AND NOT (a)-[:COLLABORATES_WITH]->(b)
MATCH (a)-[:MEMBER_OF]->(ta:Team), (b)-[:MEMBER_OF]->(tb:Team)
RETURN a {.id, .name, team: ta.name} AS from, b {.id, .name, team: tb.name} AS to
ORDER BY from.name, to.name
"""

PROJECTS_LED_ALONE = """
MATCH (p:Person {id: $id})-[:LEADS]->(pr:Project)
OPTIONAL MATCH (o:Person)-[:LEADS]->(pr) WHERE o <> p
WITH pr, count(o) AS co_leads WHERE co_leads = 0
RETURN pr.id AS id, pr.name AS name, pr.status AS status
"""

# Bus factor: how many people are deeply involved in each project, and how concentrated
# that involvement is in one person.
BUS_FACTOR = """
MATCH (pr:Project)
OPTIONAL MATCH (p:Person)-[r]->(x)
WHERE (x = pr AND type(r) IN ['LEADS', 'WORKS_ON'])
   OR (type(r) IN ['DECIDED', 'AUTHORED', 'ATTENDED'] AND (x)-[:ABOUT]->(pr))
WITH pr, p, count(r) AS links
WITH pr, collect({id: p.id, name: p.name, links: links}) AS people, sum(links) AS total
UNWIND people AS pp
WITH pr, total, people, pp ORDER BY pp.links DESC
WITH pr, total, people, collect(pp)[0] AS top
RETURN pr.id AS id, pr.name AS name, pr.status AS status,
       size(people) AS people, total AS links,
       top.id AS top_person_id, top.name AS top_person,
       round(100.0 * top.links / total) AS top_share
ORDER BY people ASC, top_share DESC
"""


def _risk_level(sole_bridges: int, exclusive: int, leads_alone: int,
                broker_rank: int, brokered_pairs: int = 0) -> str:
    """Three-way label used by the UI and the agent. Deliberately simple and explainable:
    2 points per project led alone or team bridge held alone, 1 per artifact only they
    touch, 2 for being a top-2 broker, and up to 2 for the collaborator pairs they broker."""
    points = (sole_bridges * 2 + exclusive + leads_alone * 2
              + (2 if broker_rank <= 2 else 0) + min(brokered_pairs // 5, 2))
    if points >= 5:
        return "high"
    if points >= 2:
        return "medium"
    return "low"


def person_impact(person_id: str) -> dict:
    """Everything that depends on one person."""
    ensure_collaboration()
    params = {"id": person_id}
    people = read(KEY_PEOPLE)
    ranked = [p["id"] for p in people]
    if person_id not in ranked:
        raise ValueError(f"Unknown person id: {person_id}")
    me = next(p for p in people if p["id"] == person_id)
    rank = ranked.index(person_id) + 1
    leads_alone = read(PROJECTS_LED_ALONE, params)
    bridges = read(SOLE_BRIDGES, params)
    exclusive = read(EXCLUSIVE_KNOWLEDGE, params)
    pairs = read(BROKERED_PAIRS, params)
    return {
        "person": {k: me[k] for k in ("id", "name", "role", "team")},
        "broker_score": me["broker_score"],
        "broker_rank": rank,
        "collaborators": me["collaborators"],
        "leads_alone": leads_alone,
        "sole_bridges": bridges,
        "exclusive_knowledge": exclusive,
        "brokered_pairs": pairs,
        "risk": _risk_level(len(bridges), len(exclusive), len(leads_alone), rank, len(pairs)),
    }


def key_people() -> list[dict]:
    """Ranked people with the risk signals the UI table shows."""
    ensure_collaboration()
    out = []
    for rank, p in enumerate(read(KEY_PEOPLE), start=1):
        params = {"id": p["id"]}
        bridges = read(SOLE_BRIDGES, params)
        exclusive = read(EXCLUSIVE_KNOWLEDGE, params)
        leads_alone = read(PROJECTS_LED_ALONE, params)
        pairs = read(BROKERED_PAIRS, params)
        out.append({
            **p,
            "broker_rank": rank,
            "sole_bridges": bridges,
            "exclusive_knowledge": exclusive,
            "leads_alone": [x["name"] for x in leads_alone],
            "brokered_pairs": len(pairs),
            "risk": _risk_level(len(bridges), len(exclusive), len(leads_alone), rank, len(pairs)),
        })
    return out


def bus_factor() -> list[dict]:
    return read(BUS_FACTOR)
