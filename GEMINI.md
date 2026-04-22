# Gemini Stock Selection Workflow 指導手冊

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

## 選股規範與風格要求

*   **禁止表情符號**: 嚴格禁止在程式碼、日誌、Markdown 報告或任何輸出文件中使用表情符號 (Emojis)。
*   **專業語氣**: 保持專業且簡潔的技術描述。
*   **狀態表示**: 若需表示狀態，請使用傳統符號（如 [O], [X], [!]）取代圖示。
*   **自動化更新**: 每次產生或手動修改 `.md` 報告後，**必須執行 `uv run main.py --mode sync`**，確保 `index.html` 內容與最新報告完全同步。
*   **強制同步**: 每次完成報告更新（含 .md 與 index.html）後，**必須執行 git add/commit/push 將成果同步至 GitHub**。

當您下達上述指令後，我會：
1.  執行對應的 Python 模式（系統具備 **Soft Fail 機制**，若 API 抓取失敗將自動沿用舊數據）。
2.  讀取 `data/temp/candidates.json`。
3.  **由 Gemini CLI 執行深度分析**：
    *   **統計分類**：識別 L4 通過標的的產業分佈。
    *   **深度檢索**：針對 A 級潛力股執行 `google_web_search`。
    *   **去罐頭化寫作**：結合最新趨勢與 Python 財務數據，手動撰寫具備洞察力的分析內容。
4.  將 AI 分析內容回填至 `reports/WEEKLY_REPORT_YYYY-MM-DD.md`。
5.  **強制同步**：更新 `index.html` 並推送到 GitHub。

---

## AI 分析 Prompt 規範
為避免分析內容「罐頭化」，分析時應遵循：
*   **拒絕數字重複**：不要只說「營收 YoY 很高」，要解釋「營收為何高」（如：Blackwell 需求、轉型車用成功）。
*   **尋找指標矛盾**：若 PER 高但評等為 A，必須給出理由；若 PEG 極低但評等為 C，必須指出潛在風險。
*   **標註時效性**：若有 `[!]` 標記，優先閱讀最新財報中的展望描述。

