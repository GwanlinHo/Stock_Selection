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
            
            # 讀取現有進度 (用於比對與保留舊數據)
            existing_data = {}
            if self.final_cache_file.exists():
                try:
                    with open(self.final_cache_file, "r", encoding="utf-8") as f:
                        old_list = json.load(f)
                        existing_data = {d['Ticker']: d for d in old_list}
                except: pass

            for i, cand in enumerate(tqdm(l2_candidates, desc="精煉數據")):
                ticker_full = cand['Ticker']
                ticker = ticker_full.split('.')[0]
                
                # 抓取新數據
                df_inst = premium_data.fetch_chip_data(ticker)
                df_rev = premium_data.fetch_fundamental_data(ticker)
                df_ratio = premium_data.fetch_financial_ratios(ticker)
                df_per = premium_data.fetch_per_pbr(ticker)
                
                # 執行篩選
                l3_pass, l3_val = adv_filter.run_l3(ticker, df_inst)
                l4_pass, l4_result = adv_filter.run_l4(ticker, df_rev, df_ratio, df_per)
                
                # --- 數據保護機制 (Soft Fail) ---
                # 若本次抓取失敗 (回傳值為 0 或預設值)，則嘗試從現有緩存中還原
                old_val = existing_data.get(ticker_full, {})
                
                cand['L3_Pass'] = bool(l3_pass)
                cand['L3_Value'] = float(l3_val) if l3_val != 0 else old_val.get('L3_Value', 0)
                
                cand['L4_Pass'] = bool(l4_pass)
                # 營收與基本面指標保護
                cand['L4_Value'] = float(l4_result['YoY']) if l4_result['YoY'] != 0 else old_val.get('L4_Value', 0)
                cand['ROE'] = l4_result['ROE'] if l4_result['ROE'] != 0 else old_val.get('ROE', 0)
                cand['PER'] = l4_result['PER'] if l4_result['PER'] != 0 else old_val.get('PER', 0)
                cand['PEG'] = l4_result['PEG'] if l4_result['PEG'] != 0 else old_val.get('PEG', 0)
                cand['Report_Date'] = l4_result['Report_Date'] if l4_result['Report_Date'] else old_val.get('Report_Date', "")
                
                # 重新根據可能還原後的數據判定 L4_Pass (確保篩選池正確)
                if not l4_pass:
                    # 如果是因為數據缺失導致不通過，但舊數據是通過的，則予以保留
                    if cand['L4_Value'] > 5 and cand['ROE'] > 8:
                        cand['L4_Pass'] = True

                final_data.append(cand) 

                # 每 10 筆即時存檔，保護進度
                if (i + 1) % 10 == 0:
                    with open(self.final_cache_file, "w", encoding="utf-8") as f:
                        json.dump(l2_candidates, f, ensure_ascii=False, indent=4)

                time.sleep(0.1)

                final_data = l2_candidates # 統一使用更新後的 list

            
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

        # 計算各階段統計
        self.stats["l1_l2_pass"] = len(l2_candidates)
        self.stats["l3_pass"] = len([d for d in final_data if d.get('L3_Pass')])
        self.stats["l4_pass"] = len([d for d in final_data if d.get('L3_Pass') and d.get('L4_Pass')])
        
        self.generate_rich_report(final_data)

    def generate_rich_report(self, data):
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = self.report_dir / f"WEEKLY_REPORT_{date_str}.md"
        
        # 1. 標題
        md_content = f"# 台股選股掃描綜合週報 ({date_str})\n\n"
        
        # 2. AI 深度分析 (第一順位)
        md_content += "## AI 深度分析與決策建議\n"
        md_content += "> *[Gemini CLI] 正在進行去罐頭化深度分析，請參考對話內容或稍後更新的報告。*\n\n"
        
        # 3. 篩選標準定義
        md_content += "## 篩選標準定義\n"
        md_content += "| 關卡 | 類型 | 詳細條件 |\n"
        md_content += "| :--- | :--- | :--- |\n"
        md_content += "| **L1** | 技術面 | 股價 > MA20 且 MA20 斜率 > 0.5% (趨勢確認) |\n"
        md_content += "| **L2** | 成交量 | 5 日均量 > 1,000 張 (流動性確認) |\n"
        md_content += "| **L3** | 籌碼面 | 外資 + 投信近 15 日累計買超 > 0 (大人動向) |\n"
        md_content += "| **L4** | 基本面 | 營收 YoY > 5% 且 ROE > 8% (年化) (PEG 供參考) |\n\n"

        # 4. 篩選漏斗統計
        md_content += f"*   **[L1/L2] 價量趨勢通過**: {self.stats['l1_l2_pass']} 檔\n"
        md_content += f"*   **[L3] 法人籌碼偏多**: {self.stats['l3_pass']} 檔\n"
        md_content += f"*   **[L4] 營收年增成長**: {self.stats['l4_pass']} 檔 (最終精選)\n\n"

        # 4. 最終精選池 (僅顯示 L4 通過標的)
        md_content += "## 最終精選池 (Level 4 全通過)\n"
        md_content += "| 代碼 | 名稱 | 產業 | 收盤 | MA20斜率 | 籌碼(張) | 營收YoY% | ROE% | PER | PEG |\n"
        md_content += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
        # 過濾：僅保留同時通過 L3 與 L4 的標的
        final_pool = [d for d in data if d.get('L3_Pass') and d.get('L4_Pass')]
        
        for item in sorted(final_pool, key=lambda x: x.get('M20_Slope', 0), reverse=True):
            l3_val = item.get('L3_Value', 0)
            l4_val = item.get('L4_Value', 0)
            roe = item.get('ROE', 0)
            per = item.get('PER', 0)
            peg = item.get('PEG', 0)
            
            l3_txt = f"{l3_val:+,.1f}"
            l4_txt = f"{l4_val:+.2f}%"
            roe_txt = f"{roe:.2f}%"
            per_txt = f"{per:.1f}" if per > 0 else "-"
            peg_txt = f"{peg:.2f}" if peg > 0 else "-"
            
            l3_status = "✅"
            l4_status = "✅"
            name = item.get('Name', '未知')
            
            # 若財報日期在 45 天內，標記為最新
            report_date = item.get('Report_Date', '')
            if report_date:
                try:
                    rd = datetime.strptime(report_date, "%Y-%m-%d")
                    if (datetime.now() - rd).days < 45:
                        name += " [!]"
                except: pass

            ind = item.get('Industry', '未知')
            code = item['Ticker'].split('.')[0]
            md_content += f"| {code} | {name} | {ind} | {item['Close']:.2f} | {item.get('M20_Slope', 0):.4f} | {l3_status} {l3_txt} | {l4_status} {l4_txt} | {roe_txt} | {per_txt} | {peg_txt} |\n"

        if not final_pool:
            md_content += "> *目前尚無同時符合籌碼與營收篩選標準的標的。*\n"

        # 寫入 Markdown 檔案
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        log.info(f"高品質週報已產出: {report_file}")

        # 產生 index.html 用於 GitHub Pages (讀取最新的檔案內容，包含可能已填寫的 AI 分析)
        with open(report_file, "r", encoding="utf-8") as f:
            final_md = f.read()
        self.generate_index_html(final_md)

    def generate_index_html(self, md_content):
        """將 Markdown 轉換為漂亮的 HTML 並存為 index.html"""
        # 使用更完整的擴充功能
        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'nl2br'])
        
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
        /* 表格樣式強化 */
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
        th, td {{ border: 1px solid #dfe2e5; padding: 6px 13px; text-align: left; }}
        tr:nth-child(2n) {{ background-color: #f6f8fa; }}
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

    def sync_index(self):
        """僅將最新的 .md 報告同步到 index.html，保留 AI 分析後的內容"""
        reports = sorted(self.report_dir.glob("WEEKLY_REPORT_*.md"))
        if not reports:
            log.error("找不到任何報告檔案，無法同步。")
            return
        
        latest_report = reports[-1]
        log.info(f"正在從最新報告同步 HTML: {latest_report}")
        with open(latest_report, "r", encoding="utf-8") as f:
            md_content = f.read()
        self.generate_index_html(md_content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "skip-scan", "report-only", "sync"], default="full")
    args = parser.parse_args()
    scanner = StockScanner(mode=args.mode)
    if args.mode == "sync":
        scanner.sync_index()
    else:
        scanner.run()
