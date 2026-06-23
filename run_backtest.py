"""
價值成長策略回測執行入口。

用法:
  uv run run_backtest.py                  # 近 3 年、全市場、前 15 檔等權重
  uv run run_backtest.py --no-fetch       # 僅用已快取歷史 (不對 yfinance 下載)
  uv run run_backtest.py --years 5 --top 20

注意: 首次全市場回測需對 yfinance 下載長歷史 (一次性、會落地快取)，
耗時較久且屬對外請求，已加 throttle。之後重跑會直接讀快取。
"""
import json
import argparse
from datetime import date, timedelta

from src.utils.logger import log
from src.tickers import TickerManager
from src.backtest import Backtester, fetch_histories, generate_backtest_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3, help="回測期間年數 (預設 3)")
    ap.add_argument("--hist-years", type=int, default=6, help="下載價格歷史年數 (需 >= years+1)")
    ap.add_argument("--top", type=int, default=15, help="每期持股檔數 (預設 15)")
    ap.add_argument("--benchmark", default="0050.TW")
    ap.add_argument("--no-fetch", action="store_true", help="不下載歷史，僅用既有快取")
    ap.add_argument("--limit", type=int, default=0, help="限制標的池檔數 (測試用，0=全部)")
    args = ap.parse_args()

    cfg = json.load(open("config/settings.json", encoding="utf-8"))
    vg = cfg["value_growth"]
    level = vg.get("active_level", "Standard")
    params = vg["levels"][level]
    exclude = vg.get("exclude_industries", [])

    tickers_info = TickerManager().load_tickers()
    universe = {}
    for t in tickers_info:
        code = str(t["Ticker"]).split(".")[0]
        universe[code] = {
            "yfinance_ticker": t["yfinance_ticker"],
            "Name": t.get("Name", ""), "Industry": t.get("Industry", ""),
        }
    if args.limit:
        universe = dict(list(universe.items())[:args.limit])

    end = date.today()
    start = date(end.year - args.years, end.month, 1)
    period_desc = f"{start.isoformat()} ~ {end.isoformat()}"
    log.info(f"=== 價值成長回測 [{period_desc}] 標的池 {len(universe)} 檔 ===")

    if not args.no_fetch:
        yf = [u["yfinance_ticker"] for u in universe.values()] + [args.benchmark]
        log.info(f"確保價格歷史 (下載未快取者，共 {len(yf)} 檔)...")
        fetch_histories(yf, years=args.hist_years)

    bt = Backtester(params, exclude_industries=exclude)
    res = bt.run(universe, start, end, top_n=args.top, benchmark=args.benchmark)
    m = res["metrics"]
    log.info(f"回測完成: 總報酬 {m.get('total_return')}% | CAGR {m.get('cagr')}% | "
             f"MDD {m.get('max_drawdown')}% | Sharpe {m.get('sharpe')} | "
             f"0050 {m.get('bench_total_return')}%")
    generate_backtest_report(res, level, params, period_desc, args.top)


if __name__ == "__main__":
    main()
