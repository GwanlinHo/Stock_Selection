import os
import glob
import markdown
from datetime import datetime

# 設定路徑
REPORTS_DIR = "reports"
INDEX_FILE = "index.html"
TEMPLATE_FILE = "src/utils/template.html"

# HTML 模板骨架 (保持 GitHub 風格)
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>台股選股週報 - {date}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">
    <style>
        .markdown-body {{
            box-sizing: border-box;
            min-width: 200px;
            max-width: 980px;
            margin: 0 auto;
            padding: 45px;
        }}
        @media (max-width: 767px) {{
            .markdown-body {{ padding: 15px; }}
        }}
        body {{ background-color: #f6f8fa; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
        th, td {{ border: 1px solid #dfe2e5; padding: 6px 13px; text-align: left; }}
        tr:nth-child(2n) {{ background-color: #f6f8fa; }}
    </style>
</head>
<body>
    <article class="markdown-body">
        {content}
    </article>
</body>
</html>
"""

def generate_index():
    # 尋找最新的報告檔案
    report_files = glob.glob(os.path.join(REPORTS_DIR, "WEEKLY_REPORT_*.md"))
    if not report_files:
        print("No report files found.")
        return

    latest_report = max(report_files, key=os.path.getmtime)
    print(f"Reading latest report: {latest_report}")

    with open(latest_report, "r", encoding="utf-8") as f:
        md_content = f.read()

    # 使用 Markdown 渲染器轉換 (支援表格、清單等擴充)
    html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'nl2br'])

    # 取得日期標籤
    report_date = os.path.basename(latest_report).replace("WEEKLY_REPORT_", "").replace(".md", "")

    # 寫入 index.html
    final_html = HTML_TEMPLATE.format(date=report_date, content=html_content)
    
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(final_html)
    
    print(f"Successfully updated {INDEX_FILE} from {latest_report}")

if __name__ == "__main__":
    generate_index()
