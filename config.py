# Этот файл содержит загрузку конфигурации из .env и глобальные константы для бота.

import os
from dotenv import load_dotenv
import asyncio  # Добавлен для semaphore

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8427688497:AAGkBisiTfJM3RDc8DOG9Kx9l9EnekoFGQk")
STEAM_COOKIE_STR = os.getenv("STEAM_COOKIE", "76561198375596395%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAxOF8yNkVDRjJBNV9EQkNDQSIsICJzdWIiOiAiNzY1NjExOTgzNzU1OTYzOTUiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NTc5NDYxNzYsICJuYmYiOiAxNzQ5MjE5MzkxLCAiaWF0IjogMTc1Nzg1OTM5MSwgImp0aSI6ICIwMDEyXzI2RUNGMkI5XzhEQTg1IiwgIm9hdCI6IDE3NTc3NzMyMTcsICJydF9leHAiOiAxNzcyMDgxNzEzLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMjE3LjExOC4xODQuMjQ0IiwgImlwX2NvbmZpcm1lciI6ICIxOTUuMjExLjI0LjI0MyIgfQ.lq4eB-FDDTEOLfUWZgjTxtVEZu24ECzQiOMI9nNzLRib-AeoLY4K6WuoGwrR_qktvRcE51bCrxzxRBZ4K_qiBQ")
STEAM_COOKIES = [c.strip() for c in STEAM_COOKIE_STR.split(';') if c.strip()]
APP_ID = int(os.getenv("APP_ID", "730"))
CURRENCY = int(os.getenv("CURRENCY", "5"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1002952911498"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "873939087"))
USE_THIRD_PARTY = os.getenv("USE_THIRD_PARTY_API", "1") == "1"
THIRD_PARTY_KEY = os.getenv("THIRD_PARTY_KEY", "jxgK34vHL_Wn03ENLLqD5w5RBEs")
PROXIES = [p.strip() for p in os.getenv("PROXIES", "").split(';') if p.strip()]
MAX_PAGES = int(os.getenv("MAX_PAGES", "50"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2.0"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
RETRY_429_DELAY = int(os.getenv("RETRY_429_DELAY", "60"))
POST_DELAY = int(os.getenv("POST_DELAY", "3600"))
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "7"))
DB_FILE = "steam_screener.db"

semaphore = asyncio.Semaphore(MAX_CONCURRENCY)  # Вынесен сюда для избежания цикла импортов

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

# Создаём bot и dp здесь, чтобы избежать циклических импортов
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)  # Если dp нужен глобально; иначе оставьте только bot