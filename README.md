# 台股多策略選股與回測平台

[![Report](https://img.shields.io/badge/最新選股報告-GitHub_Pages-blue?style=for-the-badge)](https://gwanlinho.github.io/Stock_Selection/)

一套「可裝載多種攻擊型策略、全程免費資料、且可回測驗證」的台股選股平台。
與 `investment_analysis`（由上而下的總經擇時/防守）分工：本平台負責由下而上的
**個股攻擊型選股**，提供可選的策略，並以回測驗證其歷史表現。

核心特性：

- **可插拔策略平台**：當期選股與回測共用「同一個策略物件」（`assemble + select`），
  確保「回測的邏輯 = 實跑的邏輯」，新增策略只需實作兩個方法。
- **零 FinMind、全免費資料**：價量、PER、籌碼、月營收、財報全部來自 yfinance 與
  TWSE / TPEx / MOPS 的免費端點，無 API 額度與限流風險。
- **內建回測引擎**：月頻換股、等權重、時點對齊（避免前視偏誤）、對標 0050，
  並將績效摘要回寫，使每份選股報告都附上策略的歷史回測表現。

---

## 內建策略

| 策略 | 定位 | 邏輯 | 狀態 |
| :--- | :--- | :--- | :--- |
| **動能 (無 L3)** | **production 週報** | L1 站上並翻揚的均線趨勢 + L2 量能 + L4 基本面 (營收YoY、ROE)。回測證實 L3 法人籌碼反而降低報酬，故移除。 | 預設 |
| **價值成長** | 選股靈感工具 | 估值便宜 (低 PER/PEG) + 品質 (高 ROE) + 成長 (營收YoY)，含軟性安全網避開急殺股。 | 可選 |

> 趨勢/大盤多空與股債現金配置由 `investment_analysis` 負責；本平台不做擇時。

---

## 安裝

```bash
uv sync
```
無需任何 API Key（不使用 FinMind / 不需 token）。

---

## 常用指令

### 當期選股（產生週報）
```bash
uv run main.py --strategy momentum --mode full       # 動能(無L3)，production 預設
uv run main.py --strategy value_growth --mode full   # 價值成長
uv run main.py --mode full                            # 依 config 的 active_strategy
uv run main.py --mode sync                            # 僅將最新 .md 報告同步到 index.html
```
產出 `reports/WEEKLY_REPORT_YYYY-MM-DD.md` 與 `index.html`（GitHub Pages）。
報告含：宏觀趨勢、核心標的深度點評（AI 撰寫）、篩選標準、策略回測績效、最終精選池。

### 回測
```bash
uv run run_backtest.py --strategy momentum --years 5 --top 15            # 動能(無L3)
uv run run_backtest.py --strategy momentum --years 5 --with-chips        # 動能(含L3 法人籌碼)
uv run run_backtest.py --strategy value_growth --years 5                 # 價值成長
uv run run_backtest.py ... --no-fetch                                    # 僅用既有快取，不下載
```
首跑會下載價格長歷史並快取於 `data/cache_bt/`；`--with-chips` 首跑會逐日補抓歷史法人籌碼。

### 策略總結（多策略對比 + 更新報告用的回測摘要）
```bash
uv run run_summary.py --years 5 --top 15
```
產出 `reports/SUMMARY_REPORT_*.{md,html}`（四方淨值疊圖 + 對比表）並回寫
`data/backtest_summary.json`（供每份選股報告嵌入回測績效）。

---

## 設定 (`config/settings.json`)

- `active_strategy`：`momentum` | `value_growth`（命令列 `--strategy` 可覆蓋）。
- `active_level` + `levels`：動能組三檔標準（Strict/Neutral/Loose）的 `l1_l2` / `l3` / `l4` 門檻。
- `value_growth`：價值成長三檔標準（`liquidity` / `valuation` / `quality_growth` / `safety_net`）
  與 `exclude_industries`（預設排除金融保險業）。
- `runtime`：報告保留天數、節流等執行參數。

---

## 免費資料來源（零 FinMind）

| 資料 | 來源 | 模組 |
| :--- | :--- | :--- |
| 日線價量 | yfinance | `src/data_ingestion.py`、回測長歷史 `src/backtest.py` |
| 本益比 PER / 籌碼(當期) | TWSE BWIBBU / T86、TPEx | `src/data_bulk.py` |
| 歷史法人籌碼(回測 L3) | TWSE T86 / TPEx（逐日） | `src/data_chips.py` |
| 月營收 + YoY | MOPS `mopsov` t21sc03 | `src/data_free.py` |
| 財報（淨利/權益/EPS） | MOPS `mopsov` ajax_t163sb04/sb05 | `src/data_free.py` |
| TTM ROE / EPS 成長 | 由上述財報換算（去累計） | `src/fundamentals.py` |

均為全市場批次端點（單期一次抓取）、永久快取。屬類爬蟲，已加 User-Agent、節流與重試。

---

## 回測結論（2021-06 ～ 2026-06，含 2022 空頭，月頻、前 15 檔等權重）

| 指標 | 動能(無L3) | 動能(含L3) | 價值成長 | 0050 |
| :--- | :--- | :--- | :--- | :--- |
| 總報酬 | +236.6% | +157.3% | +138.3% | +249.6% |
| 最大回檔 | -40.9% | -44.0% | -50.2% | ~-34% |
| Sharpe | 0.86 | 0.73 | 0.76 | - |

重點發現：

1. **動能(無 L3) 最佳**，且最接近 0050；故 production 採用此版。
2. **加 L3 法人籌碼反而扣分**（等籌碼確認會錯過中小型起漲段）。
3. **價值成長在 AI 權值股大多頭中最弱**，已定位為選股靈感工具。
4. **無一策略穩定勝過 0050**——機械化全程持有下最佳者僅接近大盤且回檔更深；
   宜搭配 `investment_analysis` 的多空研判（多頭才進場）使用。

> 所有回測含存活者偏誤（標的池採目前清單）、未計交易成本，結果偏樂觀，非未來保證。

---

## 目錄結構

- `main.py`：當期選股入口（策略分派 + 報告產出）。
- `run_backtest.py` / `run_summary.py`：回測與多策略總結入口。
- `src/strategies.py`：策略介面、`DataContext`、動能/價值策略。
- `src/backtest.py`：回測引擎與報告（含 SVG 淨值曲線）。
- `src/data_free.py`、`src/data_chips.py`、`src/data_bulk.py`、`src/data_ingestion.py`：免費資料源。
- `src/fundamentals.py`：財報指標換算。
- `config/settings.json`：策略與門檻設定。
- `data/cache/`、`data/cache_bt/`：資料快取（已 gitignore）。
- `data/backtest_summary.json`：最新回測摘要（供報告嵌入）。
- `reports/`：選股週報與回測報告。
