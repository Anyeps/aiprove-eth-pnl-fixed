# Build transcript — eth-pnl-fixed (AIProve)

Builder session: 2026-11-14 ~04:35–04:40 WIB. All steps below were executed
in this session; numbers are from the shipped stdlib code (`strategy.py`,
`backtest.py`, `validate.py`), cross-checked against an independent
pandas/numpy exploration harness.

## 04:35 — Read the spec

- `~/workspace/aiprove/aiprove-repo/challenges/eth-backtest/README.md`:
  1,440 real Binance ETH/USDT 1-minute bars, 24h ending 2026-11-13 12:17 UTC.
  Metric: net PnL after costs (maker + taker fees, slippage scaled by size).
  Sandbox replays with no phantom fills. "Overfitting to this sample is easy;
  a held-out tail punishes it."
- Data profile: ETH $2,028.68 → $1,960.59 (−3.36% over 24h). Buy & hold on
  $10k = −$335.64. Per-bar vol ~10.8 bps std, mean |return| ~7.3 bps.
  Hour-by-hour: H00–H11 choppy/range-bound, H12–H17 steady downtrend
  (−0.27/−0.66/−0.80/−1.60/−0.36/−0.23% per hour), H18–H23 partial recovery.

## 04:35 — Cost model fixed BEFORE any strategy testing

- Capital $10,000, notional $10,000 (1x, no leverage).
- Taker 5 bps per fill (market orders assumed; maker fills cannot be relied
  on under "no phantom fills").
- Slippage 2 bps base + 10 bps × (notional / bar USD volume), capped 12 bps.
- Round trip ≈ 14–15 bps (~$14–15). This is the yardstick every candidate
  had to beat.

## 04:36 — Exploration round 1: standard strategies all lose

Harness sanity first: ALWAYS SHORT = +$320.92 net (1 trade), ALWAYS LONG =
−$350.26 — harness correct, and it sets the scale: the whole day's
downtrend is worth ~$321 net at 1x.

- EMA crossovers 6/24 → 50/200: −$1,299 to −$130 net, win rates 12–21%.
  H1 chop whipsaws them (−$713 to −$939 in H1 alone); H2 trend only partly
  repays it.
- Donchian N=20/40/60/90: −$674 to +$99. Shorter = more whipsaw.
- Momentum (N=15/30/60, thresholds 20/40/80 bps): −$2,601 to −$376.
- Bollinger mean reversion (20/30, 2σ, exit at mid, 2×ATR stop): −$829 /
  −$704, win rate ~54% but avg trade negative — costs eat the small wins.
- Conclusion: at 1-minute scale, costs dominate. Anything trading more than
  ~10×/day bleeds. The strategy must trade rarely and only on big moves.

## 04:36 — Exploration round 2: long-lookback Donchian wins

- Donchian N=150/180/210/240/300/360, exit on opposite breakout:
  +$343 / +$251 / +$322 / +$322 / +$322 / +$322. N≥210 identical — a
  plateau, not a tuned peak.
- ATR trailing-stop exits: ALL negative (−$86 to −$385) — stops exit during
  pullbacks and re-entries pay fees. Rejected.
- EMA crossover + deadband (flat unless |fast−slow| > 30/50 bps): −$304 to
  +$135, worse than plain Donchian. Rejected.
- Trade log (N=240): SHORT at bar 738 ($2,006, 12:18) → LONG at bar 1307
  ($1,948, 21:47). Two trades capture the regime break and the recovery.

## 04:37 — Honest robustness check: cold-start split-sample

Recomputing the strategy independently on each half (cold start, N fixed):

| N | Full | H1 (chop) | H2 (trend) | Worst half |
|---|---|---|---|---|
| 120 | +$36 | −$321 | +$354 | −$321 |
| 150 | +$343 | −$129 | +$267 | −$129 |
| 180 | +$251 | −$60 | +$191 | −$60 |
| 190–210 | +$322 | $0 | −$40 | −$40 |
| 240 | +$322 | $0 | −$136 | −$136 |

Key insight: the full-sample edge depends on the channel having the choppy
first half as its range reference. Cold-started on the trending half alone,
N=240 enters the short far too late (bar 288 of H2, $1,915 — after most of
the fall) and loses −$136. N=190–210 keeps the full-sample result while
cutting the cold-start loss to −$40 — the best worst-case of any lookback.
- Channel-width "squeeze" filter (enter only when width < 60-bar median):
  tested at N=90/120/150/180 — no improvement (N=180 squeeze goes to −$92
  full-sample). Rejected; keep the design minimal.
- Decision: **N=200** — middle of the 190–210 plateau, ~3h20m lookback.
  Chosen for robustness (best worst-half, plateau-insensitive), NOT because
  it maximises the full-sample number (N=150 is $21 higher).

## 04:37 — Cost stress (N=200, full sample)

Maker-only +$338.70 → base +$322.13 → harsh (10 bps taker) +$290.26 →
extreme (20 bps taker + 10 bp slip) +$229.25. Positive under every cost
scenario because only 2 trades are made.

## 04:38 — Final implementation (stdlib only)

- Wrote `strategy.py` (Donchian N=200, deque rolling max/min, no lookahead:
  channel from bars [i−N, i−1], signal at close i, applies from open i+1),
  `backtest.py` (cost model as specified, per-trade log, `results.json`),
  `validate.py` (split-sample + cost stress + N-sensitivity, all from the
  shipped code), `run.sh`, `README.md`, this transcript.
- Copied `bars.csv` into the repo so it is self-contained.
- Verification: stdlib backtest reproduces the pandas exploration exactly —
  net +$322.13, gross +$351.27, costs $29.25, max DD 2.24%, 2 round trips,
  2/2 wins. (One accounting fix during the build: `gross` was initially
  computed with slippage-adjusted entry prices; corrected to mid-to-mid so
  net = gross − fees − slippage reconciles exactly: 351.27 − 20.00 − 9.25 =
  322.13, modulo a cent of rounding.)
- Positions: 738 flat bars, 569 short bars, 133 long bars, 2 position changes.

## 04:38 — Git

- `git init`, identity from `~/workspace/makefun/git-identity.json`
  (Anyeps <coepinks@gmail.com>), committed everything (see commit hash in
  the delivery report).
- NOT submitted to AIProve: no public GitHub repo exists yet for this entry
  (blocked on the GitHub-account decision — see parent agent). Build +
  commit locally only, as instructed.
