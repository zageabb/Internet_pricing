from __future__ import annotations

from unittest.mock import patch

import research_core
from research_core import best_passages
from research_core.ranking import cosine_similarity

import browser_fetch
import search
from research_core_adapter import _hv_layered_queries, install_research_core_pricing


def test_research_core_dependency_is_v02():
    assert research_core.__version__ == "0.2.0"


def test_pricing_adapter_installs_shared_mechanics():
    install_research_core_pricing()
    assert search.best_passages is best_passages
    assert search.cosine_similarity is cosine_similarity
    assert search.RESEARCH_CORE_VERSION == "0.2.0"


def test_hv_queries_split_complex_board_into_evidence_layers():
    queries = _hv_layered_queries(
        "Find pricing for 11kV AIS 3200A switchboard, 25kA, 2 incomers 2000A, 8 feeders 630A",
        [],
    )
    joined = "\n".join(queries)
    assert len(queries) >= 6
    assert '"11kV" "2000A" "25kA" incomer' in joined
    assert '"11kV" "630A" "25kA" feeder' in joined
    assert '"11kV" "3200A" busbar' in joined
    assert "TenderKart" in joined
    assert "Volza" in joined
    assert not all("3200A" in query and "2000A" in query and "630A" in query for query in queries)


@patch("research_core_adapter.browser_fetch.public_url", create=True)
def test_placeholder(_unused):
    # Kept intentionally empty; browser behaviour is covered by the existing
    # browser-fallback suite after the adapter is installed by app startup.
    pass
