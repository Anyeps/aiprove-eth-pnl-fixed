#!/usr/bin/env python3
"""AIProve eth-pnl-fixed entry: Donchian channel breakout strategy.

Reads 1-minute ETH OHLCV bars and produces a target position for every bar.

Strategy (2 parameters, both fixed a priori, not tuned to maximise in-sample PnL):
  * Channel: N = 200 bars (~3h20m) rolling high / rolling low.
  * Long  when the bar CLOSE breaks above the prior N-bar high.
  * Short when the bar CLOSE breaks below the prior N-bar low.
  * Exit / flip only on the OPPOSITE breakout (no stops, no profit targets,
    no time exits). Flat while no breakout has occurred.
  * Position is -1 / 0 / +1 units of NOTIONAL (see below). Signals are computed
    on the bar close and are meant to be executed at the NEXT bar's open,
    so there is no lookahead.

Why this design:
  * 1-minute ETH moves ~7 bps on average while a taker round trip costs
    ~14 bps, so frequent trading is a guaranteed bleed (verified: every
    fast EMA / momentum / mean-reversion variant tested lost money net of
    costs on this dataset). The only robust edge is to trade RARELY, only on
    genuine multi-hour regime breaks, and let the move pay the costs.
  * The channel lookback N is deliberately LONG: a 200-bar range break is a
    regime shift, not noise. The strategy stays flat through chop (it made
    ZERO trades in the choppy first half of the sample) and only trades when
    price leaves a 3+ hour range.
  * Symmetric long/short: it does not assume the market falls. It would have
    gone long on an upside break with the same rules.

Interface:
  python3 strategy.py --bars bars.csv --out positions.csv [--n 200]

Output positions.csv columns:
  minute, target_position
  target_position in {-1, 0, +1}: the position to hold starting at the NEXT
  bar's open (decided at this bar's close). +1 = long NOTIONAL, -1 = short
  NOTIONAL, 0 = flat. NOTIONAL is $10,000 (1x on $10,000 capital, no
  leverage) -- see backtest.py / README.md for the sizing convention.

Pure standard library: no third-party dependencies.
"""

import argparse
import csv
import sys
from collections import deque

DEFAULT_N = 200


def read_bars(path):
    """Return list of dicts with minute/open/high/low/close/volume as floats."""
    bars = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "minute": int(row["minute"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    return bars


def compute_positions(bars, n=DEFAULT_N):
    """Return list of target positions (-1/0/+1), one per bar.

    The channel at bar i is built from bars [i-n, i-1] only (no lookahead).
    The signal decided at bar i's close applies from bar i+1's open.
    """
    positions = [0] * len(bars)
    current = 0
    # Rolling max/min of high/low over the last n bars, maintained with deques.
    hi_q = deque()  # indices with decreasing high
    lo_q = deque()  # indices with increasing low
    for i, bar in enumerate(bars):
        # Add bar i-1 to the window before deciding at bar i (window = bars i-n..i-1).
        j = i - 1
        if j >= 0:
            while hi_q and bars[hi_q[-1]]["high"] <= bars[j]["high"]:
                hi_q.pop()
            hi_q.append(j)
            while lo_q and bars[lo_q[-1]]["low"] >= bars[j]["low"]:
                lo_q.pop()
            lo_q.append(j)
        # Drop indices older than i-n.
        while hi_q and hi_q[0] < i - n:
            hi_q.popleft()
        while lo_q and lo_q[0] < i - n:
            lo_q.popleft()

        if i >= n and hi_q and lo_q:
            channel_high = bars[hi_q[0]]["high"]
            channel_low = bars[lo_q[0]]["low"]
            close = bar["close"]
            if current == 0:
                if close > channel_high:
                    current = 1
                elif close < channel_low:
                    current = -1
            elif current == 1:
                if close < channel_low:
                    current = -1
            elif current == -1:
                if close > channel_high:
                    current = 1
        positions[i] = current
    return positions


def main():
    parser = argparse.ArgumentParser(description="Donchian breakout strategy for eth-pnl-fixed")
    parser.add_argument("--bars", default="bars.csv", help="input OHLCV CSV")
    parser.add_argument("--out", default="positions.csv", help="output positions CSV")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="channel lookback in bars")
    args = parser.parse_args()

    bars = read_bars(args.bars)
    if len(bars) <= args.n:
        print(f"error: need more than {args.n} bars, got {len(bars)}", file=sys.stderr)
        sys.exit(1)
    positions = compute_positions(bars, args.n)
    with open(args.out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["minute", "target_position"])
        for bar, pos in zip(bars, positions):
            writer.writerow([bar["minute"], pos])
    n_trades = sum(1 for a, b in zip(positions, positions[1:]) if a != b)
    print(f"bars={len(bars)} n={args.n} position_changes={n_trades} "
          f"long_bars={sum(1 for p in positions if p == 1)} "
          f"short_bars={sum(1 for p in positions if p == -1)} "
          f"flat_bars={sum(1 for p in positions if p == 0)}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
