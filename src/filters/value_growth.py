"""
價值成長型選股過濾器 (Value-Growth)。

與動能型 (PriceVolumeFilter + AdvancedFilter) 並存、不重疊：
趨勢/擇時交由 investment_analysis 負責，本過濾器只專注「便宜 + 成長 + 品質」。

刻意不要求站上均線、不要求法人買超 (那是動能邏輯)。改以估值便宜、
獲利品質與成長為核心，並保留一個「軟性安全網」避免接價值陷阱的下跌刀。

設計為兩階段，以最小化 FinMind 用量：
  1. prescreen(): 只用免費資料 (yfinance 量價 + TWSE/TPEx 本益比)，
     做流動性、估值上限與安全網初篩，先把全市場砍到少量候選。
  2. evaluate(): 僅對初篩通過者計算需要財報的指標 (ROE / 營收 YoY /
     EPS 成長 → PEG)，做最終判定與評分排序。
"""
from src.utils.logger import log


class ValueGrowthFilter:
    def __init__(self, config=None):
        self.cfg = config or {}
        self.liq = self.cfg.get("liquidity", {})
        self.val = self.cfg.get("valuation", {})
        self.qg = self.cfg.get("quality_growth", {})
        self.safe = self.cfg.get("safety_net", {})

    # ---------- 第一階段：免費資料初篩 ----------
    def prescreen(self, avg_vol, per, close=None, ma_slow=None):
        """只用免費資料判定是否值得花 FinMind 額度。

        回傳 (pass: bool, reason: str)。reason 為未通過原因，通過時為 "OK"。
        """
        # 流動性
        if avg_vol is None or avg_vol < self.liq.get("min_volume_avg", 0):
            return False, "liquidity"

        # 估值上限 (必須有正本益比，代表公司獲利為正且不過貴)
        per_min = self.val.get("per_min", 0)
        per_max = self.val.get("per_max", float("inf"))
        if per is None or not (per_min < per <= per_max):
            return False, "valuation_per"

        # 軟性安全網：避免買進遠低於季線的急殺股 (價值陷阱)
        max_below = self.safe.get("max_below_ma_pct")
        if max_below is not None and close and ma_slow and ma_slow > 0:
            below_pct = (close - ma_slow) / ma_slow
            if below_pct < max_below:
                return False, "safety_net"

        return True, "OK"

    # ---------- 第二階段：財報指標最終判定 + 評分 ----------
    def evaluate(self, per, roe, yoy, eps_growth):
        """對初篩通過者做最終判定。回傳 (pass, metrics)。

        metrics 含 PEG 與綜合評分 score (越高越優先)。
        """
        peg = self._calc_peg(per, eps_growth)

        roe_pass = roe is not None and roe >= self.qg.get("roe_min", float("-inf"))
        yoy_pass = yoy is not None and yoy >= self.qg.get("yoy_min", float("-inf"))
        eps_pass = eps_growth is not None and eps_growth >= self.qg.get("eps_growth_min", float("-inf"))

        if self.val.get("peg_required", True):
            peg_max = self.val.get("peg_max", float("inf"))
            peg_pass = peg is not None and 0 < peg <= peg_max
        else:
            peg_pass = True

        passed = bool(roe_pass and yoy_pass and eps_pass and peg_pass)
        metrics = {
            "PEG": peg if peg is not None else 0.0,
            "Score": self._score(per, peg, roe, yoy),
            "ROE_Pass": roe_pass,
            "YoY_Pass": yoy_pass,
            "EPS_Pass": eps_pass,
            "PEG_Pass": peg_pass,
        }
        return passed, metrics

    # ---------- 內部工具 ----------
    @staticmethod
    def _calc_peg(per, eps_growth):
        if per is None or eps_growth is None or eps_growth <= 0 or per <= 0:
            return None
        return round(per / eps_growth, 2)

    @staticmethod
    def _score(per, peg, roe, yoy):
        """價值成長綜合評分：估值越便宜、品質與成長越高，分數越高。

        以低 PEG 為核心 (成長相對股價便宜)，加上 ROE 與營收成長加分。
        分數僅用於排序，非硬性門檻；缺值以中性方式處理。
        """
        score = 0.0
        # PEG 越低越好：以 (1 / PEG) 計分，PEG<1 得高分
        if peg and peg > 0:
            score += min(2.0, 1.0 / peg) * 40
        # ROE 品質加分
        if roe is not None:
            score += max(0.0, roe) * 1.5
        # 營收成長加分
        if yoy is not None:
            score += max(0.0, yoy) * 1.0
        return round(score, 2)
