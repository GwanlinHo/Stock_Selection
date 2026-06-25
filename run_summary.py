"""
策略回測總結報告：價值成長 vs 動能(無L3) vs 動能(含L3) vs 0050。

用既有快取重跑三個策略 (純計算、無網路下載)，收集淨值曲線與績效，
產出單一總結報告 (四條淨值疊圖 + 對比表 + 結論)。

用法: uv run run_summary.py [--years 5]
"""
import json
import argparse
from datetime import date, datetime

from src.utils.logger import log
from src.tickers import TickerManager
from src.backtest import Backtester, load_history, fetch_histories
from src.strategies import get_strategy

COLORS = {"value": "#2ca02c", "mom": "#1f77b4", "mom_l3": "#ff7f0e", "bench": "#d62728"}


def _mdd(equity):
    peak, mdd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return round(mdd * 100, 2)


def _svg_multi(dates, series, w=900, h=380, pad=55):
    """series: list of (label, color, equity[])。產出多線淨值 SVG。"""
    n = len(dates)
    allv = [v for _, _, eq in series for v in eq]
    lo, hi = min(allv), max(allv)
    rng = (hi - lo) or 1.0

    def pts(eq):
        return " ".join(
            f"{pad + (w - 2*pad) * i/(n-1):.1f},{h - pad - (h - 2*pad)*(v - lo)/rng:.1f}"
            for i, v in enumerate(eq))

    y1 = h - pad - (h - 2 * pad) * (1.0 - lo) / rng
    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
             f'style="max-width:100%;border:1px solid #eee;background:#fff">']
    parts.append(f'<line x1="{pad}" y1="{y1:.1f}" x2="{w-pad}" y2="{y1:.1f}" stroke="#ccc" stroke-dasharray="4"/>')
    parts.append(f'<text x="{pad-8}" y="{y1+4:.1f}" font-size="11" text-anchor="end" fill="#888">1.0</text>')
    parts.append(f'<text x="{pad}" y="{h-pad+18}" font-size="11" fill="#888">{dates[0]}</text>')
    parts.append(f'<text x="{w-pad}" y="{h-pad+18}" font-size="11" text-anchor="end" fill="#888">{dates[-1]}</text>')
    for k, (label, color, eq) in enumerate(series):
        dash = ' stroke-dasharray="5"' if label.startswith("0050") else ''
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2"{dash} points="{pts(eq)}"/>')
        parts.append(f'<text x="{pad+12}" y="{pad+k*18}" font-size="12" fill="{color}">— {label}</text>')
    parts.append('</svg>')
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--refresh", action="store_true",
                    help="增量更新價格長快取至最新交易日 (月度刷新用)")
    args = ap.parse_args()

    cfg = json.load(open("config/settings.json", encoding="utf-8"))
    vg = cfg["value_growth"]
    exclude = vg.get("exclude_industries", [])
    vg_params = vg["levels"][vg.get("active_level", "Standard")]
    mom_params = cfg["levels"][cfg.get("active_level", "Strict")]

    ti = TickerManager().load_tickers()
    universe = {str(t["Ticker"]).split(".")[0]:
                {"yfinance_ticker": t["yfinance_ticker"], "Name": t.get("Name", ""),
                 "Industry": t.get("Industry", "")} for t in ti}

    if args.refresh:
        log.info("增量刷新價格長快取至最新交易日...")
        yf = [u["yfinance_ticker"] for u in universe.values()] + ["0050.TW"]
        fetch_histories(yf, years=args.years + 1, refresh=True)

    end = date.today()
    start = date(end.year - args.years, end.month, 1)
    period = f"{start.isoformat()} ~ {end.isoformat()}"

    runs = [
        ("價值成長", "value", get_strategy("value_growth"), vg_params, False),
        ("動能(無L3)", "mom", get_strategy("momentum"), mom_params, False),
        ("動能(含L3)", "mom_l3", get_strategy("momentum"), mom_params, True),
    ]
    results = {}
    for label, key, strat, params, chips in runs:
        log.info(f"=== 總結回測: {label} ===")
        bt = Backtester(strat, params, exclude_industries=exclude, use_chips=chips)
        results[key] = bt.run(universe, start, end, top_n=args.top)
        m = results[key]["metrics"]
        log.info(f"  {label}: 總報酬 {m['total_return']}% MDD {m['max_drawdown']}% Sharpe {m['sharpe']}")

    base = results["value"]
    dates = base["rebal_dates"][:len(base["equity"])]
    bench_eq = base["bench_eq"]
    series = [
        ("價值成長", COLORS["value"], results["value"]["equity"]),
        ("動能(無L3)", COLORS["mom"], results["mom"]["equity"]),
        ("動能(含L3)", COLORS["mom_l3"], results["mom_l3"]["equity"]),
        ("0050 基準", COLORS["bench"], bench_eq),
    ]
    svg = _svg_multi(dates, series)
    bench_total = base["metrics"]["bench_total_return"]
    bench_mdd = _mdd(bench_eq)

    today = datetime.now().strftime("%Y-%m-%d")
    md = f"# 攻擊型策略回測總結 ({today})\n\n"
    md += (f"- 回測期間: {period} (含 2022 空頭)　|　月頻換股　|　前 {args.top} 檔等權重　|　基準: 0050\n"
           f"- 全程免費資料、零 FinMind；時點對齊避免前視\n\n")
    md += ("> **限制**: 存活者偏誤 (標的池採目前清單，結果偏樂觀)、未計交易成本與滑價。"
           "僅供策略比較與研究，非投資建議。\n\n")

    md += "## 四方績效對比\n"
    md += "| 指標 | 動能(無L3) | 動能(含L3) | 價值成長 | 0050 |\n| :--- | :--- | :--- | :--- | :--- |\n"
    def col(key, field):
        return results[key]["metrics"][field]
    md += (f"| 總報酬率 | {col('mom','total_return')}% | {col('mom_l3','total_return')}% | "
           f"{col('value','total_return')}% | {bench_total}% |\n")
    md += (f"| 年化 CAGR | {col('mom','cagr')}% | {col('mom_l3','cagr')}% | {col('value','cagr')}% | - |\n")
    md += (f"| 最大回檔 | {col('mom','max_drawdown')}% | {col('mom_l3','max_drawdown')}% | "
           f"{col('value','max_drawdown')}% | {bench_mdd}% |\n")
    md += (f"| Sharpe | {col('mom','sharpe')} | {col('mom_l3','sharpe')} | {col('value','sharpe')} | - |\n")
    md += (f"| 月勝率(勝基準) | {col('mom','win_rate_vs_bench')}% | {col('mom_l3','win_rate_vs_bench')}% | "
           f"{col('value','win_rate_vs_bench')}% | - |\n\n")

    md += "## 淨值曲線疊圖\n\n" + svg + "\n\n"

    md += "## 結論\n"
    md += ("1. **最強為「動能(無L3)」**：報酬與 Sharpe 皆居首，且最接近 0050；但回檔仍比 0050 深。\n"
           "2. **加 L3 法人籌碼反而扣分**：報酬明顯下降、回檔加深——「等法人買超確認」會錯過中小型起漲段。\n"
           "3. **價值成長在此 AI 權值股大多頭中最弱**：低報酬、最深回檔。\n"
           "4. **無一策略穩定勝過 0050**：機械化操作下，最佳者也僅接近大盤、且承擔更深回檔。\n\n"
           "**啟示**：此期間「越精挑(找便宜/等籌碼確認)越錯過行情」，最簡單的趨勢條件最佳。"
           "若續發展攻擊型策略，宜以『動能(無L3)』為基礎，並考慮搭配 investment_analysis 的多空擇時"
           "(僅多頭進場) 與停利停損，而非單獨機械化全程持有。\n")

    from pathlib import Path
    Path("reports").mkdir(exist_ok=True)
    mdf = Path("reports") / f"SUMMARY_REPORT_{today}.md"
    mdf.write_text(md, encoding="utf-8")
    import markdown as _md
    body = _md.markdown(md, extensions=['tables', 'nl2br'])
    html = ('<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            '<title>攻擊型策略回測總結</title>'
            '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">'
            '<style>.markdown-body{max-width:980px;margin:0 auto;padding:45px}'
            'table{border-collapse:collapse}th,td{border:1px solid #dfe2e5;padding:6px 13px}</style>'
            '</head><body><article class="markdown-body">' + body + '</article></body></html>')
    htmlf = Path("reports") / f"summary_{today}.html"
    htmlf.write_text(html, encoding="utf-8")

    # 機器可讀摘要：供每次產生選股報告時嵌入回測績效 (不必重跑)
    summary = {
        "as_of": today, "period": period, "top_n": args.top,
        "benchmark": {"name": "0050", "total_return": bench_total, "max_drawdown": bench_mdd},
        "strategies": {
            "momentum": {"label": "動能(無L3)", **results["mom"]["metrics"]},
            "momentum_l3": {"label": "動能(含L3)", **results["mom_l3"]["metrics"]},
            "value_growth": {"label": "價值成長", **results["value"]["metrics"]},
        },
    }
    Path("data").mkdir(exist_ok=True)
    Path("data/backtest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"總結報告已產出: {mdf} / {htmlf}；摘要: data/backtest_summary.json")


if __name__ == "__main__":
    main()
