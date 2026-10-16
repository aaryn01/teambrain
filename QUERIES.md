# Cypher queries TeamBrain depends on

Source of truth: `teambrain/tools.py` (reads) and `teambrain/ingest.py` (writes). Seeding queries are in `teambrain/seed.py`.

## Read queries (agent tools)

### `find_entities`

Resolve names/keywords in a question to node ids. Scores each node by how many search tokens appear in its name/title or description.

```cypher
MATCH (n)
WITH n, toLower(coalesce(n.name, n.title, '') + ' ' +
                coalesce(n.role, n.summary, n.rationale, n.notes, '')) AS text
WITH n, size([t IN $tokens WHERE text CONTAINS t]) AS hits
WHERE hits > 0
RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.title) AS name,
       coalesce(n.role, n.status, n.date, n.kind) AS detail, hits
ORDER BY hits DESC, label
LIMIT 12
```

### `project_overview`

Everything attached to one project: owner team, lead, members, active decisions, documents, meetings.

```cypher
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
```

### `decision_trail`

The full decision history of a project in date order: who decided, in which meeting, who attended, the rationale, supporting documents, and what superseded what.

```cypher
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
```

### `person_profile`

A person's team, role, projects, decisions, documents and meetings.

```cypher
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
```

### `who_knows`

Expertise ranking: scores every person by their paths into a project. Direct links (LEADS 5, WORKS_ON 3) weigh more than indirect ones (DECIDED 3, AUTHORED 2, ATTENDED 1 per meeting).

```cypher
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
```

### `connection`

Shortest paths (up to 4 hops, any direction) between two nodes, returned as readable hops.

```cypher
MATCH path = (a {id: $from_id})-[*1..4]-(b {id: $to_id})
RETURN [n IN nodes(path) | n.id] AS ids,
       [n IN nodes(path) | coalesce(n.name, n.title)] AS names,
       [r IN relationships(path) |
          startNode(r).id + ' -' + type(r) + '-> ' + endNode(r).id] AS hops,
       length(path) AS length
ORDER BY length
LIMIT 3
```

### `run_cypher`

Free-form fallback for questions no tool covers. Executed with `GRAPH.RO_QUERY`, so FalkorDB rejects any write; a keyword check also blocks CREATE/MERGE/SET/DELETE before it reaches the server.

## Write queries (ingest)

### `WRITE_PEOPLE`

Add people mentioned in notes who aren't in the graph yet, and link them to their team.

```cypher
UNWIND $rows AS r
MERGE (p:Person {id: r.id}) ON CREATE SET p.name = r.name, p.role = r.role
WITH p, r
OPTIONAL MATCH (t:Team {id: r.team_id})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (p)-[:MEMBER_OF]->(t))
```

### `WRITE_MEETING`

Create the meeting, link it to its project and to every attendee.

```cypher
MATCH (pr:Project {id: $project_id})
MERGE (m:Meeting {id: $m.id})
  SET m.title = $m.title, m.date = $m.date, m.notes = $m.notes
MERGE (m)-[:ABOUT]->(pr)
WITH m
UNWIND $attendees AS aid
MATCH (a:Person {id: aid})
MERGE (a)-[:ATTENDED]->(m)
```

### `WRITE_DECISIONS`

Create decisions, link them to meeting, project and decider. If a decision replaces an older one, mark the old one `superseded` and add a `SUPERSEDES` edge, so the history is preserved, not overwritten.

```cypher
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
```

### `WRITE_PROJECT`

Create a project when notes are about one that doesn't exist yet.

```cypher
MERGE (pr:Project {id: $p.id})
  ON CREATE SET pr.name = $p.name, pr.summary = $p.summary, pr.status = 'in_progress'
WITH pr
OPTIONAL MATCH (t:Team {id: $p.team_id})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (t)-[:OWNS]->(pr))
```
