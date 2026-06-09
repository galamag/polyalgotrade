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


def _feat(
    wallet: str,
    archetype_hint: str = "mm",
    *,
    maker_fill_ratio: float = 0.8,
    flip_rate: float = 0.9,
    roundtrip_return_median: str = "0.02",
    entry_price_mean: str = "0.5",
    realized_share: float = 1.0,
    pnl_proxy: str = "5",
) -> WalletFeatures:
    # Minimal feature object; values chosen so the row renders.
    return WalletFeatures(
        wallet=wallet, n_fills=10, n_tokens=40,
        maker_fill_ratio=maker_fill_ratio, flip_rate=flip_rate,
        median_hold_blocks=50, entry_price_mean=Decimal(entry_price_mean),
        turnover_usdc=Decimal("100"),
        pnl_proxy=Decimal(pnl_proxy), realized_share=realized_share,
        top1_token_pnl_share=0.2, positive_token_fraction=0.6,
        roundtrip_return_median=Decimal(roundtrip_return_median),
    )


def _row(wallet: str, archetype: str, skill: bool, **feat_kw: object) -> dict:
    return {
        "wallet": wallet, "archetype": archetype, "skill": skill,
        "copyability": Decimal("0.0"),
        "features": _feat(wallet, **feat_kw),  # type: ignore[arg-type]
    }


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


def test_recommend_escalates_when_skill_cohort_too_small() -> None:
    # Only 2 skilled winners -> below the minimum of 5 -> must recommend escalation.
    winners = [_row(f"0xw{i}", "market-maker", skill=True) for i in range(2)]
    winners += [_row(f"0xu{i}", "market-maker", skill=False) for i in range(3)]
    control = [_row(f"0xc{i}", "unclassified", skill=False) for i in range(5)]
    rec = rwa._recommend(winners, control)
    assert "escalate" in rec


def test_recommend_indistinguishable_when_inside_control_iqr() -> None:
    # Build a market-maker winner whose maker_fill_ratio (discriminating feat) falls
    # INSIDE the control IQR -> should produce "indistinguishable" / "structural".
    # Control maker_fill_ratio values: 0.1, 0.2, 0.5, 0.8 -> Q1=0.2, Q3=0.65 (approx)
    # Winner cand_median = 0.4 -> inside IQR -> indistinguishable.
    control = [
        _row(f"0xc{i}", "unclassified", skill=False, maker_fill_ratio=v)
        for i, v in enumerate([0.1, 0.2, 0.5, 0.8])
    ]
    # 5 skilled market-makers each with maker_fill_ratio=0.4 (inside 0.2..0.65)
    winners = [_row(f"0xw{i}", "market-maker", skill=True, maker_fill_ratio=0.4)
               for i in range(5)]
    rec = rwa._recommend(winners, control)
    assert "indistinguishable" in rec or "structural" in rec
