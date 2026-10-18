# TeamBrain — a company brain on FalkorDB

**Track:** Company Brain · **Graph Hacks** (WeMakeDevs × FalkorDB, Oct 2026)

TeamBrain answers the questions that new joiners, managers and auditors actually ask —
*who owns this, what did we decide, why did it change, who should I talk to* — by
walking a graph of people, teams, projects, meetings, decisions and documents.
Every answer cites the graph nodes it came from and shows the Cypher that produced it.
Paste new meeting notes and the brain updates itself, including marking old decisions
as superseded. And it answers the question no document search can: **who are our
single points of failure?** Using FalkorDB's betweenness centrality on a derived
collaboration graph, it finds the brokers who hold teams together, who are usually
not the people on the org chart.

- **Live demo:** https://teambrain-n1kt.onrender.com
- **Demo video:** https://youtu.be/xxxxx

![TeamBrain screenshot](docs/screenshot.png)

## Why this needs a graph

The useful answers live in the **relationships**, not in any single document:

| Question | Graph walk |
|---|---|
| Why is the fraud auto-block threshold 0.78? | `Decision -SUPERSEDES-> Decision`, `-DECIDED_IN-> Meeting <-ATTENDED- Person` |
| Who should I ask about the ledger migration? | Rank people by `LEADS`, `WORKS_ON`, `DECIDED`, `AUTHORED`, `ATTENDED` paths into the project |
| How is Sana connected to the fraud threshold decision? | Shortest paths up to 4 hops between the two nodes |
| What's the current autopay limit? | Active decision on the project, following `SUPERSEDES` back to what it replaced |
| Who are our single points of failure? | `algo.betweenness` on a derived `COLLABORATES_WITH` projection, plus "only link from their team" and "only person on this artifact" patterns |
| What do we lose if Sana leaves? | Projects led alone, team bridges that break, exclusive artifacts, and collaborator pairs whose only link is her |

Remove FalkorDB and nothing works: the agent has no other source of truth, and is
told never to answer from outside knowledge.

### Key-person risk: the part a document search cannot do

![Key-person risk view](docs/risk.png)

In the demo company the official leads (Meera, Priya, Neha) look safe. The graph says
the real risks are **Sana Qureshi**, a data engineer who is Platform's only link into
Fraud Scoring and Onboarding, and **Kabir Shah**, the compliance officer who is Risk's
only link into two Payments projects. Both score highest on betweenness centrality:
the shortest path between two other people runs through them more often than through
anyone else. Project leads score zero because they are hubs inside one project, not
bridges between projects. That is why this needs graph algorithms, not search.

How it works (all in FalkorDB):
1. **Collaboration projection**: people never point at each other in the source data,
   so a Cypher query derives `(Person)-[:COLLABORATES_WITH {shared}]->(Person)` between
   people who share a project, meeting, decision or document. It is rebuilt after every
   ingest, so the risk view stays current.
2. **`CALL algo.betweenness({nodeLabels: ['Person'], relationshipTypes: ['COLLABORATES_WITH']})`**
   ranks the brokers.
3. Three pattern queries explain *why*: projects led by no one else, projects where the
   person is their team's only link, and artifacts where they are the only person attached.

## Architecture

```mermaid
flowchart LR
  UI[Web UI<br/>vis-network graph] -->|/api/ask| API[FastAPI]
  UI -->|/api/ingest| API
  API --> AG[Agent<br/>LLM tool-calling loop]
  AG -->|7 graph tools| T[Cypher tools]
  T -->|GRAPH.RO_QUERY| DB[(FalkorDB)]
  API --> IN[Ingest]
  IN -->|1. extract + match<br/>against existing nodes| LLM[LLM]
  IN -->|2. human review<br/>3. MERGE| DB
```

- **Agent** (`teambrain/agent.py`): an LLM with 10 graph tools. It resolves names to node
  ids, picks the right traversal, and must cite node ids like `[d-4]` for every fact.
- **Tools** (`teambrain/tools.py`): each is one Cypher query. All reads go through
  FalkorDB's `GRAPH.RO_QUERY`, so even the free-form `run_cypher` tool cannot write.
- **Risk** (`teambrain/risk.py`): the collaboration projection, `algo.betweenness`, and
  the bus-factor / sole-bridge / exclusive-knowledge queries behind the Key-person risk tab.
- **Ingest** (`teambrain/ingest.py`): meeting notes → LLM extraction using the graph's
  existing people/projects/decisions as context → ids validated in Python → shown to
  the user → written with `MERGE` (idempotent). New decisions can `SUPERSEDE` old ones.
- **UI** (`static/index.html`): chat, citations that highlight nodes in the graph,
  the Cypher behind each answer, and the ingest review screen.

## Graph data model

```mermaid
graph LR
  Person -- MEMBER_OF --> Team
  Team -- OWNS --> Project
  Person -- LEADS --> Project
  Person -- WORKS_ON --> Project
  Person -- ATTENDED --> Meeting
  Meeting -- ABOUT --> Project
  Person -- DECIDED --> Decision
  Decision -- DECIDED_IN --> Meeting
  Decision -- ABOUT --> Project
  Decision -- SUPERSEDES --> Decision
  Person -- AUTHORED --> Document
  Document -- ABOUT --> Project
  Document -- REFERENCES --> Decision
  Person -. COLLABORATES_WITH (derived) .-> Person
```

| Label | Properties |
|---|---|
| `Person` | `id`, `name`, `role` |
| `Team` | `id`, `name` |
| `Project` | `id`, `name`, `status`, `summary` |
| `Meeting` | `id`, `title`, `date`, `notes` |
| `Decision` | `id`, `title`, `rationale`, `date`, `status` (`active` / `superseded`) |
| `Document` | `id`, `title`, `kind`, `url`, `summary` |

Every label has a range index on `id`. `COLLABORATES_WITH` is derived from the other
relationships and carries `shared`, the number of projects/meetings/decisions/documents
the two people have in common. All Cypher and graph algorithms the product depends on
are in [QUERIES.md](QUERIES.md).

## Run it locally

Requires Python 3.11+ and a FalkorDB instance (free [FalkorDB Cloud](https://app.falkordb.cloud)
or `docker run -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest`), plus a free
[Gemini API key](https://aistudio.google.com/apikey) (any OpenAI-compatible LLM works).

```bash
git clone https://github.com/aaryn01/teambrain.git && cd teambrain
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in FalkorDB + LLM settings
python seed.py                # loads the demo company (safe to re-run)
uvicorn main:app --reload     # open http://localhost:8000
```

Try the example questions, then open **Update the brain** → **Load sample notes** →
**Extract updates** → **Write to graph**, and ask *"What's the current autopay limit?"* again.
Then open **Key-person risk** and click a person.

Agent from the terminal: `python -m teambrain.agent "Who should I ask about the ledger?"`

Tests (no DB or LLM needed): `pip install pytest && python -m pytest -q`

## Deploy

`render.yaml` deploys the app to Render's free tier: **New → Blueprint**, pick this repo,
and fill in the `FALKORDB_*` and `LLM_API_KEY` secrets. The graph itself lives on FalkorDB Cloud.

## Project layout

```
main.py                 FastAPI app and endpoints
seed.py                 python seed.py  -> rebuild demo graph
teambrain/db.py         FalkorDB connection, read-only query helper
teambrain/tools.py      the agent's Cypher tools
teambrain/risk.py       collaboration projection + betweenness + bus factor
teambrain/agent.py      tool-calling agent with citations
teambrain/ingest.py     meeting notes -> reviewed graph updates
teambrain/seed_data.py  synthetic company data
static/index.html       UI
tests/                  offline tests
```

## Data

All data is **synthetic**. Northwind Pay and everyone in it are fictional.

## AI assistance disclosure

Built with help from Claude (Anthropic) as an AI coding assistant for code generation
and review. I designed the graph model and queries with it, tested every
query against FalkorDB, and can explain each part of the system.
