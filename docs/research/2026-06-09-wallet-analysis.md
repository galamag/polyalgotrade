# Wallet Behavioral Analysis — Results

**Provenance:** {'winners': 50, 'control': 25} · V1 share = 0.0%

**Realized share (median):** winners = 0.000, control = 1.000

## Archetype counts (winners)
- directional-holder: 40
- unclassified: 7
- longshot-farmer: 3

## Archetype counts (control)
- unclassified: 25

## Winners vs Control Feature Table

| Feature | Winners median | Control median | Control IQR (Q1..Q3) |
|---|---|---|---|
| maker_fill_ratio | 0.9547 | 0.5833 | 0.5370..0.5975 |
| flip_rate | 0.0000 | 0.9318 | 0.8367..0.9788 |
| median_hold_blocks | 0.0000 | 14218.0000 | 12670.5000..21708.5000 |
| entry_price_mean | 0.5135 | 0.4960 | 0.3693..0.5254 |
| roundtrip_return_median | 0.0000 | 0.0000 | 0.0000..0.0000 |
| realized_share | 0.0000 | 1.0000 | 0.9999..1.0000 |
| pnl_proxy | -58723.8960 | -1.2270 | -5.0635..1.2130 |

> **Caveat:** control is V2-geopolitics, single-category, narrow window. Differences on category-sensitive features (entry_price_mean, median_hold_blocks) are NOT trustworthy as evidence of edge. A category-matched control is a recorded escalation (spec §19 S3).

## Recommendation

LEAN READ INCONCLUSIVE. Dominant label 'directional-holder' (40/50) FAILS the gates: §2/B1 control gate (directional discriminator roundtrip_return_median=0 for all holders) and §9/S1 skill cohort (0 qualify; median realized_share 0.00). The label is artifact-laden (recent-trade-window + redemptions absent from /trades) and SURVIVORSHIP-tautological (all-time-PnL frame selects directional bets that WON). -> Do NOT pick a strategy. Escalate to Approach 2 (resolution-grounded P&L) + a non-survivorship sample (rank at entry, not outcome). C1 (copy-trading; hold-to-resolution is highly copyable) and D3 (directional/news) BOTH remain open, pending Approach 2/3.