import pandas as pd
import numpy as np
from src.utils.logger import log

class TechnicalIndicators:
    """計算技術指標模組"""

    @staticmethod
    def calculate_ma(df: pd.DataFrame, window: int) -> pd.Series:
        """計算移動平均線 (MA)"""
        if len(df) < window:
            return pd.Series([np.nan] * len(df))
        return df['Close'].rolling(window=window).mean()

    @staticmethod
    def calculate_slope(series: pd.Series, window: int = 3) -> float:
        """
        計算斜率 (判定趨勢方向)
        使用最近 window 天的數值進行簡單線性回歸或差值判定
        """
        if len(series) < window or series.iloc[-window:].isnull().any():
            return 0.0
        
        # 簡單判定: 最近一筆是否大於前一筆，且呈現上升趨勢
        # 這裡使用最近 3 期的平均變動率
        changes = series.tail(window).pct_change().dropna()
        return float(changes.mean())

    @staticmethod
    def is_trend_up(series: pd.Series, window: int = 3) -> bool:
        """判定趨勢是否向上"""
        slope = TechnicalIndicators.calculate_slope(series, window)
        return slope > 0
