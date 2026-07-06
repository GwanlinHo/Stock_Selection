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

# 朗讀功能(Web Speech API,與 investment_analysis 報告同款作法):
# 只對「宏觀趨勢與大盤研判 / 核心標的深度點評 / 策略回測績效」三個 h2 區塊插入朗讀按鈕;
# 表格逐列轉成「欄名 值」口語句子再唸,避免唸出一串無上下文的數字。
TTS_ASSETS = r"""
    <style>
        .tts-btn { background: #f0f2f5; border: 1px solid #ddd; border-radius: 20px; padding: 4px 14px; font-size: 14px; font-weight: 600; color: #555; cursor: pointer; margin-left: 12px; vertical-align: middle; transition: all 0.2s; }
        .tts-btn:hover { background: #e4e6e9; border-color: #ccc; }
        .tts-btn.playing { background: #e8f5e9; color: #2e7d32; border-color: #c8e6c9; }
    </style>
    <script>
    (function () {
        var TTS_SECTIONS = ["宏觀趨勢與大盤研判", "核心標的深度點評", "策略回測績效"];
        var synth = window.speechSynthesis;
        if (!synth) return;
        var activeBtn = null;
        var chunks = [];
        var idx = 0;

        function tableToSpeech(tbl) {
            var headers = Array.prototype.map.call(tbl.querySelectorAll("thead th"), function (th) { return th.innerText.trim(); });
            var out = [];
            Array.prototype.forEach.call(tbl.querySelectorAll("tbody tr"), function (tr) {
                var parts = [];
                Array.prototype.forEach.call(tr.querySelectorAll("td,th"), function (td, i) {
                    var c = td.innerText.trim();
                    if (!c || c === "-" || c === "--") return; // 空值欄不唸
                    parts.push(i === 0 || !headers[i] ? c : headers[i] + " " + c);
                });
                if (parts.length) out.push(parts.join("，") + "。");
            });
            return out.join(" ");
        }

        function sectionText(nodes, title) {
            var buf = [title + "。"];
            nodes.forEach(function (n) {
                if (n.tagName === "TABLE") buf.push(tableToSpeech(n));
                else buf.push(n.innerText || "");
            });
            return buf.join(" ").replace(/\s+/g, " ").trim();
        }

        function stopTTS() {
            synth.cancel();
            if (activeBtn) { activeBtn.classList.remove("playing"); activeBtn.textContent = "朗讀"; }
            activeBtn = null; chunks = []; idx = 0;
        }

        function pickVoice() {
            var voices = synth.getVoices();
            var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
            var isAndroid = /Android/.test(navigator.userAgent);
            var v = null;
            if (isIOS) {
                v = voices.find(function (x) { return x.lang.indexOf("zh-TW") >= 0 && x.name.indexOf("Siri") >= 0; }) ||
                    voices.find(function (x) { return x.lang.indexOf("zh-TW") >= 0 && (x.name.indexOf("Mei-Jia") >= 0 || x.name.indexOf("Ting-Ting") >= 0); });
            } else if (isAndroid) {
                v = voices.find(function (x) { return x.lang.indexOf("zh-TW") >= 0 && x.name.indexOf("Google") >= 0; });
            }
            return v || voices.find(function (x) { return x.lang.indexOf("zh-TW") >= 0; }) ||
                        voices.find(function (x) { return x.lang.indexOf("zh") >= 0; }) || null;
        }

        function speakNext() {
            if (idx >= chunks.length || !activeBtn) { stopTTS(); return; }
            var u = new SpeechSynthesisUtterance(chunks[idx]);
            var v = pickVoice();
            if (v) u.voice = v;
            u.lang = "zh-TW";
            u.onend = function () { idx++; speakNext(); };
            u.onerror = function () { stopTTS(); };
            synth.speak(u);
        }

        function toggle(btn, text) {
            if (synth.speaking && activeBtn === btn) { stopTTS(); return; }
            if (synth.speaking) stopTTS();
            chunks = text.match(/[^。！？；]+[。！？；]?/g) || [text];
            idx = 0; activeBtn = btn;
            btn.classList.add("playing"); btn.textContent = "停止";
            speakNext();
        }

        document.addEventListener("visibilitychange", function () { if (document.hidden) stopTTS(); });
        if (speechSynthesis.onvoiceschanged !== undefined) {
            speechSynthesis.onvoiceschanged = function () { synth.getVoices(); };
        }

        Array.prototype.forEach.call(document.querySelectorAll(".markdown-body h2"), function (h2) {
            var title = h2.innerText.trim();
            if (!TTS_SECTIONS.some(function (t) { return title.indexOf(t) === 0; })) return;
            var nodes = [];
            var n = h2.nextElementSibling;
            while (n && n.tagName !== "H2") { nodes.push(n); n = n.nextElementSibling; }
            if (!nodes.length) return;
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "tts-btn";
            btn.textContent = "朗讀";
            btn.addEventListener("click", function () { toggle(btn, sectionText(nodes, title)); });
            h2.appendChild(btn);
        });
    })();
    </script>"""

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

    def _backtest_section(self, strategy_key):
        """讀取 data/backtest_summary.json，產生「策略回測績效」區塊；無檔則回空字串。"""
        f = Path("data/backtest_summary.json")
        if not f.exists():
            return ""
        try:
            s = json.load(open(f, encoding="utf-8"))
        except Exception:
            return ""
        st = s.get("strategies", {}).get(strategy_key)
        if not st:
            return ""
        b = s.get("benchmark", {})
        md = f"## 策略回測績效 (截至 {s.get('as_of','')})\n"
        md += f"- 回測期間 {s.get('period','')}；月頻換股、前 {s.get('top_n','')} 檔等權重、對標 0050\n\n"
        md += "| 指標 | 本策略 | 0050 |\n| :--- | :--- | :--- |\n"
        md += f"| 總報酬率 | {st.get('total_return')}% | {b.get('total_return')}% |\n"
        md += f"| 年化 CAGR | {st.get('cagr')}% | - |\n"
        md += f"| 最大回檔 | {st.get('max_drawdown')}% | {b.get('max_drawdown')}% |\n"
        md += f"| Sharpe | {st.get('sharpe')} | - |\n\n"
        md += "> 歷史回測 (含存活者偏誤、未計交易成本)，非未來績效保證。執行 `uv run run_summary.py` 可更新。\n\n"
        return md

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

        md += self._backtest_section("value_growth")

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

    def run_momentum_live(self):
        """動能選股流程 (無 L3、零 FinMind、走可插拔平台；與回測同一套邏輯)。"""
        from src.strategies import get_strategy, DataContext
        from src.data_ingestion import DataIngestion
        from src.data_free import BulkRevenueProvider, BulkFinancialProvider
        from src.fundamentals import FundamentalsAssembler

        level = self.active_level
        params = self.params   # config levels[active_level]: l1_l2 / l3 / l4
        log.info(f"=== 啟動選股程序 [策略: 動能(無L3)] [標準: {level}] ===")
        self.cleanup_old_files()

        tickers_info = TickerManager().load_tickers()
        self.stats["total"] = len(tickers_info)
        universe = {str(t['Ticker']).split('.')[0]:
                    {"yfinance_ticker": t['yfinance_ticker'], "Name": t.get('Name', ''),
                     "Industry": t.get('Industry', '')} for t in tickers_info}

        if self.mode == "report-only" and self.final_cache_file.exists():
            picks = json.load(open(self.final_cache_file, encoding="utf-8"))
        else:
            raw = DataIngestion(batch_size=50).fetch_weekly_data(
                [t['yfinance_ticker'] for t in tickers_info])
            ctx = DataContext(universe, raw,
                              FundamentalsAssembler(BulkFinancialProvider()),
                              BulkRevenueProvider(),
                              self.vg_config.get("exclude_industries", []),
                              chip_provider=None)   # 不帶籌碼 = 無 L3
            strat = get_strategy("momentum")
            metrics = strat.assemble(ctx, datetime.now().date())
            picks = strat.select(metrics, params)
            with open(self.final_cache_file, "w", encoding="utf-8") as f:
                json.dump(picks, f, ensure_ascii=False, indent=4)

        self.stats["mom_pass"] = len(picks)
        self.generate_momentum_report(picks, level, params)

    def generate_momentum_report(self, picks, level, params):
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_file = self.report_dir / f"WEEKLY_REPORT_{date_str}.md"
        l12, l4 = params["l1_l2"], params["l4"]

        md = f"# 台股動能選股週報 ({date_str})\n\n"
        md += (
            "> **本工具策略重心（請勿遺忘）**\n>\n"
            "> 這是「攻擊型個股選股」工具，與 `investment_analysis`（總經擇時/防守）分工："
            "後者判斷多空與股債現金配置、決定**何時**進場；本工具決定多頭時**買哪些股**。\n>\n"
            "> production 採「**動能（無 L3）**」：經 5 年回測（含 2022 空頭）為各攻擊型策略中"
            "表現最佳者（加 L3 法人籌碼、價值成長型皆較差，已捨棄）。\n>\n"
            "> **重要**：機械化操作下無一策略能穩定勝過 0050，務必搭配 investment_analysis 的"
            "多空研判、**僅在多頭時進場**，本清單僅為選股依據而非擇時訊號。\n\n")
        # AI 三段 (宏觀趨勢 / 核心標的深度點評) 由 ai_analysis 檔注入；缺檔則留骨架
        ai_file = self.report_dir / f"ai_analysis_{date_str}.md"
        if ai_file.exists():
            ai_lines = ai_file.read_text(encoding="utf-8").strip().split("\n")
            if ai_lines and ai_lines[0].lstrip().startswith("# "):
                ai_lines = ai_lines[1:]
            md += "\n".join(ai_lines).strip() + "\n\n"
        else:
            md += ("## 宏觀趨勢與大盤研判\n> *待 AI 撰寫：綜合 investment_analysis 總經訊號，"
                   "研判目前多空格局與風險水位，決定本週是否適合進場。*\n\n")
            md += ("## 核心標的深度點評\n> *待 AI 撰寫：針對精選池前幾名，結合產業趨勢與最新"
                   "財報展望做深度點評，並指出指標矛盾與風險。*\n\n")

        md += f"## 篩選標準定義 (策略: 動能(無L3) / 標準: {level})\n"
        md += "| 關卡 | 類型 | 詳細條件 |\n| :--- | :--- | :--- |\n"
        md += f"| L1 | 趨勢 | 收盤 > MA{l12['ma_fast']} 且 MA{l12['ma_fast']} 斜率 > {l12['ma_20_slope']*100:.2f}%、MA{l12['ma_slow']}不下彎 |\n"
        md += f"| L2 | 量能 | 5 日均量 > {int(l12['min_volume_avg']/1000):,} 張 |\n"
        md += f"| L4 | 基本面 | 營收 YoY > {l4['yoy_min']}% 且 ROE > {l4['roe_min']}% |\n\n"
        md += ("> L3 法人籌碼經回測證實會降低報酬，已移除。趨勢/大盤擇時請參考 investment_analysis 總經報告；"
               "回測顯示本策略接近但未穩定勝過 0050，宜搭配多空研判 (多頭才進場) 使用。\n\n")

        md += f"*   **掃描標的**: {self.stats.get('total',0)} 檔\n"
        md += f"*   **動能精選**: {self.stats.get('mom_pass',0)} 檔\n\n"

        md += self._backtest_section("momentum")

        md += "## 最終精選池 (依 MA20 斜率排序)\n"
        md += "| 排名 | 代碼 | 名稱 | 產業 | 收盤 | MA20斜率 | ROE% | 營收YoY% | 分數 |\n"
        md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        for i, s in enumerate(picks, 1):
            roe = f"{s['ROE']:.2f}" if s.get('ROE') is not None else "-"
            yoy = f"{s['YoY']:+.2f}" if s.get('YoY') is not None else "-"
            slope = f"{s.get('M20_Slope', 0):.4f}"
            md += (f"| {i} | {s['Ticker']} | {s.get('Name','')} | {s.get('Industry','')} | "
                   f"{s['Close']:.2f} | {slope} | {roe} | {yoy} | {s['Score']:.1f} |\n")
        if not picks:
            md += "> *目前無符合動能標準的標的 (可能大盤轉弱，宜保守)。*\n"

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(md)
        log.info(f"動能週報已產出: {report_file}")
        self.generate_index_html(open(report_file, encoding="utf-8").read())

    def run(self):
        # 各策略走可插拔平台 (零 FinMind)
        if self.active_strategy == "value_growth":
            return self.run_value_growth()
        if self.active_strategy == "momentum":
            return self.run_momentum_live()

        raise ValueError(f"未知策略: {self.active_strategy}")

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
{TTS_ASSETS}
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
    import sys

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
        
        # 註：run() 過程中的中間結果已於各階段即時落檔（見 scanner.run()），
        # 此處不再嘗試二次存檔，避免給人「有崩潰保護」的錯覺（原假存檔區塊已移除）。
        print(f"\n[X] 程序發生嚴重錯誤: {str(e)}")
        print(f"[i] 請檢查 logs/error.log 獲取完整堆疊資訊。")
        sys.exit(1)
