"""FalkorDB connection and result helpers."""
import os
from functools import lru_cache

from dotenv import load_dotenv
from falkordb import FalkorDB
from falkordb.edge import Edge
from falkordb.node import Node

load_dotenv()

GRAPH_NAME = os.getenv("GRAPH_NAME", "teambrain")

# Every node carries an `id` and one of these labels.
LABELS = ("Person", "Team", "Project", "Meeting", "Decision", "Document")


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    return FalkorDB(
        host=os.getenv("FALKORDB_HOST", "localhost"),
        port=int(os.getenv("FALKORDB_PORT", "6379")),
        username=os.getenv("FALKORDB_USERNAME") or None,
        password=os.getenv("FALKORDB_PASSWORD") or None,
    )


def get_graph(name: str = GRAPH_NAME):
    return get_db().select_graph(name)


def _plain(value):
    """Turn FalkorDB result values into JSON-serialisable Python values."""
    if isinstance(value, Node):
        props = dict(value.properties)
        props["_label"] = value.labels[0] if value.labels else None
        return props
    if isinstance(value, Edge):
        return {"_type": value.relation, **dict(value.properties)}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def to_rows(result) -> list[dict]:
    """QueryResult -> list of {column: value} dicts."""
    columns = [h[1] for h in result.header]
    return [dict(zip(columns, (_plain(v) for v in row))) for row in result.result_set]


def read(query: str, params: dict | None = None, graph=None) -> list[dict]:
    """Run a read-only query. FalkorDB itself rejects any write via GRAPH.RO_QUERY."""
    g = graph or get_graph()
    return to_rows(g.ro_query(query, params or {}))


def write(query: str, params: dict | None = None, graph=None) -> list[dict]:
    g = graph or get_graph()
    return to_rows(g.query(query, params or {}))
