import pandas as pd
from src.data_premium import DataPremium
from src.filters.advanced_filter import AdvancedFilter
from src.ai_analyzer import AIAnalyzer
from src.utils.logger import log

def test_advanced_logic():
    # 模擬一檔候選股 (例如 2330 台積電)
    ticker = "2330.TW"
    
    # 1. 測試 Premium 資料獲取 (匿名模式)
    premium = DataPremium()
    log.info(f"測試獲取 {ticker} 的籌碼與營收數據...")
    
    df_inst = premium.fetch_chip_data(ticker)
    df_rev = premium.fetch_fundamental_data(ticker)
    
    # 2. 測試進階篩選邏輯
    adv_filter = AdvancedFilter()
    l3_pass = adv_filter.run_l3(ticker, df_inst)
    l4_pass = adv_filter.run_l4(ticker, df_rev)
    
    log.info(f"L3 (籌碼) 通過: {l3_pass}")
    log.info(f"L4 (基本面) 通過: {l4_pass}")
    
    # 3. 測試 AI 分析架構
    analyzer = AIAnalyzer()
    dummy_info = {"Ticker": ticker, "L3_Pass": l3_pass, "L4_Pass": l4_pass}
    ai_result = analyzer.analyze_and_classify(dummy_info)
    
    log.info(f"AI 分析結果預覽: {ai_result}")

if __name__ == "__main__":
    test_advanced_logic()
