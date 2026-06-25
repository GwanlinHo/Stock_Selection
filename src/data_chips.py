"""
歷史三大法人籌碼資料源 (供回測 L3 使用，免費)。

與 data_bulk.BulkChipProvider 不同：後者抓「從今天往前 N 天」，本模組可抓
「任意歷史日期」的單日全市場籌碼，並逐日永久快取，供回測在每個換股日
回溯近 N 個交易日的外資+投信累計買超。

資料源：TWSE T86 + TPEx 三大法人，與 data_bulk 同端點。
單日快取於 data/cache/chips/{YYYY-MM-DD}.json = {code: 外資+投信淨買股數}。
holiday/無資料的日期也快取為空字典，避免重複空打。
"""
import json
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from src.utils.logger import log

_UA = {"User-Agent": "Mozilla/5.0"}
_CACHE = Path("data/cache/chips")


def _to_num(s):
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


class HistoricalChipProvider:
    def __init__(self, sleep=0.6):
        _CACHE.mkdir(parents=True, exist_ok=True)
        self.sleep = sleep
        self._mem = {}   # date_str -> {code: net_shares}

    # ---------- 單日抓取 (外資+投信淨買股數) ----------
    def _fetch_twse_day(self, dt):
        ymd = dt.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALL&response=json"
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=25))
        except Exception:
            return None
        if j.get("stat") != "OK" or not j.get("data"):
            return None
        out = {}
        for row in j["data"]:
            tk = str(row[0]).strip()
            if not (len(tk) == 4 and tk.isdigit()):   # 只留上市櫃普通股，濾掉權證等
                continue
            net = (_to_num(row[2]) - _to_num(row[3])) + (_to_num(row[8]) - _to_num(row[9]))
            out[tk] = out.get(tk, 0.0) + net
        return out

    def _fetch_tpex_day(self, dt):
        roc = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
        url = ("https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
               f"3itrade_hedge_result.php?l=zh-tw&d={roc}&se=EW&t=D")
        try:
            j = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=25))
        except Exception:
            return None
        if j.get("stat") != "ok" or not j.get("tables"):
            return None
        data = j["tables"][0].get("data") or []
        if not data:
            return None
        out = {}
        for row in data:
            tk = str(row[0]).strip()
            if not (len(tk) == 4 and tk.isdigit()):   # 只留上市櫃普通股，濾掉權證等
                continue
            net = (_to_num(row[2]) - _to_num(row[3])) + (_to_num(row[11]) - _to_num(row[12]))
            out[tk] = out.get(tk, 0.0) + net
        return out

    def get_day(self, dt):
        """回傳該日 {code: 外資+投信淨買股數}；holiday 回 {} (並快取)。"""
        ds = dt.strftime("%Y-%m-%d")
        if ds in self._mem:
            return self._mem[ds]
        cache_file = _CACHE / f"{ds}.json"
        if cache_file.exists():
            try:
                d = json.loads(cache_file.read_text(encoding="utf-8"))
                self._mem[ds] = d
                return d
            except Exception:
                pass
        twse = self._fetch_twse_day(dt)
        tpex = self._fetch_tpex_day(dt)
        merged = {}
        if twse:
            merged.update(twse)
        if tpex:
            merged.update(tpex)
        # 即使空 (holiday) 也快取，避免重複空打
        is_trading = bool(twse or tpex)
        cache_file.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        self._mem[ds] = merged
        time.sleep(self.sleep)
        return merged if is_trading else {}

    def window_netbuy(self, end_date, days=15, max_probes=None):
        """回溯 <= end_date 的近 days 個交易日，回傳 {code: 外資+投信累計淨買(張)}。"""
        max_probes = max_probes or (days * 2 + 12)
        acc = {}
        got = 0
        dt = end_date if isinstance(end_date, datetime) else datetime(end_date.year, end_date.month, end_date.day)
        probes = 0
        while got < days and probes < max_probes:
            probes += 1
            if dt.weekday() < 5:
                day = self.get_day(dt)
                if day:
                    got += 1
                    for code, net in day.items():
                        acc[code] = acc.get(code, 0.0) + net
            dt -= timedelta(days=1)
        # 股 -> 張 (與 advanced_filter.run_l3 慣例一致)
        return {code: round(v / 1000, 1) for code, v in acc.items()}
