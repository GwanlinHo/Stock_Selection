import sys
from loguru import logger
from pathlib import Path

# 確保 logs 目錄存在
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 結構化日誌格式
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

def setup_logger():
    """配置 Loguru 日誌系統"""
    # 移除預設的處理器
    logger.remove()

    # 輸出至終端機
    logger.add(sys.stderr, format=LOG_FORMAT, level="INFO")

    # 輸出至檔案 (包含錯誤碼與詳細資訊)
    logger.add(
        LOG_DIR / "stock_selection.log",
        format=LOG_FORMAT,
        level="DEBUG",
        rotation="10 MB",
        retention="1 month",
        encoding="utf-8"
    )

    # 針對重大錯誤建立獨立日誌
    logger.add(
        LOG_DIR / "error.log",
        format=LOG_FORMAT,
        level="ERROR",
        rotation="1 week",
        encoding="utf-8"
    )

    return logger

# 全域 logger 實例
log = setup_logger()

# 錯誤碼定義
class ErrorCode:
    ERR_NET_CONN = "ERR_NET_CONN"     # 網路連線失敗
    ERR_DATA_MISSING = "ERR_DATA_MISSING" # 數據缺失
    ERR_API_LIMIT = "ERR_API_LIMIT"    # API 額度限制
    ERR_AI_FAIL = "ERR_AI_FAIL"      # AI 解析失敗
    ERR_INVALID_TICKER = "ERR_INVALID_TICKER" # 無效的股票代碼
