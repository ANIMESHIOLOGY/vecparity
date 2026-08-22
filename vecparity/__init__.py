"""VecParity: live, quality-verified migration between vector databases."""

from vecparity.verify.parity import ParityReport, verify_parity

__version__ = "0.1.0"

__all__ = [
    "ParityReport",
    "verify_parity",
    "__version__",
]
