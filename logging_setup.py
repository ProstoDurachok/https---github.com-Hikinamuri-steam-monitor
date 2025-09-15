# Этот файл настраивает логирование с улучшенным форматом: структурированные сообщения, эмодзи, цвета для читаемости.

import logging
from datetime import datetime

def setup_logging():
    class ColoredFormatter(logging.Formatter):
        COLORS = {
            'INFO': '\033[92m',    # Зелёный
            'WARNING': '\033[93m', # Жёлтый
            'ERROR': '\033[91m',   # Красный
            'DEBUG': '\033[94m'    # Синий
        }
        RESET = '\033[0m'
        def format(self, record):
            prefix = f"[{record.levelname}:{record.module}]"
            color = self.COLORS.get(record.levelname, '')
            emoji = {'INFO': 'ℹ️', 'WARNING': '⚠️', 'ERROR': '❌', 'DEBUG': '🔍'}.get(record.levelname, '')
            msg = f"{color}{emoji} {prefix} {record.getMessage()}{self.RESET}"
            return msg

    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
    
    file_handler = logging.FileHandler("steam_screener.log", encoding="utf-8")
    file_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    file_handler.setFormatter(file_formatter)
    
    logging.basicConfig(level=logging.INFO, handlers=[handler, file_handler])
    return logging.getLogger("steam_screener")