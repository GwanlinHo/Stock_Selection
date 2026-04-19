import json
import random
from src.tickers import TickerManager
from src.data_ingestion import DataIngestion
from src.filters.price_volume import PriceVolumeFilter
from src.utils.logger import log

def test_workflow():
    # 1. 載入標的
    manager = TickerManager()
    tickers_all = manager.load_tickers()
    if not tickers_all:
        log.error("無法載入標的清單")
        return

    # 隨機抽取 20 檔進行壓力與邏輯測試 (避免測試過久)
    sample_tickers = [t['yfinance_ticker'] for t in random.sample(tickers_all, 20)]
    log.info(f"測試樣本: {sample_tickers}")

    # 2. 抓取數據
    ingestion = DataIngestion(batch_size=10)
    data = ingestion.fetch_weekly_data(sample_tickers)

    # 3. 執行篩選
    pv_filter = PriceVolumeFilter()
    results = pv_filter.run(data)

    log.info(f"測試完成！入選標的: {[r['Ticker'] for r in results]}")

if __name__ == "__main__":
    test_workflow()
