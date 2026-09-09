from __future__ import annotations

from research_core import __version__ as research_core_version, best_passages
from research_core.ranking import cosine_similarity


def install_research_core_pricing() -> None:
    """Adopt low-risk shared research primitives without changing pricing policy."""
    import search

    if getattr(search, "_research_core_v01_installed", False):
        return

    # These are deliberately mechanics-only substitutions. Internet Pricing
    # still owns request planning, pricing strategy, source review, commercial
    # benchmark sufficiency, FX handling, answer QA and citation review.
    search.best_passages = best_passages
    search.cosine_similarity = cosine_similarity
    search.RESEARCH_CORE_VERSION = research_core_version
    search._research_core_v01_installed = True
