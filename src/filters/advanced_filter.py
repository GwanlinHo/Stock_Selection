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

    def run_l4(self, ticker: str, df_revenue: pd.DataFrame, df_ratio: pd.DataFrame = None, df_per: pd.DataFrame = None):
        """第四層基本面過濾: 營收 YoY + ROIC + PER + PEG"""
        result = {
            "Pass": False,
            "YoY": 0.0,
            "ROIC": 0.0,
            "PER": 0.0,
            "PEG": 0.0,
            "EPS_Growth": 0.0,
            "Report_Date": ""
        }

        # 1. 營收 YoY (基礎門檻)
        if df_revenue is not None and len(df_revenue) >= 13:
            try:
                latest_rev = float(df_revenue.iloc[-1]['revenue'])
                last_year_rev = float(df_revenue.iloc[-13]['revenue'])
                if last_year_rev > 0:
                    result["YoY"] = float(round(((latest_rev - last_year_rev) / last_year_rev) * 100, 2))
            except Exception: pass

        # 2. ROIC (從財務比率提取)
        if df_ratio is not None and not df_ratio.empty:
            try:
                roic_data = df_ratio[df_ratio['type'] == 'ROIC']
                if not roic_data.empty:
                    result["ROIC"] = float(round(roic_data.iloc[-1]['value'], 2))
                    result["Report_Date"] = str(roic_data.iloc[-1]['date'])
                
                # 計算 EPS Growth (用於 PEG)
                eps_data = df_ratio[df_ratio['type'] == 'BasicEarningsPerShare']
                if len(eps_data) >= 5: # 至少要有四五個季度資料
                    latest_eps = eps_data.iloc[-1]['value']
                    prev_year_eps = eps_data.iloc[-5]['value'] # 去年同期
                    if prev_year_eps > 0:
                        result["EPS_Growth"] = float(round(((latest_eps - prev_year_eps) / prev_year_eps) * 100, 2))
            except Exception: pass

        # 3. PER & PEG
        if df_per is not None and not df_per.empty:
            try:
                result["PER"] = float(round(df_per.iloc[-1]['PER'], 2))
                if result["EPS_Growth"] > 0:
                    result["PEG"] = float(round(result["PER"] / result["EPS_Growth"], 2))
            except Exception: pass

        # 綜合判定: YoY > 0 且 ROIC > 5% (基本門檻，可依需求調整)
        result["Pass"] = bool(result["YoY"] > 0 and result["ROIC"] > 5)
        
        return result["Pass"], result
