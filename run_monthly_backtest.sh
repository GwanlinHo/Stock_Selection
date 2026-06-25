#!/bin/bash
# 月度回測績效刷新：增量更新價格長快取 -> 重跑三策略總結 -> 更新 data/backtest_summary.json
# (週報會自動嵌入此 JSON 的回測績效)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PATH=/home/pi/.local/bin:$PATH
export PYTHONPATH=$PYTHONPATH:.

echo "[1/2] 增量刷新回測資料並重跑三策略總結..."
uv run run_summary.py --refresh --years 5

echo "[2/2] 提交回測摘要與總結報告..."
git pull --no-rebase || true
git add data/backtest_summary.json reports/SUMMARY_REPORT_*.md reports/summary_*.html
if ! git diff-index --quiet HEAD --; then
    git commit -m "chore: 月度回測績效刷新 $(date '+%Y-%m-%d')"
    git push
else
    echo "回測績效無變化，不需提交。"
fi
echo "月度回測刷新完成。"
