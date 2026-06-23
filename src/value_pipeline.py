"""
價值成長選股管線。

組裝免費資料 → 餵入 ValueGrowthFilter → 產出排序後的精選清單。
選股核心函式 select_value_growth() 為純函式，當期選股與回測共用。

全程零 FinMind：價量(yfinance)、PER(TWSE/TPEx)、月營收與財報(mopsov) 皆免費。
"""
from datetime import date

from src.utils.logger import log
from src.filters.value_growth import ValueGrowthFilter


# ---------- 時點期別 (避免回測前視偏誤) ----------
def as_of_revenue_period(d: date):
    """指定日期當下「已公布」的最新月營收期別 -> (roc_year, month)。
    月營收約每月 10 號公布上月，保守用 12 號為界。"""
    y, m = d.year, d.month
    back = 1 if d.day >= 12 else 2     # 未過 12 號則退到上上月
    for _ in range(back):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return y - 1911, m


def as_of_financial_period(d: date):
    """指定日期當下「已公布」的最新財報季別 -> (roc_year, season)。
    Q1~5/15、Q2~8/14、Q3~11/14、年報(Q4)~隔年 3/31。"""
    pubs = []
    for yr in (d.year - 1, d.year):
        pubs.append((date(yr, 3, 31), (yr - 1, 4)))
        pubs.append((date(yr, 5, 15), (yr, 1)))
        pubs.append((date(yr, 8, 14), (yr, 2)))
        pubs.append((date(yr, 11, 14), (yr, 3)))
    avail = [(pub, per) for pub, per in pubs if pub <= d]
    pub, (ad_year, season) = max(avail, key=lambda x: x[0])
    return ad_year - 1911, season


# ---------- 純選股 (當期與回測共用) ----------
def select_value_growth(metrics: dict, vg_config: dict):
    """對 {ticker: {avg_vol, per, close, ma_slow, roe, yoy, eps_growth}} 篩選。

    回傳通過清單 (dict)，已依 Score 由高到低排序。
    """
    vf = ValueGrowthFilter(vg_config)
    passed = []
    for tk, m in metrics.items():
        ok, _reason = vf.prescreen(
            avg_vol=m.get("avg_vol"), per=m.get("per"),
            close=m.get("close"), ma_slow=m.get("ma_slow"),
        )
        if not ok:
            continue
        final_ok, ev = vf.evaluate(
            per=m.get("per"), roe=m.get("roe"),
            yoy=m.get("yoy"), eps_growth=m.get("eps_growth"),
        )
        if not final_ok:
            continue
        passed.append({
            "Ticker": tk,
            "Close": m.get("close"),
            "PER": m.get("per"),
            "PEG": ev["PEG"],
            "ROE": m.get("roe"),
            "YoY": m.get("yoy"),
            "EPS_Growth": m.get("eps_growth"),
            "Score": ev["Score"],
        })
    passed.sort(key=lambda x: x["Score"], reverse=True)
    return passed


# ---------- 當期選股：組裝即時免費資料 ----------
def run_current_selection(tickers_info: list, vg_config: dict, as_of: date = None,
                          exclude_industries=None):
    """跑當期價值成長選股，回傳排序後的精選清單。"""
    exclude_industries = set(exclude_industries or [])
    from src.data_ingestion import DataIngestion
    from src.data_bulk import BulkChipProvider
    from src.data_free import BulkRevenueProvider, BulkFinancialProvider
    from src.fundamentals import FundamentalsAssembler

    as_of = as_of or date.today()
    ma_slow = vg_config.get("safety_net", {}).get("ma_slow", 60)

    # 1. 價量 (yfinance, 免費, 快取)
    yf_tickers = [t["yfinance_ticker"] for t in tickers_info]
    raw = DataIngestion(batch_size=50).fetch_weekly_data(yf_tickers)

    # 2. PER (TWSE/TPEx, 免費)；days=1 僅取最新一日，最省
    chip = BulkChipProvider(days=1)
    chip.build()

    # 3. 月營收 YoY (mopsov, 免費)
    rev_y, rev_m = as_of_revenue_period(as_of)
    rev_map = BulkRevenueProvider().get_month(rev_y, rev_m)

    # 4. 財報指標 ROE/EPS成長 (mopsov, 免費)
    fin_y, fin_s = as_of_financial_period(as_of)
    fund_map = FundamentalsAssembler(BulkFinancialProvider()).metrics_at(fin_y, fin_s)

    log.info(f"[ValueGrowth] 期別 - 月營收 {rev_y}/{rev_m}、財報 {fin_y} Q{fin_s}")

    # 5. 組裝每檔指標
    metrics = {}
    for t in tickers_info:
        if t.get("Industry", "") in exclude_industries:
            continue
        yf = t["yfinance_ticker"]
        code = str(t["Ticker"]).split(".")[0]
        df = raw.get(yf)
        if df is None or len(df) < ma_slow + 1:
            continue
        close = float(df["Close"].iloc[-1])
        ma = float(df["Close"].rolling(ma_slow).mean().iloc[-1])
        avg_vol = float(df["Volume"].tail(5).mean())
        per_df = chip.get_per_df(code)
        per = float(per_df.iloc[-1]["PER"]) if not per_df.empty else None
        fm = fund_map.get(code, {})
        metrics[code] = {
            "avg_vol": avg_vol, "per": per, "close": close, "ma_slow": ma,
            "roe": fm.get("roe_ttm"), "eps_growth": fm.get("eps_yoy"),
            "yoy": rev_map.get(code, {}).get("yoy"),
            "Name": t.get("Name", ""), "Industry": t.get("Industry", ""),
        }

    selected = select_value_growth(metrics, vg_config)
    # 補回名稱/產業
    for s in selected:
        info = metrics.get(s["Ticker"], {})
        s["Name"] = info.get("Name", "")
        s["Industry"] = info.get("Industry", "")
    log.info(f"[ValueGrowth] 當期精選 {len(selected)} 檔 (掃描 {len(metrics)} 檔)")
    return selected
