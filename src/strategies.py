"""
可插拔選股策略平台。

核心理念：當期選股與回測共用「同一個策略物件」，策略只需實作
  - assemble(ctx, as_of): 用資料情境組出 {code: 指標}  (時點對齊由 ctx 負責)
  - select(metrics, params): 純選股，回傳排序後的 picks
如此「回測的邏輯 = 實跑的邏輯」，且換策略只是換物件，引擎不必改。

目前內建兩種攻擊型策略 (與 investment_analysis 的防守/擇時互補)：
  - ValueGrowthStrategy: 便宜成長 (低 PER/PEG + 高 ROE + 營收成長)
  - MomentumStrategy:    趨勢動能 (站上均線 + 均線翻揚 + 量 + 基本面)，
                         回測版省略 L3 法人籌碼 (歷史籌碼成本高，另議)。
"""
import pandas as pd

from src.value_pipeline import select_value_growth


class DataContext:
    """持有所有資料源，提供時點對齊查詢；當期與回測共用。"""

    def __init__(self, universe, histories, fundamentals_assembler, revenue_provider,
                 exclude_industries=None):
        self.universe = universe                 # {code: {yfinance_ticker, Name, Industry}}
        self.histories = histories               # {yf_ticker: price df}
        self.fin = fundamentals_assembler
        self.rev = revenue_provider
        self.exclude = set(exclude_industries or [])
        self._fund_cache = {}
        self._rev_cache = {}

    def fundamentals(self, d):
        from src.value_pipeline import as_of_financial_period
        key = as_of_financial_period(d)
        if key not in self._fund_cache:
            self._fund_cache[key] = self.fin.metrics_at(*key)
        return self._fund_cache[key]

    def revenue(self, d):
        from src.value_pipeline import as_of_revenue_period
        key = as_of_revenue_period(d)
        if key not in self._rev_cache:
            self._rev_cache[key] = self.rev.get_month(*key)
        return self._rev_cache[key]

    def price_asof(self, yf_ticker, d):
        """回傳 (<=d 的子序列 df)；無資料回 None。"""
        df = self.histories.get(yf_ticker)
        if df is None:
            return None
        sub = df[df.index <= pd.Timestamp(d)]
        return sub if not sub.empty else None


class Strategy:
    name = "base"

    def assemble(self, ctx, as_of):
        raise NotImplementedError

    def select(self, metrics, params):
        raise NotImplementedError


class ValueGrowthStrategy(Strategy):
    name = "value_growth"

    def assemble(self, ctx, as_of):
        ma_slow = 60
        fund = ctx.fundamentals(as_of)
        rev = ctx.revenue(as_of)
        metrics = {}
        for code, info in ctx.universe.items():
            if info.get("Industry", "") in ctx.exclude:
                continue
            sub = ctx.price_asof(info["yfinance_ticker"], as_of)
            if sub is None or len(sub) < ma_slow + 1:
                continue
            close = float(sub["Close"].iloc[-1])
            ma = float(sub["Close"].rolling(ma_slow).mean().iloc[-1])
            avg_vol = float(sub["Volume"].tail(5).mean())
            fm = fund.get(code, {})
            eps_ttm = fm.get("eps_ttm")
            per = round(close / eps_ttm, 2) if eps_ttm and eps_ttm > 0 else None
            metrics[code] = {
                "avg_vol": avg_vol, "per": per, "close": close, "ma_slow": ma,
                "roe": fm.get("roe_ttm"), "eps_growth": fm.get("eps_yoy"),
                "yoy": rev.get(code, {}).get("yoy"),
                "Name": info.get("Name", ""), "Industry": info.get("Industry", ""),
            }
        return metrics

    def select(self, metrics, params):
        picks = select_value_growth(metrics, params)
        for p in picks:
            info = metrics.get(p["Ticker"], {})
            p["Name"] = info.get("Name", "")
            p["Industry"] = info.get("Industry", "")
        return picks


class MomentumStrategy(Strategy):
    """趨勢動能 (回測版 = L1+L2+L4，省略 L3 法人籌碼)。

    params 取自 config 動能組: l1_l2 (ma_fast/ma_slow/ma_20_slope/ma_60_slope/
    min_volume_avg) 與 l4 (yoy_min/roe_min)。
    """
    name = "momentum"

    def assemble(self, ctx, as_of):
        # assemble 只算出原始技術/基本面數值，門檻判定留給 select(params)
        ma_fast, ma_slow = 20, 60
        fund = ctx.fundamentals(as_of)
        rev = ctx.revenue(as_of)
        metrics = {}
        for code, info in ctx.universe.items():
            if info.get("Industry", "") in ctx.exclude:
                continue
            sub = ctx.price_asof(info["yfinance_ticker"], as_of)
            if sub is None or len(sub) < ma_slow + 2:
                continue
            closes = sub["Close"]
            ma20 = closes.rolling(ma_fast).mean()
            ma60 = closes.rolling(ma_slow).mean()
            m20_prev, m20_now = ma20.iloc[-2], ma20.iloc[-1]
            m60_prev, m60_now = ma60.iloc[-2], ma60.iloc[-1]
            if pd.isna(m20_prev) or m20_prev <= 0:
                continue
            m20_slope = (m20_now - m20_prev) / m20_prev
            m60_slope = (m60_now - m60_prev) / m60_prev if (not pd.isna(m60_prev) and m60_prev > 0) else None
            fm = fund.get(code, {})
            metrics[code] = {
                "close": float(closes.iloc[-1]),
                "ma20": float(m20_now), "m20_slope": float(m20_slope),
                "m60_slope": float(m60_slope) if m60_slope is not None else None,
                "avg_vol": float(sub["Volume"].tail(5).mean()),
                "roe": fm.get("roe_ttm"), "yoy": rev.get(code, {}).get("yoy"),
                "Name": info.get("Name", ""), "Industry": info.get("Industry", ""),
            }
        return metrics

    def select(self, metrics, params):
        l12 = params["l1_l2"]
        l4 = params["l4"]
        passed = []
        for code, m in metrics.items():
            # L1: 站上 MA20 + MA20 翻揚 + (有 MA60 時) MA60 不下彎
            if m["close"] <= m["ma20"]:
                continue
            if m["m20_slope"] < l12.get("ma_20_slope", 0):
                continue
            if m["m60_slope"] is not None and m["m60_slope"] < l12.get("ma_60_slope", 0):
                continue
            # L2: 量
            if m["avg_vol"] < l12.get("min_volume_avg", 0):
                continue
            # L4: 基本面 (免費源)
            roe = m.get("roe")
            yoy = m.get("yoy")
            if roe is None or roe <= l4.get("roe_min", -1e9):
                continue
            if yoy is None or yoy <= l4.get("yoy_min", -1e9):
                continue
            passed.append({
                "Ticker": code, "Close": m["close"],
                "M20_Slope": round(m["m20_slope"], 4),
                "ROE": roe, "YoY": yoy,
                "Score": round(m["m20_slope"] * 100, 2),  # 以 MA20 斜率排序 (同原邏輯)
                "Name": m.get("Name", ""), "Industry": m.get("Industry", ""),
            })
        passed.sort(key=lambda x: x["Score"], reverse=True)
        return passed


def get_strategy(name):
    return {"value_growth": ValueGrowthStrategy, "momentum": MomentumStrategy}[name]()
