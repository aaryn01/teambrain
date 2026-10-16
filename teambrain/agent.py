"""The TeamBrain agent: answers questions by calling graph tools, then cites nodes."""
import json
import re

from .db import read
from .llm import chat
from .tools import TOOL_SCHEMAS, TOOLS

MAX_STEPS = 8

SYSTEM_PROMPT = """You are TeamBrain, the company brain of Northwind Pay, a fintech.
You answer questions about people, teams, projects, meetings, decisions and documents
using ONLY data returned by your graph tools. Never use outside knowledge about the company.

Graph schema (FalkorDB, every node has an `id`):
  (:Person {id, name, role})       (:Team {id, name})
  (:Project {id, name, status, summary})
  (:Meeting {id, title, date, notes})
  (:Decision {id, title, rationale, date, status: 'active'|'superseded'})
  (:Document {id, title, kind, url, summary})
  (Person)-[:MEMBER_OF]->(Team)        (Team)-[:OWNS]->(Project)
  (Person)-[:LEADS]->(Project)         (Person)-[:WORKS_ON]->(Project)
  (Person)-[:ATTENDED]->(Meeting)      (Meeting)-[:ABOUT]->(Project)
  (Person)-[:DECIDED]->(Decision)      (Decision)-[:DECIDED_IN]->(Meeting)
  (Decision)-[:ABOUT]->(Project)       (Decision)-[:SUPERSEDES]->(Decision)
  (Person)-[:AUTHORED]->(Document)     (Document)-[:ABOUT]->(Project)
  (Document)-[:REFERENCES]->(Decision)

How to work:
1. Use find_entities to resolve names in the question to ids (unless you already know them).
2. Use the most specific tool (project_overview, decision_trail, person_profile,
   who_knows, connection). Use run_cypher only when none fits.
3. Prefer active decisions; when a decision was superseded, explain what replaced it and why.
4. If the graph has no answer, say so plainly. Do not guess.

Answer format:
- Short and direct; lead with the answer. Use bullet points only for lists.
- Cite every fact with the node id in square brackets right after it, one id per
  bracket, e.g. "The threshold is 0.78 [d-4], decided by Rohan Mehta [p-rohan]."
"""

_ID = r"[a-z]+-[a-z0-9-]+"
_CITATION = re.compile(rf"\[({_ID}(?:\s*,\s*{_ID})*)\]")


def _citation_ids(text: str) -> list[str]:
    ids = []
    for group in _CITATION.findall(text):
        ids += [i.strip() for i in group.split(",")]
    return list(dict.fromkeys(ids))


def _assistant_message(msg) -> dict:
    # model_dump keeps provider extras (e.g. Gemini thought signatures on tool
    # calls) that must be echoed back on the next request.
    out = msg.model_dump(exclude_none=True)
    out["role"] = "assistant"
    out["content"] = msg.content or ""
    return out


def _cited_nodes(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return read(
        """
        MATCH (n) WHERE n.id IN $ids
        RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.title) AS name
        """,
        {"ids": ids},
    )


def ask(question: str, history: list[dict] | None = None) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    trace = []
    for _ in range(MAX_STEPS):
        msg = chat(messages, tools=TOOL_SCHEMAS)
        if not msg.tool_calls:
            answer = (msg.content or "").strip()
            return {"answer": answer, "citations": _cited_nodes(_citation_ids(answer)),
                    "trace": trace}

        messages.append(_assistant_message(msg))
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = TOOLS[name](**args)
                payload = result["rows"]
                trace.append({"tool": name, "args": args,
                              "cypher": result["cypher"], "params": result["params"],
                              "row_count": len(result["rows"])})
            except Exception as exc:  # report the error back to the model
                payload = {"error": str(exc)}
                trace.append({"tool": name, "args": tc.function.arguments, "error": str(exc)})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(payload, default=str)[:12000],
            })

    return {
        "answer": "I couldn't finish answering within the step limit. Try a narrower question.",
        "citations": [],
        "trace": trace,
    }


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "Why is the fraud auto-block threshold 0.78?"
    out = ask(q)
    for step in out["trace"]:
        print(f"> {step['tool']}({step['args']})")
    print()
    print(out["answer"])
    print("\nCited:", [c["id"] for c in out["citations"]])
