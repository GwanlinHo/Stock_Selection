import pandas as pd
from src.utils.logger import log

class AdvancedFilter:
    """第三、四層過濾網: 籌碼與基本面過濾"""

    def run_l3(self, ticker: str, df_inst: pd.DataFrame):
        """L3: 籌碼過濾 (法人動向)"""
        if df_inst.empty:
            return False
            
        # 計算近 5 日法人累計買賣超
        # FinMind 格式: name 欄位包含 'Foreign_Investor', 'Investment_Trust'
        recent_inst = df_inst.tail(15) # 考慮到三種法人，取近 15 筆約為 5 天
        net_buy = recent_inst[recent_inst['name'].isin(['Foreign_Investor', 'Investment_Trust'])]['buy'].sum() - \
                  recent_inst[recent_inst['name'].isin(['Foreign_Investor', 'Investment_Trust'])]['sell'].sum()
        
        return net_buy > 0

    def run_l4(self, ticker: str, df_revenue: pd.DataFrame):
        """L4: 基本面過濾 (營收 YoY)"""
        if len(df_revenue) < 2:
            return False
        
        # 取得最新一筆與去年同期的營收 (假設資料按月排列)
        # 注意: 如果資料包含去年同期，則計算 (本月 - 去年本月) / 去年本月
        # 簡單化判定: 如果最新一筆大於前一筆 (MoM) 且為正，或簡單檢查數值
        # 精確做法: FinMind 的營收資料通常有 12 筆以上才可算 YoY
        if len(df_revenue) >= 13:
            latest_rev = df_revenue.iloc[-1]['revenue']
            last_year_rev = df_revenue.iloc[-13]['revenue']
            yoy = (latest_rev - last_year_rev) / last_year_rev
            return yoy > 0
        
        # 資料不足時，至少確保最新營收為正
        return df_revenue.iloc[-1]['revenue'] > 0
