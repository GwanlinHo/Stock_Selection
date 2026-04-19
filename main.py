import json
import time
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

from src.utils.logger import log, ErrorCode
from src.tickers import TickerManager
from src.data_ingestion import DataIngestion
from src.filters.price_volume import PriceVolumeFilter
from src.data_premium import DataPremium
from src.filters.advanced_filter import AdvancedFilter

class StockScanner:
    def __init__(self):
        self.data_dir = Path("data")
        self.report_dir = Path("reports")
        self.temp_dir = Path("data/temp")
        self.config_file = Path("config/settings.json")
        
        for d in [self.data_dir, self.report_dir, self.temp_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
        self.stats = {"total": 0, "l1_l2_pass": 0, "l3_l4_pass": 0}
        self.load_config()

    def load_config(self):
        with open(self.config_file, "r") as f:
            full_config = json.load(f)
            self.active_level = full_config["active_level"]
            self.params = full_config["levels"][self.active_level]
            log.info(f"載入配置層級: {self.active_level}")

    def run(self):
        log.info("=== 啟動選股 Workflow (詳細數據版) ===")
        
        # 1. 獲取標的與名稱映射
        ticker_mgr = TickerManager()
        tickers = ticker_mgr.load_tickers()
        name_map = {t['yfinance_ticker']: t['Name'] for t in tickers}
        industry_map = {t['yfinance_ticker']: t['Industry'] for t in tickers}
        self.stats["total"] = len(tickers)
        
        # 2. L1 & L2 海選
        yfinance_tickers = list(name_map.keys())
        raw_data = DataIngestion(batch_size=50).fetch_weekly_data(yfinance_tickers)
        
        pv_filter = PriceVolumeFilter(config={
            "ma_fast": 20, "ma_slow": 60, 
            "min_volume": self.params["min_volume_avg"],
            "ma_20_slope": self.params["ma_20_slope"],
            "ma_60_slope": self.params["ma_60_slope"]
        })
        l2_candidates = pv_filter.run(raw_data)
        self.stats["l1_l2_pass"] = len(l2_candidates)
        
        # 3. L3 & L4 精選
        final_data = []
        if l2_candidates:
            premium_data = DataPremium()
            adv_filter = AdvancedFilter()
            for cand in tqdm(l2_candidates, desc="處理數據"):
                ticker = cand['Ticker']
                # 補上名稱與產業
                cand['Name'] = name_map.get(cand['Ticker']+".TW", name_map.get(cand['Ticker']+".TWO", "未知"))
                cand['Industry'] = industry_map.get(cand['Ticker']+".TW", industry_map.get(cand['Ticker']+".TWO", "未知"))
                
                df_inst = premium_data.fetch_chip_data(ticker)
                df_rev = premium_data.fetch_fundamental_data(ticker)
                
                cand['L3_Pass'] = adv_filter.run_l3(ticker, df_inst)
                cand['L4_Pass'] = adv_filter.run_l4(ticker, df_rev)
                
                # 即使不完全通過也紀錄，但過濾掉極差的
                if cand['L3_Pass'] or cand['L4_Pass']:
                    final_data.append(cand)
                time.sleep(0.3)
        
        self.stats["l3_l4_pass"] = len(final_data)
        with open(self.temp_dir / "candidates.json", "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
            
        self.generate_report(final_data)

    def generate_report(self, data):
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = self.report_dir / f"SCAN_DATA_{date_str}.md"
        
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# 🔍 數據掃描候選名單 ({date_str})\n\n")
            f.write(f"**標準**: `{self.active_level}` | **總標的**: {self.stats['total']} | **技術面通過**: {self.stats['l1_l2_pass']} | **籌碼/基本面通過**: {self.stats['l3_l4_pass']}\n\n")
            f.write("| 代碼 | 名稱 | 產業 | 收盤 | MA20斜率 | 5日均量 | 籌碼 | 營收YoY |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            
            for item in sorted(data, key=lambda x: x.get('M20_Slope', 0), reverse=True):
                l3 = "✅" if item['L3_Pass'] else "❌"
                l4 = "✅" if item['L4_Pass'] else "❌"
                f.write(f"| {item['Ticker']} | {item['Name']} | {item['Industry']} | {item['Close']:.2f} | {item['M20_Slope']:.4f} | {item['AvgDailyVol']:.0f} | {l3} | {l4} |\n")

        log.info(f"詳細數據報告已產出: {report_file}")

if __name__ == "__main__":
    StockScanner().run()
