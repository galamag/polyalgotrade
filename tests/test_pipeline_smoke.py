"""End-to-end pipeline smoke test — Phase 1 gate.

Proves the fee + analytics pipeline processes >= 1000 synthetic TAKER fills
and produces a correct net-of-fee Result.

NOTE on BacktestBroker and fill types:
  BacktestBroker produces MAKER fills only (resting limit orders that are traded
  through).  Polymarket maker fee = 0 by design, so BacktestBroker fills have
  fee_drag == 0 — using it here would prove nothing about the fee pipeline.

  This smoke generates TAKER fills directly via polymarket_taker_fee() (Category.POLITICS,
  rate 0.04, nonzero at prices near 0.5).  The BacktestBroker's maker model is
  exercised by tests/execution/test_backtest.py.  This test proves the fee + analytics
  pipeline end-to-end.
"""


def test_pipeline_runs_1000_trades_with_fees(tmp_path):  # type: ignore[no-untyped-def]
    from scripts.run_backtest_smoke import run

    r = run(n=1000, journal_dir=tmp_path)
    assert r.n_trades >= 1000
    assert r.fee_drag > 0
    assert r.net_pnl == r.gross_pnl - r.fee_drag
