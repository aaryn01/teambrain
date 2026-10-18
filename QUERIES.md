# Cypher queries and graph algorithms TeamBrain depends on

Source of truth: `teambrain/tools.py` (reads), `teambrain/risk.py` (collaboration projection and centrality) and `teambrain/ingest.py` (writes). Seeding queries are in `teambrain/seed.py`.

## Read queries (agent tools)

### find_entities

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

### project_overview

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

### decision_trail

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

### person_profile

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

### who_knows

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

### connection

Shortest paths (up to 4 hops, any direction) between two nodes over the source relationships, returned as readable hops.

```cypher
MATCH path = (a {id: $from_id})
             -[:MEMBER_OF|OWNS|LEADS|WORKS_ON|ATTENDED|ABOUT|DECIDED|DECIDED_IN|SUPERSEDES|AUTHORED|REFERENCES*1..4]-
             (b {id: $to_id})
RETURN [n IN nodes(path) | n.id] AS ids,
       [n IN nodes(path) | coalesce(n.name, n.title)] AS names,
       [r IN relationships(path) |
          startNode(r).id + ' -' + type(r) + '-> ' + endNode(r).id] AS hops,
       length(path) AS length
ORDER BY length
LIMIT 3
```

### run_cypher

Free-form fallback for questions no tool covers. Executed with `GRAPH.RO_QUERY`, so FalkorDB rejects any write; a keyword check also blocks CREATE/MERGE/SET/DELETE before it reaches the server.

## Key-person risk (graph algorithms)

### Collaboration projection

People never point at each other in the source data, only at projects, meetings, decisions and documents. This derives `(Person)-[:COLLABORATES_WITH {shared}]->(Person)` edges (both directions) between people who share any of those, so centrality algorithms have a people-to-people graph to run on. Rebuilt after seeding and after every ingest.

```cypher
MATCH (a:Person)-[:LEADS|WORKS_ON|ATTENDED|DECIDED|AUTHORED]->(x)
OPTIONAL MATCH (x)-[:ABOUT]->(pr:Project)
WITH a, CASE WHEN x:Project THEN x ELSE coalesce(pr, x) END AS ctx
WITH a, collect(DISTINCT ctx) AS ctxs
UNWIND ctxs AS ctx
MATCH (b:Person)-[:LEADS|WORKS_ON|ATTENDED|DECIDED|AUTHORED]->(y)
OPTIONAL MATCH (y)-[:ABOUT]->(pr2:Project)
WITH a, b, ctx, CASE WHEN y:Project THEN y ELSE coalesce(pr2, y) END AS ctx2
WHERE a <> b AND ctx = ctx2
WITH a, b, count(DISTINCT ctx) AS shared
MERGE (a)-[c:COLLABORATES_WITH]->(b) SET c.shared = shared
RETURN count(c) AS edges
```

### key_people — betweenness centrality

FalkorDB's built-in `algo.betweenness` on the collaboration projection. The score counts how often the shortest path between two other people runs through this person: the brokers who connect teams. Project leads are hubs inside one project and often score zero here, which is the whole point of the view.

```cypher
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
```

### Sole bridges

Projects owned by another team where this person is their own team's only link. If they leave, their team loses visibility into that project.

```cypher
MATCH (p:Person {id: $id})-[:MEMBER_OF]->(t:Team)
MATCH (p)-[:LEADS|WORKS_ON|ATTENDED|DECIDED|AUTHORED]->(x)
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
```

### Exclusive knowledge

Meetings, decisions and documents where this person is the only person directly attached.

```cypher
MATCH (p:Person {id: $id})-[r]->(x)
WHERE NOT x:Team AND NOT x:Person
OPTIONAL MATCH (o:Person)-[]->(x) WHERE o <> p
WITH x, type(r) AS rel, count(o) AS others
WHERE others = 0
RETURN x.id AS id, labels(x)[0] AS label, coalesce(x.name, x.title) AS name, rel
ORDER BY label, name
```

### Brokered pairs

Pairs of this person's collaborators who do not collaborate directly with each other: today their knowledge flows through this person.

```cypher
MATCH (p:Person {id: $id})-[:COLLABORATES_WITH]->(c:Person)
WITH p, collect(c) AS cs
UNWIND cs AS a
UNWIND cs AS b
WITH a, b WHERE a.id < b.id AND NOT (a)-[:COLLABORATES_WITH]->(b)
MATCH (a)-[:MEMBER_OF]->(ta:Team), (b)-[:MEMBER_OF]->(tb:Team)
RETURN a {.id, .name, team: ta.name} AS from, b {.id, .name, team: tb.name} AS to
ORDER BY from.name, to.name
```

### bus_factor

Per project: how many people are deeply involved and how concentrated that involvement is in one person.

```cypher
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
```

## Write queries (ingest)

### WRITE_PEOPLE

Add people mentioned in notes who aren't in the graph yet, and link them to their team.

```cypher
UNWIND $rows AS r
MERGE (p:Person {id: r.id}) ON CREATE SET p.name = r.name, p.role = r.role
WITH p, r
OPTIONAL MATCH (t:Team {id: r.team_id})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (p)-[:MEMBER_OF]->(t))
```

### WRITE_MEETING

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

### WRITE_DECISIONS

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

### WRITE_PROJECT

Create a project when notes are about one that doesn't exist yet.

```cypher
MERGE (pr:Project {id: $p.id})
  ON CREATE SET pr.name = $p.name, pr.summary = $p.summary, pr.status = 'in_progress'
WITH pr
OPTIONAL MATCH (t:Team {id: $p.team_id})
FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (t)-[:OWNS]->(pr))
```
