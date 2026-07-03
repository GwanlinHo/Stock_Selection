#!/bin/bash
# 台股選股週報 - 全自動化流程 (Claude Code)
# 流程：掃描精煉 -> Claude 寫入專屬 AI 分析檔 -> 重生報告(注入) -> 同步 GitHub
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# cron 環境需顯式設定 PATH (claude 與 uv 皆位於 ~/.local/bin)
export PATH=/home/pi/.local/bin:$PATH:/home/pi/.config/nvm/versions/node/v22.17.0/bin
export PYTHONPATH=$PYTHONPATH:.

# 全域重型鎖(避免與其他 claude/ASR 併發 OOM);wait 模式:週報重要,寧可等也要跑。
source /home/pi/WorkDir/_lib/heavy_lock.sh
acquire_heavy_lock /home/pi/WorkDir/_logs/stock_selection_cron.log "stock_weekly" "wait" || exit 0

DATE=$(date +%Y-%m-%d)

echo "[1/4] 掃描 + 動能(無L3)選股 + 骨架報告 (full)..."
uv run main.py --mode full

echo "[2/4] Claude 深度分析，寫入專屬 AI 檔 reports/ai_analysis_${DATE}.md ..."
timeout 30m claude -p "請依照本專案目錄的 CLAUDE.md 為台股動能(無L3)選股週報撰寫 AI 分析，將內容以 Markdown 寫入 reports/ai_analysis_${DATE}.md，只用以下兩個 ## 標題：

## 宏觀趨勢與大盤研判
請讀取 /home/pi/WorkDir/investment_analysis/index.html (最新總經報告) 的內容，綜合其多空研判與風險水位，判斷本週是否適合進場（此為攻擊型選股，須多頭才進場）。

## 核心標的深度點評
讀取 data/temp/candidates.json (最終精選池)，針對分數前幾名的標的，結合產業趨勢與最新財報展望做去罐頭化深度點評，指出指標矛盾與風險。

要求：不得出現任何 AI 工具或模型名稱；繁體中文；只寫這一個檔，不要修改其他檔案、不要執行任何 git 指令。" --model claude-opus-4-8 --dangerously-skip-permissions

echo "[3/4] 重新生成報告 (注入 AI 分析) 與 index.html (report-only)..."
uv run main.py --mode report-only

echo "[4/4] 同步至 GitHub..."
./sync.sh

echo "執行完成！最新報告已產生並同步。"
