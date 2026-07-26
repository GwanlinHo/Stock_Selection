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
        /* 免責聲明彈窗 */
        #disclaimer-overlay {{
            display: none;
            position: fixed; inset: 0; z-index: 9999;
            background: rgba(0,0,0,0.55);
            align-items: center; justify-content: center;
            padding: 20px; box-sizing: border-box;
        }}
        #disclaimer-overlay.show {{ display: flex; }}
        #disclaimer-box {{
            background: #fff; max-width: 560px; width: 100%;
            border-radius: 8px; padding: 28px 30px;
            box-shadow: 0 8px 30px rgba(0,0,0,0.25);
            font-size: 15px; line-height: 1.7; color: #24292e;
            max-height: 90vh; overflow-y: auto;
        }}
        #disclaimer-box h2 {{
            margin: 0 0 16px; font-size: 19px; color: #b3261e;
            border: none; padding: 0;
        }}
        #disclaimer-box p {{ margin: 0 0 14px; }}
        #disclaimer-box .accent {{ font-weight: 600; }}
        #disclaimer-box .actions {{ text-align: right; margin-top: 20px; }}
        #disclaimer-close {{
            background: #b3261e; color: #fff; border: none;
            border-radius: 6px; padding: 9px 22px;
            font-size: 15px; cursor: pointer;
        }}
        #disclaimer-close:hover {{ background: #911d17; }}
    </style>
</head>
<body>
    <div id="disclaimer-overlay">
        <div id="disclaimer-box" role="dialog" aria-modal="true" aria-labelledby="disclaimer-title">
            <h2 id="disclaimer-title">[!] 重要聲明：這是一項實驗性嘗試，非投資建議</h2>
            <p>本報告是一項與「指數投資」<span class="accent">完全不同方向</span>的嘗試。週報中的動能選股方法，我目前仍在觀察其是否可行——我希望至少經歷過<span class="accent">一次較大幅度的衰退</span>、確認它是否管用之後，才會考慮納入投資組合策略。</p>
            <p>因此，<span class="accent">不建議</span>依照本報告的選股進行投資，以免蒙受不必要的損失。</p>
            <div class="actions">
                <button type="button" id="disclaimer-close">我了解了</button>
            </div>
        </div>
    </div>
    <article class="markdown-body">
        {content}
    </article>
    <script>
    (function () {{
        var KEY = "ss_disclaimer_dismissed";
        var overlay = document.getElementById("disclaimer-overlay");
        var btn = document.getElementById("disclaimer-close");
        if (!overlay || !btn) return;
        var dismissed = false;
        try {{ dismissed = localStorage.getItem(KEY) === "1"; }} catch (e) {{}}
        if (!dismissed) overlay.classList.add("show");
        btn.addEventListener("click", function () {{
            overlay.classList.remove("show");
            try {{ localStorage.setItem(KEY, "1"); }} catch (e) {{}}
        }});
    }})();
    </script>
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
