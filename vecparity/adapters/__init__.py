"""Backend adapters: thin read/write/list-changed-since wrappers per vector DB.

VecParity deliberately does NOT ship a permanent query-language abstraction
(that's how projects like this end up leaky; see LangChain's vectorstore
interface). Adapters only need to support migration-time operations: get,
upsert, delete, list_changed_since, and search (for parity verification).
"""

from vecparity.adapters.base import VectorDBAdapter

__all__ = ["VectorDBAdapter"]
