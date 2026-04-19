import requests
from bs4 import BeautifulSoup
import json
import pandas as pd
from pathlib import Path
from src.utils.logger import log, ErrorCode

class TickerManager:
    """管理台股全市場標的清單"""
    
    URL_LISTED = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2" # 上市
    URL_OTC = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"    # 上櫃
    
    TICKER_FILE = Path("data/tickers.json")

    def __init__(self):
        self.tickers = []

    def _parse_isin_table(self, html_text, market_suffix):
        """極致穩定的 BeautifulSoup 逐行解析"""
        soup = BeautifulSoup(html_text, 'html.parser')
        table = soup.find('table', {'class': 'h4'})
        if not table:
            return []
        
        results = []
        rows = table.find_all('tr')
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 6:
                continue
                
            id_name = cols[0].get_text(strip=True)
            isin = cols[1].get_text(strip=True)
            market = cols[3].get_text(strip=True)
            industry = cols[4].get_text(strip=True)
            cfi = cols[5].get_text(strip=True)
            
            # 過濾邏輯:
            # 1. 必須包含全形空格 (區分代碼與名稱)
            # 2. CFI Code 必須以 ES 開頭 (Equity Shares)
            # 3. 代碼必須是 4 碼 (過濾掉權證等)
            if '　' in id_name and cfi.startswith('ES'):
                ticker, name = id_name.split('　', 1)
                ticker = ticker.strip()
                if len(ticker) == 4:
                    results.append({
                        "Ticker": ticker,
                        "Name": name.strip(),
                        "yfinance_ticker": f"{ticker}.{market_suffix}",
                        "Market": market,
                        "Industry": industry
                    })
        return results

    def fetch_tickers(self):
        """爬取證交所與櫃買中心網頁，獲取普通股清單"""
        log.info("開始從證交所/櫃買中心獲取全市場標的清單...")
        
        all_tickers = []
        for url, market_suffix in [(self.URL_LISTED, "TW"), (self.URL_OTC, "TWO")]:
            try:
                # 增加 User-Agent 避免被擋
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(url, headers=headers, timeout=30)
                response.encoding = 'cp950'
                
                if response.status_code != 200:
                    log.error(f"HTTP 錯誤: {response.status_code}")
                    continue
                
                market_data = self._parse_isin_table(response.text, market_suffix)
                if market_data:
                    all_tickers.extend(market_data)
                    log.info(f"成功獲取 {market_suffix} 市場標的，共 {len(market_data)} 檔普通股。")
                else:
                    log.warning(f"{market_suffix} 市場未解析出任何資料。")
                
            except Exception as e:
                log.error(f"[{ErrorCode.ERR_NET_CONN}] 獲取 {url} 資料失敗: {str(e)}")
        
        if not all_tickers:
            log.critical("未能獲取任何市場標的清單！")
            return []

        # 去重與儲存
        seen = set()
        self.tickers = []
        for t in all_tickers:
            if t['Ticker'] not in seen:
                seen.add(t['Ticker'])
                self.tickers.append(t)

        self.save_to_json()
        return self.tickers

    def save_to_json(self):
        """將清單儲存至本地 JSON 檔案"""
        try:
            self.TICKER_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.TICKER_FILE, "w", encoding="utf-8") as f:
                json.dump(self.tickers, f, ensure_ascii=False, indent=4)
            log.info(f"清單已儲存至 {self.TICKER_FILE}，總計 {len(self.tickers)} 檔標的。")
        except Exception as e:
            log.error(f"儲存清單失敗: {str(e)}")

    def load_tickers(self):
        """從本地讀取清單"""
        if self.TICKER_FILE.exists():
            with open(self.TICKER_FILE, "r", encoding="utf-8") as f:
                self.tickers = json.load(f)
            return self.tickers
        return self.fetch_tickers()

if __name__ == "__main__":
    manager = TickerManager()
    manager.fetch_tickers()
