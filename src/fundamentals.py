"""
財報指標組裝器：把逐季「原始財報」換算成選股/回測要用的指標。

台股財報的淨利與 EPS 為「年度累計值」(Q1=Q1, Q2=H1, Q3=9M, Q4=全年)，
故計算 TTM 需先「去累計」還原各單季值，再加總最近四季。

對外提供 (皆為全市場 dict)：
  - metrics_at(year, season): {ticker: {roe_ttm, eps_yoy, eps_ttm}}
共用同一個 BulkFinancialProvider，季別資料永久快取、零重複抓取。
"""
from src.utils.logger import log


def prev_season(year: int, season: int):
    return (year - 1, 4) if season == 1 else (year, season - 1)


def trailing_seasons(year: int, season: int, n: int):
    """回傳含 (year,season) 在內、往前 n 季的 (年,季) 清單 (由舊到新)。"""
    seq = [(year, season)]
    y, s = year, season
    for _ in range(n - 1):
        y, s = prev_season(y, s)
        seq.append((y, s))
    return list(reversed(seq))


class FundamentalsAssembler:
    def __init__(self, fin_provider):
        self.fin = fin_provider

    def metrics_at(self, year: int, season: int) -> dict:
        """計算指定季別下全市場每檔的 TTM ROE、EPS YoY、TTM EPS。"""
        # 取最近 5 季 (去累計需多一季緩衝) + 去年同季 (算 EPS YoY)
        window = trailing_seasons(year, season, 5)
        ly_year, ly_season = year - 1, season
        if (ly_year, ly_season) not in window:
            window = [(ly_year, ly_season)] + window

        season_data = {}
        for (y, s) in window:
            season_data[(y, s)] = self.fin.get_season(y, s)

        latest = season_data.get((year, season), {})
        out = {}
        for ticker, rec in latest.items():
            equity = rec.get("equity", 0)
            ttm_ni = self._ttm_value(season_data, ticker, year, season, "net_income")
            roe = round(ttm_ni / equity * 100, 2) if equity and equity > 0 and ttm_ni is not None else None

            eps_ttm = self._ttm_value(season_data, ticker, year, season, "eps")
            eps_yoy = self._eps_yoy(season_data, ticker, year, season)

            out[ticker] = {"roe_ttm": roe, "eps_yoy": eps_yoy, "eps_ttm": eps_ttm}
        return out

    # ---------- 內部 ----------
    def _quarter_value(self, season_data, ticker, y, s, field):
        """還原單季值 (去累計)。資料不足回 None。"""
        cur = season_data.get((y, s), {}).get(ticker, {}).get(field)
        if cur is None:
            return None
        if s == 1:
            return cur
        py, ps = prev_season(y, s)
        prev = season_data.get((py, ps), {}).get(ticker, {}).get(field)
        if prev is None:
            return None
        return cur - prev

    def _ttm_value(self, season_data, ticker, year, season, field):
        """最近四季單季值之和 (TTM)。任一季缺失回 None。"""
        total = 0.0
        for (y, s) in trailing_seasons(year, season, 4):
            q = self._quarter_value(season_data, ticker, y, s, field)
            if q is None:
                return None
            total += q
        return round(total, 4)

    def _eps_yoy(self, season_data, ticker, year, season):
        """累計 EPS 的同期年增率 (%)。基期 <= 0 或缺值回 None。"""
        cur = season_data.get((year, season), {}).get(ticker, {}).get("eps")
        prev = season_data.get((year - 1, season), {}).get(ticker, {}).get("eps")
        if cur is None or prev is None or prev <= 0:
            return None
        return round((cur - prev) / prev * 100, 2)
