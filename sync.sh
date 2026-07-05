#!/bin/bash
# 安全同步選股週報到公開 repo：白名單 add(不用 git add .) + 推送前金鑰/敏感檔掃描護欄。
# 只發布報表產物; 原始碼/設定變更請人工另行 commit。(.gitignore 另已過濾 reports/SCAN_DATA_*、REPORT_*)

set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

WHITELIST=(index.html reports data)

SECRET_PATTERNS='(sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
FORBIDDEN_FILES='(^|/)(\.env|\.env\..+|\.credentials\.json|credentials\.json|\.git-credentials|.+\.pem|id_rsa|.+\.key)$'

REPO_API="https://api.github.com/repos/GwanlinHo/Stock_Selection"

# 查詢指定 commit 的 GitHub Pages 部署結論(公開 API,免 token)。
# 輸出: success | failure | timeout | unknown
check_pages_deploy() {
  local sha="$1" i concl
  for i in $(seq 1 12); do  # 每 15 秒查一次,最多等 3 分鐘
    concl=$(curl -sf --max-time 20 "$REPO_API/actions/runs?per_page=5" | python3 -c "
import json, sys
sha = sys.argv[1]
try:
    runs = json.load(sys.stdin).get('workflow_runs', [])
except Exception:
    print('unknown'); sys.exit()
for r in runs:
    if r.get('head_sha') == sha and r.get('name') == 'pages build and deployment':
        print(r.get('conclusion') or 'pending'); break
else:
    print('pending')
" "$sha" 2>/dev/null) || { echo "unknown"; return; }
    case "$concl" in
      success|failure|unknown) echo "$concl"; return ;;
    esac
    sleep 15
  done
  echo "timeout"
}

# Pages 部署護欄:GitHub 偶發「Deployment failed, try again later」(2026-07-03 曾連續失敗,
# 網頁停在舊版一週無人知)。推送後確認部署結果,失敗就以空 commit 重觸發一次;查不到狀態只警告不中斷。
verify_pages_or_retrigger() {
  local result
  result=$(check_pages_deploy "$(git rev-parse HEAD)")
  if [ "$result" = "failure" ]; then
    echo "[!] Pages 部署失敗(GitHub 端),推空 commit 重觸發一次..."
    git commit --allow-empty -m "chore: retrigger pages deployment" && git push || { echo "[X] 重觸發推送失敗。"; return 1; }
    result=$(check_pages_deploy "$(git rev-parse HEAD)")
  fi
  case "$result" in
    success) echo "[O] GitHub Pages 部署成功。" ;;
    failure) echo "[X] 重觸發後 Pages 仍部署失敗,請至 GitHub Actions 頁面人工檢查。"; return 1 ;;
    *)       echo "[!] 無法確認 Pages 部署狀態($result),請稍後自行檢查網頁是否更新。" ;;
  esac
}

echo "正在從遠端拉取最新狀態..."
git pull --no-rebase || { echo "[X] 拉取衝突或錯誤，請手動解決後再繼續。"; exit 1; }

for p in "${WHITELIST[@]}"; do
  [ -e "$p" ] && git add -- "$p"
done

if git diff --cached --quiet; then
  echo "沒有白名單內的變更需要提交。"
  exit 0
fi

STAGED="$(git diff --cached --name-only)"
BAD="$(printf '%s\n' "$STAGED" | grep -iE "$FORBIDDEN_FILES")"
if [ -n "$BAD" ]; then
  echo "[X] staged 含禁列敏感檔，中止推送："; printf '%s\n' "$BAD"
  printf '%s\n' "$BAD" | while IFS= read -r bf; do [ -n "$bf" ] && git reset -q HEAD -- "$bf"; done
  exit 1
fi
HIT="$(git diff --cached -U0 | grep -aE "$SECRET_PATTERNS" | head -5)"
if [ -n "$HIT" ]; then
  echo "[X] staged 內容命中金鑰樣式，中止推送(請檢查)："; printf '%s\n' "$HIT"
  exit 1
fi

echo "發現白名單變更，提交並推送..."
git commit -m "chore: 選股週報自動更新 $(date '+%Y-%m-%d %H:%M:%S')" || exit 1
git push || exit 1
verify_pages_or_retrigger
