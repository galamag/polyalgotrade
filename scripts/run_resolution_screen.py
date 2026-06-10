"""Resolution-grounded concentration screen (ADR 0021 Step 1) over saved wallet trades.

Reads data/raw/wallet_trades/ + data/raw/resolutions.json (both produced by earlier
scripts; fully offline here), computes per-wallet resolution metrics, renders the
winners-vs-control report and the PRE-REGISTERED kill verdict. Money = Decimal.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import structlog  # noqa: E402

from pat.analytics.resolution_pnl import (  # noqa: E402
    WalletResolutionMetrics,
    condition_pnls,
    screen_verdict,
    wallet_metrics,
)

log = structlog.get_logger(__name__)

_TABLE_FEATS = [
    "total_resolution_pnl", "n_conditions_resolved", "n_events_resolved",
    "n_events_positive", "top1_share", "n_frame_incomplete", "n_unresolved",
    "unresolved_exposure",
]


def _median_table(
    winners: list[WalletResolutionMetrics], control: list[WalletResolutionMetrics]
) -> str:
    lines = ["| Metric | Winners median | Control median |", "|---|---|---|"]
    for feat in _TABLE_FEATS:
        wv = [float(getattr(m, feat)) for m in winners]
        cv = [float(getattr(m, feat)) for m in control]
        w_med = f"{statistics.median(wv):.4f}" if wv else "n/a"
        c_med = f"{statistics.median(cv):.4f}" if cv else "n/a"
        lines.append(f"| {feat} | {w_med} | {c_med} |")
    return "\n".join(lines)


def _winners_table(winners: list[WalletResolutionMetrics]) -> str:
    lines = [
        "| Wallet | resolution P&L | events+ | top1 | frame-inc | unresolved | div? |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in sorted(winners, key=lambda m: m.total_resolution_pnl, reverse=True):
        lines.append(
            f"| {m.wallet} | {m.total_resolution_pnl:.2f} | {m.n_events_positive} "
            f"| {m.top1_share:.2f} | {m.n_frame_incomplete} | {m.n_unresolved} "
            f"| {'YES' if m.diversified else 'no'} |"
        )
    return "\n".join(lines)


def render_report(
    winners: list[WalletResolutionMetrics],
    control: list[WalletResolutionMetrics],
) -> str:
    n_div, killed = screen_verdict(winners)
    lines = ["# Resolution-Grounded Concentration Screen — Results", ""]
    lines.append(
        f"**Frame:** {len(winners)} winners / {len(control)} control; gate defined on the "
        "50-winner frame (ADR 0021). Resolution P&L = trades cashflow + redemption at the "
        "actual outcome; RESOLVED markets only (no curPrice in the gate)."
    )
    lines.append("")
    if killed:
        lines.append(
            f"## VERDICT: KILL — n_diversified = {n_div} < 5\n\n"
            "Branch (B) CLOSES per the pre-registered ADR 0021 criterion: no "
            "non-survivorship build; C1 archived via follow-up ADR. Focus -> A2."
        )
    else:
        lines.append(
            f"## VERDICT: PASS — n_diversified = {n_div} >= 5\n\n"
            "The expensive half of branch (B) is justified: build the non-survivorship "
            "sample + persistence test (ADR 0021 Step 3)."
        )
    lines.append("")
    lines.append("## Winners vs Control (medians)")
    lines.append("")
    lines.append(_median_table(winners, control))
    lines.append("")
    lines.append("## Per-winner metrics")
    lines.append("")
    lines.append(_winners_table(winners))
    lines.append("")
    lines.append(
        "> **Caveats (binding):** all-time-PnL survivorship frame (ADR 0020); "
        "recent-2000 trade window -> frame_incomplete/unresolved counters show how much "
        "the window hides. The diversified flag is a screen, not an edge claim."
    )
    return "\n".join(lines)


def run(trades_dir: Path, resolutions_path: Path, out_path: Path) -> Path:
    resolutions: dict[str, dict[str, Any]] = json.loads(
        resolutions_path.read_text(encoding="utf-8")
    )
    winners_addrs: list[str] = json.loads(
        (trades_dir / "_winners.json").read_text(encoding="utf-8")
    )
    control_addrs: list[str] = json.loads(
        (trades_dir / "_control.json").read_text(encoding="utf-8")
    )

    def _metrics(addrs: list[str]) -> list[WalletResolutionMetrics]:
        out: list[WalletResolutionMetrics] = []
        for w in addrs:
            f = trades_dir / f"{w}.json"
            if not f.exists():
                log.warning("wallet.file_missing", wallet=w)
                continue
            trades = json.loads(f.read_text(encoding="utf-8"))
            out.append(wallet_metrics(w, condition_pnls(trades, resolutions)))
        return out

    win, ctrl = _metrics(winners_addrs), _metrics(control_addrs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(win, ctrl), encoding="utf-8")

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    with (logs_dir / "resolution_features.jsonl").open("w", encoding="utf-8") as fh:
        for group, rows in (("winner", win), ("control", ctrl)):
            for m in rows:
                fh.write(
                    json.dumps({**m.model_dump(mode="json"), "group": group}) + "\n"
                )
    n_div, killed = screen_verdict(win)
    log.info("screen.written", out=str(out_path), n_diversified=n_div, killed=killed)
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Resolution-grounded concentration screen (ADR 0021 Step 1)."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument("--resolutions", type=Path, default=Path("data/raw/resolutions.json"))
    p.add_argument(
        "--out", type=Path,
        default=Path("docs/research/2026-06-10-resolution-screen.md"),
    )
    return p.parse_args()


if __name__ == "__main__":
    import logging

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    args = _parse_args()
    print(run(args.trades_dir, args.resolutions, args.out))  # noqa: T201
