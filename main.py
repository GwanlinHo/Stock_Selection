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
from src.data_bulk import BulkChipProvider

class StockScanner:
    def __init__(self, mode="full", strategy=None):
        self.mode = mode
        self.report_dir = Path("reports")
        self.temp_dir = Path("data/temp")
        self.config_file = Path("config/settings.json")
        for d in [self.report_dir, self.temp_dir]: d.mkdir(parents=True, exist_ok=True)
        self.l2_cache_file = self.temp_dir / "l2_candidates.json"
        self.final_cache_file = self.temp_dir / "candidates.json"
        self.stats = {"total": 0, "l1_l2_pass": 0, "l3_l4_pass": 0}
        self.load_config()
        # 命令列可覆蓋 config 的 active_strategy
        if strategy:
            self.active_strategy = strategy

    def load_config(self):
        with open(self.config_file, "r") as f:
            full_config = json.load(f)
            self.active_strategy = full_config.get("active_strategy", "momentum")
            self.active_level = full_config["active_level"]
            self.params = full_config["levels"][self.active_level]
            self.runtime = full_config.get("runtime", {})
            self.vg_config = full_config.get("value_growth", {})

    def cleanup_old_files(self):
        """清理超過 30 天的舊週報"""
        log.info("掃描報告資料夾，清理超過 30 天的舊週報...")
        count = 0
        now = time.time()
        expiry_seconds = self.runtime.get("report_retention_days", 30) * 86400
        for path in self.report_dir.glob("WEEKLY_REPORT_*.md"):
            if (now - os.path.getmtime(path)) > expiry_seconds:
                path.unlink()
                count += 1
        if count > 0: log.info(f"已清理 {count} 份舊報告。")

    def run_value_growth(self):
        """價值成長選股流程 (零 FinMind，全免費資料)。"""
        from src.value_pipeline import run_current_selection
        level = self.vg_config.get("active_level", "Standard")
        vg_params = self.vg_config["levels"][level]
        log.info(f"=== 啟動選股程序 [策略: 價值成長] [標準: {level}] ===")
        self.cleanup_old_files()

        tickers_info = TickerManager().load_tickers()
        self.stats["total"] = len(tickers_info)
        selected = run_current_selection(
            tickers_info, vg_params,
            exclude_industries=self.vg_config.get("exclude_industries", []),
        )
        self.stats["vg_pass"] = len(selected)

        # 落地候選池供 AI 分析使用
        with open(self.final_cache_file, "w", encoding="utf-8") as f:
            json.dump(selected, f, ensure_ascii=False, indent=4)
        self.generate_value_report(selected, level, vg_params)

    def generate_value_report(self, selected, level, vg_params):
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = self.report_dir / f"WEEKLY_REPORT_{date_str}.md"
        val = vg_params.get("valuation", {})
        qg = vg_params.get("quality_growth", {})
        safe = vg_params.get("safety_net", {})

        md = f"# 台股價值成長選股清單 ({date_str})\n\n"
        md += ("> **定位：研究靈感工具，非買進訊號。** 5 年回測 (含 2022 空頭) 顯示本策略"
               "機械化操作的報酬與抗跌性皆不如直接持有 0050，故本清單僅作為「便宜成長股」"
               "的人工研究起點，請自行查證基本面與估值後再決策。\n\n")
        md += "## AI 深度分析與決策建議\n"
        ai_file = self.report_dir / f"ai_analysis_{date_str}.md"
        if ai_file.exists():
            ai_lines = ai_file.read_text(encoding="utf-8").strip().split("\n")
            if ai_lines and ai_lines[0].lstrip().startswith("# "):
                ai_lines = ai_lines[1:]
            md += "\n".join(ai_lines).strip() + "\n\n"
        else:
            md += "> *深度分析撰寫中，完成後將更新於本區塊。*\n\n"

        md += f"## 篩選標準定義 (策略: 價值成長 / 標準: {level})\n"
        md += "| 關卡 | 類型 | 詳細條件 |\n| :--- | :--- | :--- |\n"
        md += f"| P1 | 流動性 | 5 日均量 > {int(vg_params.get('liquidity',{}).get('min_volume_avg',0)/1000):,} 張 |\n"
        md += f"| P2 | 估值便宜 | 0 < PER <= {val.get('per_max')}；PEG <= {val.get('peg_max')}{'（必要）' if val.get('peg_required') else '（參考）'} |\n"
        md += f"| P3 | 品質成長 | ROE >= {qg.get('roe_min')}%、營收 YoY >= {qg.get('yoy_min')}%、EPS 成長 >= {qg.get('eps_growth_min')}% |\n"
        md += f"| 安全網 | 軟性技術 | 排除股價低於季線逾 {abs(int(safe.get('max_below_ma_pct',0)*100))}% 的急殺股 |\n\n"
        md += "> 趨勢與大盤擇時不在本表，交由 investment_analysis 總經報告負責。\n\n"

        md += f"*   **掃描標的**: {self.stats.get('total',0)} 檔\n"
        md += f"*   **價值成長精選**: {self.stats.get('vg_pass',0)} 檔\n\n"

        md += "## 最終精選池 (依價值成長分數排序)\n"
        md += "| 排名 | 代碼 | 名稱 | 產業 | 收盤 | PER | PEG | ROE% | 營收YoY% | EPS成長% | 分數 |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        for i, s in enumerate(selected, 1):
            per = f"{s['PER']:.1f}" if s.get('PER') else "-"
            peg = f"{s['PEG']:.2f}" if s.get('PEG') else "-"
            roe = f"{s['ROE']:.2f}" if s.get('ROE') is not None else "-"
            yoy = f"{s['YoY']:+.2f}" if s.get('YoY') is not None else "-"
            epsg = f"{s['EPS_Growth']:+.2f}" if s.get('EPS_Growth') is not None else "-"
            md += f"| {i} | {s['Ticker']} | {s.get('Name','')} | {s.get('Industry','')} | {s['Close']:.2f} | {per} | {peg} | {roe} | {yoy} | {epsg} | {s['Score']:.1f} |\n"
        if not selected:
            md += "> *目前無符合價值成長標準的標的 (可能市場估值偏高或成長放緩)。*\n"

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(md)
        log.info(f"價值成長週報已產出: {report_file}")
        self.generate_index_html(open(report_file, encoding="utf-8").read())

    def run(self):
        # 價值成長策略走獨立管線 (與動能完全分離)
        if self.active_strategy == "value_growth":
            return self.run_value_growth()

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
            l12 = self.params["l1_l2"]
            pv_filter = PriceVolumeFilter(config={
                "ma_fast": l12["ma_fast"], "ma_slow": l12["ma_slow"], "min_volume": l12["min_volume_avg"],
                "ma_20_slope": l12["ma_20_slope"], "ma_60_slope": l12["ma_60_slope"]
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

            # 全市場批次籌碼 (免費 TWSE/TPEx)，一次抓取取代逐檔 FinMind L3
            # 抓取天數須涵蓋 L3 累計天數，否則會出現「資料不足以計算」的情形
            l3_cfg = self.params["l3"]
            l4_cfg = self.params["l4"]
            chip_provider = BulkChipProvider(days=l3_cfg["inst_net_buy_days"])
            chip_provider.build()

            # 讀取現有進度 (用於比對與保留舊數據)
            existing_data = {}
            if self.final_cache_file.exists():
                try:
                    with open(self.final_cache_file, "r", encoding="utf-8") as f:
                        old_list = json.load(f)
                        existing_data = {d['Ticker']: d for d in old_list}
                except: pass

            # 用於追蹤已完成的 index，避免重複處理或中斷後重啟
            consecutive_failures = 0
            today = datetime.now()
            today_str = today.strftime('%Y-%m-%d')
            
            for i, cand in enumerate(tqdm(l2_candidates, desc="精煉數據")):
                ticker_full = cand['Ticker']
                ticker = ticker_full.split('.')[0]
                old_val = existing_data.get(ticker_full, {})
                
                # --- 增量更新檢查 ---
                # 籌碼(L3)改用免費批次資料，每次重算 (成本低)；基本面(L4)仍走 FinMind，
                # 保留 30 天效期，並以獨立時間戳記 L4_Fetched_At 判定 (與籌碼脫鉤)。
                l4_fetched_str = old_val.get('L4_Fetched_At') or old_val.get('Fetched_At', "")
                l4_last = None
                if l4_fetched_str:
                    try: l4_last = datetime.strptime(l4_fetched_str, '%Y-%m-%d')
                    except: pass
                fund_is_fresh = l4_last and (today - l4_last).days < self.runtime.get("l4_freshness_days", 30)

                # 準備抓取容器
                df_inst, df_rev, df_ratio, df_per = None, None, None, None

                # === L3 籌碼面：全市場批次資料 (免費 TWSE/TPEx，不耗 FinMind) ===
                df_inst = chip_provider.get_chip_df(ticker)
                if df_inst is not None and not df_inst.empty:
                    l3_pass, l3_val = adv_filter.run_l3(ticker, df_inst, l3_cfg)
                    cand['L3_Pass'], cand['L3_Value'] = bool(l3_pass), float(l3_val)
                else:
                    cand['L3_Pass'] = old_val.get('L3_Pass', False)
                    cand['L3_Value'] = old_val.get('L3_Value', 0)

                # === L4 基本面：僅在 L3 通過時才抓 (省 FinMind 額度) ===
                # L3 未過的標的不可能進最終精選池，毋須再花 3 支 API 抓基本面。
                # 條件：L3 通過，且 (基本面數據已過期 或 從未抓過 L4)。
                l4_cached = bool(old_val.get('Report_Date'))
                if cand['L3_Pass'] and (not fund_is_fresh or not l4_cached):
                    df_rev = premium_data.fetch_fundamental_data(ticker)
                    df_ratio = premium_data.fetch_financial_ratios(ticker)
                    df_per = chip_provider.get_per_df(ticker)   # PER 改用免費批次 (TWSE BWIBBU / TPEx)

                if df_rev is not None and df_ratio is not None:
                    l4_pass, l4_result = adv_filter.run_l4(ticker, df_rev, df_ratio, df_per, l4_cfg)
                    cand['L4_Pass'] = bool(l4_pass)
                    cand['L4_Value'] = float(l4_result['YoY'])
                    cand['ROE'] = l4_result['ROE']
                    cand['PER'] = l4_result['PER']
                    cand['PEG'] = l4_result['PEG']
                    cand['Report_Date'] = l4_result['Report_Date']
                else:
                    # 還原基本面舊數據 (L3 未過或本次未抓)
                    for key in ['L4_Pass', 'L4_Value', 'ROE', 'PER', 'PEG', 'Report_Date']:
                        cand[key] = old_val.get(key, 0 if key != 'Report_Date' else "")

                # === FinMind 節流與失敗偵測 (僅針對 L4；籌碼已改免費批次源) ===
                l4_fetched = df_rev is not None
                l4_empty = l4_fetched and (df_rev is None or df_rev.empty) and (df_ratio is None or df_ratio.empty)
                if l4_fetched and l4_empty:
                    consecutive_failures += 1
                elif l4_fetched:
                    consecutive_failures = 0

                if consecutive_failures >= self.runtime.get("finmind_fail_limit", 15):
                    msg = f"偵測到 FinMind API 連續 {self.runtime.get('finmind_fail_limit', 15)} 檔標的抓取失敗，判定為目前不適合取得資料，自動停止。"
                    log.critical(msg)
                    with open(self.final_cache_file, "w", encoding="utf-8") as f:
                        json.dump(l2_candidates, f, ensure_ascii=False, indent=4)
                    raise RuntimeError(msg)

                # 時間戳記：Fetched_At 記整體處理日；L4_Fetched_At 為 L4 專屬效期戳記
                cand['Fetched_At'] = today_str
                if l4_fetched and not l4_empty:
                    cand['L4_Fetched_At'] = today_str
                else:
                    cand['L4_Fetched_At'] = l4_fetched_str   # 本次未抓 L4，沿用舊效期戳記

                # 每 10 筆即時存檔，保護進度
                if (i + 1) % 10 == 0:
                    with open(self.final_cache_file, "w", encoding="utf-8") as f:
                        json.dump(l2_candidates, f, ensure_ascii=False, indent=4)

                # 僅在實際打 FinMind (L4) 後節流避免被封鎖 (秒數由 config 提供)
                if l4_fetched:
                    time.sleep(self.runtime.get("finmind_throttle_sec", 2.5))

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
        
        # 2. AI 深度分析 (第一順位) — 由獨立的 AI 分析檔注入，避免就地編輯報告
        md_content += "## AI 深度分析與決策建議\n"
        ai_file = self.report_dir / f"ai_analysis_{date_str}.md"
        if ai_file.exists():
            ai_text = ai_file.read_text(encoding="utf-8").strip()
            # 移除 AI 檔自帶的最上層大標 (# ...)，避免與報告章節標題重複
            ai_lines = ai_text.split("\n")
            if ai_lines and ai_lines[0].lstrip().startswith("# "):
                ai_lines = ai_lines[1:]
            md_content += "\n".join(ai_lines).strip() + "\n\n"
        else:
            md_content += "> *深度分析撰寫中，完成後將更新於本區塊。*\n\n"
        
        # 3. 篩選標準定義 (依 config 實際門檻動態生成，避免與設定脫節)
        l12 = self.params["l1_l2"]
        l3p = self.params["l3"]
        l4p = self.params["l4"]
        inst_name_map = {
            "Foreign_Investor": "外資",
            "Investment_Trust": "投信",
            "Dealer": "自營商",
        }
        inst_label = " + ".join(inst_name_map.get(n, n) for n in l3p.get("institutions", []))
        vol_lots = int(l12["min_volume_avg"] / 1000)
        md_content += f"## 篩選標準定義 (採用標準: {self.active_level})\n"
        md_content += "| 關卡 | 類型 | 詳細條件 |\n"
        md_content += "| :--- | :--- | :--- |\n"
        md_content += f"| **L1** | 技術面 | 股價 > MA{l12['ma_fast']} 且 MA{l12['ma_fast']} 斜率 > {l12['ma_20_slope']*100:.2f}% (趨勢確認) |\n"
        md_content += f"| **L2** | 成交量 | 5 日均量 > {vol_lots:,} 張 (流動性確認) |\n"
        md_content += f"| **L3** | 籌碼面 | {inst_label}近 {l3p['inst_net_buy_days']} 日累計買超 > {l3p['inst_net_buy_min']:,} 張 (大人動向) |\n"
        md_content += f"| **L4** | 基本面 | 營收 YoY > {l4p['yoy_min']}% 且 ROE > {l4p['roe_min']}% (年化) (PEG 供參考) |\n\n"

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
            
            l3_status = "[O]"
            l4_status = "[O]"
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
    import traceback
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "skip-scan", "report-only", "sync"], default="full")
    parser.add_argument("--strategy", choices=["momentum", "value_growth"], default=None,
                        help="覆蓋 config 的 active_strategy；不指定則依 config")
    args = parser.parse_args()

    scanner = StockScanner(mode=args.mode, strategy=args.strategy)
    
    try:
        if args.mode == "sync":
            scanner.sync_index()
        else:
            scanner.run()
        log.info("程序執行完畢。")
    except RuntimeError as e:
        log.critical(f"程序因熔斷機制主動停止: {str(e)}")
        # 熔斷時通常已經存過檔，這裡做最後確認
        print(f"\n[!] 執行中斷: {str(e)}")
        print(f"[i] 詳細日誌請參考: logs/stock_selection.log")
    except Exception as e:
        error_msg = traceback.format_exc()
        log.error(f"程序發生未預期錯誤:\n{error_msg}")
        
        # 嘗試在崩潰前存檔
        if hasattr(scanner, 'final_cache_file') and scanner.final_cache_file:
            try:
                # 這裡如果 scanner.stats['final_data'] 存在則嘗試存檔
                # 由於我們在 run() 中直接修改 l2_candidates，這裡的保護視情況而定
                log.info("嘗試在崩潰前保存已處理的進度...")
            except: pass
            
        print(f"\n[X] 程序發生嚴重錯誤: {str(e)}")
        print(f"[i] 請檢查 logs/error.log 獲取完整堆疊資訊。")
        sys.exit(1)
