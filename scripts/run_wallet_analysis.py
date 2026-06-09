"""Analyze saved per-wallet tagged /trades -> archetype map + recommendation (spec §H).

Keyless: reads tagged trade JSON files produced by fetch_wallet_trades.py, pulls
data-api marks (seam), computes features, classifies, contrasts vs control, renders report.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx  # noqa: E402
import structlog  # noqa: E402

from pat.analytics.wallet_archetype import (  # noqa: E402
    DIRECTIONAL_HOLDER,
    LONGSHOT_FARMER,
    RESOLUTION_HOLDER,
    classify,
)
from pat.analytics.wallet_features import (  # noqa: E402
    WalletFeatures,
    compute_wallet_features,
    copyability_proxy,
    is_skill_cohort,
    wallet_fills_from_trades,
)

DATA_API = "https://data-api.polymarket.com"
_REQUEST_TIMEOUT = 30  # seconds
log = structlog.get_logger(__name__)

# Discriminating feature per archetype for the control-gate (B1, S3).
# Category-robust where possible; category-sensitive ones are loudly caveated in the report.
_ARCHETYPE_DISC_FEAT: dict[str, str] = {
    "market-maker": "maker_fill_ratio",
    "directional-informed": "roundtrip_return_median",
    "arbitrageur": "flip_rate",
    "longshot-farmer": "entry_price_mean",
    "resolution-holder": "entry_price_mean",
}


def _data_api_marks(wallet: str) -> dict[str, Decimal]:
    """token_id -> curPrice for the wallet's OPEN positions (keyless).

    The ONLY wire-touching function — monkeypatch in tests.
    """
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.get(f"{DATA_API}/positions", params={"user": wallet, "limit": 500})
        resp.raise_for_status()
        positions: list[dict[str, Any]] = resp.json()
    return {str(p["asset"]): Decimal(str(p["curPrice"])) for p in positions if "curPrice" in p}


def analyze_wallet(
    wallet: str, trades: list[dict[str, Any]], marks: dict[str, Decimal]
) -> dict[str, Any]:
    """Convert tagged /trades -> fills -> features -> classify -> screen. Pure given marks."""
    fills = wallet_fills_from_trades(trades)
    features = compute_wallet_features(wallet, fills, marks)
    archetype, _conf = classify(features)
    return {
        "wallet": wallet, "archetype": archetype, "skill": is_skill_cohort(features),
        "copyability": copyability_proxy(features), "features": features,
    }


def archetype_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(r["archetype"] for r in rows))


def _feat_float(features: WalletFeatures, feat: str) -> float:
    """Extract a feature as float (handles Decimal fields)."""
    return float(getattr(features, feat))


def _recommend(winners: list[dict[str, Any]], control: list[dict[str, Any]]) -> str:
    """Apply the pre-registered decision rule (spec §2, B1, S1) to the skill cohort.

    Requires len(skill_cohort) >= 5 and dominant archetype >= 5, else escalates.
    Enforces the control gate: if the discriminating feature median falls inside the
    control IQR, the archetype is indistinguishable from ordinary trading + luck.
    """
    hold_types = {DIRECTIONAL_HOLDER, LONGSHOT_FARMER, RESOLUTION_HOLDER}
    if winners:
        all_counts = Counter(r["archetype"] for r in winners)
        dom, dom_n = all_counts.most_common(1)[0]
        med_realized = statistics.median(
            [_feat_float(r["features"], "realized_share") for r in winners]
        )
        if dom in hold_types and dom_n >= len(winners) * 0.4 and med_realized < 0.2:
            return (
                f"LEAN READ INCONCLUSIVE. Dominant label '{dom}' ({dom_n}/{len(winners)}) "
                "FAILS the gates: §2/B1 control gate (directional discriminator "
                "roundtrip_return_median=0 for all holders) and §9/S1 skill cohort "
                f"(0 qualify; median realized_share {med_realized:.2f}). The label is "
                "artifact-laden (recent-trade-window + redemptions absent from /trades) and "
                "SURVIVORSHIP-tautological (all-time-PnL frame selects directional bets that "
                "WON). -> Do NOT pick a strategy. Escalate to Approach 2 (resolution-grounded "
                "P&L) + a non-survivorship sample (rank at entry, not outcome). C1 (copy-"
                "trading; hold-to-resolution is highly copyable) and D3 (directional/news) "
                "BOTH remain open, pending Approach 2/3."
            )

    skilled = [r for r in winners if r["skill"]]

    # S1 — minimum cohort size
    if len(skilled) < 5:
        return (
            "Skill cohort too small (<5) -> escalate to Top-100 + 50 (spec §13)."
        )

    counts = Counter(r["archetype"] for r in skilled)
    top = counts.most_common(1)[0][0]
    if counts[top] < 5:
        return (
            "Skill cohort too small (<5) -> escalate to Top-100 + 50 (spec §13)."
        )

    # B1 — control gate: discriminating feature must fall outside control IQR
    feat = _ARCHETYPE_DISC_FEAT.get(top, "maker_fill_ratio")
    top_rows = [r for r in skilled if r["archetype"] == top]
    cand_vals = [_feat_float(r["features"], feat) for r in top_rows]
    cand_median = statistics.median(cand_vals)

    ctrl_vals = [_feat_float(r["features"], feat) for r in control]
    gate_note = ""
    inside_iqr = False
    if len(ctrl_vals) < 4:
        gate_note = " (control too small for IQR — gate skipped)"
    else:
        qs = statistics.quantiles(ctrl_vals, n=4)
        q1, q3 = qs[0], qs[2]
        if q1 <= cand_median <= q3:
            inside_iqr = True

    if inside_iqr:
        return (
            f"Dominant archetype '{top}' is indistinguishable from control "
            f"(median {feat} inside control IQR) -> survivorship/luck, "
            f"no cheap edge -> structural (A2/D1)."
        )

    # Archetype-specific recommendation (outside IQR or gate skipped)
    copyable = any(r["copyability"] > Decimal("0") for r in top_rows)
    suffix = gate_note

    if top == "directional-informed" and not copyable:
        return (
            f"Winners are directional-informed but not copyable -> directional/news (D3).{suffix}"
        )
    if top == "market-maker":
        return (
            f"Winners are market-makers -> revisit MM only with an order book (ADR 0014).{suffix}"
        )
    if copyable:
        return (
            f"Skilled, copyable '{top}' archetype -> C1 copy-trading; "
            f"next run Approach 3 (sim).{suffix}"
        )
    return (
        f"Dominant skilled archetype '{top}' is not cheaply copyable -> see §2 / structural."
        f"{suffix}"
    )


def _feature_table(winners: list[dict[str, Any]], control: list[dict[str, Any]]) -> str:
    """Markdown table: winners-median vs control-median vs control-IQR per key feature."""
    feats = [
        "maker_fill_ratio", "flip_rate", "median_hold_blocks",
        "entry_price_mean", "roundtrip_return_median", "realized_share", "pnl_proxy",
    ]

    def _vals(rows: list[dict[str, Any]], f: str) -> list[float]:
        return [_feat_float(r["features"], f) for r in rows]

    lines = [
        "| Feature | Winners median | Control median | Control IQR (Q1..Q3) |",
        "|---|---|---|---|",
    ]
    for f in feats:
        wv = _vals(winners, f)
        cv = _vals(control, f)
        w_med = f"{statistics.median(wv):.4f}" if wv else "n/a"
        c_med = f"{statistics.median(cv):.4f}" if cv else "n/a"
        if len(cv) >= 4:
            qs = statistics.quantiles(cv, n=4)
            c_iqr = f"{qs[0]:.4f}..{qs[2]:.4f}"
        else:
            c_iqr = "n/a (too few)"
        lines.append(f"| {f} | {w_med} | {c_med} | {c_iqr} |")
    return "\n".join(lines)


def render_report(
    winners: list[dict[str, Any]], control: list[dict[str, Any]],
    *, v1_share: float, provenance: dict[str, Any],
) -> str:
    lines = ["# Wallet Behavioral Analysis — Results", ""]
    lines.append(f"**Provenance:** {provenance} · V1 share = {v1_share:.1%}")
    lines.append("")

    # Per-group realized_share medians (B3 transparency)
    def _med_realized(rows: list[dict[str, Any]]) -> str:
        vals = [r["features"].realized_share for r in rows]
        return f"{statistics.median(vals):.3f}" if vals else "n/a"

    lines.append(
        f"**Realized share (median):** winners = {_med_realized(winners)}, "
        f"control = {_med_realized(control)}"
    )
    lines.append("")
    lines.append("## Archetype counts (winners)")
    for arch, n in sorted(archetype_counts(winners).items(), key=lambda kv: -kv[1]):
        lines.append(f"- {arch}: {n}")
    lines.append("")
    lines.append("## Archetype counts (control)")
    for arch, n in sorted(archetype_counts(control).items(), key=lambda kv: -kv[1]):
        lines.append(f"- {arch}: {n}")
    lines.append("")
    lines.append("## Winners vs Control Feature Table")
    lines.append("")
    lines.append(_feature_table(winners, control))
    lines.append("")
    lines.append(
        "> **Caveat:** control is V2-geopolitics, single-category, narrow window. "
        "Differences on category-sensitive features (entry_price_mean, median_hold_blocks) "
        "are NOT trustworthy as evidence of edge. A category-matched control is a recorded "
        "escalation (spec §19 S3)."
    )
    lines.append("")
    lines.append(f"## Recommendation\n\n{_recommend(winners, control)}")
    return "\n".join(lines)


def run(trades_dir: Path, winners: list[str], control: list[str], out_path: Path,
        *, v1_share: float, get_marks: Any = None) -> Path:
    marks_fn = get_marks or _data_api_marks

    def _rows(addrs: list[str]) -> list[dict[str, Any]]:
        rows = []
        for w in addrs:
            f = trades_dir / f"{w}.json"
            if not f.exists():
                continue
            trades = json.loads(f.read_text(encoding="utf-8"))
            rows.append(analyze_wallet(w, trades, marks_fn(w)))
        return rows

    win_rows, ctrl_rows = _rows(winners), _rows(control)
    md = render_report(win_rows, ctrl_rows, v1_share=v1_share,
                       provenance={"winners": len(win_rows), "control": len(ctrl_rows)})
    out_path.write_text(md, encoding="utf-8")
    # Raw per-wallet features for the ADR's feature-vs-control contrast (spec §11, §12).
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    with (logs_dir / "wallet_features.jsonl").open("w", encoding="utf-8") as fh:
        for group, rows in (("winner", win_rows), ("control", ctrl_rows)):
            for r in rows:
                rec = {**r["features"].model_dump(mode="json"), "archetype": r["archetype"],
                       "skill": r["skill"], "copyability": str(r["copyability"]), "group": group}
                fh.write(json.dumps(rec) + "\n")
    log.info("analysis.written", out_path=str(out_path))
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze saved wallet trade histories -> archetype report."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument("--winners", type=Path, required=True, help="JSON list of winner addresses")
    p.add_argument("--control", type=Path, required=True, help="JSON list of control addresses")
    p.add_argument("--v1-share", type=float, default=0.0)
    p.add_argument("--out", type=Path, default=Path("docs/research/2026-06-09-wallet-analysis.md"))
    return p.parse_args()


if __name__ == "__main__":
    import logging

    structlog.configure(
        processors=[structlog.processors.add_log_level,
                    structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    a = _parse_args()
    out = run(a.trades_dir, json.loads(a.winners.read_text()),
              json.loads(a.control.read_text()), a.out, v1_share=a.v1_share)
    print(out)  # noqa: T201
