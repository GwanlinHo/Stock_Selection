# Gemini Stock Selection Workflow 指導手冊

## 常用指令

### 1. `stock selection` (完整執行)
啟動全流程掃描。適合每週五或週日執行。
*   **動作**: `uv run main.py --mode full` + AI 分析。

### 2. `stock selection skip` (跳過海選)
跳過 2000 檔標的的技術面掃描，直接讀取上一次的 L2 結果進行籌碼與基本面精煉。
*   **動作**: `uv run main.py --mode skip-scan` + AI 分析。
*   **適用情境**: 當您剛跑完掃描，想針對現有名單重新獲取最新法人數據時。

### 3. `stock selection report` (僅重新產生報告)
完全不抓取新數據，直接讀取上一次的精選結果產出 Markdown 週報。
*   **動作**: `uv run main.py --mode report-only` + AI 分析。
*   **適用情境**: 調整報告格式、或純粹想要我針對現有名單重新進行語意分析與新聞檢索時。

---

## 選股規範與風格要求

*   **禁止表情符號**: 嚴格禁止在程式碼、日誌、Markdown 報告或任何輸出文件中使用表情符號 (Emojis)。
*   **專業語氣**: 保持專業且簡潔的技術描述。
*   **狀態表示**: 若需表示狀態，請使用傳統符號（如 [O], [X], [!]）取代圖示。

當您下達上述指令後，我會：
1.  執行對應的 Python 模式。
2.  讀取 `data/temp/candidates.json`。
3.  對技術面最強的標的進行 `google_web_search`。
4.  將 AI 分析內容回填至 `reports/WEEKLY_REPORT_YYYY-MM-DD.md` 並呈現在對話中。
5.  將產生的報告與json檔上傳至github。
