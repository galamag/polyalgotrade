# tests/venues/polymarket/test_leaderboard.py
from __future__ import annotations

from decimal import Decimal

from pat.venues.polymarket.leaderboard import LeaderEntry, parse_leaderboard

# A redacted real-shaped data-api /v1/leaderboard page (I11 sample, 2026-06-09).
_RAW_PAGE = [
    {"rank": "1", "proxyWallet": "0x2CFF41636FE21FAD120FED603D54D4FDD96259DB",
     "userName": "ThisAgain", "vol": 2008.34, "pnl": 441640.87},
    {"rank": "2", "proxyWallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
     "userName": "Theo4", "vol": 0.0, "pnl": 408000.0},
]


def test_parse_leaderboard_extracts_lowercased_addr_and_decimal_pnl() -> None:
    entries = parse_leaderboard(_RAW_PAGE)
    assert entries == [
        LeaderEntry(rank=1, wallet="0x2cff41636fe21fad120fed603d54d4fdd96259db",
                    user_name="ThisAgain", vol=Decimal("2008.34"), pnl=Decimal("441640.87")),
        LeaderEntry(rank=2, wallet="0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                    user_name="Theo4", vol=Decimal("0.0"), pnl=Decimal("408000.0")),
    ]


def test_parse_leaderboard_skips_rows_without_proxywallet() -> None:
    assert parse_leaderboard([{"rank": "9", "userName": "ghost"}]) == []
