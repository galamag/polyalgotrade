# tests/scripts/test_run_wallet_analysis.py
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_wallet_analysis",
    Path(__file__).resolve().parents[2] / "scripts" / "run_wallet_analysis.py",
)
assert _SPEC and _SPEC.loader
rwa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rwa)

from pat.analytics.wallet_features import WalletFeatures  # noqa: E402


def _feat(wallet: str, archetype_hint: str) -> WalletFeatures:
    # Minimal feature object; values chosen so the row renders.
    return WalletFeatures(
        wallet=wallet, n_fills=10, n_tokens=40, maker_fill_ratio=0.8, flip_rate=0.9,
        median_hold_blocks=50, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("100"),
        pnl_proxy=Decimal("5"), realized_share=1.0, top1_token_pnl_share=0.2,
        positive_token_fraction=0.6, roundtrip_return_median=Decimal("0.02"),
    )


def test_archetype_counts_tallies_labels() -> None:
    rows = [
        {"archetype": "market-maker"}, {"archetype": "market-maker"},
        {"archetype": "directional-informed"},
    ]
    assert rwa.archetype_counts(rows) == {"market-maker": 2, "directional-informed": 1}


def test_render_report_contains_recommendation_and_counts() -> None:
    winners = [{"wallet": "0xw1", "archetype": "market-maker", "skill": True,
                "copyability": Decimal("0.0"), "features": _feat("0xw1", "mm")}]
    control = [{"wallet": "0xc1", "archetype": "unclassified", "skill": False,
                "copyability": Decimal("0.0"), "features": _feat("0xc1", "u")}]
    md = rwa.render_report(winners, control, v1_share=0.05, provenance={"top_n": 1})
    assert "market-maker" in md
    assert "Recommendation" in md
