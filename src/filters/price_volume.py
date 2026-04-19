import pandas as pd
import numpy as np
from src.indicators import TechnicalIndicators as TI
from src.utils.logger import log

class PriceVolumeFilter:
    """第一、二層過濾網: 週級別價量過濾 (修正版：連動 Config)"""

    def __init__(self, config=None):
        self.config = config or {
            "ma_fast": 20,
            "ma_slow": 60,
            "min_volume": 1000,
            "ma_20_slope": 0.0,
            "ma_60_slope": 0.0
        }

    def run(self, ticker_data: dict):
        log.info(f"開始執行價量篩選，使用參數: {self.config}")
        
        candidates = []
        for ticker, df in ticker_data.items():
            # 降低門檻：只要有足夠 MA20 的資料即可開始評估
            if len(df) < self.config["ma_fast"] + 5:
                continue
            
            df = df.copy()
            df['MA20'] = TI.calculate_ma(df, self.config["ma_fast"])
            df['MA60'] = TI.calculate_ma(df, self.config["ma_slow"])
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # 計算實際斜率 (百分比變動)
            m20_slope = (latest['MA20'] - prev['MA20']) / prev['MA20'] if prev['MA20'] > 0 else 0
            
            # MA60 處理：若無資料則不判定 MA60
            m60_pass = True
            if not np.isnan(latest['MA60']) and not np.isnan(prev['MA60']):
                m60_slope = (latest['MA60'] - prev['MA60']) / prev['MA60']
                m60_pass = m60_slope >= self.config.get("ma_60_slope", 0)

            # 核心邏輯判定
            is_l1 = (latest['Close'] > latest['MA20']) and \
                    (m20_slope >= self.config.get("ma_20_slope", 0)) and \
                    m60_pass
            
            if not is_l1:
                continue
            
            # L2: 成交量 (改為近 5 日平均量)
            avg_daily_vol = df['Volume'].tail(5).mean()
            is_l2 = avg_daily_vol >= self.config["min_volume"]
            
            if is_l2:
                candidates.append({
                    "Ticker": ticker,
                    "Close": latest['Close'],
                    "MA20": latest['MA20'],
                    "MA60": latest['MA60'] if not np.isnan(latest['MA60']) else 0,
                    "AvgDailyVol": avg_daily_vol,
                    "M20_Slope": m20_slope
                })
        
        log.info(f"篩選完成，共 {len(candidates)} 檔入選。")
        return candidates
