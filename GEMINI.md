# Gemini Stock Selection Workflow 指導手冊

當使用者輸入 `stock selection` 或要求執行選股時，請執行以下 Workflow：

### 階段 1-3：數據掃描與初步篩選
1.  執行 `uv run main.py`。
2.  讀取 `data/temp/candidates.json`。

### 階段 4：AI 深度分析 (由 Agent 執行)
1.  **標的選擇**：從數據中挑選技術面斜率最強、且籌碼或基本面有 ✅ 的前 5-8 檔。
2.  **新聞搜尋**：對每檔標的執行 `google_web_search`。
3.  **報告撰寫**：
    *   **數據面板**：列出該標的的收盤價、MA20斜率、5日均量、法人買賣狀態、營收狀態。
    *   **新聞摘要**：彙整搜尋到的利多或利空。
    *   **決策理由**：根據數據與新聞進行 A/B/C 組分類，並給出理由。

### 階段 5：存檔報告
1.  將彙整後的精選報告存至 `reports/WEEKLY_REPORT_YYYY-MM-DD.md`。

---

## 常用指令
*   `stock selection`: 啟動全自動選股並生成詳細數據週報。
