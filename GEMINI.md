# Gemini Stock Selection Workflow 指導手冊

## 常用指令

### 1. `stock selection` (完整執行)
啟動全流程掃描。適合每週五或週日執行。
*   **動作**: `uv run main.py --mode full` + AI 分析 + **更新 index.html** + **Git 同步 (GitHub)**。

### 2. `stock selection skip` (跳過海選)
跳過 2000 檔標的的技術面掃描，直接讀取上一次的 L2 結果進行籌碼與基本面精煉。
*   **動作**: `uv run main.py --mode skip-scan` + AI 分析 + **更新 index.html** + **Git 同步 (GitHub)**。

### 3. `stock selection report` (僅重新產生報告)
完全不抓取新數據，直接讀取上一次的精選結果產出 Markdown 週報。
*   **動作**: `uv run main.py --mode report-only` + AI 分析 + **更新 index.html** + **Git 同步 (GitHub)**。

---

## 選股規範與風格要求

*   **禁止表情符號**: 嚴格禁止在程式碼、日誌、Markdown 報告或任何輸出文件中使用表情符號 (Emojis)。
*   **專業語氣**: 保持專業且簡潔的技術描述。
*   **狀態表示**: 若需表示狀態，請使用傳統符號（如 [O], [X], [!]）取代圖示。
*   **原子化更新**: 每次產生或手動修改 `.md` 報告後，**必須立即更新 `index.html`**，確保 GitHub Pages 內容與最新報告完全同步。
*   **強制同步**: 每次完成報告更新（含 .md 與 index.html）後，**必須執行 git add/commit/push 將成果同步至 GitHub**。

當您下達上述指令後，我會：
1.  執行對應的 Python 模式。
2.  讀取 `data/temp/candidates.json`。
3.  **執行去罐頭化 AI 分析**：
    *   **統計分類**：識別 L4 通過標的的產業分佈。
    *   **深度檢索**：針對「評等 A」或「技術面最強」的標的，必須執行 `google_web_search` 查詢最新產業動態（如：法說會展望、關鍵訂單、技術突破）。
    *   **質化回填**：將搜尋到的外部資訊與 Python 產出的財務數據結合，產出具備「故事性」與「前瞻性」的分析理由。
4.  將 AI 分析內容回填至 `reports/WEEKLY_REPORT_YYYY-MM-DD.md` 並呈現在對話中。
5.  **立即同步更新 `index.html` 並將所有檔案上傳至 GitHub。**

---

## AI 分析 Prompt 規範
為避免分析內容「罐頭化」，分析時應遵循：
*   **拒絕數字重複**：不要只說「營收 YoY 很高」，要解釋「營收為何高」（如：Blackwell 需求、轉型車用成功）。
*   **尋找指標矛盾**：若 PER 高但評等為 A，必須給出理由；若 PEG 極低但評等為 C，必須指出潛在風險。
*   **標註時效性**：若有 `[!]` 標記，優先閱讀最新財報中的展望描述。

