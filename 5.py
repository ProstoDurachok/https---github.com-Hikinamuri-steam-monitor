# -*- coding: utf-8 -*-
import os
import re
import json
import html
import asyncio
import logging
import sqlite3
from io import BytesIO
from datetime import datetime, timedelta
from time import time
import aiohttp
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InputMediaPhoto
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiohttp import TCPConnector, ClientResponseError
import urllib.parse
import pytz

load_dotenv()

# ---------- КОНФИГУРАЦИЯ ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8427688497:AAGkBisiTfJM3RDc8DOG9Kx9l9EnekoFGQk")
STEAM_COOKIE_STR = os.getenv("STEAM_COOKIE", "76561198375596395%7C%7CeyAidHlwIjogIkpXVCIsICJhbGciOiAiRWREU0EiIH0.eyAiaXNzIjogInI6MDAxOF8yNkVDRjJBNV9EQkNDQSIsICJzdWIiOiAiNzY1NjExOTgzNzU1OTYzOTUiLCAiYXVkIjogWyAid2ViOmNvbW11bml0eSIgXSwgImV4cCI6IDE3NTc5NDYxNzYsICJuYmYiOiAxNzQ5MjE5MzkxLCAiaWF0IjogMTc1Nzg1OTM5MSwgImp0aSI6ICIwMDEyXzI2RUNGMkI5XzhEQTg1IiwgIm9hdCI6IDE3NTc3NzMyMTcsICJydF9leHAiOiAxNzc2MDgxNzEzLCAicGVyIjogMCwgImlwX3N1YmplY3QiOiAiMjE3LjExOC4xODQuMjQ0IiwgImlwX2NvbmZpcm1lciI6ICIxOTUuMjExLjI0LjI0MyIgfQ.lq4eB-FDDTEOLfUWZgjTxtVEZu24ECzQiOMI9nNzLRib-AeoLY4K6WuoGwrR_qktvRcE51bCrxzxRBZ4K_qiBQ")
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
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "7"))  # Limit history to 7 days

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("steam_screener.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("steam_screener")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
_cache = {}

# ---------- БД ----------
DB_FILE = "steam_screener.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER PRIMARY KEY,
    volatility FLOAT DEFAULT 20.0,
    volume_growth FLOAT DEFAULT 50.0,
    schedule_time TEXT DEFAULT '09:00'
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS items (
    item_name TEXT PRIMARY KEY,
    russian_name TEXT,
    last_update INTEGER
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS price_history (
    item_name TEXT,
    timestamp TEXT,
    price FLOAT,
    volume INTEGER,
    PRIMARY KEY (item_name, timestamp)
)
''')
conn.commit()

# ---------- FSM ----------
class PublishState(StatesGroup):
    waiting_for_number = State()

# ---------- ХЕЛПЕРЫ ----------
def html_escape(s: str) -> str:
    return html.escape(s)

def cache_get(key):
    entry = _cache.get(key)
    if not entry:
        return None
    data, ts = entry
    if time() - ts > CACHE_TTL:
        del _cache[key]
        return None
    return data

def cache_set(key, data):
    _cache[key] = (data, time())

cookie_index = 0
proxy_index = 0

def get_next_cookie():
    global cookie_index
    if not STEAM_COOKIES:
        return ""
    cookie = STEAM_COOKIES[cookie_index]
    cookie_index = (cookie_index + 1) % len(STEAM_COOKIES)
    return f"steamLoginSecure={cookie}; steamCountry=RU; steamLanguage=russian"

def get_next_proxy():
    global proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[proxy_index]
    proxy_index = (proxy_index + 1) % len(PROXIES)
    return proxy

async def get_session(proxy=None):
    connector = TCPConnector(ssl=False) if proxy else None
    return aiohttp.ClientSession(connector=connector)

async def safe_get(session, url, params=None, headers=None, proxy=None, retries=3, timeout=30):
    headers = headers or {}
    headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    headers.setdefault("Accept", "application/json, text/javascript, */*; q=0.01")
    headers.setdefault("Accept-Language", "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7")
    headers.setdefault("X-Requested-With", "XMLHttpRequest")
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"GET {url} | params={params} | headers={headers} | proxy={proxy} | attempt={attempt}")
            async with session.get(url, params=params, headers=headers, proxy=proxy, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                text = await resp.text(errors="ignore")
                if resp.status == 200:
                    logger.info(f"Request successful | URL={url} | Status=200")
                    if "application/json" in content_type or text.strip().startswith("{") or text.strip().startswith("["):
                        try:
                            return await resp.json()
                        except Exception as e:
                            logger.error(f"JSON parsing error | URL={url} | Error={e} | Response={text[:500]}")
                            return text
                    else:
                        return text
                elif resp.status == 429:
                    logger.warning(f"HTTP 429: Rate limit exceeded | URL={url} | Waiting {RETRY_429_DELAY}s")
                    await asyncio.sleep(RETRY_429_DELAY)
                else:
                    logger.warning(f"HTTP {resp.status} | URL={url} | Response={text[:500]}")
        except Exception as e:
            logger.error(f"Request failed | URL={url} | Attempt={attempt} | Error={e}")
        await asyncio.sleep(REQUEST_DELAY * attempt)
    logger.error(f"Request failed after {retries} attempts | URL={url}")
    return None

# ---------- THIRD PARTY API FALLBACK ----------
async def get_third_party_pricehistory(session, appid, market_hash_name):
    if not THIRD_PARTY_KEY:
        logger.warning("THIRD_PARTY_KEY not set, fallback disabled")
        return None
    url = f"https://api.steamapis.com/market/item/{appid}/{urllib.parse.quote(market_hash_name)}?api_key={THIRD_PARTY_KEY}&format=json"
    data = await safe_get(session, url)
    if data and isinstance(data, dict) and data.get("data"):
        logger.info(f"SteamApis.com returned data for {market_hash_name}: {len(data['data'].get('prices', []))} entries")
        prices = data.get("data", {}).get("prices", [])
        formatted_prices = [
            [p["time"], str(p["price"]), str(p.get("volume", 0))]
            for p in prices
            if p.get("price") and p.get("time")
        ]
        return {"success": True, "prices": formatted_prices}
    logger.warning(f"SteamApis.com API failed for {market_hash_name}: {data}")
    return None

# ---------- STEAM ENDPOINTS ----------
async def get_priceoverview(session, appid, currency, market_hash_name):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": appid, "currency": currency, "market_hash_name": market_hash_name, "l": "russian"}
    headers = {"Cookie": get_next_cookie(), "Referer": f"https://steamcommunity.com/market/listings/{appid}/{urllib.parse.quote(market_hash_name)}"}
    proxy = get_next_proxy()
    data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES)
    if isinstance(data, dict) and data.get("success"):
        logger.info(f"Price overview fetched for {market_hash_name}: {data}")
        return data
    logger.warning(f"Price overview failed for {market_hash_name}")
    return {}

async def get_pricehistory(session, appid, market_hash_name):
    url = "https://steamcommunity.com/market/pricehistory/"
    proxy = get_next_proxy()
    headers = {
        "Cookie": get_next_cookie(),
        "Referer": f"https://steamcommunity.com/market/listings/{appid}/{urllib.parse.quote(market_hash_name)}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-Requested-With": "XMLHttpRequest",
    }
    variants = [
        {"appid": appid, "market_hash_name": market_hash_name, "currency": CURRENCY, "country": "RU"},
        {"appid": appid, "market_hash_name": market_hash_name, "currency": CURRENCY, "country": "RU", "language": "russian"},
        {"appid": appid, "market_hash_name": market_hash_name, "currency": CURRENCY, "language": "russian"},
        {"appid": appid, "market_hash_name": market_hash_name, "currency": CURRENCY},
        {"appid": appid, "market_hash_name": market_hash_name, "language": "russian"},
        {"appid": appid, "market_hash_name": market_hash_name},
    ]
    for params in variants:
        data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES)
        if data and isinstance(data, dict) and data.get("success"):
            logger.info(f"Price history fetched from Steam API for {market_hash_name}")
            return data
        await asyncio.sleep(1)
    logger.info(f"Steam price history API failed for {market_hash_name}, trying listing page")
    listing_page = await get_listing_page(session, appid, market_hash_name)
    if listing_page:
        match = re.search(r'var line1\s*=\s*(\[.*?\]);', listing_page, re.DOTALL)
        if match:
            try:
                prices_raw = json.loads(match.group(1))
                logger.info(f"Price history extracted from listing page for {market_hash_name}")
                return {"success": True, "prices": prices_raw}
            except json.JSONDecodeError as e:
                logger.error(f"Price history parsing error for {market_hash_name}: {e}")
    if USE_THIRD_PARTY:
        logger.info(f"Trying third-party API (SteamApis.com) for {market_hash_name}")
        third_party_data = await get_third_party_pricehistory(session, appid, market_hash_name)
        if third_party_data:
            return third_party_data
    logger.error(f"Failed to fetch price history for {market_hash_name}")
    return None

async def get_itemordershistogram(session, currency, item_nameid):
    if not item_nameid:
        logger.warning("No item_nameid provided for histogram")
        return {}
    url = "https://steamcommunity.com/market/itemordershistogram"
    params = {"country": "RU", "language": "russian", "currency": currency, "item_nameid": item_nameid}
    headers = {"Cookie": get_next_cookie(), "Referer": "https://steamcommunity.com/market/"}
    proxy = get_next_proxy()
    data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES)
    if data and isinstance(data, dict) and data.get("success"):
        logger.info(f"Histogram fetched for item_nameid={item_nameid}: {data}")
        return data
    logger.warning(f"Histogram fetch failed for item_nameid={item_nameid}")
    return {}

async def get_listing_page(session, appid, market_hash_name):
    url = f"https://steamcommunity.com/market/listings/{appid}/{urllib.parse.quote(market_hash_name)}"
    headers = {"Cookie": get_next_cookie()}
    proxy = get_next_proxy()
    try:
        async with semaphore:
            async with session.get(url, headers=headers, timeout=15, proxy=proxy) as resp:
                text = await resp.text(errors="ignore")
                logger.info(f"Listing page fetched for {market_hash_name}")
                with open(f"listing_{market_hash_name.replace('|', '_').replace(' ', '_')}.html", "w", encoding="utf-8") as f:
                    f.write(text)
                return text
    except Exception as e:
        logger.warning(f"Failed to fetch listing page for {market_hash_name}: {e}")
        return ""

# ---------- ПАРСИНГ NAMEID ----------
async def get_nameid_and_russian_name(session, market_hash_name):
    try:
        listing_page = await get_listing_page(session, APP_ID, market_hash_name)
        if not listing_page:
            logger.warning(f"No listing page for {market_hash_name}")
            return None, market_hash_name, None
        nameid = None
        soup = BeautifulSoup(listing_page, "html.parser")
        # Новый способ: Market_LoadOrderSpread
        match = re.search(r'Market_LoadOrderSpread\(\s*(\d+)\s*\);', listing_page)
        if match:
            nameid = match.group(1)
            logger.info(f"Extracted nameid via Market_LoadOrderSpread: {nameid}")
        
        # Другие способы, если не сработал
        if not nameid:
            scripts = soup.find_all("script", type="text/javascript")
            for script in scripts:
                if script.string:
                    # Поиск через g_rgAssets
                    match = re.search(r'var g_rgAssets\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                    if match:
                        try:
                            assets = json.loads(match.group(1))
                            for asset_classid in assets:
                                for asset_instanceid in assets[asset_classid]:
                                    if "market_name" in assets[asset_classid][asset_instanceid] and assets[asset_classid][asset_instanceid]["market_name"] == market_hash_name:
                                        nameid = assets[asset_classid][asset_instanceid].get("id")
                                        break
                                if nameid:
                                    break
                        except json.JSONDecodeError:
                            continue
                    # Поиск через market_name и nameid
                    if not nameid:
                        match = re.search(r'"market_name"\s*:\s*"[^"]*"\s*,\s*"nameid"\s*:\s*"(\d+)"', script.string)
                        if match:
                            nameid = match.group(1)
                    # Поиск через item_nameid в тегах
                    if not nameid:
                        match = re.search(r'item_nameid\s*=\s*["\'](\d+)["\']', listing_page)
                        if match:
                            nameid = match.group(1)
                    # Дополнительный поиск через data атрибуты
                    if not nameid:
                        data_tag = soup.find("div", {"data-hash-name": market_hash_name})
                        if data_tag and "data-id" in data_tag.attrs:
                            nameid = data_tag["data-id"]
        if not nameid:
            logger.warning(f"Failed to extract nameid for {market_hash_name}")
        
        # Русское имя
        russian_name_tag = soup.find("span", id="largeiteminfo_item_name")
        russian_name = russian_name_tag.text.strip() if russian_name_tag else market_hash_name
        
        # Изображение
        image_tag = soup.find("div", class_="market_listing_largeimage")
        image_url = image_tag.find("img")["src"] if image_tag else None
        if not image_url:
            # Альтернатива
            image_tag = soup.find("img", id="largeiteminfo_item_icon")
            image_url = image_tag["src"] if image_tag else None
        if not image_url:
            # Fallback с правильным форматом
            image_url = f"https://steamcommunity-a.akamaihd.net/economy/image/class/{APP_ID}/{market_hash_name.lower().replace(' ', '-').replace('|', '')}/330x192"
            logger.info(f"Using fallback image URL: {image_url}")
        
        logger.info(f"NameID={nameid}, Russian name={russian_name}, Image URL={image_url} for {market_hash_name}")
        return nameid, russian_name, image_url
    except Exception as e:
        logger.warning(f"Error parsing listing page for {market_hash_name}: {e}")
        return None, market_hash_name, None
    
# ---------- ПАРСИНГ ЦЕН ----------
def parse_price_string(s: str) -> float:
    if s is None:
        return 0.0
    s = str(s).replace('\xa0', '').replace('руб.', '').replace('RUB', '').replace(',', '.').strip()
    m = re.search(r'([0-9]*\.?[0-9]+)', s)
    return float(m.group(1)) if m else 0.0

# ---------- ПАРСИНГ ИСТОРИИ ЦЕН ----------
def df_from_pricehistory(prices_raw):
    rows = []
    logger.info(f"Processing price history with {len(prices_raw or [])} entries")
    now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
    cutoff_date = now - timedelta(days=HISTORY_DAYS)
    for i, p in enumerate(prices_raw or [], 1):
        try:
            if isinstance(p, list) and len(p) >= 3:
                date_raw, price_str, volume_str = p[0], p[1], p[2]
                date_raw = re.sub(r' \+\d+$', '', str(date_raw)).strip()
                price = parse_price_string(price_str)
                volume = int(volume_str)
            elif isinstance(p, dict):
                date_raw = p.get("timestamp") or p.get("date") or p.get("time")
                price = float(p.get("price", 0))
                volume = int(p.get("volume", 0))
            else:
                logger.warning(f"Invalid price entry format at index {i}: {p}")
                continue
            date_formats = [
                '%b %d %Y %H:%M',
                '%b %d %Y %H:',
                '%Y-%m-%d %H:%M:%S',
                '%d %b %Y %H:%M',
                '%Y-%m-%d',
                '%d/%m/%Y %H:%M',
                '%m/%d/%Y %H:%M',
                '%Y-%m-%dT%H:%M:%SZ'
            ]
            dt = None
            for fmt in date_formats:
                try:
                    dt = pd.to_datetime(date_raw, format=fmt, errors='coerce', utc=True)
                    if not pd.isna(dt):
                        break
                except Exception:
                    continue
            if pd.isna(dt):
                dt = pd.to_datetime(date_raw, errors='coerce', utc=True)
            if pd.isna(dt):
                logger.warning(f"Failed to parse date at index {i}: {date_raw}")
                continue
            dt = dt.tz_convert('Europe/Moscow') if not pd.isna(dt) else dt
            if dt < cutoff_date:
                logger.debug(f"Skipping old entry at index {i}: {date_raw} (before {cutoff_date})")
                continue
            rows.append({"timestamp": dt, "price": price, "volume": volume})
            if i <= 5:
                logger.debug(f"Parsed entry {i}: date={date_raw}, timestamp={dt}, price={price}, volume={volume}")
        except Exception as e:
            logger.warning(f"Error processing price entry at index {i}: {p}, Error: {e}")
            continue
    if not rows:
        logger.warning("No valid price history entries processed within the last {} days".format(HISTORY_DAYS))
        return pd.DataFrame(columns=["timestamp", "price", "volume"])
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    logger.info(f"Created DataFrame with {len(df)} rows after filtering for last {HISTORY_DAYS} days")
    return df

# ---------- АНАЛИЗ ----------
def analyze_dataframe(df: pd.DataFrame, current_median: float, current_volume: int):
    if df.empty or len(df) < 2:
        logger.warning("Empty or insufficient DataFrame for analysis")
        return {
            "volatility": 0.0,
            "price_growth": 0.0,
            "volume_growth": 0.0,
            "publications": 0,
            "avg_price": current_median,
        }
    prices = df["price"].values
    avg_price = float(prices.mean())
    stdev_price = float(prices.std(ddof=0))
    volatility = (stdev_price / avg_price * 100) if avg_price > 0 else 0.0

    now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
    yesterday = now.replace(hour=23, minute=59, second=59, microsecond=0) - timedelta(days=1)
    last_24h = df[df["timestamp"] >= (now - timedelta(hours=24))]
    prev_day = df[(df["timestamp"] >= (yesterday - timedelta(hours=1))) & (df["timestamp"] <= (yesterday + timedelta(hours=1)))]
    
    prev_price = prev_day["price"].mean() if not prev_day.empty else avg_price
    price_growth = ((current_median - prev_price) / prev_price * 100) if prev_price > 0 else 0.0
    
    prev_volume = prev_day["volume"].sum() if not prev_day.empty else 0
    volume_growth = 0.0
    if prev_volume > 0:
        volume_growth = ((current_volume - prev_volume) / prev_volume * 100)
    elif prev_volume == 0 and current_volume > 0:
        volume_growth = 100.0  # Минимальный рост для случая "из ничего"
    elif current_volume == 0:
        volume_growth = -100.0  # Уменьшение до 0
    
    publications = len(last_24h)
    logger.info(f"Analysis results: volatility={volatility:.2f}, price_growth={price_growth:.2f}, volume_growth={volume_growth:.2f}, publications={publications}")
    return {
        "volatility": round(volatility, 2),
        "price_growth": round(price_growth, 2),
        "volume_growth": round(volume_growth, 2),
        "publications": int(publications),
        "avg_price": round(avg_price, 2),
    }

# ---------- ГРАФИКИ ----------
def plot_price_week(df: pd.DataFrame, title: str):
    logger.info(f"Plotting price week for {title}")
    if df.empty:
        logger.warning(f"Empty dataframe for price plot: {title}")
        return None
    now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
    week_df = df[df["timestamp"] >= (now - timedelta(days=HISTORY_DAYS))]
    if week_df.empty:
        logger.warning(f"No data for last {HISTORY_DAYS} days, using full dataframe for {title}")
        week_df = df.copy()
    fig, ax = plt.subplots(figsize=(10, 4))  # Увеличен размер
    ax.plot(week_df["timestamp"], week_df["price"], linestyle='-', color='#32CD32', linewidth=1.5)  # Зеленый, без точек
    ax.set_title(title, fontsize=10, color='#fff', pad=10)
    ax.set_xlabel("Дата", fontsize=8, color='#ccc')
    ax.set_ylabel("Цена (руб)", fontsize=8, color='#ccc')
    ax.grid(True, linestyle='--', alpha=0.2, color='#555')
    ax.tick_params(axis='x', colors='#ccc', labelrotation=45)
    ax.tick_params(axis='y', colors='#ccc')
    fig.patch.set_facecolor('#1b2838')
    ax.set_facecolor('#1b2838')
    plt.tight_layout()  # Чтобы не обрезалось
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor='#1b2838', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    logger.info(f"Price plot generated for {title}")
    return buf

def plot_volume_week(df: pd.DataFrame, title: str):
    logger.info(f"Plotting volume week for {title}")
    if df.empty:
        logger.warning(f"Empty dataframe for volume plot: {title}")
        return None
    now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
    week_df = df[df["timestamp"] >= (now - timedelta(days=HISTORY_DAYS))]
    if week_df.empty:
        logger.warning(f"No data for last {HISTORY_DAYS} days, using full dataframe for {title}")
        week_df = df.copy()
    fig, ax = plt.subplots(figsize=(10, 4))  # Увеличен размер
    ax.plot(week_df["timestamp"], week_df["volume"], linestyle='-', color='#00a1d6', linewidth=1.5)  # Синий, без точек
    ax.set_title(title, fontsize=10, color='#fff', pad=10)
    ax.set_xlabel("Дата", fontsize=8, color='#ccc')
    ax.set_ylabel("Объём", fontsize=8, color='#ccc')
    ax.grid(True, linestyle='--', alpha=0.2, color='#555')
    ax.tick_params(axis='x', colors='#ccc', labelrotation=45)
    ax.tick_params(axis='y', colors='#ccc')
    fig.patch.set_facecolor('#1b2838')
    ax.set_facecolor('#1b2838')
    plt.tight_layout()  # Чтобы не обрезалось
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor='#1b2838', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    logger.info(f"Volume plot generated for {title}")
    return buf

def plot_orders_histogram(histogram_json, title: str, image_url: str = None):
    logger.info(f"Plotting orders histogram for {title}")
    if not histogram_json or not isinstance(histogram_json, dict):
        logger.warning(f"No histogram data for {title}")
        return None
    buy = histogram_json.get("buy_order_graph", [])
    sell = histogram_json.get("sell_order_graph", [])
    if not buy and not sell:
        logger.warning(f"No buy or sell orders for histogram: {title}")
        return None
    
    fig, ax = plt.subplots(figsize=(10, 4))  # Увеличен размер
    if buy:
        prices_b = [p[0] for p in buy]
        cum_b = [p[1] for p in buy]
        ax.plot(prices_b, cum_b, linestyle='-', color='#32CD32', label="Покупки", linewidth=1.5)  # Зеленый, без точек, без аннотаций

    if sell:
        prices_s = [p[0] for p in sell]
        cum_s = [p[1] for p in sell]
        ax.plot(prices_s, cum_s, linestyle='-', color='#00a1d6', label="Продажи", linewidth=1.5)  # Синий, без точек, без аннотаций

    ax.set_xlabel("Цена (руб)", fontsize=8, color='#ccc')
    ax.set_ylabel("Количество", fontsize=8, color='#ccc')
    ax.set_title(title, fontsize=10, color='#fff', pad=10)
    ax.legend(fontsize=8, facecolor='#2a475e', edgecolor='#2a475e', labelcolor='#fff')
    ax.grid(True, linestyle='--', alpha=0.2, color='#555')
    ax.tick_params(axis='x', colors='#ccc', labelrotation=45)
    ax.tick_params(axis='y', colors='#ccc')
    all_prices = [p[0] for p in buy + sell]
    if all_prices:
        ax.set_xlim(min(all_prices) - 100, max(all_prices) + 100)
        all_cum = [p[1] for p in buy + sell]
        ax.set_ylim(0, max(all_cum) + 100 if all_cum else 100)
    fig.patch.set_facecolor('#1b2838')
    ax.set_facecolor('#1b2838')
    plt.tight_layout()  # Чтобы не обрезалось
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor='#1b2838', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    logger.info(f"Histogram plot generated for {title}")
    return buf

# ---------- ОБРАБОТКА ОДНОГО ПРЕДМЕТА ----------
async def process_item(session, market_hash_name):
    logger.info(f"Processing item: {market_hash_name}")
    try:
        priceoverview = await get_priceoverview(session, APP_ID, CURRENCY, market_hash_name)
        if not priceoverview or not priceoverview.get("success"):
            logger.warning(f"No price overview data for {market_hash_name}")
            return None
        median = parse_price_string(priceoverview.get("median_price"))
        volume = int(str(priceoverview.get("volume") or "0").replace(",", "").replace(" ", ""))
        nameid, russian_name, image_url = await get_nameid_and_russian_name(session, market_hash_name)
        histogram = await get_itemordershistogram(session, CURRENCY, nameid)
        history_json = await get_pricehistory(session, APP_ID, market_hash_name)
        prices_raw = []
        if isinstance(history_json, dict):
            prices_raw = history_json.get("prices") or history_json.get("history") or []
        elif isinstance(history_json, str):
            try:
                parsed = json.loads(history_json)
                prices_raw = parsed.get("prices") or []
            except Exception:
                prices_raw = []
        elif isinstance(history_json, list):
            prices_raw = history_json
        logger.info(f"Price history data for {market_hash_name}: {len(prices_raw)} entries")
        df = df_from_pricehistory(prices_raw)
        for _, row in df.iterrows():
            cursor.execute("INSERT OR IGNORE INTO price_history (item_name, timestamp, price, volume) VALUES (?, ?, ?, ?)",
                          (market_hash_name, row["timestamp"].isoformat(), row["price"], row["volume"]))
        conn.commit()
        analysis = analyze_dataframe(df, median, volume)
        analysis.update({
            "current_median": median,
            "current_volume": volume,
            "sell_order_count": 0,
            "buy_order_count": 0,
        })
        if isinstance(histogram, dict) and histogram.get("success"):
            so = histogram.get("sell_order_summary", "")
            bo = histogram.get("buy_order_summary", "")
            sell_match = re.search(r"Лотов на продажу:\s*<span[^>]*>(\d+)</span>", so)
            buy_match = re.search(r"Запросов на покупку:\s*<span[^>]*>(\d+)</span>", bo)
            analysis["sell_order_count"] = int(sell_match.group(1)) if sell_match else 0
            analysis["buy_order_count"] = int(buy_match.group(1)) if buy_match else 0
            logger.info(f"Histogram analysis for {market_hash_name}: sell_orders={analysis['sell_order_count']}, buy_orders={analysis['buy_order_count']}")
        return {
            "item": market_hash_name,
            "russian_name": russian_name,
            "analysis": analysis,
            "price_data": priceoverview,
            "histogram": histogram,
            "df": df,
            "image_url": image_url
        }
    except Exception as e:
        logger.exception(f"Error processing item {market_hash_name}: {e}")
        return None

# ---------- ФОРМАТИРОВАНИЕ И ПУБЛИКАЦИЯ ----------
def build_caption_html(res: dict) -> str:
    an = res["analysis"]
    rn = html_escape(res["russian_name"])
    item_link = f"https://steamcommunity.com/market/listings/{APP_ID}/{urllib.parse.quote(res['item'])}"
    title_html = f'<a href="{item_link}">{rn}</a>'
    cur_med = an.get("current_median", 0.0)
    cur_vol = an.get("current_volume", 0)
    price_growth = an.get("price_growth", 0.0)
    volume_growth = an.get("volume_growth", 0.0)
    
    sell_order_count = an.get("sell_order_count", 0)
    buy_order_count = an.get("buy_order_count", 0)
    publications = an.get("publications", 0)
    
    text = (
        f"{title_html}\n\n"
        f"<b>Стоимость: {cur_med:,.2f} руб (24 часа: {price_growth:+.2f}%)</b>\n"
        f"<b>Объем продаж: {cur_vol} (24 часа: {volume_growth:+.2f}%)</b>\n\n"
        f"<b>Лотов на продажу: {sell_order_count}</b>\n"
        f"<b>Запросов на покупку: {buy_order_count}</b>\n\n"
        f"<b>Публикаций за сутки: {publications}</b>\n"
    )
    logger.info(f"Caption built for {res['item']}: sell_orders={sell_order_count}, buy_orders={buy_order_count}, publications={publications}")
    return text

async def publish_item(session, chat_id: int, res: dict):
    logger.info(f"Publishing item {res['item']} to chat {chat_id}")
    caption_html = build_caption_html(res)
    temp_files = []
    media = []
    try:
        # Загрузка изображения предмета
        if res.get("image_url"):
            try:
                async with session.get(res["image_url"]) as r:
                    if r.status == 200:
                        data = await r.read()
                        fn = f"img_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.png"
                        with open(fn, "wb") as f:
                            f.write(data)
                        temp_files.append(fn)
                        media.append(InputMediaPhoto(media=FSInputFile(fn), caption=caption_html if not media else None))
                        logger.info(f"Item image added for {res['item']}")
            except Exception as e:
                logger.warning(f"Failed to download item image for {res['item']}: {e}")

        # Графики
        price_buf = plot_price_week(res.get("df", pd.DataFrame()), f"Изменение цены за {HISTORY_DAYS} дней — {res['russian_name']}")
        if price_buf:
            fn = f"price_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.png"
            with open(fn, "wb") as f:
                f.write(price_buf.read())
            temp_files.append(fn)
            media.append(InputMediaPhoto(media=FSInputFile(fn)))
            logger.info(f"Price plot added for {res['item']}")

        volume_buf = plot_volume_week(res.get("df", pd.DataFrame()), f"Объём продаж за {HISTORY_DAYS} дней — {res['russian_name']}")
        if volume_buf:
            fn = f"vol_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.png"
            with open(fn, "wb") as f:
                f.write(volume_buf.read())
            temp_files.append(fn)
            media.append(InputMediaPhoto(media=FSInputFile(fn)))
            logger.info(f"Volume plot added for {res['item']}")

        histogram_buf = plot_orders_histogram(res.get("histogram", {}), f"Гистограмма заказов — {res['russian_name']}")
        if histogram_buf:
            fn = f"hist_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.png"
            with open(fn, "wb") as f:
                f.write(histogram_buf.read())
            temp_files.append(fn)
            media.append(InputMediaPhoto(media=FSInputFile(fn)))
            logger.info(f"Histogram plot added for {res['item']}")

        # Отправка одним сообщением
        if media:
            if not media[0].caption:  # Если изображение предмета не первое, добавляем caption к первому медиа
                media[0].caption = caption_html
            await bot.send_media_group(chat_id=chat_id, media=media)
            logger.info(f"Media group sent for {res['item']} with {len(media)} items")
        else:
            # Если нет медиа, отправляем только текст с изображением из ссылки, если доступно
            await bot.send_photo(chat_id, photo=res["image_url"], caption=caption_html, parse_mode=ParseMode.HTML)
            logger.info(f"Text and image sent for {res['item']}")

    except Exception as e:
        logger.exception(f"Error publishing item {res['item']}: {e}")
    finally:
        for fpath in temp_files:
            try:
                os.remove(fpath)
            except Exception:
                pass

# ---------- СКАН РЫНКА ----------
async def fetch_market_page(session, start=0, count=100):
    url = "https://steamcommunity.com/market/search/render/"
    params = {"query": "", "start": start, "count": count, "appid": APP_ID, "l": "russian"}
    headers = {"Cookie": get_next_cookie()}
    proxy = get_next_proxy()
    data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES)
    return data

async def update_all_items(session, max_pages=MAX_PAGES, page_size=100):
    items = set()
    start = 0
    for page in range(max_pages):
        data = await fetch_market_page(session, start=start, count=page_size)
        if not data or not isinstance(data, dict) or not data.get("results_html"):
            logger.info("No more results or blocked")
            break
        soup = BeautifulSoup(data["results_html"], "html.parser")
        rows = soup.find_all("a", class_="market_listing_row_link")
        if not rows:
            break
        for r in rows:
            name_tag = r.find("span", class_="market_listing_item_name")
            if name_tag:
                items.add(name_tag.text.strip())
        logger.info(f"Page {page+1}: found {len(rows)} items, unique {len(items)}")
        start += page_size
        await asyncio.sleep(REQUEST_DELAY)
    for it in items:
        cursor.execute("INSERT OR IGNORE INTO items (item_name, russian_name, last_update) VALUES (?, ?, ?)", (it, it, int(time())))
    conn.commit()
    return list(items)

# ---------- СКАН И ОТБОР ----------
async def scan_and_select(session, max_items=200, vol_threshold=20.0, vol_growth_threshold=50.0):
    cursor.execute("SELECT item_name FROM items LIMIT ?", (max_items,))
    rows = cursor.fetchall()
    items = [r[0] for r in rows] if rows else []
    if not items:
        items = await update_all_items(session, max_pages=10)
    tasks = []
    for it in items[:max_items]:
        async with semaphore:
            tasks.append(process_item(session, it))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    selected = []
    for r in results:
        if not r or isinstance(r, Exception):
            continue
        an = r.get("analysis", {})
        if (an.get("volatility", 0) >= vol_threshold and 
            an.get("volume_growth", 0) >= vol_growth_threshold):
            selected.append(r)
    selected.sort(key=lambda x: x.get("analysis", {}).get("volume_growth", 0), reverse=True)
    logger.info(f"Selected {len(selected)} items (volatility >= {vol_threshold}%, volume growth >= {vol_growth_threshold}%)")
    return selected

# ---------- ПЛАНИРОВЩИК ----------
async def daily_scheduler_loop():
    while True:
        try:
            cursor.execute("SELECT schedule_time FROM settings LIMIT 1")
            row = cursor.fetchone()
            schedule_time = row[0] if row else "09:00"
            now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
            hour, minute = map(int, schedule_time.split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=5, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            wait = (next_run - now).total_seconds()
            logger.info(f"Scheduler sleeping for {wait} seconds until {next_run}")
            await asyncio.sleep(wait)
            async with aiohttp.ClientSession() as session:
                cursor.execute("SELECT volatility, volume_growth FROM settings LIMIT 1")
                row = cursor.fetchone()
                vol_threshold, vol_growth_threshold = row if row else (20.0, 50.0)
                selected = await scan_and_select(session, max_items=200, vol_threshold=vol_threshold, vol_growth_threshold=vol_growth_threshold)
                if not selected:
                    if ADMIN_ID:
                        await bot.send_message(ADMIN_ID, "ℹ️ No items matched criteria today.")
                else:
                    for item in selected:
                        await publish_item(session, CHANNEL_ID, item)
                        await asyncio.sleep(POST_DELAY)
                    if ADMIN_ID:
                        await bot.send_message(ADMIN_ID, f"✅ Published {len(selected)} items.")
        except Exception as e:
            logger.exception(f"Scheduler error: {e}")
            try:
                if ADMIN_ID:
                    await bot.send_message(ADMIN_ID, f"⚠️ Scheduler error: {e}")
            except Exception:
                pass
            await asyncio.sleep(60)

# ---------- КОМАНДЫ БОТА ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="🔧 Критерии", callback_data="set_thresholds"))
    kb.add(types.InlineKeyboardButton(text="🔍 Проверить", callback_data="check_specific"))
    kb.add(types.InlineKeyboardButton(text="📊 Скан рынка", callback_data="scan_market"))
    kb.adjust(2)
    text = "Привет! Я скринер рынка Steam для CS2. Используй команды или кнопки."
    await message.answer(text, reply_markup=kb.as_markup())

@dp.message(Command("set"))
async def cmd_set(message: types.Message):
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("Использование: /set <волатильность> <рост_объема>")
    try:
        vol = float(parts[1])
        volgr = float(parts[2])
        cursor.execute("INSERT OR REPLACE INTO settings (user_id, volatility, volume_growth) VALUES (?, ?, ?)",
                       (message.from_user.id, vol, volgr))
        conn.commit()
        await message.answer(f"Установлено: волатильность ≥ {vol}%, рост объёма ≥ {volgr}%")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("check"))
async def cmd_check(message: types.Message):
    arg = message.text.partition(" ")[2].strip()
    if not arg:
        return await message.answer("Пример: /check AK-47 | Redline (Field-Tested)")
    item_name = arg
    await message.answer(f"Проверяю: {html_escape(item_name)}")
    async with aiohttp.ClientSession() as session:
        res = await process_item(session, item_name)
        if not res:
            return await message.answer("Нет данных по предмету или ошибка доступа.")
        await publish_item(session, message.chat.id, res)

@dp.message(Command("scan"))
async def cmd_scan(message: types.Message):
    parts = message.text.split()
    num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 100
    await message.answer(f"Сканирую рынок (максимум {num} предметов)... Это может занять время.")
    async with aiohttp.ClientSession() as session:
        cursor.execute("SELECT volatility, volume_growth FROM settings WHERE user_id=?", (message.from_user.id,))
        row = cursor.fetchone()
        vol_threshold, vol_growth_threshold = row if row else (20.0, 50.0)
        selected = await scan_and_select(session, max_items=num, vol_threshold=vol_threshold, vol_growth_threshold=vol_growth_threshold)
        if not selected:
            return await message.answer("Ничего не найдено по критериям.")
        for r in selected:
            await publish_item(session, message.chat.id, r)
            await asyncio.sleep(1)
        await message.answer(f"Готово — опубликовано {len(selected)} предметов в чат.")

@dp.callback_query(lambda c: c.data == "check_specific")
async def cb_check_specific(callback: types.CallbackQuery):
    await callback.message.answer("Отправь /check с названием предмета, например: /check AK-47 | Redline (Field-Tested)")

@dp.callback_query(lambda c: c.data == "set_thresholds")
async def cb_set_thresholds(callback: types.CallbackQuery):
    await callback.message.answer("Отправь /set с волатильностью и ростом объема, например: /set 20 50")

@dp.callback_query(lambda c: c.data == "scan_market")
async def cb_scan_market(callback: types.CallbackQuery):
    await callback.message.answer("Отправь /scan с количеством предметов, например: /scan 100")

# ---------- RUN ----------
async def main():
    logger.info("Starting bot polling")
    max_retries = 5
    retry_delay = 5
    for attempt in range(1, max_retries + 1):
        try:
            asyncio.create_task(daily_scheduler_loop())
            await dp.start_polling(bot)
            break
        except Exception as e:
            logger.error(f"Polling failed, attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached, stopping bot")
                raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception(f"Critical error: {e}")