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
            return None, True, None
        try:
            df = pd.read_parquet(path)
            if df.empty: return None, True, None
            # 修改為以週為單位 (7天)
            last_date = df.index.max()
            needs_update = (datetime.now() - last_date).days >= 7
            return df, needs_update, last_date
        except:
            return None, True, None

    def fetch_weekly_data(self, tickers: list):
        """抓取日線數據 (優化版：週更新 + 增量合併 + 自動清理)"""
        self.cleanup_cache() # 執行快取清理
        log.info(f"開始檢查 {len(tickers)} 檔標的的快取狀態...")
        
        to_download = {} # ticker -> start_date
        all_final_data = {}

        for ticker in tickers:
            df, needs_update, last_date = self._get_cache_info(ticker)
            if df is None:
                to_download[ticker] = None # 全量下載
            elif needs_update:
                to_download[ticker] = last_date # 增量下載
                all_final_data[ticker] = df
            else:
                all_final_data[ticker] = df

        if to_download:
            log.info(f"需下載/更新 {len(to_download)} 檔標的")
            # 為了簡化批次下載邏輯，我們將「全新下載」與「增量更新」分開處理或統一使用 start 參數
            new_data = self._batch_download_incremental(to_download)
            
            for t, new_df in new_data.items():
                if t in all_final_data:
                    # 合併舊資料與新資料
                    combined_df = pd.concat([all_final_data[t], new_df])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')].sort_index()
                    all_final_data[t] = combined_df
                else:
                    all_final_data[t] = new_df
                
                self.save_to_cache(t, all_final_data[t])

        return all_final_data

    def _batch_download_incremental(self, ticker_map):
        """支援增量抓取的批次下載"""
        results = {}
        tickers = list(ticker_map.keys())
        
        for i in range(0, len(tickers), self.batch_size):
            batch = tickers[i:i + self.batch_size]
            # 若批次中大家的 start_date 不同，yf.download 的批次處理會變複雜
            # 為求穩定，若有 start_date，則逐一或按相同 start_date 分組下載
            for ticker in batch:
                start_date = ticker_map[ticker]
                try:
                    if start_date:
                        # 增量下載：從最後一天的隔天開始
                        start_str = (start_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                        df = yf.download(ticker, start=start_str, interval="1d", progress=False)
                    else:
                        # 全量下載
                        df = yf.download(ticker, period="1y", interval="1d", progress=False)
                    
                    if not df.empty:
                        # yfinance 傳回的 multi-index 處理
                        if isinstance(df.columns, pd.MultiIndex):
                            df = df[ticker]
                        results[ticker] = df.dropna(subset=['Close'])
                except Exception as e:
                    log.error(f"下載 {ticker} 失敗: {str(e)}")
            
            time.sleep(random.uniform(1, 2))
        return results

    def save_to_cache(self, ticker, df, max_rows=250):
        """儲存快取並限制最大行數，確保資料量適中"""
        df_slim = df.sort_index().tail(max_rows)
        df_slim.to_parquet(self.CACHE_DIR / f"{ticker}.parquet")

    def cleanup_cache(self, expiry_days=90):
        """清理超過 N 天未更新的過時快取檔案"""
        log.info(f"掃描快取資料夾，清理超過 {expiry_days} 天未更新的資料...")
        count = 0
        for path in self.CACHE_DIR.glob("*.parquet"):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    last_date = df.index.max()
                    # 確保 last_date 是 datetime 型態
                    if (datetime.now() - pd.to_datetime(last_date)).days > expiry_days:
                        path.unlink()
                        count += 1
            except:
                path.unlink()
                count += 1
        if count > 0:
            log.info(f"已清理 {count} 個過時快取檔案。")
