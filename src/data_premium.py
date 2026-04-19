import pandas as pd
from FinMind.data import DataLoader
from src.utils.logger import log, ErrorCode
import os
from dotenv import load_dotenv

load_dotenv()

class DataPremium:
    """獲取法人籌碼與財報數據的模組"""

    def __init__(self, api_token=None):
        self.dl = DataLoader()
        # 如果有 token 則登入，沒有則使用匿名 (有頻率限制)
        self.api_token = api_token or os.getenv("FINMIND_TOKEN")
        if self.api_token:
            self.dl.login(api_token=self.api_token)

    def fetch_chip_data(self, ticker: str, days=30):
        """獲取法人買賣超數據"""
        try:
            raw_ticker = ticker.split('.')[0]
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
            
            # 使用法人買賣超
            df_inst = self.dl.taiwan_stock_institutional_investors(
                stock_id=raw_ticker,
                start_date=start_date
            )
            return df_inst
        except Exception as e:
            log.error(f"[{ErrorCode.ERR_NET_CONN}] 獲取 {ticker} 籌碼失敗: {str(e)}")
            return pd.DataFrame()

    def fetch_fundamental_data(self, ticker: str):
        """獲取營收與 EPS"""
        try:
            raw_ticker = ticker.split('.')[0]
            # 獲取最近三個月營收
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=120)).strftime('%Y-%m-%d')
            df_revenue = self.dl.taiwan_stock_month_revenue(
                stock_id=raw_ticker,
                start_date=start_date
            )
            return df_revenue
        except Exception as e:
            log.error(f"[{ErrorCode.ERR_NET_CONN}] 獲取 {ticker} 營收失敗: {str(e)}")
            return pd.DataFrame()
