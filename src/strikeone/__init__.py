"""Strike One — bring-your-own-scorer fraud evaluation.

The corrected (first-hit) evaluation, blocklist routing, cost-derived
actions, and a citation-validated AI narration layer. The CLI wraps this
same API:

    import strikeone
    df = strikeone.apply_mapping(raw_frame, mapping)   # canonical columns
    result = strikeone.audit(df, label_delay_days=7)
    print(result.to_text())

`__version__` comes from the installed package metadata (single source of
truth: pyproject.toml), so it cannot drift from the PyPI release again.
"""

import importlib.metadata as _im

try:
    __version__ = _im.version("strikeone")
except _im.PackageNotFoundError:  # running from a source tree, uninstalled
    __version__ = "0.0.0+source"
del _im

from strikeone.audit import audit
from strikeone.contract import (
    ContractError,
    Mapping,
    apply_mapping,
    check,
    read_source,
)
from strikeone.policy_engine import policy
from strikeone.route import route

__all__ = [
    "__version__",
    "audit", "route", "policy", "check",
    "Mapping", "apply_mapping", "read_source", "ContractError",
]
