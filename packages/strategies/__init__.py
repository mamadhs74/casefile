"""Strategy packages: one per content vertical.

Each packages/strategies/<slug>/ owns its own risk-flag vocabulary,
subject-category vocabulary, attribute shape, and eligibility scoring logic,
and registers itself with packages.research.dispatch on import. See
docs/SCHEMA.md's "Strategy" section for why this is code, not database
configuration.
"""

from __future__ import annotations
