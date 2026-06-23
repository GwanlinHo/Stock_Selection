"""
免費的全市場「月營收」與「財報」批次資料源 (取代 FinMind)。

資料來自公開資訊觀測站舊站 mopsov.twse.com.tw 的歷史端點，特性：
  - 一次請求即取得「全市場、單一期間」的資料 (非逐檔)，用量極省。
  - 可指定任意歷史年月/季別，支援回測時點查詢。
  - 回傳 HTML 表格，需以 pandas.read_html 解析；表格會依產業別分多個子表，
    欄位順序不一，故一律以「欄名關鍵字」定位，不寫死索引。

時點 (避免回測前視偏誤)：
  - 月營收：每月約 10 號公布上月。
  - 季報：Q1≈5/15、Q2≈8/14、Q3≈11/14、年報≈隔年 3/31。
呼叫方式比照 data_bulk：加 User-Agent、低頻、sleep、結果落地快取。
"""
import json
import time
import urllib.request
import urllib.parse
from io import StringIO
from pathlib import Path

import pandas as pd

from src.utils.logger import log

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_SLEEP = 1.2   # 對 mopsov 友善，避免被視為攻擊


def _open(req, retries=2, backoff=2.0):
    """送出請求並回傳 bytes；遇暫時性錯誤 (如 502) 重試。"""
    last = None
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=40).read()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last


def _to_num(s):
    try:
        return float(str(s).replace(",", "").replace("(", "-").replace(")", "").strip() or 0)
    except Exception:
        return 0.0


def _find_col(cols, *keywords):
    """在欄名 (可能為 tuple/多層) 中找出第一個包含全部關鍵字的欄。找不到回 None。"""
    for c in cols:
        name = " ".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
        if all(k in name for k in keywords):
            return c
    return None


class BulkRevenueProvider:
    """全市場月營收 (含 YoY)。單期一次抓取，永久快取於 data/cache/revenue/。"""

    def __init__(self, cache_dir: str = "data/cache/revenue"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _url(self, roc_year: int, month: int, market: str) -> str:
        seg = "sii" if market == "sii" else "otc"
        # 月份不補零、結尾固定 _0、主機須為舊站 mopsov
        return f"https://mopsov.twse.com.tw/nas/t21/{seg}/t21sc03_{roc_year}_{month}_0.html"

    def _parse(self, html: str) -> dict:
        out = {}
        try:
            tables = pd.read_html(StringIO(html))
        except Exception as e:
            log.error(f"[BulkRevenue] read_html 解析失敗: {e}")
            return out
        for df in tables:
            cols = list(df.columns)
            # 月營收頁欄名含空格 (如「公司 代號」「去年同月 增減」)，故用較鬆的關鍵字
            c_id = _find_col(cols, "代號")
            c_rev = _find_col(cols, "當月營收")
            c_yoy = _find_col(cols, "去年同月")
            if c_id is None or c_rev is None:
                continue
            for _, row in df.iterrows():
                tk = str(row[c_id]).strip()
                if not tk or not tk[0].isdigit():
                    continue
                out[tk] = {
                    "revenue": _to_num(row[c_rev]),
                    "yoy": _to_num(row[c_yoy]) if c_yoy is not None else 0.0,
                }
        return out

    def get_month(self, roc_year: int, month: int, force: bool = False) -> dict:
        """回傳 {ticker: {revenue, yoy}}，合併上市與上櫃。整月快取。"""
        cache_file = self.cache_dir / f"{roc_year}_{month:02d}.json"
        if not force and cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        merged = {}
        for market in ("sii", "otc"):
            url = self._url(roc_year, month, market)
            try:
                req = urllib.request.Request(url, headers=_UA)
                raw = _open(req)
                html = raw.decode("big5", errors="ignore")   # 月營收頁為 BIG5
                merged.update(self._parse(html))
            except Exception as e:
                log.warning(f"[BulkRevenue] {market} {roc_year}/{month} 抓取失敗: {e}")
            time.sleep(_SLEEP)

        if merged:
            cache_file.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            log.info(f"[BulkRevenue] {roc_year}/{month} 取得 {len(merged)} 檔月營收。")
        return merged


class BulkFinancialProvider:
    """全市場財報 (淨利、股東權益、EPS)。單季一次抓取，永久快取於 data/cache/financial/。"""

    INCOME_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"
    BALANCE_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb05"

    def __init__(self, cache_dir: str = "data/cache/financial"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _post(self, url: str, roc_year: int, season: int, market: str) -> str:
        params = {
            "encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1,
            "TYPEK": "sii" if market == "sii" else "otc",
            "year": roc_year, "season": f"{season:02d}",
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=_UA)
        return _open(req).decode("utf-8", errors="ignore")

    def _parse_income(self, html: str) -> dict:
        out = {}
        try:
            tables = pd.read_html(StringIO(html))
        except Exception as e:
            log.error(f"[BulkFinancial] 損益表解析失敗: {e}")
            return out
        for df in tables:
            cols = list(df.columns)
            c_id = _find_col(cols, "公司代號") or _find_col(cols, "代號")
            c_eps = _find_col(cols, "基本每股盈餘")
            # 淨利優先取「歸屬於母公司業主」，否則取本期淨利
            c_ni = _find_col(cols, "歸屬於母公司業主") or _find_col(cols, "本期淨利") or _find_col(cols, "本期稅後淨利")
            if c_id is None or c_ni is None:
                continue
            for _, row in df.iterrows():
                tk = str(row[c_id]).strip()
                if not tk or not tk[0].isdigit():
                    continue
                rec = out.setdefault(tk, {})
                rec["net_income"] = _to_num(row[c_ni])
                if c_eps is not None:
                    rec["eps"] = _to_num(row[c_eps])
        return out

    def _parse_balance(self, html: str) -> dict:
        out = {}
        try:
            tables = pd.read_html(StringIO(html))
        except Exception as e:
            log.error(f"[BulkFinancial] 資產負債表解析失敗: {e}")
            return out
        for df in tables:
            cols = list(df.columns)
            c_id = _find_col(cols, "公司代號") or _find_col(cols, "代號")
            c_eq = _find_col(cols, "歸屬於母公司業主之權益") or _find_col(cols, "權益總額") or _find_col(cols, "權益總計")
            if c_id is None or c_eq is None:
                continue
            for _, row in df.iterrows():
                tk = str(row[c_id]).strip()
                if not tk or not tk[0].isdigit():
                    continue
                out.setdefault(tk, {})["equity"] = _to_num(row[c_eq])
        return out

    def get_season(self, roc_year: int, season: int, force: bool = False) -> dict:
        """回傳 {ticker: {net_income, eps, equity}}，合併上市與上櫃、損益與資負。整季快取。"""
        cache_file = self.cache_dir / f"{roc_year}_Q{season}.json"
        if not force and cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        merged = {}
        for market in ("sii", "otc"):
            try:
                inc = self._parse_income(self._post(self.INCOME_URL, roc_year, season, market))
                time.sleep(_SLEEP)
                bal = self._parse_balance(self._post(self.BALANCE_URL, roc_year, season, market))
                time.sleep(_SLEEP)
                for tk, rec in inc.items():
                    merged.setdefault(tk, {}).update(rec)
                for tk, rec in bal.items():
                    merged.setdefault(tk, {}).update(rec)
            except Exception as e:
                log.warning(f"[BulkFinancial] {market} {roc_year} Q{season} 抓取失敗: {e}")

        if merged:
            cache_file.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
            log.info(f"[BulkFinancial] {roc_year} Q{season} 取得 {len(merged)} 檔財報。")
        return merged
