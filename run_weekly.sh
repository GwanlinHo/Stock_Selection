#!/bin/bash
# 自動化選股週報執行腳本

echo "正在啟動台股選股 Workflow..."

# 檢查 .env 是否存在
if [ ! -f .env ]; then
    echo "錯誤: 找不到 .env 檔案！請參考 .env.example 建立並填入 API Key。"
    exit 1
fi

# 執行主程式
export PYTHONPATH=$PYTHONPATH:.
uv run main.py

echo "執行完成！請至 reports 目錄查看最新的選股週報。"
