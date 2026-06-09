from __future__ import annotations

from pat.analytics.wallet_control import sample_control_wallets


def _ev(maker: str, taker: str) -> dict:
    return {"maker": maker, "taker": taker}


def test_sample_control_picks_median_activity_excludes_given_set() -> None:
    # Wallets with fill counts: A=5, B=4, C=3, D=2, E=1 (as maker). Exclude A (a "winner").
    events: list[dict] = []
    op = "0x" + "00" * 20  # operator/zero-ish counterparty, ignored
    for addr, count in {"0xa": 5, "0xb": 4, "0xc": 3, "0xd": 2, "0xe": 1}.items():
        events += [_ev(addr, op) for _ in range(count)]
    picked = sample_control_wallets(events, n=3, exclude={"0xa"})
    # Median-activity 3 of {B,C,D,E} closest to the median fill count.
    assert "0xa" not in picked
    assert len(picked) == 3
    assert "0xc" in picked  # the median-most wallet is always included
