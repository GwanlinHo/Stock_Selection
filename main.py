import json
import time
import argparse
import markdown
import os
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
    def __init__(self, mode="full"):
        self.mode = mode
        self.report_dir = Path("reports")
        self.temp_dir = Path("data/temp")
        self.config_file = Path("config/settings.json")
        for d in [self.report_dir, self.temp_dir]: d.mkdir(parents=True, exist_ok=True)
        self.l2_cache_file = self.temp_dir / "l2_candidates.json"
        self.final_cache_file = self.temp_dir / "candidates.json"
        self.stats = {"total": 0, "l1_l2_pass": 0, "l3_l4_pass": 0}
        self.load_config()

    def load_config(self):
        with open(self.config_file, "r") as f:
            full_config = json.load(f)
            self.active_level = full_config["active_level"]
            self.params = full_config["levels"][self.active_level]

    def cleanup_old_files(self):
        """清理超過 30 天的舊週報"""
        log.info("掃描報告資料夾，清理超過 30 天的舊週報...")
        count = 0
        now = time.time()
        expiry_seconds = 30 * 86400
        for path in self.report_dir.glob("WEEKLY_REPORT_*.md"):
            if (now - os.path.getmtime(path)) > expiry_seconds:
                path.unlink()
                count += 1
        if count > 0: log.info(f"已清理 {count} 份舊報告。")

    def run(self):
        log.info(f"=== 啟動選股程序 [模式: {self.mode}] [標準: {self.active_level}] ===")
        self.cleanup_old_files()
        
        tickers_info = TickerManager().load_tickers()
        meta_map = {str(t['Ticker']): {"Name": t['Name'], "Industry": t['Industry']} for t in tickers_info}
        self.stats["total"] = len(tickers_info)
        l2_candidates = []
        final_data = []

        if self.mode == "full":
            # Full 模式下清空暫存
            for f in self.temp_dir.glob("*.json"): f.unlink()
            
            yfinance_tickers = [t['yfinance_ticker'] for t in tickers_info]
            raw_data = DataIngestion(batch_size=50).fetch_weekly_data(yfinance_tickers)
            pv_filter = PriceVolumeFilter(config={
                "ma_fast": 20, "ma_slow": 60, "min_volume": self.params["min_volume_avg"],
                "ma_20_slope": self.params["ma_20_slope"], "ma_60_slope": self.params["ma_60_slope"]
            })
            l2_candidates = pv_filter.run(raw_data)
            for cand in l2_candidates:
                pure_ticker = cand['Ticker'].split('.')[0]
                info = meta_map.get(pure_ticker, {"Name": "未知", "Industry": "未知"})
                cand.update(info)
            with open(self.l2_cache_file, "w", encoding="utf-8") as f:
                json.dump(l2_candidates, f, ensure_ascii=False, indent=4)
        else:
            if self.l2_cache_file.exists():
                with open(self.l2_cache_file, "r", encoding="utf-8") as f:
                    l2_candidates = json.load(f)
                for cand in l2_candidates:
                    pure_ticker = cand['Ticker'].split('.')[0]
                    info = meta_map.get(pure_ticker, {"Name": "未知", "Industry": "未知"})
                    cand.update(info)

        self.stats["l1_l2_pass"] = len(l2_candidates)

        if self.mode in ["full", "skip-scan"] and l2_candidates:
            premium_data = DataPremium()
            adv_filter = AdvancedFilter()
            
            # [斷點續傳邏輯] 讀取現有進度
            existing_progress = {}
            if self.final_cache_file.exists():
                try:
                    with open(self.final_cache_file, "r", encoding="utf-8") as f:
                        old_data = json.load(f)
                        # 只有當 L3_Pass 或 L4_Pass 且數值非 0 時才視為已完成
                        existing_progress = {d['Ticker']: d for d in old_data if d.get('L3_Value') != 0 or d.get('L4_Value') != 0}
                    log.info(f"偵測到現有進度，將跳過 {len(existing_progress)} 檔已處理標的。")
                except: pass

            for i, cand in enumerate(tqdm(l2_candidates, desc="精煉數據")):
                ticker_full = cand['Ticker']
                ticker = ticker_full.split('.')[0]
                
                # 檢查是否可跳過
                if ticker_full in existing_progress:
                    l2_candidates[i] = existing_progress[ticker_full]
                    continue
                
                df_inst = premium_data.fetch_chip_data(ticker)
                df_rev = premium_data.fetch_fundamental_data(ticker)
                l3_pass, l3_val = adv_filter.run_l3(ticker, df_inst)
                l4_pass, l4_val = adv_filter.run_l4(ticker, df_rev)
                
                cand['L3_Pass'], cand['L3_Value'] = bool(l3_pass), float(l3_val)
                cand['L4_Pass'], cand['L4_Value'] = bool(l4_pass), float(l4_val)
                final_data.append(cand) # 舊邏輯，改為直接更新 l2_candidates 並定期儲存
                
                # 每 10 筆存檔一次，確保斷點
                if (i + 1) % 10 == 0:
                    with open(self.final_cache_file, "w", encoding="utf-8") as f:
                        json.dump(l2_candidates, f, ensure_ascii=False, indent=4)
                
                time.sleep(0.1)
            
            final_data = l2_candidates # 統一使用更新後的 list
            with open(self.final_cache_file, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=4)
        else:
            if self.final_cache_file.exists():
                with open(self.final_cache_file, "r", encoding="utf-8") as f:
                    final_data = json.load(f)
                for cand in final_data:
                    pure_ticker = cand['Ticker'].split('.')[0]
                    info = meta_map.get(pure_ticker, {"Name": "未知", "Industry": "未知"})
                    cand.update(info)

        self.stats["l3_l4_pass"] = len([d for d in final_data if d.get('L3_Pass')])
        self.generate_rich_report(final_data)

    def generate_rich_report(self, data):
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = self.report_dir / f"WEEKLY_REPORT_{date_str}.md"
        
        md_content = f"# 台股選股掃描綜合週報 ({date_str})\n\n"
        md_content += f"**摘要**: (待 AI 填寫...)\n\n"
        md_content += f"**標準**: `{self.active_level}` | **海選通過**: {self.stats['l1_l2_pass']} 檔 | **籌碼偏多**: {self.stats['l3_l4_pass']} 檔\n\n"
        
        md_content += "## AI 深度分析與市場動態\n"
        md_content += "(請執行 AI 分析流程以填充此章節...)\n\n"

        md_content += "## 候選名單詳細數據面板\n"
        md_content += "| 代碼 | 名稱 | 產業 | 收盤 | MA20斜率 | 5日均量 | 籌碼(張) | 營收YoY% |\n"
        md_content += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
        for item in sorted(data, key=lambda x: x.get('M20_Slope', 0), reverse=True):
            l3_val = item.get('L3_Value', 0)
            l4_val = item.get('L4_Value', 0)
            l3_txt = f"{l3_val:+,.1f}"
            l4_txt = f"{l4_val:+.2f}%"
            l3_status = "✅" if item.get('L3_Pass') else "❌"
            l4_status = "✅" if item.get('L4_Pass') else "⚠️"
            name = item.get('Name', '未知')
            ind = item.get('Industry', '未知')
            code = item['Ticker'].split('.')[0]
            md_content += f"| {code} | {name} | {ind} | {item['Close']:.2f} | {item.get('M20_Slope', 0):.4f} | {item['AvgDailyVol']:.0f} | {l3_status} {l3_txt} | {l4_status} {l4_txt} |\n"

        # 寫入 Markdown 檔案
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        log.info(f"高品質週報已產出: {report_file}")

        # 產生 index.html 用於 GitHub Pages
        self.generate_index_html(md_content)

    def generate_index_html(self, md_content):
        """將 Markdown 轉換為漂亮的 HTML 並存為 index.html"""
        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        
        html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>台股選股週報 - GitHub Pages</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">
    <style>
        .markdown-body {{
            box-sizing: border-box;
            min-width: 200px;
            max-width: 980px;
            margin: 0 auto;
            padding: 45px;
        }}
        @media (max-width: 767px) {{
            .markdown-body {{ padding: 15px; }}
        }}
        body {{ background-color: #f6f8fa; }}
    </style>
</head>
<body>
    <article class="markdown-body">
        {html_body}
    </article>
</body>
</html>"""
        
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_template)
        log.info("GitHub Pages 入口首頁 index.html 已更新。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "skip-scan", "report-only"], default="full")
    args = parser.parse_args()
    StockScanner(mode=args.mode).run()
