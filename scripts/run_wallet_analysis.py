"""Analyze saved per-wallet OrderFilled history -> archetype map + recommendation (spec §H).

AI may run this (keyless): decode V2 logs, pull data-api marks (seam), compute features,
classify, contrast vs control, render the report. Per the measure-first gate, if the fetch
flagged V1 as material, decode_v1_orderfilled (Task 10) must exist and be wired in first.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import httpx  # noqa: E402
import structlog  # noqa: E402

from pat.analytics.wallet_archetype import classify  # noqa: E402
from pat.analytics.wallet_features import (  # noqa: E402
    compute_wallet_features,
    copyability_proxy,
    derive_wallet_fills,
    is_skill_cohort,
)
from pat.data.polymarket_on_chain import decode_v2_orderfilled  # noqa: E402

DATA_API = "https://data-api.polymarket.com"
_REQUEST_TIMEOUT = 30  # seconds
log = structlog.get_logger(__name__)


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
    wallet: str, raw_logs: list[dict[str, Any]], marks: dict[str, Decimal]
) -> dict[str, Any]:
    """Decode -> derive fills -> features -> classify -> screen. Pure given marks."""
    decoded = [d for d in (decode_v2_orderfilled(x) for x in raw_logs) if d is not None]
    fills = derive_wallet_fills(decoded, wallet)
    features = compute_wallet_features(wallet, fills, marks)
    archetype, _conf = classify(features)
    return {
        "wallet": wallet, "archetype": archetype, "skill": is_skill_cohort(features),
        "copyability": copyability_proxy(features), "features": features,
    }


def archetype_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(r["archetype"] for r in rows))


def _recommend(winners: list[dict[str, Any]]) -> str:
    """Apply the pre-registered decision rule (spec §2) to the skill cohort."""
    skilled = [r for r in winners if r["skill"]]
    counts = Counter(r["archetype"] for r in skilled)
    if not skilled:
        return "No skill-cohort winners (P&L luck-dominated) -> structural strategies (A2/D1)."
    top = counts.most_common(1)[0][0]
    copyable = any(r["copyability"] > Decimal("0") for r in skilled if r["archetype"] == top)
    if top == "directional-informed" and not copyable:
        return "Winners are directional-informed but not copyable -> directional/news (D3)."
    if top == "market-maker":
        return "Winners are market-makers -> revisit MM only with an order book (ADR 0014)."
    if copyable:
        return f"Skilled, copyable '{top}' archetype -> C1 copy-trading; next run Approach 3 (sim)."
    return f"Dominant skilled archetype '{top}' is not cheaply copyable -> see §2 / structural."


def render_report(
    winners: list[dict[str, Any]], control: list[dict[str, Any]],
    *, v1_share: float, provenance: dict[str, Any],
) -> str:
    lines = ["# Wallet Behavioral Analysis — Results", ""]
    lines.append(f"**Provenance:** {provenance} · V1 share = {v1_share:.1%}")
    lines.append("")
    lines.append("## Archetype counts (winners)")
    for arch, n in sorted(archetype_counts(winners).items(), key=lambda kv: -kv[1]):
        lines.append(f"- {arch}: {n}")
    lines.append("")
    lines.append("## Archetype counts (control)")
    for arch, n in sorted(archetype_counts(control).items(), key=lambda kv: -kv[1]):
        lines.append(f"- {arch}: {n}")
    lines.append("")
    lines.append(f"## Recommendation\n\n{_recommend(winners)}")
    return "\n".join(lines)


def run(wallets_dir: Path, winners: list[str], control: list[str], out_path: Path,
        *, v1_share: float, get_marks: Any = None) -> Path:
    marks_fn = get_marks or _data_api_marks

    def _rows(addrs: list[str]) -> list[dict[str, Any]]:
        rows = []
        for w in addrs:
            f = wallets_dir / f"{w}.json"
            if not f.exists():
                continue
            raw = json.loads(f.read_text(encoding="utf-8"))
            rows.append(analyze_wallet(w, raw, marks_fn(w)))
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
    p = argparse.ArgumentParser(description="Analyze saved wallet histories -> archetype report.")
    p.add_argument("--wallets-dir", type=Path, default=Path("data/raw/wallets"))
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
    out = run(a.wallets_dir, json.loads(a.winners.read_text()),
              json.loads(a.control.read_text()), a.out, v1_share=a.v1_share)
    print(out)  # noqa: T201
