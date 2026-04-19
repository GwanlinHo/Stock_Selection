import pandas as pd
import numpy as np
from src.utils.logger import log

class AdvancedFilter:
    """第三、四層過濾網: 籌碼與基本面過濾 (修正 JSON 序列化版)"""

    def run_l3(self, ticker: str, df_inst: pd.DataFrame):
        if df_inst is None or df_inst.empty:
            return False, 0.0
            
        recent_inst = df_inst.tail(15) 
        buy = float(recent_inst[recent_inst['name'].isin(['Foreign_Investor', 'Investment_Trust'])]['buy'].sum())
        sell = float(recent_inst[recent_inst['name'].isin(['Foreign_Investor', 'Investment_Trust'])]['sell'].sum())
        net_buy_shares = (buy - sell) / 1000
        
        return bool(net_buy_shares > 0), float(round(net_buy_shares, 1))

    def run_l4(self, ticker: str, df_revenue: pd.DataFrame):
        if df_revenue is None or len(df_revenue) < 13:
            return False, 0.0
        
        try:
            latest_rev = float(df_revenue.iloc[-1]['revenue'])
            last_year_rev = float(df_revenue.iloc[-13]['revenue'])
            if last_year_rev == 0: return False, 0.0
            yoy = ((latest_rev - last_year_rev) / last_year_rev) * 100
            return bool(yoy > 0), float(round(yoy, 2))
        except:
            return False, 0.0
