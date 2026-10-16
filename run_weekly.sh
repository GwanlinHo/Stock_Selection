#!/bin/bash
# 台股選股週報 - 全自動化流程 (Claude Code)
# 流程：掃描精煉 -> Claude 寫入專屬 AI 分析檔 -> 重生報告(注入) -> 同步 GitHub
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# cron 環境需顯式設定 PATH (claude 與 uv 皆位於 ~/.local/bin)
export PATH=/home/pi/.local/bin:$PATH:/home/pi/.node-current/bin
export PYTHONPATH=$PYTHONPATH:.

# 全域重型鎖(避免與其他 claude/ASR 併發 OOM);wait 模式:週報重要,寧可等也要跑。
source /home/pi/WorkDir/_lib/heavy_lock.sh
acquire_heavy_lock /home/pi/WorkDir/_logs/stock_selection_cron.log "stock_weekly" "wait" || exit 0

DATE=$(date +%Y-%m-%d)

echo "[1/4] 掃描 + 動能(無L3)選股 + 骨架報告 (full)..."
uv run main.py --mode full

echo "[2/4] Claude 深度分析，寫入專屬 AI 檔 reports/ai_analysis_${DATE}.md ..."
# 撰寫指示放在 config/ai_analysis_prompt.md（2026-10-16 改精簡版：上限 2,500 字、固定結構）
AI_OUT="reports/ai_analysis_${DATE}.md"
PREV=$(ls reports/ai_analysis_*.md 2>/dev/null | grep -v "_${DATE}.md" | sort | tail -1)
ISSUES="logs/system_issues_${DATE}.md"   # 撰寫時發現的系統問題（不進週報、不發布）
PROMPT=$(sed -e "/^<!--.*-->$/d" -e "s#__OUT__#${AI_OUT}#g" -e "s#__PREV__#${PREV:-（無）}#g" -e "s#__ISSUES__#${ISSUES}#g" config/ai_analysis_prompt.md)
timeout 30m claude -p "$PROMPT" --model claude-opus-5 --dangerously-skip-permissions

# 字數檢查：超過上限就要求壓縮一次（只計漢字，表格與數字不計）
MAX_ZH=2500
count_zh() { python3 -c "import re,sys;print(len(re.findall(r'[\u4e00-\u9fff]',open(sys.argv[1],encoding='utf-8').read())))" "$1"; }
if [ -f "$AI_OUT" ]; then
  N=$(count_zh "$AI_OUT")
  echo "AI 分析字數：${N}（上限 ${MAX_ZH}）"
  if [ "$N" -gt "$MAX_ZH" ]; then
    echo "[!] 超過上限，要求壓縮一次..."
    timeout 15m claude -p "請把 ${AI_OUT} 精簡到 ${MAX_ZH} 個中文字以內並直接覆寫該檔：保留兩個 ## 標題、研判結論、表格與「本週可建倉／避開」那一行，刪除重複與修辭；規則同 config/ai_analysis_prompt.md。只改這一個檔，不要執行 git。" --model claude-opus-5 --dangerously-skip-permissions || true
    echo "壓縮後字數：$(count_zh "$AI_OUT")"
  fi
else
  echo "[!] 找不到 ${AI_OUT}，報告將不含 AI 分析"
fi

echo "[3/4] 重新生成報告 (注入 AI 分析) 與 index.html (report-only)..."
uv run main.py --mode report-only

echo "[4/4] 同步至 GitHub..."
./sync.sh

echo "執行完成！最新報告已產生並同步。"
