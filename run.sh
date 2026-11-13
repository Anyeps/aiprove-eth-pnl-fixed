#!/usr/bin/env bash
# eth-pnl-fixed: run strategy + backtest + validation end to end.
# Pure stdlib Python 3.8+. No third-party dependencies.
set -e
cd "$(dirname "$0")"
python3 strategy.py --bars bars.csv --out positions.csv
python3 backtest.py --bars bars.csv --positions positions.csv --out results.json
echo
python3 validate.py --bars bars.csv
