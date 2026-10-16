"""Build the Northwind Pay graph in FalkorDB from teambrain.seed_data."""
from .db import GRAPH_NAME, LABELS, get_db, read
from .seed_data import DECISIONS, DOCUMENTS, MEETINGS, PEOPLE, PROJECTS, TEAMS


def reset_graph(graph_name: str = GRAPH_NAME):
    """Delete the graph (if any) and return a fresh handle with indexes."""
    db = get_db()
    if graph_name in db.list_graphs():
        db.select_graph(graph_name).delete()
    g = db.select_graph(graph_name)
    for label in LABELS:
        g.create_node_range_index(label, "id")
    return g


def load(g):
    g.query("UNWIND $rows AS r MERGE (t:Team {id: r.id}) SET t.name = r.name", {"rows": TEAMS})

    g.query(
        """
        UNWIND $rows AS r
        MERGE (p:Person {id: r.id}) SET p.name = r.name, p.role = r.role
        WITH p, r
        MATCH (t:Team {id: r.team})
        MERGE (p)-[:MEMBER_OF]->(t)
        """,
        {"rows": PEOPLE},
    )

    g.query(
        """
        UNWIND $rows AS r
        MERGE (pr:Project {id: r.id})
          SET pr.name = r.name, pr.status = r.status, pr.summary = r.summary
        WITH pr, r
        MATCH (t:Team {id: r.team}), (lead:Person {id: r.lead})
        MERGE (t)-[:OWNS]->(pr)
        MERGE (lead)-[:LEADS]->(pr)
        WITH pr, r
        UNWIND r.members AS mid
        MATCH (m:Person {id: mid})
        MERGE (m)-[:WORKS_ON]->(pr)
        """,
        {"rows": PROJECTS},
    )

    g.query(
        """
        UNWIND $rows AS r
        MERGE (m:Meeting {id: r.id})
          SET m.title = r.title, m.date = r.date, m.notes = r.notes
        WITH m, r
        MATCH (pr:Project {id: r.project})
        MERGE (m)-[:ABOUT]->(pr)
        WITH m, r
        UNWIND r.attendees AS aid
        MATCH (a:Person {id: aid})
        MERGE (a)-[:ATTENDED]->(m)
        """,
        {"rows": MEETINGS},
    )

    g.query(
        """
        UNWIND $rows AS r
        MERGE (d:Decision {id: r.id})
          SET d.title = r.title, d.rationale = r.rationale,
              d.date = r.date, d.status = r.status
        WITH d, r
        MATCH (m:Meeting {id: r.meeting}), (pr:Project {id: r.project}),
              (by:Person {id: r.by})
        MERGE (d)-[:DECIDED_IN]->(m)
        MERGE (d)-[:ABOUT]->(pr)
        MERGE (by)-[:DECIDED]->(d)
        """,
        {"rows": DECISIONS},
    )

    g.query(
        """
        UNWIND $rows AS r
        MATCH (new:Decision {id: r.id}), (old:Decision {id: r.supersedes})
        MERGE (new)-[:SUPERSEDES]->(old)
        """,
        {"rows": [d for d in DECISIONS if d["supersedes"]]},
    )

    g.query(
        """
        UNWIND $rows AS r
        MERGE (doc:Document {id: r.id})
          SET doc.title = r.title, doc.kind = r.kind,
              doc.url = r.url, doc.summary = r.summary
        WITH doc, r
        MATCH (au:Person {id: r.author}), (pr:Project {id: r.project})
        MERGE (au)-[:AUTHORED]->(doc)
        MERGE (doc)-[:ABOUT]->(pr)
        WITH doc, r
        UNWIND r.references AS did
        MATCH (d:Decision {id: did})
        MERGE (doc)-[:REFERENCES]->(d)
        """,
        {"rows": DOCUMENTS},
    )


def stats(g) -> dict:
    nodes = read("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label", graph=g)
    edges = read("MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY rel", graph=g)
    return {
        "nodes": {r["label"]: r["n"] for r in nodes},
        "edges": {r["rel"]: r["n"] for r in edges},
    }


def seed_graph(graph_name: str = GRAPH_NAME) -> dict:
    g = reset_graph(graph_name)
    load(g)
    return stats(g)


def main():
    result = seed_graph()
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])


if __name__ == "__main__":
    main()
