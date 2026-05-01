import yfinance as yf
import pandas as pd
import time
import os
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
        """支援增量抓取的批次下載 (加入網路異常偵測)"""
        results = {}
        tickers = list(ticker_map.keys())
        
        consecutive_failures = 0
        max_consecutive = 20
        total_fail = 0
        
        for i, ticker in enumerate(tickers):
            start_date = ticker_map[ticker]
            try:
                if start_date:
                    start_str = (start_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    df = yf.download(ticker, start=start_str, interval="1d", progress=False, timeout=10)
                else:
                    df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=10)
                
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df = df[ticker]
                    results[ticker] = df.dropna(subset=['Close'])
                    consecutive_failures = 0 # 成功則重置
                else:
                    log.warning(f"下載 {ticker} 回傳空數據")
                    consecutive_failures += 1
                    total_fail += 1
            except Exception as e:
                log.error(f"下載 {ticker} 失敗: {str(e)}")
                consecutive_failures += 1
                total_fail += 1
            
            # 熔斷機制 1: 連續失敗
            if consecutive_failures >= max_consecutive:
                msg = f"偵測到網路異常: 已連續 {max_consecutive} 檔標的抓取失敗，自動停止程式。"
                log.critical(msg)
                raise RuntimeError(msg)
            
            # 熔斷機制 2: 處理一定數量後的失敗率 (例如處理超過 50 筆後，失敗率大於 80%)
            if i > 50 and (total_fail / (i + 1)) > 0.8:
                msg = f"偵測到高失敗率 ({(total_fail / (i + 1)) * 100:.1f}%)，判定為目前不適合取得資料，自動停止。"
                log.critical(msg)
                raise RuntimeError(msg)

            # 每批次間隔
            if (i + 1) % self.batch_size == 0:
                time.sleep(random.uniform(2, 5))
            else:
                time.sleep(0.1) # 即使在 batch 內也微幅間隔，對 yfinance 更友善
                
        return results

    def save_to_cache(self, ticker, df, max_rows=250):
        """儲存快取並限制最大行數，確保資料量適中"""
        df_slim = df.sort_index().tail(max_rows)
        df_slim.to_parquet(self.CACHE_DIR / f"{ticker}.parquet")

    def cleanup_cache(self, expiry_days=90):
        """清理超過 N 天未更新的過時快取檔案 (通常為下市或停止追蹤的股票)"""
        log.info(f"掃描快取資料夾，清理超過 {expiry_days} 天未更新的過時資料...")
        count = 0
        now = time.time()
        expiry_seconds = expiry_days * 86400

        for path in self.CACHE_DIR.glob("*.parquet"):
            try:
                # 使用檔案最後修改時間判定，效能較佳
                mtime = os.path.getmtime(path)
                if (now - mtime) > expiry_seconds:
                    path.unlink()
                    count += 1
            except Exception as e:
                log.warning(f"清理快取檔案 {path.name} 時出錯: {e}")
        
        if count > 0:
            log.info(f"清理完成: 已移除 {count} 檔過時股票資料。")
        else:
            log.info("快取檢查完成，無過時資料需要移除。")
            log.info(f"已清理 {count} 個過時快取檔案。")
