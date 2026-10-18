---
title: I built a "company brain" on FalkorDB in a weekend — and the graph found risks the org chart hides
published: true
tags: falkordb, graphdatabase, ai, hackathon
---

*Built for Graph Hacks 2026 (WeMakeDevs × FalkorDB), Company Brain track.*
*Live demo: https://teambrain-n1kt.onrender.com · Code: https://github.com/aaryn01/teambrain · Video: https://youtu.be/1q945ylk8Pg*

## The problem I wanted to solve

I work as a backend engineer at a bank. Every few months someone joins the team, or someone leaves, and the same questions come up:

- Who owns this project?
- Why did we decide that? Wasn't it different last quarter?
- Who should I talk to about the ledger migration?
- If this person leaves, what do we lose?

The answers exist. They're just spread across old meeting notes, Confluence pages, Slack threads and — mostly — people's heads. A document search can find a page that *mentions* the fraud threshold. It can't tell you that the threshold was changed in September, by whom, in which meeting, and what the previous value was.

Those are questions about *relationships*, not documents. So for the hackathon I built TeamBrain: a company's knowledge as a graph, with an AI agent that walks it.

## The graph

I made up a small fintech, Northwind Pay: 10 people, 4 teams, 4 projects, 6 meetings, 6 decisions, 5 documents. Six node types, thirteen relationship types:

```
(Person)-[:MEMBER_OF]->(Team)        (Team)-[:OWNS]->(Project)
(Person)-[:LEADS]->(Project)         (Person)-[:WORKS_ON]->(Project)
(Person)-[:ATTENDED]->(Meeting)      (Meeting)-[:ABOUT]->(Project)
(Person)-[:DECIDED]->(Decision)      (Decision)-[:DECIDED_IN]->(Meeting)
(Decision)-[:ABOUT]->(Project)       (Decision)-[:SUPERSEDES]->(Decision)
(Person)-[:AUTHORED]->(Document)     (Document)-[:ABOUT]->(Project)
(Document)-[:REFERENCES]->(Decision)
```

The one I'm most attached to is `SUPERSEDES`. When a decision changes, the old one isn't deleted — it gets `status: superseded` and an edge pointing to its replacement. The history stays in the graph, so "why is it 0.78 now?" can be answered with "because it was 0.85, and here's the meeting where that changed."

![TeamBrain answering a question with citations and the graph path highlighted](https://raw.githubusercontent.com/aaryn01/teambrain/main/docs/screenshot.png)

## The agent: tools, not free-form queries

My first instinct was "let the LLM write Cypher." I kept that as a fallback, but the main design is a set of **tools that are each one parameterised Cypher query**: find entities, project overview, decision trail, person profile, who-knows ranking, shortest connection between two nodes. The LLM picks a tool and fills in the ids; FalkorDB does the actual work.

Two rules make the answers trustworthy:

1. **Every fact must cite a node id.** The UI turns `[d-4]` into a clickable chip that highlights the node in the graph, and shows the exact Cypher that ran under each answer.
2. **All reads go through `GRAPH.RO_QUERY`.** FalkorDB's read-only mode rejects any write server-side, so even the free-form Cypher tool can't mutate anything. This turned out to be a great safety primitive for LLM agents.

## Keeping the brain current

A company brain that goes stale is useless. So the second feature: paste meeting notes, and the agent extracts a plan — which existing people attended, which new people appeared, what was decided, and whether a decision *replaces* an existing one. You review the plan, then it's written with idempotent `MERGE`s and deterministic ids, so applying the same notes twice doesn't duplicate anything.

The nice moment in the demo: write the notes, ask "what's the current autopay limit?", and the answer is already the new one — with the old decision shown as superseded, not gone.

## The part a document search can't do

The feature I'm proudest of came from a question I asked myself on day one: *who are our single points of failure?*

People never point at each other in the raw data — only at projects, meetings, decisions and documents. So first I derive a collaboration graph with one Cypher query: two people are connected if they share any project, meeting, decision or document, with a `shared` count on the edge. It's rebuilt after every ingest.

Then FalkorDB's built-in **betweenness centrality** runs on that projection:

```cypher
CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES_WITH']})
YIELD node, score
```

Betweenness answers: how often does the shortest path between two *other* people run through this person? A high score means they're a bridge between groups.

![Key-person risk view: project leads score zero, the real risks are the brokers between teams](https://raw.githubusercontent.com/aaryn01/teambrain/main/docs/risk.png)

The result surprised me even though I wrote the data. The three project leads — Meera, Priya, Neha — all score **zero**. They're hubs inside one project, not bridges between projects. The real risks are **Sana**, a data engineer who turns out to be Platform's only link into two other teams' projects, and **Kabir**, the compliance officer who is Risk's only link into two Payments projects. An org chart would never show you that. The graph does.

Three more pattern queries explain *why* each person is risky: projects they lead alone, projects where they're their team's only link, and artifacts where they're the only person attached. Click a person and the graph lights up exactly what depends on them.

I tried PageRank first. It just rediscovered the leads — the most-connected people. Betweenness finds the people *between* clusters, which is where the hidden risk lives. That one choice is the whole feature.

## What I learned

- **Graphs earn their place when the question is a chain.** "Decision → replaced decision → meeting → attendees → their other projects" is one query in Cypher and a nightmare anywhere else.
- **Directed edges matter for algorithms.** My first betweenness run returned 0 for everyone, because people only have outgoing edges — no shortest path ever passes *through* a person. The fix was the bidirectional collaboration projection. Obvious in hindsight.
- **Make the agent show its work.** Citations plus the visible query turned "trust me" into "check for yourself." Judges, teammates and future me all benefit.
- **Keep the scope small enough to explain.** 35 nodes, 16 queries, one algorithm. I can walk anyone through every piece.

## Stack and honesty

FalkorDB Cloud (free tier, Mumbai region), Python + FastAPI, Gemini via the OpenAI-compatible API, vis-network for the graph view, deployed on Render. All data is synthetic.

I used Claude as a coding assistant throughout — for generating and reviewing code — and said so in the README. I designed the graph model and the features with it, tested every query against FalkorDB, and the explanations above are mine. The hackathon rules allow this with disclosure, and I think that's the right norm: use the tools, own the understanding.

If you want to try it: clone the repo, point it at a free FalkorDB Cloud instance and a Gemini key, run `python seed.py`, and ask it who you can't afford to lose.
