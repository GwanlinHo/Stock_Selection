"""
全市場批次籌碼資料源 (免費)。

以證交所 (TWSE T86) 與櫃買 (TPEx) 的免費全市場端點，一次取得三大法人
買賣超，取代逐檔 FinMind 抓取，大幅降低 FinMind API 用量。

回傳 FinMind 相容形狀的 DataFrame (欄位: date / name / buy / sell)，
其中 name 僅產生 'Foreign_Investor' 與 'Investment_Trust' 兩類，
供 AdvancedFilter.run_l3 直接使用。
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.utils.logger import log

_UA = {"User-Agent": "Mozilla/5.0"}


def _to_num(s):
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


class BulkChipProvider:
    """一次抓取全市場、近 N 個交易日的三大法人籌碼資料並快取於記憶體/磁碟。"""

    def __init__(self, days: int = 15, cache_dir: str = "data/temp"):
        self.days = days
        self.cache_file = Path(cache_dir) / "bulk_chip.json"
        self.by_ticker: dict = {}   # 原始代號(不含.TW/.TWO) -> [ {date,name,buy,sell}, ... ]
        self.per_by_ticker: dict = {}   # 原始代號 -> 最新本益比 (float)
        self.trading_dates: list = []

    # ---------- 單日抓取 ----------
    def _fetch_twse(self, dt: datetime) -> bool:
        ymd = dt.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALL&response=json"
        try:
            req = urllib.request.Request(url, headers=_UA)
            j = json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            log.error(f"[BulkChip] TWSE T86 {ymd} 連線失敗: {e}")
            return False
        if j.get("stat") != "OK" or not j.get("data"):
            return False
        d = dt.strftime("%Y-%m-%d")
        for row in j["data"]:
            tk = str(row[0]).strip()
            # idx 2/3 外陸資(不含外資自營商)買/賣; idx 8/9 投信買/賣
            self.by_ticker.setdefault(tk, []).append(
                {"date": d, "name": "Foreign_Investor", "buy": _to_num(row[2]), "sell": _to_num(row[3])})
            self.by_ticker.setdefault(tk, []).append(
                {"date": d, "name": "Investment_Trust", "buy": _to_num(row[8]), "sell": _to_num(row[9])})
        return True

    def _fetch_tpex(self, dt: datetime) -> bool:
        roc = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
        url = ("https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
               f"3itrade_hedge_result.php?l=zh-tw&d={roc}&se=EW&t=D")
        try:
            req = urllib.request.Request(url, headers=_UA)
            j = json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            log.error(f"[BulkChip] TPEx {roc} 連線失敗: {e}")
            return False
        if j.get("stat") != "ok" or not j.get("tables"):
            return False
        data = j["tables"][0].get("data") or []
        if not data:
            return False
        d = dt.strftime("%Y-%m-%d")
        for row in data:
            tk = str(row[0]).strip()
            # idx 2/3 外資及陸資(不含外資自營商)買/賣; idx 11/12 投信買/賣
            self.by_ticker.setdefault(tk, []).append(
                {"date": d, "name": "Foreign_Investor", "buy": _to_num(row[2]), "sell": _to_num(row[3])})
            self.by_ticker.setdefault(tk, []).append(
                {"date": d, "name": "Investment_Trust", "buy": _to_num(row[11]), "sell": _to_num(row[12])})
        return True

    # ---------- 本益比 (僅需最新一個交易日) ----------
    def _fetch_twse_per(self, dt: datetime) -> bool:
        ymd = dt.strftime("%Y%m%d")
        url = ("https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
               f"?date={ymd}&selectType=ALL&response=json")
        try:
            req = urllib.request.Request(url, headers=_UA)
            j = json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            log.error(f"[BulkChip] TWSE BWIBBU {ymd} 連線失敗: {e}")
            return False
        if j.get("stat") != "OK" or not j.get("data"):
            return False
        for row in j["data"]:           # idx0 代號, idx5 本益比
            per = _to_num(row[5])
            if per > 0:
                self.per_by_ticker[str(row[0]).strip()] = per
        return True

    def _fetch_tpex_per(self, dt: datetime) -> bool:
        roc = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
        url = ("https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/"
               f"pera_result.php?l=zh-tw&d={roc}&c=&o=json")
        try:
            req = urllib.request.Request(url, headers=_UA)
            j = json.load(urllib.request.urlopen(req, timeout=25))
        except Exception as e:
            log.error(f"[BulkChip] TPEx pera {roc} 連線失敗: {e}")
            return False
        if j.get("stat") != "ok" or not j.get("tables"):
            return False
        data = j["tables"][0].get("data") or []
        for row in data:                # idx0 代號, idx2 本益比
            per = _to_num(row[2])
            if per > 0:
                self.per_by_ticker[str(row[0]).strip()] = per
        return bool(data)

    # ---------- 快取 ----------
    def _load_cache(self) -> bool:
        if not self.cache_file.exists():
            return False
        try:
            obj = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception:
            return False
        # 同一天且天數足夠才重用，避免重複打證交所
        if obj.get("built_on") != datetime.now().strftime("%Y-%m-%d"):
            return False
        if obj.get("days", 0) < self.days:
            return False
        if not obj.get("per_by_ticker"):   # 舊快取缺 PER → 重建
            return False
        self.by_ticker = obj.get("by_ticker", {})
        self.per_by_ticker = obj.get("per_by_ticker", {})
        self.trading_dates = obj.get("trading_dates", [])
        return bool(self.by_ticker)

    def _save_cache(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps({
                "built_on": datetime.now().strftime("%Y-%m-%d"),
                "days": self.days,
                "trading_dates": self.trading_dates,
                "by_ticker": self.by_ticker,
                "per_by_ticker": self.per_by_ticker,
            }, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.error(f"[BulkChip] 快取寫入失敗: {e}")

    # ---------- 對外 ----------
    def build(self, force: bool = False) -> int:
        """抓取近 self.days 個交易日的全市場籌碼。回傳實際取得的交易日數。"""
        if not force and self._load_cache():
            log.info(f"[BulkChip] 重用今日快取，交易日 {len(self.trading_dates)} 天，"
                     f"涵蓋 {len(self.by_ticker)} 檔。")
            return len(self.trading_dates)

        self.by_ticker = {}
        self.trading_dates = []
        got = 0
        dt = datetime.now()
        probes = 0
        max_probes = self.days * 2 + 12   # 預留假日/連假緩衝
        while got < self.days and probes < max_probes:
            probes += 1
            if dt.weekday() < 5:   # 跳過週末
                ok_twse = self._fetch_twse(dt)
                ok_tpex = self._fetch_tpex(dt)
                if ok_twse or ok_tpex:
                    got += 1
                    self.trading_dates.append(dt.strftime("%Y-%m-%d"))
                time.sleep(0.6)    # 對證交所友善
            dt -= timedelta(days=1)

        # 本益比：僅需最新一個交易日 (TWSE BWIBBU + TPEx pera)
        for ds in self.trading_dates[:3]:
            pdt = datetime.strptime(ds, "%Y-%m-%d")
            ok_a = self._fetch_twse_per(pdt)
            ok_b = self._fetch_tpex_per(pdt)
            if ok_a or ok_b:
                break

        log.info(f"[BulkChip] 抓取完成：交易日 {got} 天，涵蓋 {len(self.by_ticker)} 檔個股，"
                 f"本益比 {len(self.per_by_ticker)} 檔。")
        if got:
            self._save_cache()
        return got

    def get_chip_df(self, ticker: str) -> pd.DataFrame:
        """回傳指定代號的籌碼 DataFrame (FinMind 相容形狀)；查無資料則回空表。"""
        raw = ticker.split(".")[0].strip()
        rows = self.by_ticker.get(raw)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    def get_per_df(self, ticker: str) -> pd.DataFrame:
        """回傳指定代號的本益比單列 DataFrame (欄位 PER)；查無則回空表。"""
        raw = ticker.split(".")[0].strip()
        per = self.per_by_ticker.get(raw)
        if per is None:
            return pd.DataFrame()
        return pd.DataFrame([{"PER": float(per)}])
