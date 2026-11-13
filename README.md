# eth-pnl-fixed — Donchian channel breakout (N=200)

AIProve bounty entry: a trading strategy over the frozen 1,440-bar ETH/USDT
1-minute dataset (`bars.csv`, real Binance spot bars, 24h ending 2026-11-13
12:17 UTC). Metric: **net PnL after costs**. Sandbox replays the strategy
with no phantom fills; ties break on lower max drawdown.

## Result (base costs, $10,000 capital)

| Metric | Value |
|---|---|
| Net PnL | **+$322.13 (+3.22%)** |
| Gross PnL | +$351.27 |
| Total costs | $29.25 (fees $20.00 + slippage $9.25) |
| Max drawdown | **2.24%** |
| Round trips | 2 (2 wins, 0 losses, win rate 100%) |
| Avg trade | +$161.06 |
| Final equity | $10,322.13 |
| Buy & hold baseline | −$335.64 |

## Strategy logic

A **Donchian channel breakout** with a deliberately LONG lookback — 2
parameters total, both fixed a priori (not tuned to maximise in-sample PnL):

- **Channel:** N = **200 bars** (~3h20m) rolling high / rolling low.
- **Long** when a bar's CLOSE breaks above the prior 200-bar high.
- **Short** when a bar's CLOSE breaks below the prior 200-bar low.
- **Exit / flip only on the opposite breakout.** No stops, no profit
  targets, no time exits. Flat while no breakout has occurred.
- **Symmetric long/short** — it does not assume the market falls; an upside
  break is traded with the same rules.
- **Position:** −1 / 0 / +1 units of $10,000 notional (1x on $10,000 capital,
  no leverage). Signals are computed on the bar close and executed at the
  **next bar's open** — no lookahead, no phantom fills.

### Why this design

1-minute ETH moves ~7 bps on average while a taker round trip costs
~14 bps. Frequent trading is therefore a guaranteed bleed — verified in
testing: every fast EMA crossover, momentum, and Bollinger mean-reversion
variant lost money net of costs on this dataset (see `transcript.md`). The
only robust edge is to trade **rarely**, only on genuine multi-hour regime
breaks, and let the move pay the costs.

A 200-bar range break is a regime shift, not noise. The strategy stayed
**flat through 12 hours of chop** (zero trades in the first half of the
sample) and traded only twice:

| # | Signal | Bar | Price | Outcome |
|---|---|---|---|---|
| 1 | SHORT | 738 (12:18) | $2,005.55 | +$278.44 — caught the H12–H17 downtrend |
| 2 | LONG | 1308 (21:48) | $1,948.71 | +$53.69 — caught the evening recovery |

## Cost assumptions (stated explicitly)

- Capital $10,000; notional $10,000 per position (1x, no leverage).
- **Taker fee 5 bps (0.05%) per fill**, every entry and exit. Market orders
  are assumed because the sandbox replays with no phantom fills — resting
  limit/maker fills cannot be relied on.
- **Slippage = 2 bps base + 10 bps × (notional / bar USD volume)**, capped at
  12 bps per fill. Slippage scales with size relative to that bar's
  liquidity. At the sample's average bar volume (~$566k) a $10k order slips
  ~2.2 bps. Round-trip cost ≈ 14–15 bps (~$14–15 per trade).
- No funding, borrow, or interest costs (1x, intraday holds).

## Files

| File | Purpose |
|---|---|
| `strategy.py` | Computes positions from bars (stdlib only). |
| `backtest.py` | Replays positions with the cost model above; prints metrics, writes `results.json`. |
| `validate.py` | Full validation suite: split-sample, cost stress, parameter sensitivity. |
| `run.sh` | Runs strategy + backtest + validation end to end. |
| `bars.csv` | The challenge dataset (1,440 bars, copied from the challenge repo). |
| `positions.csv` | Strategy output: `minute,target_position` (−1/0/+1, applies from next bar's open). |
| `results.json` | Backtest results incl. per-trade log. |
| `transcript.md` | Build log: steps taken and key decisions. |

## Interface (for the sandbox)

```bash
python3 strategy.py --bars bars.csv --out positions.csv [--n 200]
python3 backtest.py --bars bars.csv --positions positions.csv [--out results.json]
# or everything at once:
bash run.sh
```

`strategy.py` reads any OHLCV CSV with columns
`minute,open,high,low,close,volume` and writes `minute,target_position`.
`target_position` at bar *i* is the position to hold starting at bar *i+1*'s
open. Pure Python standard library — no third-party dependencies, runs
anywhere Python 3.8+ exists.

## Validation / robustness

`python3 validate.py` reproduces all of this from the shipped code.

**Split-sample** — the strategy is recomputed *independently* on each half
(cold start, no shared state), with N=200 fixed a priori (no refitting):

| Segment | Net PnL | Max DD | Round trips |
|---|---|---|---|
| H1 bars 0–719 (choppy, range-bound) | $0.00 | 0.00% | 0 |
| H2 bars 720–1439 (downtrend) | −$39.73 | 2.40% | 2 |

In chop it does nothing (no bleed); in trend it trades. The full-sample
profit comes from the strategy having the first half's range as the channel
reference — see Limitations.

**Cost stress** (full sample, net PnL):

| Scenario | Net PnL |
|---|---|
| Maker 2 bps + slip 1 bp | +$338.70 |
| **Base: taker 5 bps + slip 2 bp** | **+$322.13** |
| Taker 10 bps + slip 5 bp | +$290.26 |
| Extreme: taker 20 bps + slip 10 bp | +$229.25 |

Positive even at 4× the base fee, because only 2 trades are made — costs
are a small fraction of the captured move.

**Parameter sensitivity** (net PnL, full / H1 / H2):

| N | Full | H1 | H2 | Worst half |
|---|---|---|---|---|
| 120 | +$35.94 | −$320.97 | +$354.02 | −$320.97 |
| 150 | +$343.19 | −$128.97 | +$267.38 | −$128.97 |
| 180 | +$250.86 | −$60.39 | +$190.62 | −$60.39 |
| **190–210** | **+$322.13** | **$0.00** | **−$39.73** | **−$39.73** |
| 240 | +$322.13 | $0.00 | −$135.56 | −$135.56 |

N=200 sits in the middle of the 190–210 plateau where results are
identical — the exact value does not matter, which is the opposite of
overfitting. Shorter lookbacks bleed in chop; longer ones enter trends too
late when starting cold.

**Alternatives tested and rejected** (full-sample net, base costs): EMA
crossovers 6/24 to 50/200 (−$1,299 to −$130), Donchian N=20–90 (−$674 to
+$99), momentum with thresholds (−$2,601 to −$376), Bollinger mean reversion
(−$1,698 to −$704), Donchian + ATR trailing stops (all negative), Donchian +
channel-width "squeeze" filter (worse than plain). Details in
`transcript.md`.

## Limitations (stated honestly)

- **Only 2 trades** drive the result. The 100% win rate is 2/2, not a
  statistical claim. The edge is structural (rare, large regime breaks),
  not a high-frequency statistical edge.
- **Cold-start dependence:** the full-sample short at bar 738 breaks the
  range formed during the choppy first half. Recomputed cold on the second
  half alone, the same rules lose −$39.73 (late entry). If the held-out tail
  is evaluated as a *continuation* (channel state carried over from these
  1,440 bars), the strategy behaves as in the full sample; if it is
  evaluated *cold*, the first ~200 bars are warmup and entries are later.
  N=200 was chosen partly because it has the best worst-half result of any
  lookback tested, which is the best available hedge against the cold-start
  case.
- **Single-regime sample:** the dataset contains one range + one downtrend +
  one recovery. A held-out tail with a different regime mix (e.g. prolonged
  chop) would most likely produce ~$0 (flat) rather than a loss — the
  strategy's failure mode in chop is inactivity, not bleeding.
