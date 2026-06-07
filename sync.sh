#!/bin/bash
# 將最新選股週報成果同步至 GitHub

echo "正在從遠端拉取最新狀態... (Pulling from remote...)"
git pull --no-rebase

if [ $? -ne 0 ]; then
    echo "拉取時發生衝突或錯誤，請先手動解決後再繼續。"
    exit 1
fi

git add .

if ! git diff-index --quiet HEAD --; then
    echo "發現本地變更，正在提交... (Committing...)"
    git commit -m "chore: 選股週報自動更新 $(date '+%Y-%m-%d %H:%M:%S')"
else
    echo "沒有本地變更需要提交。"
fi

echo "正在推送到遠端... (Pushing to remote...)"
git push
