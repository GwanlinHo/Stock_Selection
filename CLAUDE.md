# Stock Selection Workflow 指導手冊

## 常用指令

### 1. `stock selection` (完整執行)
啟動全流程掃描。適合每週五或週日執行。
*   **動作**: `uv run main.py --mode full` + AI 分析 + **更新 index.html** + **Git 同步 (GitHub)**。

### 2. `stock selection skip` (跳過海選)
跳過 2000 檔標的的技術面掃描，直接讀取上一次的 L2 結果進行籌碼與基本面精煉。
*   **動作**: `uv run main.py --mode skip-scan` + AI 分析 + **更新 index.html** + **Git 同步 (GitHub)**。

### 4. `stock selection sync` (僅同步網頁內容)
當手動修改了 `reports/*.md` 檔案（例如填入 AI 分析）後，執行此指令同步至 `index.html`。
*   **動作**: `uv run main.py --mode sync` + **Git 同步 (GitHub)**。

---

## 價值成長策略 (value_growth) — 與動能並存

另有一套「價值成長」選股 (分支 feat/value-growth-backtest 開發)，與上述動能策略**並存且不重疊**：
動能抓「已轉強的強勢股」、價值成長抓「便宜的成長股 (低 PER/PEG + 高 ROE + 營收成長)」。
趨勢/大盤擇時交由 investment_analysis (總經報告) 負責，本策略刻意不含趨勢與籌碼條件。

*   **切換**: `config/settings.json` 的 `active_strategy` (momentum | value_growth)，或 `--strategy value_growth`。
*   **當期選股**: `uv run main.py --strategy value_growth --mode full`
*   **回測**: `uv run run_backtest.py --years 5 --top 15`  (首跑會下載價格長歷史並快取；之後加 `--no-fetch`)
*   **資料源**: 全程免費、零 FinMind。月營收/財報走 mopsov 批次端點 (見 src/data_free.py)，PER/籌碼走既有 TWSE/TPEx。

### 重要：回測結論 (務必告知使用者，勿誤用)
5 年回測 (2021-2026，含 2022 空頭) 顯示此策略**機械化操作的報酬 (CAGR 19%) 與最大回檔 (-50%) 皆顯著不如直接持有 0050** (報酬 270%、回檔 -34%)。3 年版那個漂亮的低回檔是「無空頭環境」造成的假象。
**因此此策略定位為「選股靈感/研究清單工具」，不可當作機械化交易訊號或抗跌衛星。** 產出清單僅供人工進一步研究。

---

## 選股規範與風格要求

*   **禁止表情符號**: 嚴格禁止在程式碼、日誌、Markdown 報告或任何輸出文件中使用表情符號 (Emojis)。
*   **不尋找 API Key**: 絕對不要嘗試尋找、請求或設定 API Key (例如 FinMind Token)。系統應直接使用預設的匿名模式執行。
*   **專業語氣**: 保持專業且簡潔的技術描述。
*   **狀態表示**: 若需表示狀態，請使用傳統符號（如 [O], [X], [!]）取代圖示。
*   **自動化更新**: 每次產生或手動修改 `.md` 報告後，**必須執行 `uv run main.py --mode sync`**，確保 `index.html` 內容與最新報告完全同步。
*   **強制同步**: 每次完成報告更新（含 .md 與 index.html）後，**必須執行 git add/commit/push 將成果同步至 GitHub**。

當您下達上述指令後，我會：
1.  執行對應的 Python 模式（系統具備 **Soft Fail 機制**，若 API 抓取失敗將自動沿用舊數據）。
2.  讀取 `data/temp/candidates.json`。
3.  **由 Claude Code 執行深度分析**：
    *   **統計分類**：識別 L4 通過標的的產業分佈。
    *   **深度檢索**：針對 A 級潛力股使用 WebSearch 工具搜尋。
    *   **去罐頭化寫作**：結合最新趨勢與 Python 財務數據，手動撰寫具備洞察力的分析內容。
4.  將 AI 分析內容回填至 `reports/WEEKLY_REPORT_YYYY-MM-DD.md`。
5.  **強制同步**：更新 `index.html` 並推送到 GitHub。

---

## AI 分析 Prompt 規範
為避免分析內容「罐頭化」，分析時應遵循：
*   **拒絕數字重複**：不要只說「營收 YoY 很高」，要解釋「營收為何高」（如：Blackwell 需求、轉型車用成功）。
*   **尋找指標矛盾**：若 PER 高但評等為 A，必須給出理由；若 PEG 極低但評等為 C，必須指出潛在風險。
*   **標註時效性**：若有 `[!]` 標記，優先閱讀最新財報中的展望描述。
