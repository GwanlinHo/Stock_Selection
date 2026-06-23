"""
價值成長策略回測引擎。

月頻換股、等權重持有、對標 0050，全程使用免費資料且嚴守時點對齊
(point-in-time) 避免前視偏誤：每個換股日只用「該日已公布」的營收與財報。

資料來源 (皆免費)：
  - 價格：yfinance 長歷史，快取於 data/cache_bt/ (與當期選股的 1 年快取分開)。
  - 月營收 / 財報：mopsov 批次端點，全市場單期一次抓取、永久快取。
  - 歷史 PER：以 close / TTM_EPS 計算 (免抓 BWIBBU 歷史)。

已知限制 (報告會明確標註)：
  - 存活者偏誤：標的池採目前清單近似，未還原歷史下市/新上市成分。
  - 不計交易成本與滑價 (可後續加入)。
"""
import time
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.utils.logger import log
from src.value_pipeline import (
    as_of_revenue_period, as_of_financial_period, select_value_growth,
)
from src.data_free import BulkRevenueProvider, BulkFinancialProvider
from src.fundamentals import FundamentalsAssembler

_BT_CACHE = Path("data/cache_bt")


# ---------- 價格歷史 (長期、獨立快取) ----------
def fetch_histories(yf_tickers, years=5, throttle=0.3):
    """抓取並快取長期日線歷史。已快取者跳過。回傳成功檔數。"""
    import yfinance as yf
    _BT_CACHE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, tk in enumerate(yf_tickers):
        path = _BT_CACHE / f"{tk}.parquet"
        if path.exists():
            ok += 1
            continue
        try:
            df = yf.download(tk, period=f"{years}y", interval="1d", progress=False, timeout=15)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.dropna(subset=["Close"]).to_parquet(path)
                ok += 1
        except Exception as e:
            log.warning(f"[Backtest] 下載 {tk} 歷史失敗: {e}")
        time.sleep(throttle)
        if (i + 1) % 50 == 0:
            log.info(f"[Backtest] 歷史下載進度 {i+1}/{len(yf_tickers)}")
    return ok


def load_history(yf_ticker):
    path = _BT_CACHE / f"{yf_ticker}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        return df.sort_index()
    except Exception:
        return None


def _month_ends(start: date, end: date):
    """產生每月最後一個日曆日 (換股日)。"""
    dates = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        nm_y, nm_m = (y + 1, 1) if m == 12 else (y, m + 1)
        last = date(nm_y, nm_m, 1) - timedelta(days=1)
        if start <= last <= end:
            dates.append(last)
        y, m = nm_y, nm_m
    return dates


def _svg_equity(dates, equity, bench_eq, w=860, h=320, pad=50):
    """產生策略 vs 基準的淨值曲線 SVG (無外部套件)。"""
    n = len(equity)
    if n < 2:
        return "<p>資料不足，無法繪圖。</p>"
    lo = min(min(equity), min(bench_eq))
    hi = max(max(equity), max(bench_eq))
    rng = (hi - lo) or 1.0

    def pts(series):
        out = []
        for i, v in enumerate(series):
            x = pad + (w - 2 * pad) * i / (n - 1)
            y = h - pad - (h - 2 * pad) * (v - lo) / rng
            out.append(f"{x:.1f},{y:.1f}")
        return " ".join(out)

    # y 軸基準線 (淨值=1.0)
    y1 = h - pad - (h - 2 * pad) * (1.0 - lo) / rng
    grid = (f'<line x1="{pad}" y1="{y1:.1f}" x2="{w-pad}" y2="{y1:.1f}" '
            f'stroke="#ccc" stroke-dasharray="4"/>'
            f'<text x="{pad-8}" y="{y1+4:.1f}" font-size="11" text-anchor="end" fill="#888">1.0</text>')
    # x 軸首尾日期
    xlabels = (f'<text x="{pad}" y="{h-pad+18}" font-size="11" fill="#888">{dates[0]}</text>'
               f'<text x="{w-pad}" y="{h-pad+18}" font-size="11" text-anchor="end" fill="#888">{dates[-1]}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="max-width:100%;border:1px solid #eee;background:#fff">'
            f'{grid}{xlabels}'
            f'<polyline fill="none" stroke="#1f77b4" stroke-width="2" points="{pts(equity)}"/>'
            f'<polyline fill="none" stroke="#d62728" stroke-width="2" stroke-dasharray="5" points="{pts(bench_eq)}"/>'
            f'<text x="{w-pad-150}" y="{pad}" font-size="12" fill="#1f77b4">— 價值成長策略</text>'
            f'<text x="{w-pad-150}" y="{pad+18}" font-size="12" fill="#d62728">-- 0050 基準</text>'
            f'</svg>')


def generate_backtest_report(res, level, params, period_desc, top_n, report_dir="reports"):
    """產出回測報告 (Markdown + 獨立 HTML，含內嵌 SVG 淨值曲線)。"""
    from datetime import datetime
    rd = Path(report_dir)
    rd.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    m = res["metrics"]
    dates = res["rebal_dates"]
    svg = _svg_equity(dates, res["equity"], res["bench_eq"])

    md = f"# 價值成長策略回測報告 ({today})\n\n"
    md += (f"- 回測期間: {period_desc}　|　換股頻率: 月頻　|　持股: 前 {top_n} 檔等權重\n"
           f"- 篩選標準: 價值成長 / {level}　|　基準: 0050\n\n")
    md += ("> **重要限制**：(1) 存活者偏誤——標的池採目前清單近似，未還原歷史下市/新上市成分，"
           "實際結果可能偏樂觀。(2) 未計交易成本、滑價與稅費。(3) 月營收/財報採公布後時點，"
           "已盡量避免前視偏誤。本報告僅供策略驗證參考，非投資建議。\n\n")

    md += "## 績效摘要\n"
    md += "| 指標 | 價值成長策略 | 0050 基準 |\n| :--- | :--- | :--- |\n"
    md += f"| 總報酬率 | {m.get('total_return')}% | {m.get('bench_total_return')}% |\n"
    md += f"| 年化報酬 (CAGR) | {m.get('cagr')}% | - |\n"
    md += f"| 最大回檔 | {m.get('max_drawdown')}% | - |\n"
    md += f"| Sharpe (年化) | {m.get('sharpe')} | - |\n"
    md += f"| 月勝率 (勝過基準) | {m.get('win_rate_vs_bench')}% | - |\n"
    md += f"| 換股次數 | {m.get('months')} | - |\n\n"

    md += "## 淨值曲線\n\n" + svg + "\n\n"

    md += "## 各期選股與報酬\n"
    md += "| 換股日 | 選股數 | 當期報酬% | 前五持股 |\n| :--- | :--- | :--- | :--- |\n"
    for p in res["picks_log"]:
        md += f"| {p['date']} | {p['n']} | {p['ret']:+.2f} | {', '.join(p['top'])} |\n"

    md_file = rd / f"BACKTEST_REPORT_{today}.md"
    md_file.write_text(md, encoding="utf-8")

    import markdown as _md
    body = _md.markdown(md, extensions=['tables', 'nl2br'])
    html = (f'<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            f'<title>價值成長回測報告</title>'
            f'<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">'
            f'<style>.markdown-body{{max-width:980px;margin:0 auto;padding:45px}}'
            f'table{{border-collapse:collapse}}th,td{{border:1px solid #dfe2e5;padding:6px 13px}}</style>'
            f'</head><body><article class="markdown-body">{body}</article></body></html>')
    html_file = rd / f"backtest_{today}.html"
    html_file.write_text(html, encoding="utf-8")
    log.info(f"[Backtest] 報告已產出: {md_file} / {html_file}")
    return md_file, html_file


class Backtester:
    def __init__(self, vg_config: dict, exclude_industries=None):
        self.vg = vg_config
        self.exclude = set(exclude_industries or [])
        self.ma_slow = vg_config.get("safety_net", {}).get("ma_slow", 60)
        self.rev = BulkRevenueProvider()
        self.fin = FundamentalsAssembler(BulkFinancialProvider())
        self._fund_cache = {}   # (year,season) -> metrics dict
        self._rev_cache = {}    # (year,month) -> revenue map

    def _fund_at(self, d: date):
        key = as_of_financial_period(d)
        if key not in self._fund_cache:
            self._fund_cache[key] = self.fin.metrics_at(*key)
        return self._fund_cache[key]

    def _rev_at(self, d: date):
        key = as_of_revenue_period(d)
        if key not in self._rev_cache:
            self._rev_cache[key] = self.rev.get_month(*key)
        return self._rev_cache[key]

    @staticmethod
    def _price_asof(df, d: date):
        """回傳 <= d 的最後收盤價與該列位置；無資料回 (None,None)。"""
        sub = df[df.index <= pd.Timestamp(d)]
        if sub.empty:
            return None, None
        return float(sub["Close"].iloc[-1]), sub

    def _metrics_at(self, universe, histories, d: date):
        """組裝 universe 在 d 當下的時點指標 (供 select_value_growth)。"""
        fund = self._fund_at(d)
        rev = self._rev_at(d)
        metrics = {}
        for code, info in universe.items():
            if info.get("Industry", "") in self.exclude:
                continue
            df = histories.get(info["yfinance_ticker"])
            if df is None:
                continue
            close, sub = self._price_asof(df, d)
            if close is None or len(sub) < self.ma_slow + 1:
                continue
            ma = float(sub["Close"].rolling(self.ma_slow).mean().iloc[-1])
            avg_vol = float(sub["Volume"].tail(5).mean())
            fm = fund.get(code, {})
            eps_ttm = fm.get("eps_ttm")
            per = round(close / eps_ttm, 2) if eps_ttm and eps_ttm > 0 else None
            metrics[code] = {
                "avg_vol": avg_vol, "per": per, "close": close, "ma_slow": ma,
                "roe": fm.get("roe_ttm"), "eps_growth": fm.get("eps_yoy"),
                "yoy": rev.get(code, {}).get("yoy"),
            }
        return metrics

    def run(self, universe: dict, start: date, end: date, top_n=15, benchmark="0050.TW"):
        """universe: {code: {yfinance_ticker, Name, Industry}}。回傳結果 dict。"""
        histories = {info["yfinance_ticker"]: load_history(info["yfinance_ticker"])
                     for info in universe.values()}
        histories = {k: v for k, v in histories.items() if v is not None}
        bench_df = load_history(benchmark)
        rebal = _month_ends(start, end)
        log.info(f"[Backtest] 換股日 {len(rebal)} 個，標的池 {len(histories)} 檔有歷史。")

        equity, bench_eq = [1.0], [1.0]
        port_rets, bench_rets, picks_log = [], [], []

        for i in range(len(rebal) - 1):
            d0, d1 = rebal[i], rebal[i + 1]
            metrics = self._metrics_at(universe, histories, d0)
            picks = select_value_growth(metrics, self.vg)[:top_n]

            # 投組報酬：等權重，d0->d1 的價格變動
            rets = []
            for p in picks:
                df = histories.get(universe[p["Ticker"]]["yfinance_ticker"])
                c0, _ = self._price_asof(df, d0)
                c1, _ = self._price_asof(df, d1)
                if c0 and c1 and c0 > 0:
                    rets.append(c1 / c0 - 1)
            port_ret = sum(rets) / len(rets) if rets else 0.0

            # 基準報酬
            b0, _ = self._price_asof(bench_df, d0) if bench_df is not None else (None, None)
            b1, _ = self._price_asof(bench_df, d1) if bench_df is not None else (None, None)
            bench_ret = (b1 / b0 - 1) if (b0 and b1 and b0 > 0) else 0.0

            equity.append(equity[-1] * (1 + port_ret))
            bench_eq.append(bench_eq[-1] * (1 + bench_ret))
            port_rets.append(port_ret)
            bench_rets.append(bench_ret)
            picks_log.append({"date": d0.isoformat(), "n": len(picks),
                              "ret": round(port_ret * 100, 2),
                              "top": [p["Ticker"] for p in picks[:5]]})

        return {
            "rebal_dates": [d.isoformat() for d in rebal],
            "equity": equity, "bench_eq": bench_eq,
            "port_rets": port_rets, "bench_rets": bench_rets,
            "picks_log": picks_log,
            "metrics": self._summary(equity, bench_eq, port_rets, bench_rets),
        }

    @staticmethod
    def _summary(equity, bench_eq, port_rets, bench_rets):
        import math
        n = len(port_rets)
        if n == 0:
            return {}
        total = equity[-1] - 1
        years = n / 12
        cagr = (equity[-1] ** (1 / years) - 1) if years > 0 and equity[-1] > 0 else 0
        # 最大回檔
        peak, mdd = equity[0], 0.0
        for v in equity:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        mean = sum(port_rets) / n
        var = sum((r - mean) ** 2 for r in port_rets) / n
        std = math.sqrt(var)
        sharpe = (mean / std * math.sqrt(12)) if std > 0 else 0
        win = sum(1 for p, b in zip(port_rets, bench_rets) if p > b) / n
        return {
            "total_return": round(total * 100, 2),
            "cagr": round(cagr * 100, 2),
            "max_drawdown": round(mdd * 100, 2),
            "sharpe": round(sharpe, 2),
            "win_rate_vs_bench": round(win * 100, 1),
            "bench_total_return": round((bench_eq[-1] - 1) * 100, 2),
            "months": n,
        }
