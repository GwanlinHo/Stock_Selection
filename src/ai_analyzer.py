import os
import google.generativeai as genai
from src.utils.logger import log, ErrorCode
from dotenv import load_dotenv

load_dotenv()

class AIAnalyzer:
    """使用 Gemini API 進行語意分析與分類決策"""

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            log.warning("未偵測到 GOOGLE_API_KEY，AI 分析功能將受限。")
            self.model = None
        else:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')

    def analyze_and_classify(self, ticker_info: dict, news_text: str = ""):
        """
        根據數據與新聞進行 A/B/C 分類
        ticker_info: 包含價量、籌碼、基本面指標的字典
        """
        if not self.model:
            return "B", "未配置 AI，預設分類為 B (觀察中)"

        prompt = f"""
        你是一位資深的台股分析師。請根據以下數據，將這檔股票分類為 A, B 或 C 組。
        A組：趨勢強勁、法人大買、基本面好，明天可進場。
        B組：條件符合但漲幅已大，等拉回。
        C組：勉強過關，再觀察。

        股票數據：{ticker_info}
        近期新聞摘要：{news_text if news_text else "無重大消息"}

        請回覆 JSON 格式，包含 "category" (A/B/C) 與 "reason" (理由)。
        """

        try:
            response = self.model.generate_content(prompt)
            # 這裡可以加入更嚴謹的 JSON 解析
            return response.text
        except Exception as e:
            log.error(f"[{ErrorCode.ERR_AI_FAIL}] AI 分析失敗: {str(e)}")
            return "B", "AI 分析異常"
