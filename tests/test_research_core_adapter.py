from __future__ import annotations

import research_core
from research_core import best_passages
from research_core.ranking import cosine_similarity

import search
from research_core_adapter import install_research_core_pricing


def test_research_core_dependency_is_v01():
    assert research_core.__version__ == "0.1.0"


def test_pricing_adapter_installs_shared_mechanics():
    install_research_core_pricing()
    assert search.best_passages is best_passages
    assert search.cosine_similarity is cosine_similarity
    assert search.RESEARCH_CORE_VERSION == "0.1.0"
