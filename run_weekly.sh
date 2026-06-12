#!/bin/bash
# 台股選股週報 - 全自動化流程 (Claude Code)
# 流程：掃描精煉 -> Claude 寫入專屬 AI 分析檔 -> 重生報告(注入) -> 同步 GitHub
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# cron 環境需顯式設定 PATH (claude 與 uv 皆位於 ~/.local/bin)
export PATH=/home/pi/.local/bin:$PATH:/home/pi/.config/nvm/versions/node/v22.17.0/bin
export PYTHONPATH=$PYTHONPATH:.

DATE=$(date +%Y-%m-%d)

echo "[1/4] 掃描 + 籌碼/基本面精煉 + 骨架報告 (full)..."
uv run main.py --mode full

echo "[2/4] Claude 深度分析，寫入專屬 AI 檔 reports/ai_analysis_${DATE}.md ..."
claude -p "請依照本專案目錄的 CLAUDE.md 執行台股選股深度分析：讀取 data/temp/candidates.json，針對 L3 與 L4 全通過的最終精選池標的，做去罐頭化的深度分析（宏觀趨勢、核心標的深度點評、指標矛盾與風險）。將分析內容以 Markdown 寫入 reports/ai_analysis_${DATE}.md。要求：不得出現任何 AI 工具或模型名稱；只寫這一個檔，不要修改其他檔案、不要執行任何 git 指令。" --model claude-opus-4-8 --dangerously-skip-permissions

echo "[3/4] 重新生成報告 (注入 AI 分析) 與 index.html (report-only)..."
uv run main.py --mode report-only

echo "[4/4] 同步至 GitHub..."
./sync.sh

echo "執行完成！最新報告已產生並同步。"
