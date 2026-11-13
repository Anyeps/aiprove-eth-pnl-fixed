#!/usr/bin/env python3
"""Backtest for the eth-pnl-fixed Donchian strategy.

Replays positions.csv against bars.csv with realistic costs and NO phantom
fills: a position change decided at bar i's close is executed at bar i+1's
OPEN (never at the signal bar's close). Any open position is closed at the
final bar's close.

Cost model (stated explicitly; deliberately conservative):
  * CAPITAL   = $10,000. NOTIONAL = $10,000 per position (1x, no leverage).
  * TAKER_FEE = 5 bps (0.05%) per fill, charged on every entry and exit.
    (We assume market orders: the sandbox states it replays with no phantom
    fills, so resting limit/maker fills cannot be relied on.)
  * SLIPPAGE  = 2 bps base + 10 bps * (NOTIONAL / bar USD volume), capped at
    12 bps per fill. Slippage scales with size relative to that bar's
    liquidity, as the challenge specifies. At the sample's average bar volume
    (~$566k) a $10k order slips ~2.2 bps.
  * Round-trip cost is therefore ~14-15 bps (~$14-15 per trade on $10k).
  * No funding, no borrow cost, no interest (1x, short holds are intraday).

Metrics reported: net PnL (after all costs), gross PnL, total costs, max
drawdown (peak-to-trough on marked-to-market equity), number of round trips,
win rate, average trade, and a per-trade log. Results are written to
results.json.

Usage:
  python3 backtest.py --bars bars.csv --positions positions.csv [--out results.json]
  python3 backtest.py --help   (fee/slippage overrides for stress tests)

Pure standard library.
"""

import argparse
import csv
import json
import sys

CAPITAL = 10_000.0
NOTIONAL = 10_000.0
TAKER_FEE_BPS = 5.0
SLIPPAGE_BASE_BPS = 2.0
SLIPPAGE_IMPACT_BPS = 10.0
SLIPPAGE_CAP_BPS = 12.0


def read_bars(path):
    bars = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            bars.append({
                "minute": int(row["minute"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    return bars


def read_positions(path):
    positions = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            positions.append(int(row["target_position"]))
    return positions


def slippage_bps(bar_volume_usd, notional=NOTIONAL,
                 base=SLIPPAGE_BASE_BPS, impact=SLIPPAGE_IMPACT_BPS,
                 cap=SLIPPAGE_CAP_BPS):
    if bar_volume_usd <= 0:
        return cap
    return min(base + impact * (notional / bar_volume_usd), cap)


def backtest(bars, positions, capital=CAPITAL, notional=NOTIONAL,
             taker_fee_bps=TAKER_FEE_BPS, slip_base=SLIPPAGE_BASE_BPS,
             slip_impact=SLIPPAGE_IMPACT_BPS, slip_cap=SLIPPAGE_CAP_BPS):
    n = len(bars)
    if len(positions) != n:
        raise ValueError(f"positions ({len(positions)}) != bars ({n})")
    pos = 0            # current signed position in units of notional
    entry_px = None    # fill price of the current position (net of slippage)
    entry_mid = None   # mid price (raw open) at entry, for gross accounting
    realised = 0.0     # realised PnL net of fees
    gross = 0.0        # realised PnL before fees/slippage
    fees = 0.0
    slip_cost = 0.0
    peak = capital
    max_dd = 0.0
    trades = []        # closed round trips
    wins = 0

    def equity_at(i):
        # Mark-to-market equity after bar i's close.
        eq = capital + realised
        if pos != 0:
            eq += pos * notional * (bars[i]["close"] - entry_px) / entry_px
        return eq

    for i in range(n - 1):
        target = positions[i]
        if target != pos:
            bar = bars[i + 1]
            px = bar["open"]
            slip = slippage_bps(bar["volume"] * px, notional, slip_base,
                                slip_impact, slip_cap)
            if pos != 0:
                # Close the existing position at next open, paying slippage.
                fill = px - (1 if pos > 0 else -1) * px * slip / 1e4
                pnl_gross = pos * notional * (fill - entry_px) / entry_px
                fee = notional * taker_fee_bps / 1e4
                pnl = pnl_gross - fee
                # Slippage cost embedded in pnl_gross vs mid:
                slip_c = abs(pos) * notional * (px * slip / 1e4) / px
                gross += pos * notional * (px - entry_mid) / entry_mid
                fees += fee
                slip_cost += slip_c
                realised += pnl
                trades.append({
                    "direction": pos, "entry_px": entry_px,
                    "exit_px": fill, "exit_bar": i + 1, "pnl": pnl,
                })
                if pnl > 0:
                    wins += 1
            if target != 0:
                # Open the new position at next open, paying slippage + fee.
                fill = px + (1 if target > 0 else -1) * px * slip / 1e4
                entry_px = fill
                entry_mid = px
                fees += notional * taker_fee_bps / 1e4
                slip_cost += notional * (px * slip / 1e4) / px
                realised -= notional * taker_fee_bps / 1e4
            pos = target
        eq = equity_at(i + 1)
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak)

    # Close any open position at the final close.
    if pos != 0:
        bar = bars[-1]
        px = bar["close"]
        slip = slippage_bps(bar["volume"] * px, notional, slip_base,
                            slip_impact, slip_cap)
        fill = px - (1 if pos > 0 else -1) * px * slip / 1e4
        pnl_gross = pos * notional * (fill - entry_px) / entry_px
        fee = notional * taker_fee_bps / 1e4
        pnl = pnl_gross - fee
        slip_c = abs(pos) * notional * (px * slip / 1e4) / px
        gross += pos * notional * (px - entry_mid) / entry_mid
        fees += fee
        slip_cost += slip_c
        realised += pnl
        trades.append({
            "direction": pos, "entry_px": entry_px,
            "exit_px": fill, "exit_bar": n - 1, "pnl": pnl,
        })
        if pnl > 0:
            wins += 1

    net = realised
    n_rt = len(trades)
    return {
        "capital": capital,
        "notional": notional,
        "taker_fee_bps": taker_fee_bps,
        "slippage_base_bps": slip_base,
        "slippage_impact_bps": slip_impact,
        "slippage_cap_bps": slip_cap,
        "bars": n,
        "net_pnl": round(net, 2),
        "gross_pnl": round(gross, 2),
        "total_fees": round(fees, 2),
        "total_slippage_cost": round(slip_cost, 2),
        "total_costs": round(fees + slip_cost, 2),
        "net_pnl_pct": round(net / capital * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "round_trips": n_rt,
        "wins": wins,
        "losses": n_rt - wins,
        "win_rate_pct": round(100.0 * wins / n_rt, 1) if n_rt else 0.0,
        "avg_trade": round(net / n_rt, 2) if n_rt else 0.0,
        "final_equity": round(capital + net, 2),
        "trades": [{**t, "pnl": round(t["pnl"], 2),
                    "entry_px": round(t["entry_px"], 2),
                    "exit_px": round(t["exit_px"], 2)} for t in trades],
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest for eth-pnl-fixed")
    parser.add_argument("--bars", default="bars.csv")
    parser.add_argument("--positions", default="positions.csv")
    parser.add_argument("--out", default="results.json")
    parser.add_argument("--taker-fee-bps", type=float, default=TAKER_FEE_BPS)
    parser.add_argument("--slip-base-bps", type=float, default=SLIPPAGE_BASE_BPS)
    parser.add_argument("--slip-impact-bps", type=float, default=SLIPPAGE_IMPACT_BPS)
    args = parser.parse_args()

    bars = read_bars(args.bars)
    positions = read_positions(args.positions)
    try:
        res = backtest(bars, positions, taker_fee_bps=args.taker_fee_bps,
                       slip_base=args.slip_base_bps,
                       slip_impact=args.slip_impact_bps)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"net PnL      : ${res['net_pnl']:+.2f} ({res['net_pnl_pct']:+.2f}% on ${res['capital']:,.0f})")
    print(f"gross PnL    : ${res['gross_pnl']:+.2f}")
    print(f"total costs  : ${res['total_costs']:.2f} (fees ${res['total_fees']:.2f} + slippage ${res['total_slippage_cost']:.2f})")
    print(f"max drawdown : {res['max_drawdown_pct']:.2f}%")
    print(f"round trips  : {res['round_trips']}  (wins {res['wins']}, losses {res['losses']}, win rate {res['win_rate_pct']}%)")
    print(f"avg trade    : ${res['avg_trade']:+.2f}")
    print(f"final equity : ${res['final_equity']:.2f}")
    for t in res["trades"]:
        d = "LONG " if t["direction"] > 0 else "SHORT"
        print(f"  {d} entry ${t['entry_px']:.2f} -> exit ${t['exit_px']:.2f} (bar {t['exit_bar']}): PnL ${t['pnl']:+.2f}")
    with open(args.out, "w") as f:
        json.dump(res, f, indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
