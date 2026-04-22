import pandas as pd
from src.data_premium import DataPremium
from src.utils.logger import log

def test_roic():
    ticker = '2330.TW'
    log.info(f'測試抓取 {ticker} 的 ROIC...')
    premium = DataPremium()
    df_ratio = premium.fetch_financial_ratios(ticker)
    
    if df_ratio is None or df_ratio.empty:
        print('失敗：無法取得財務比率數據')
        return

    print('成功取得數據！欄位包含：', df_ratio.columns.tolist())
    
    roic_data = df_ratio[df_ratio['type'] == 'ROIC']
    if not roic_data.empty:
        latest_roic = roic_data.iloc[-1]
        print(f'\n最新 ROIC 日期: {latest_roic["date"]}, 數值: {latest_roic["value"]}%')
    else:
        print('\n警告：數據庫中找不到 ROIC 類型，現有的 type 如下：')
        print(df_ratio['type'].unique())

if __name__ == '__main__':
    test_roic()
