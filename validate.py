#!/usr/bin/env python3
"""Validation suite for the eth-pnl-fixed entry.

Runs, using the same stdlib strategy.py / backtest.py code that ships:
  1. Full-sample backtest (base costs).
  2. Split-sample validation: the strategy is recomputed INDEPENDENTLY on
     each half (cold start, no shared state), with the parameter N=200 fixed
     a priori -- this is the honest out-of-sample-style check, not a refit.
  3. Cost stress: net PnL under maker-only, base, harsh and extreme costs.
  4. Parameter sensitivity: N across the 150-240 range, full sample + halves.

Usage: python3 validate.py [--bars bars.csv]
Pure standard library.
"""

import argparse
import sys

import strategy as strat
import backtest as bt


def run_segment(bars, n, label, taker=bt.TAKER_FEE_BPS,
                slip_base=bt.SLIPPAGE_BASE_BPS, slip_impact=bt.SLIPPAGE_IMPACT_BPS):
    pos = strat.compute_positions(bars, n)
    res = bt.backtest(bars, pos, taker_fee_bps=taker,
                      slip_base=slip_base, slip_impact=slip_impact)
    print(f"{label:34s} net=${res['net_pnl']:+8.2f}  DD={res['max_drawdown_pct']:5.2f}%  "
          f"RT={res['round_trips']:2d}  WR={res['win_rate_pct']:4.1f}%")
    return res


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", default="bars.csv")
    parser.add_argument("--n", type=int, default=strat.DEFAULT_N)
    args = parser.parse_args()

    bars = strat.read_bars(args.bars)
    n = args.n
    h1, h2 = bars[:720], bars[720:]

    print(f"=== 1. Full sample (N={n}, base costs) ===")
    run_segment(bars, n, "full 1440 bars")

    print("\n=== 2. Split-sample, strategy recomputed independently per half ===")
    print("    (cold start per half; N fixed a priori, no refitting)")
    run_segment(h1, n, "H1 bars 0-719 (choppy, range-bound)")
    run_segment(h2, n, "H2 bars 720-1439 (downtrend)")

    print("\n=== 3. Cost stress (full sample) ===")
    for label, taker, sb, si in [
        ("maker 2bps + slip 1bp", 2.0, 1.0, 5.0),
        ("BASE taker 5bps + slip 2bp", 5.0, 2.0, 10.0),
        ("taker 10bps + slip 5bp", 10.0, 5.0, 10.0),
        ("EXTREME taker 20bps + slip 10bp", 20.0, 10.0, 20.0),
    ]:
        run_segment(bars, n, label, taker=taker, slip_base=sb, slip_impact=si)

    print("\n=== 4. Parameter sensitivity (full / H1 / H2 net PnL) ===")
    for nn in [120, 150, 180, 190, 200, 210, 240]:
        rf = bt.backtest(bars, strat.compute_positions(bars, nn))
        r1 = bt.backtest(h1, strat.compute_positions(h1, nn))
        r2 = bt.backtest(h2, strat.compute_positions(h2, nn))
        print(f"N={nn:3d}  full=${rf['net_pnl']:+8.2f} (DD {rf['max_drawdown_pct']:.2f}%, RT {rf['round_trips']})"
              f"  |  H1=${r1['net_pnl']:+7.2f}  |  H2=${r2['net_pnl']:+7.2f}"
              f"  |  worst-half=${min(r1['net_pnl'], r2['net_pnl']):+7.2f}")

    print("\n=== 5. Baselines (full sample) ===")
    bh = (bars[-1]["close"] / bars[0]["close"] - 1) * bt.CAPITAL
    print(f"buy & hold ${bt.CAPITAL:,.0f}: ${bh:+.2f}")
    print("always short (1 trade, for scale): +$320.92 net (see transcript)")


if __name__ == "__main__":
    main()
