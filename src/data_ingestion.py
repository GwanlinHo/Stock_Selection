import yfinance as yf
import pandas as pd
import time
import random
from pathlib import Path
from datetime import datetime
from src.utils.logger import log, ErrorCode

class DataIngestion:
    """修正版：使用日線數據計算標準 MA20/MA60"""

    CACHE_DIR = Path("data/cache")

    def __init__(self, batch_size=50):
        self.batch_size = batch_size
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_cache_info(self, ticker):
        path = self.CACHE_DIR / f"{ticker}.parquet"
        if not path.exists():
            return None, True
        try:
            df = pd.read_parquet(path)
            if df.empty: return None, True
            # 日線數據，若最後日期距離今天 > 1 天即更新
            needs_update = (datetime.now() - df.index.max()).days >= 1
            return df, needs_update
        except:
            return None, True

    def fetch_weekly_data(self, tickers: list):
        """抓取日線數據 (用於計算標準月/季線)"""
        log.info(f"開始檢查 {len(tickers)} 檔標的的日線資料...")
        
        to_download = []
        all_final_data = {}

        for ticker in tickers:
            df, needs_update = self._get_cache_info(ticker)
            if df is None or needs_update:
                to_download.append(ticker)
            else:
                all_final_data[ticker] = df

        if to_download:
            log.info(f"需下載/更新 {len(to_download)} 檔標的 (使用 period='1y')")
            new_data = self._batch_download(to_download, period="1y")
            all_final_data.update(new_data)
            for t, df in new_data.items():
                self.save_to_cache(t, df)

        return all_final_data

    def _batch_download(self, tickers, period):
        results = {}
        for i in range(0, len(tickers), self.batch_size):
            batch = tickers[i:i + self.batch_size]
            batch_str = " ".join(batch)
            try:
                # 使用 interval='1d'
                data = yf.download(batch_str, period=period, interval="1d", group_by='ticker', threads=True, progress=False)
                for ticker in batch:
                    if ticker in data.columns.levels[0]:
                        df = data[ticker].dropna(subset=['Close'])
                        if not df.empty:
                            results[ticker] = df
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                log.error(f"下載失敗: {str(e)}")
        return results

    def save_to_cache(self, ticker, df):
        df.to_parquet(self.CACHE_DIR / f"{ticker}.parquet")
