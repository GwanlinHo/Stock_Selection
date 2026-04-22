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
        """
        if not self.model:
            return {"category": "B", "reason": "未配置 AI API"}

        prompt = f"""
        你是一位專業的台股投資分析師。請針對以下標的進行深度分析。
        
        【標的數據】:
        - 名稱: {ticker_info.get('Name')} ({ticker_info.get('Ticker')})
        - 產業: {ticker_info.get('Industry')}
        - 營收 YoY: {ticker_info.get('L4_Value')}%
        - ROE (TTM): {ticker_info.get('ROE')}%
        - PER: {ticker_info.get('PER')}
        - PEG: {ticker_info.get('PEG')}
        
        【任務】:
        1. 給予評等 (A: 強烈推薦, B: 穩健觀察, C: 投機/風險)。
        2. 提供核心分析邏輯 (兩句)。
        
        請嚴格遵守 Traditional Chinese，且不要使用 Emoji。
        請僅回覆 JSON 格式: {{"category": "A/B/C", "reason": "分析理由"}}
        """

        try:
            response = self.model.generate_content(prompt)
            # 簡單清理 Markdown JSON 格式
            clean_json = response.text.replace('```json', '').replace('```', '').strip()
            import json
            return json.loads(clean_json)
        except Exception as e:
            log.error(f"[{ErrorCode.ERR_AI_FAIL}] AI 分析失敗: {str(e)}")
            return {"category": "B", "reason": "AI 分析服務暫時不可用"}
