"""VecParity — live, quality-verified migration between vector databases.

Moves vector data from one vector database to another and proves — with a
retrieval-quality parity report, not just a row count — that the new
database returns the same search results before you cut over.
"""

from vecparity.verify.parity import ParityReport, verify_parity

__version__ = "0.1.0"

__all__ = [
    "ParityReport",
    "verify_parity",
    "__version__",
]
