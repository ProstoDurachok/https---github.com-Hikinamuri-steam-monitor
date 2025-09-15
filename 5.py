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
from aiohttp import TCPConnector
import urllib.parse
import pytz
from filters import FACETS, build_filter_keyboard  # Updated import with full FACETS
load_dotenv()
# ---------- КОНФИГУРАЦИЯ ----------
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
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "7")) # Limit history to 7 days
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler("steam_screener.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
setup_logging()
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
def init_db():
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
        english_hash TEXT,
        category TEXT,
        subcategory TEXT,
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
def get_settings(user_id=None):
    if user_id:
        cursor.execute("SELECT volatility, volume_growth, schedule_time FROM settings WHERE user_id=?", (user_id,))
    else:
        cursor.execute("SELECT volatility, volume_growth, schedule_time FROM settings LIMIT 1")
    row = cursor.fetchone()
    return row if row else (20.0, 50.0, '09:00')
def set_settings(user_id, vol, volgr, schedule_time=None):
    if schedule_time:
        cursor.execute("INSERT OR REPLACE INTO settings (user_id, volatility, volume_growth, schedule_time) VALUES (?, ?, ?, ?)", (user_id, vol, volgr, schedule_time))
    else:
        cursor.execute("INSERT OR REPLACE INTO settings (user_id, volatility, volume_growth) VALUES (?, ?, ?)", (user_id, vol, volgr))
    conn.commit()
def save_item(item_name, russian_name, english_hash, category, subcategory):
    cursor.execute("INSERT OR REPLACE INTO items (item_name, russian_name, english_hash, category, subcategory, last_update) VALUES (?, ?, ?, ?, ?, ?)",
                   (item_name, russian_name, english_hash, category, subcategory, int(time())))
    conn.commit()
def save_price_history(item_name, timestamp, price, volume):
    cursor.execute("INSERT OR IGNORE INTO price_history (item_name, timestamp, price, volume) VALUES (?, ?, ?, ?)",
                   (item_name, timestamp, price, volume))
    conn.commit()
# ---------- FSM ----------
class CheckState(StatesGroup):
    waiting_for_query = State()
    selecting_variant = State()
class ScanState(StatesGroup):
    selecting_num_items = State()  # New state for number of items
    selecting_type = State()
    selecting_subcategory = State()
    selecting_exterior = State()
    selecting_itemset = State()
    selecting_rarity = State()
    selecting_quality = State()
    selecting_keywords = State()
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
async def safe_get(session, url, params=None, headers=None, proxy=None, retries=3, timeout=30, logger=logger):
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
async def find_english_hash_name(session, query, logger=logger):
    if not re.search(r'[а-яА-Я]', query):
        return query
    variations = [
        query,
        query + " CS2",
        query.replace(" ", "") + " CSGO"
    ]
    for var in variations:
        url = f"https://steamcommunity.com/market/search?appid={APP_ID}&q={urllib.parse.quote(var)}&l=russian"
        headers = {"Cookie": get_next_cookie()}
        proxy = get_next_proxy()
        page = await safe_get(session, url, headers=headers, proxy=proxy, logger=logger)
        if not page:
            continue
        soup = BeautifulSoup(page, "html.parser")
        row = soup.find("a", class_="market_listing_row_link")
        if row:
            href = row.get("href")
            if href:
                try:
                    hash_part = href.split('/listings/730/')[1].split('?')[0]
                    english_hash = urllib.parse.unquote(hash_part)
                    logger.info(f"Found English hash_name for '{query}' with variation '{var}': {english_hash}")
                    return english_hash
                except IndexError:
                    pass
    logger.warning(f"No results found for {query} after 3 attempts")
    return None
async def search_market_items(session, query, facets=None, limit=1000, logger=logger):
    cache_key = f"search_{query}_{json.dumps(facets, sort_keys=True)}_{limit}"
    cached = cache_get(cache_key)
    if cached:
        logger.debug(f"Returning cached results for key: {cache_key}")
        return cached
    results = []
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    start = 0
    page_size = 100
    while True:
        if facets:
            url = "https://steamcommunity.com/market/search/render/"
            params = {
                "query": query,
                "start": start,
                "count": page_size,
                "appid": APP_ID,
                "l": "russian"
            }
            valid_facets = {k: v for k, v in facets.items() if v and v != 'skip' and v in FACETS.get(k, {})}
            for key, value in valid_facets.items():
                tag = f"tag_{value}"
                if key == "type":
                    params[f"category_{APP_ID}_Type[]"] = tag
                elif key == "subcategory":
                    params[f"category_{APP_ID}_Weapon[]"] = tag
                elif key == "exterior":
                    params[f"category_{APP_ID}_Exterior[]"] = tag
                elif key == "itemset":
                    params[f"category_{APP_ID}_ItemSet[]"] = tag
                elif key == "rarity":
                    params[f"category_{APP_ID}_Rarity[]"] = tag
                elif key == "quality":
                    params[f"category_{APP_ID}_Quality[]"] = tag
            logger.debug(f"Sending request to Steam with params: {params}")
            headers = {"Cookie": get_next_cookie()}
            proxy = get_next_proxy()
            data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, logger=logger)
            if not data or not isinstance(data, dict) or not data.get("results_html"):
                logger.error(f"No valid response from Steam: {data}")
                break
            soup = BeautifulSoup(data["results_html"], "html.parser")
            rows = soup.find_all("a", class_="market_listing_row_link")
            if not rows:
                break
            for row in rows:
                name_tag = row.find("span", class_="market_listing_item_name")
                if name_tag:
                    russian = name_tag.text.strip()
                    href = row.get("href")
                    if href:
                        try:
                            hash_part = href.split('/listings/730/')[1].split('?')[0]
                            english = urllib.parse.unquote(hash_part)
                            cat = (
                                'weapon' if '|' in english
                                else 'sticker' if 'Sticker' in english
                                else 'case' if 'Case' in english
                                else 'other'
                            )
                            sub = english.split('|')[0].strip() if '|' in english else ''
                            save_item(english, russian, english, cat, sub)
                            results.append({"russian": russian, "english": english})
                        except IndexError:
                            logger.warning(f"Failed to parse href: {href}")
                            continue
            start += page_size
            if len(results) >= limit:
                break
            await asyncio.sleep(REQUEST_DELAY)
        else:
            sql_query = "SELECT russian_name, english_hash FROM items WHERE russian_name LIKE ? LIMIT ?"
            params = [f"%{query}%", limit]
            cursor.execute(sql_query, params)
            rows = cursor.fetchall()
            if rows:
                logger.debug(f"Found {len(rows)} items in database for query: {query}")
                results = [{"russian": row[0], "english": row[1]} for row in rows]
                break  # Use DB results if available
            else:
                url = "https://steamcommunity.com/market/search/render/"
                params = {
                    "query": query,
                    "start": start,
                    "count": page_size,
                    "appid": APP_ID,
                    "l": "russian"
                }
                headers = {"Cookie": get_next_cookie()}
                proxy = get_next_proxy()
                logger.debug(f"Sending request to Steam without facets: {params}")
                data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, logger=logger)
                if not data or not isinstance(data, dict) or not data.get("results_html"):
                    logger.error(f"No valid response from Steam: {data}")
                    break
                soup = BeautifulSoup(data["results_html"], "html.parser")
                rows = soup.find_all("a", class_="market_listing_row_link")
                if not rows:
                    break
                for row in rows:
                    name_tag = row.find("span", class_="market_listing_item_name")
                    if name_tag:
                        russian = name_tag.text.strip()
                        href = row.get("href")
                        if href:
                            try:
                                hash_part = href.split('/listings/730/')[1].split('?')[0]
                                english = urllib.parse.unquote(hash_part)
                                cat = (
                                    'weapon' if '|' in english
                                    else 'sticker' if 'Sticker' in english
                                    else 'case' if 'Case' in english
                                    else 'other'
                                )
                                sub = english.split('|')[0].strip() if '|' in english else ''
                                save_item(english, russian, english, cat, sub)
                                results.append({"russian": russian, "english": english})
                            except IndexError:
                                logger.warning(f"Failed to parse href: {href}")
                                continue
                start += page_size
                if len(results) >= limit:
                    break
                await asyncio.sleep(REQUEST_DELAY)
    conn.commit()
    conn.close()
    cache_set(cache_key, results)
    logger.debug(f"Returning {len(results)} results for query: {query}")
    return results

async def get_third_party_pricehistory(session, appid, market_hash_name, logger=logger):
    if not THIRD_PARTY_KEY:
        logger.warning("THIRD_PARTY_KEY not set, fallback disabled")
        return None
    url = f"https://api.steamapis.com/market/item/{appid}/{urllib.parse.quote(market_hash_name)}?api_key={THIRD_PARTY_KEY}&format=json"
    data = await safe_get(session, url, logger=logger)
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
async def get_priceoverview(session, appid, currency, market_hash_name, logger=logger):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": appid, "currency": currency, "market_hash_name": market_hash_name, "l": "russian"}
    headers = {"Cookie": get_next_cookie(), "Referer": f"https://steamcommunity.com/market/listings/{appid}/{urllib.parse.quote(market_hash_name)}"}
    proxy = get_next_proxy()
    data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES, logger=logger)
    if isinstance(data, dict) and data.get("success"):
        logger.info(f"Price overview fetched for {market_hash_name}: {data}")
        return data
    logger.warning(f"Price overview failed for {market_hash_name}")
    return {}
async def get_pricehistory(session, appid, market_hash_name, logger=logger):
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
        data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES, logger=logger)
        if data and isinstance(data, dict) and data.get("success"):
            logger.info(f"Price history fetched from Steam API for {market_hash_name}")
            return data
        await asyncio.sleep(1)
    logger.info(f"Steam price history API failed for {market_hash_name}, trying listing page")
    listing_page = await get_listing_page(session, appid, market_hash_name, logger=logger)
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
        third_party_data = await get_third_party_pricehistory(session, appid, market_hash_name, logger=logger)
        if third_party_data:
            return third_party_data
    logger.error(f"Failed to fetch price history for {market_hash_name}")
    return None
async def get_itemordershistogram(session, currency, item_nameid, logger=logger):
    if not item_nameid:
        logger.warning("No item_nameid provided for histogram")
        return {}
    url = "https://steamcommunity.com/market/itemordershistogram"
    params = {"country": "RU", "language": "russian", "currency": currency, "item_nameid": item_nameid}
    headers = {"Cookie": get_next_cookie(), "Referer": "https://steamcommunity.com/market/"}
    proxy = get_next_proxy()
    data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, retries=MAX_RETRIES, logger=logger)
    if data and isinstance(data, dict) and data.get("success"):
        logger.info(f"Histogram fetched for item_nameid={item_nameid}: {data}")
        return data
    logger.warning(f"Histogram fetch failed for item_nameid={item_nameid}")
    return {}
async def get_listing_page(session, appid, market_hash_name, logger=logger):
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
async def get_nameid_and_russian_name(session, market_hash_name, logger=logger):
    try:
        listing_page = await get_listing_page(session, APP_ID, market_hash_name, logger)
        if not listing_page:
            logger.warning(f"No listing page for {market_hash_name}")
            return None, market_hash_name, None
        nameid = None
        soup = BeautifulSoup(listing_page, "html.parser")
        match = re.search(r'Market_LoadOrderSpread\(\s*(\d+)\s*\);', listing_page)
        if match:
            nameid = match.group(1)
            logger.info(f"Extracted nameid via Market_LoadOrderSpread: {nameid}")
        if not nameid:
            scripts = soup.find_all("script", type="text/javascript")
            for script in scripts:
                if script.string:
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
                    if not nameid:
                        match = re.search(r'"market_name"\s*:\s*"[^"]*"\s*,\s*"nameid"\s*:\s*"(\d+)"', script.string)
                        if match:
                            nameid = match.group(1)
                    if not nameid:
                        match = re.search(r'item_nameid\s*=\s*["\'](\d+)["\']', listing_page)
                        if match:
                            nameid = match.group(1)
                    if not nameid:
                        data_tag = soup.find("div", {"data-hash-name": market_hash_name})
                        if data_tag and "data-id" in data_tag.attrs:
                            nameid = data_tag["data-id"]
        if not nameid:
            logger.warning(f"Failed to extract nameid for {market_hash_name}")
        russian_name_tag = soup.find("span", id="largeiteminfo_item_name")
        russian_name = russian_name_tag.text.strip() if russian_name_tag else market_hash_name
        image_tag = soup.find("div", class_="market_listing_largeimage")
        image_url = image_tag.find("img")["src"] if image_tag else None
        if not image_url:
            image_tag = soup.find("img", id="largeiteminfo_item_icon")
            image_url = image_tag["src"] if image_tag else None
        if not image_url:
            image_url = f"https://steamcommunity-a.akamaihd.net/economy/image/class/{APP_ID}/{market_hash_name.lower().replace(' ', '-').replace('|', '')}/330x192"
            logger.info(f"Using fallback image URL: {image_url}")
        logger.info(f"NameID={nameid}, Russian name={russian_name}, Image URL={image_url} for {market_hash_name}")
        return nameid, russian_name, image_url
    except Exception as e:
        logger.warning(f"Error parsing listing page for {market_hash_name}: {e}")
        return None, market_hash_name, None
def parse_price_string(s: str) -> float:
    if s is None:
        return 0.0
    s = str(s).replace('\xa0', '').replace('руб.', '').replace('RUB', '').replace(',', '.').strip()
    m = re.search(r'([0-9]*\.?[0-9]+)', s)
    return float(m.group(1)) if m else 0.0
def df_from_pricehistory(prices_raw, logger=logger):
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
        logger.warning(f"No valid price history entries processed within the last {HISTORY_DAYS} days")
        return pd.DataFrame(columns=["timestamp", "price", "volume"])
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    logger.info(f"Created DataFrame with {len(df)} rows after filtering for last {HISTORY_DAYS} days")
    return df
def analyze_dataframe(df: pd.DataFrame, current_median: float, current_volume: int, logger=logger):
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
    last_24h_start = now - timedelta(hours=24)
    prev_24h_start = now - timedelta(hours=48)
    prev_24h_end = last_24h_start
    last_24h = df[df["timestamp"] >= last_24h_start]
    prev_24h = df[(df["timestamp"] >= prev_24h_start) & (df["timestamp"] < prev_24h_end)]
    prev_price = prev_24h["price"].mean() if not prev_24h.empty else avg_price
    price_growth = ((current_median - prev_price) / prev_price * 100) if prev_price > 0 else 0.0
    prev_volume = prev_24h["volume"].sum() if not prev_24h.empty else 0
    volume_growth = 0.0
    if prev_volume > 0:
        volume_growth = ((current_volume - prev_volume) / prev_volume * 100)
    elif prev_volume == 0 and current_volume > 0:
        volume_growth = 100.0
    elif current_volume == 0:
        volume_growth = -100.0
    publications = len(last_24h)
    logger.info(f"Analysis results: volatility={volatility:.2f}, price_growth={price_growth:.2f}, volume_growth={volume_growth:.2f}, publications={publications}")
    return {
        "volatility": round(volatility, 2),
        "price_growth": round(price_growth, 2),
        "volume_growth": round(volume_growth, 2),
        "publications": int(publications),
        "avg_price": round(avg_price, 2),
    }
def plot_price_week(df: pd.DataFrame, title: str, logger=logger):
    logger.info(f"Plotting price week for {title}")
    if df.empty:
        logger.warning(f"Empty dataframe for price plot: {title}")
        return None
    now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
    week_df = df[df["timestamp"] >= (now - timedelta(days=HISTORY_DAYS))]
    if week_df.empty:
        logger.warning(f"No data for last {HISTORY_DAYS} days, using full dataframe for {title}")
        week_df = df.copy()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(week_df["timestamp"], week_df["price"], linestyle='-', color='#32CD32', linewidth=1.5)
    ax.set_title(title, fontsize=10, color='#fff', pad=10)
    ax.set_xlabel("Дата", fontsize=8, color='#ccc')
    ax.set_ylabel("Цена (руб)", fontsize=8, color='#ccc')
    ax.grid(True, linestyle='--', alpha=0.2, color='#555')
    ax.tick_params(axis='x', colors='#ccc', labelrotation=45)
    ax.tick_params(axis='y', colors='#ccc')
    fig.patch.set_facecolor('#1b2838')
    ax.set_facecolor('#1b2838')
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor='#1b2838', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    logger.info(f"Price plot generated for {title}")
    return buf
def plot_volume_week(df: pd.DataFrame, title: str, logger=logger):
    logger.info(f"Plotting volume week for {title}")
    if df.empty:
        logger.warning(f"Empty dataframe for volume plot: {title}")
        return None
    now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
    week_df = df[df["timestamp"] >= (now - timedelta(days=HISTORY_DAYS))]
    if week_df.empty:
        logger.warning(f"No data for last {HISTORY_DAYS} days, using full dataframe for {title}")
        week_df = df.copy()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(week_df["timestamp"], week_df["volume"], linestyle='-', color='#00a1d6', linewidth=1.5)
    ax.set_title(title, fontsize=10, color='#fff', pad=10)
    ax.set_xlabel("Дата", fontsize=8, color='#ccc')
    ax.set_ylabel("Объём", fontsize=8, color='#ccc')
    ax.grid(True, linestyle='--', alpha=0.2, color='#555')
    ax.tick_params(axis='x', colors='#ccc', labelrotation=45)
    ax.tick_params(axis='y', colors='#ccc')
    fig.patch.set_facecolor('#1b2838')
    ax.set_facecolor('#1b2838')
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor='#1b2838', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    logger.info(f"Volume plot generated for {title}")
    return buf
def plot_orders_histogram(histogram_json, title: str, image_url: str = None, logger=logger):
    logger.info(f"Plotting orders histogram for {title}")
    if not histogram_json or not isinstance(histogram_json, dict):
        logger.warning(f"No histogram data for {title}")
        return None
    buy = histogram_json.get("buy_order_graph", [])
    sell = histogram_json.get("sell_order_graph", [])
    if not buy and not sell:
        logger.warning(f"No buy or sell orders for histogram: {title}")
        return None
    fig, ax = plt.subplots(figsize=(10, 4))
    if buy:
        prices_b = [p[0] for p in buy]
        cum_b = [p[1] for p in buy]
        ax.plot(prices_b, cum_b, linestyle='-', color='#32CD32', label="Покупки", linewidth=1.5)
    if sell:
        prices_s = [p[0] for p in sell]
        cum_s = [p[1] for p in sell]
        ax.plot(prices_s, cum_s, linestyle='-', color='#00a1d6', label="Продажи", linewidth=1.5)
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
    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor='#1b2838', edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    logger.info(f"Histogram plot generated for {title}")
    return buf
async def process_item(session, market_hash_name, logger=logger):
    logger.info(f"Processing item: {market_hash_name}")
    try:
        if re.search(r'[а-яА-Я]', market_hash_name):
            market_hash_name = await find_english_hash_name(session, market_hash_name, logger)
            if market_hash_name is None:
                return None
        priceoverview = await get_priceoverview(session, APP_ID, CURRENCY, market_hash_name, logger)
        if not priceoverview or not priceoverview.get("success"):
            logger.warning(f"No price overview data for {market_hash_name}")
            return None
        median = parse_price_string(priceoverview.get("median_price"))
        volume = int(str(priceoverview.get("volume") or "0").replace(",", "").replace(" ", ""))
        nameid, russian_name, image_url = await get_nameid_and_russian_name(session, market_hash_name, logger)
        histogram = await get_itemordershistogram(session, CURRENCY, nameid, logger)
        history_json = await get_pricehistory(session, APP_ID, market_hash_name, logger)
        prices_raw = []
        if isinstance(history_json, dict):
            prices_raw = history_json.get("prices") or history_json.get("history") or []
        elif isinstance(history_json, str):
            try:
                parsed = json.loads(history_json)
                prices_raw = parsed.get("prices") or []
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error in price history for {market_hash_name}: {e}")
                prices_raw = []
        elif isinstance(history_json, list):
            prices_raw = history_json
        logger.info(f"Price history data for {market_hash_name}: {len(prices_raw)} entries")
        df = df_from_pricehistory(prices_raw, logger)
        for _, row in df.iterrows():
            save_price_history(market_hash_name, row["timestamp"].isoformat(), row["price"], row["volume"])
        analysis = analyze_dataframe(df, median, volume, logger)
        analysis.update({
            "current_median": median,
            "current_volume": volume,
            "sell_order_count": 0,
            "buy_order_count": 0,
        })
        if isinstance(histogram, dict) and histogram.get("success"):
            so = histogram.get("sell_order_summary", "")
            bo = histogram.get("buy_order_summary", "")
            logger.debug(f"Histogram data: sell_order_summary={so}, buy_order_summary={bo}")
            # Updated regex to handle different formats
            sell_match = re.search(r"(\d+)", so)  # Simplified to capture any number
            buy_match = re.search(r"(\d+)", bo)   # Simplified to capture any number
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
def build_caption_html(res: dict):
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
    volatility = an.get("volatility", 0.0)
    text = (
        f"{title_html}\n\n"
        f"Стоимость: {cur_med:,.2f} руб (24 часа: {price_growth:+.2f}%)\n"
        f"Объем продаж: {cur_vol} (24 часа: {volume_growth:+.2f}%)\n"
        f"Волатильность: {volatility:.2f}%\n\n"
        f"Лотов на продажу: {sell_order_count}\n"
        f"Запросов на покупку: {buy_order_count}\n\n"
        f"Публикаций за сутки: {publications}\n"
    )
    logger.info(f"Caption built for {res['item']}: sell_orders={sell_order_count}, buy_orders={buy_order_count}, publications={publications}, volatility={volatility}")
    return text
async def publish_item(session, chat_id: int, res: dict, logger=logger, with_publish_button=False):
    logger.info(f"Publishing item {res['item']} to chat {chat_id}, with_publish_button={with_publish_button}")
    caption_html = build_caption_html(res)
    temp_files = []
    media = []
    try:
        # Добавляем изображение предмета
        if res.get("image_url"):
            async with session.get(res["image_url"]) as r:
                if r.status == 200:
                    data = await r.read()
                    fn = f"img_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
                    with open(fn, "wb") as f:
                        f.write(data)
                    temp_files.append(fn)
                    media.append(types.InputMediaPhoto(media=FSInputFile(fn), caption=caption_html, parse_mode=ParseMode.HTML))
                    logger.info(f"Item image added for {res['item']}")
        
        # Добавляем график цены
        price_buf = plot_price_week(res.get("df", pd.DataFrame()), f"Изменение цены за {HISTORY_DAYS} дней — {res['russian_name']}", logger)
        if price_buf:
            fn = f"price_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
            with open(fn, "wb") as f:
                f.write(price_buf.read())
            temp_files.append(fn)
            media.append(types.InputMediaPhoto(media=FSInputFile(fn)))
            logger.info(f"Price plot added for {res['item']}")
        
        # Добавляем график объёма
        volume_buf = plot_volume_week(res.get("df", pd.DataFrame()), f"Объём продаж за {HISTORY_DAYS} дней — {res['russian_name']}", logger)
        if volume_buf:
            fn = f"vol_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
            with open(fn, "wb") as f:
                f.write(volume_buf.read())
            temp_files.append(fn)
            media.append(types.InputMediaPhoto(media=FSInputFile(fn)))
            logger.info(f"Volume plot added for {res['item']}")
        
        # Добавляем гистограмму заказов
        histogram_buf = plot_orders_histogram(res.get("histogram", {}), f"Гистограмма заказов — {res['russian_name']}", logger=logger)
        if histogram_buf:
            fn = f"hist_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
            with open(fn, "wb") as f:
                f.write(histogram_buf.read())
            temp_files.append(fn)
            media.append(types.InputMediaPhoto(media=FSInputFile(fn)))
            logger.info(f"Histogram plot added for {res['item']}")
        
        # Создаём клавиатуру, если нужна кнопка
        kb = None
        if with_publish_button:
            kb_builder = InlineKeyboardBuilder()
            kb_builder.add(types.InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data=f"publish_{res['item']}"))
            kb = kb_builder.as_markup()
        
        # Отправляем медиагруппу, если есть изображения
        if media:
            # Ограничиваем до 10 медиафайлов (ограничение Telegram)
            sent_messages = await bot.send_media_group(chat_id=chat_id, media=media[:10])
            if with_publish_button and sent_messages:
                # Отправляем отдельное сообщение с кнопкой, replying to the first message in the group
                await bot.send_message(
                    chat_id=chat_id,
                    text="Хотите опубликовать в канал?",
                    reply_markup=kb,
                    reply_to_message_id=sent_messages[0].message_id
                )
            logger.info(f"Media group sent for {res['item']} to {chat_id}")
        else:
            # Если нет изображений, отправляем только текст
            await bot.send_message(chat_id, caption_html, parse_mode=ParseMode.HTML, reply_markup=kb)
            logger.info(f"Text sent for {res['item']} to {chat_id}")
            
    except Exception as e:
        logger.exception(f"Error publishing item {res['item']}: {e}")
        await bot.send_message(chat_id, f"Ошибка при публикации: {e}", parse_mode=ParseMode.HTML)
    finally:
        # Удаляем временные файлы
        for fpath in temp_files:
            try:
                os.remove(fpath)
                logger.debug(f"Removed temporary file: {fpath}")
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {fpath}: {e}")

async def fetch_market_page(session, query="", start=0, count=100, logger=logger):
    url = "https://steamcommunity.com/market/search/render/"
    params = {"query": query, "start": start, "count": count, "appid": APP_ID, "l": "russian"}
    headers = {"Cookie": get_next_cookie()}
    proxy = get_next_proxy()
    data = await safe_get(session, url, params=params, headers=headers, proxy=proxy, logger=logger)
    return data
async def update_all_items(session, max_pages=MAX_PAGES, page_size=100, logger=logger):
    items = set()
    start = 0
    for page in range(max_pages):
        data = await fetch_market_page(session, start=start, count=page_size, logger=logger)
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
                russian = name_tag.text.strip()
                href = r.get("href")
                if href:
                    hash_part = href.split('/listings/730/')[1].split('?')[0]
                    english = urllib.parse.unquote(hash_part)
                    cat = 'weapon' if '|' in english else 'sticker' if 'Sticker' in english else 'case' if 'Case' in english else 'other'
                    sub = english.split('|')[0].strip() if '|' in english else ''
                    items.add((english, russian, cat, sub))
        logger.info(f"Page {page+1}: found {len(rows)} items, unique {len(items)}")
        start += page_size
        await asyncio.sleep(REQUEST_DELAY)
    for eng, rus, cat, sub in items:
        save_item(eng, rus, eng, cat, sub)
    return list(items)
async def scan_and_select(session, query="", max_items=100, vol_threshold=20.0, vol_growth_threshold=50.0, logger=logger, num_items=None, **facets):
    logger.info(f"Scanning market: query='{query}', facets={facets}, max_items={max_items}, vol_threshold={vol_threshold}, vol_growth_threshold={vol_growth_threshold}, num_items={num_items}")
    results = await search_market_items(session, query, facets, limit=max_items, logger=logger)
    items = [r["english"] for r in results]
    logger.info(f"Found {len(items)} items from initial search")
    if not items:
        logger.info("No items found, updating all items")
        await update_all_items(session, max_pages=MAX_PAGES, logger=logger)
        results = await search_market_items(session, query, facets, limit=max_items, logger=logger)
        items = [r["english"] for r in results]
        logger.info(f"Found {len(items)} items after updating all items")
    
    tasks = []
    selected = []
    target_num = num_items if num_items is not None else max_items
    
    for it in items:
        if len(selected) >= target_num:  # Прерываем, если уже нашли нужное количество
            logger.info(f"Reached target number of items ({target_num}), stopping processing")
            break
            
        async with semaphore:
            tasks.append(process_item(session, it, logger))
            if len(tasks) >= MAX_CONCURRENCY:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if not r or isinstance(r, Exception):
                        if isinstance(r, Exception):
                            logger.error(f"Error processing item: {r}")
                        continue
                    an = r.get("analysis", {})
                    volatility = an.get("volatility", 0)
                    volume_growth = an.get("volume_growth", 0)
                    logger.info(f"Item {r['item']}: volatility={volatility:.2f}%, volume_growth={volume_growth:.2f}%")
                    if volatility >= vol_threshold and volume_growth >= vol_growth_threshold and volume_growth > 0:
                        selected.append(r)
                        logger.info(f"Item {r['item']} selected: volatility={volatility:.2f}%, volume_growth={volume_growth:.2f}%")
                        if len(selected) >= target_num:  # Прерываем, если нашли достаточно
                            logger.info(f"Reached target number of items ({target_num}) in processing")
                            break
                    else:
                        logger.info(f"Item {r['item']} skipped: does not meet criteria (volatility={volatility:.2f}%, volume_growth={volume_growth:.2f}%)")
                tasks = []
    
    # Обработка оставшихся задач, если они есть
    if tasks and len(selected) < target_num:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if len(selected) >= target_num:  # Прерываем, если нашли достаточно
                logger.info(f"Reached target number of items ({target_num}) in final processing")
                break
            if not r or isinstance(r, Exception):
                if isinstance(r, Exception):
                    logger.error(f"Error processing item: {r}")
                continue
            an = r.get("analysis", {})
            volatility = an.get("volatility", 0)
            volume_growth = an.get("volume_growth", 0)
            logger.info(f"Item {r['item']}: volatility={volatility:.2f}%, volume_growth={volume_growth:.2f}%")
            if volatility >= vol_threshold and volume_growth >= vol_growth_threshold and volume_growth > 0:
                selected.append(r)
                logger.info(f"Item {r['item']} selected: volatility={volatility:.2f}%, volume_growth={volume_growth:.2f}%")
            else:
                logger.info(f"Item {r['item']} skipped: does not meet criteria (volatility={volatility:.2f}%, volume_growth={volume_growth:.2f}%)")
    
    # Сортировка по volume_growth (на случай, если набралось больше, чем нужно)
    selected.sort(key=lambda x: x.get("analysis", {}).get("volume_growth", 0), reverse=True)
    selected = selected[:target_num]  # Ограничиваем до target_num, если вдруг набралось больше
    logger.info(f"Selected {len(selected)} items (volatility >= {vol_threshold}%, volume_growth >= {vol_growth_threshold}%)")
    return selected

async def daily_scheduler_loop():
    while True:
        try:
            vol_threshold, vol_growth_threshold, schedule_time = get_settings()
            now = datetime.now(tz=pytz.UTC).astimezone(pytz.timezone('Europe/Moscow'))
            hour, minute = map(int, schedule_time.split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=5, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            wait = (next_run - now).total_seconds()
            logger.info(f"Scheduler sleeping for {wait} seconds until {next_run}")
            await asyncio.sleep(wait)
            async with aiohttp.ClientSession() as session:
                selected = await scan_and_select(session, max_items=100, vol_threshold=vol_threshold, vol_growth_threshold=vol_growth_threshold, logger=logger)
                if not selected:
                    if ADMIN_ID:
                        await bot.send_message(ADMIN_ID, "ℹ️ No items matched criteria today.")
                else:
                    for item in selected:
                        await publish_item(session, CHANNEL_ID, item, logger)
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
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info("Received /start command")
    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="🔧 Критерии", callback_data="set_thresholds"))
    kb.add(types.InlineKeyboardButton(text="🔍 Проверить предмет", callback_data="check_specific"))
    kb.add(types.InlineKeyboardButton(text="📊 Скан рынка", callback_data="scan_market"))
    kb.adjust(2)
    text = "Привет! Я скринер рынка Steam для CS2. Выбери действие:"
    await message.answer(text, reply_markup=kb.as_markup())
@dp.message(Command("set"))
async def cmd_set(message: types.Message):
    logger.info(f"Received /set command: {message.text}")
    parts = message.text.split()
    if len(parts) < 3:
        return await message.answer("Использование: /set <волатильность> <рост_объема>")
    try:
        vol = float(parts[1])
        volgr = float(parts[2])
        set_settings(message.from_user.id, vol, volgr)
        await message.answer(f"Установлено: волатильность ≥ {vol}%, рост объёма ≥ {volgr}%")
    except Exception as e:
        logger.error(f"Error in /set command: {e}")
        await message.answer(f"Ошибка: {e}")
@dp.message(Command("check"))
async def cmd_check(message: types.Message, state: FSMContext):
    logger.info(f"Received /check command: {message.text}")
    arg = message.text.partition(" ")[2].strip()
    if not arg:
        await state.set_state(CheckState.waiting_for_query)
        return await message.answer("Введите название скина, оружия, стикера или другого предмета (например, 'Redline', 'AK-47', 'Sticker Holo'):")
    await process_check_query(message, arg, state)
async def process_check_query(message: types.Message, query: str, state: FSMContext):
    logger.info(f"Processing check query: {query}")
    await message.answer(f"Ищу варианты для: {html_escape(query)}")
    async with aiohttp.ClientSession() as session:
        variants = await search_market_items(session, query, limit=20, logger=logger)
        if not variants:
            logger.info(f"No variants found for query: {query}")
            await message.answer("Не найдено вариантов. Попробуйте уточнить запрос (например, добавьте 'CS2' или укажите качество).")
            await state.clear()
            return
        if len(variants) == 1:
            res = await process_item(session, variants[0]["english"], logger)
            if res:
                await publish_item(session, message.chat.id, res, logger, with_publish_button=True)
            else:
                logger.warning(f"Failed to process item: {variants[0]['english']}")
                await message.answer("Не удалось обработать предмет.")
            await state.clear()
            return
        kb = InlineKeyboardBuilder()
        for i, v in enumerate(variants):
            kb.add(types.InlineKeyboardButton(text=v["russian"], callback_data=f"check_select_{i}_{query}"))
        kb.adjust(1)
        await message.answer(f"Найдено {len(variants)} вариантов. Выберите:", reply_markup=kb.as_markup())
        await state.update_data(variants=[v["english"] for v in variants])
        await state.set_state(CheckState.selecting_variant)
@dp.callback_query(CheckState.selecting_variant)
async def cb_check_select(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"Received callback for check_select: {callback.data}")
    await callback.answer()
    data = await state.get_data()
    variants = data.get("variants", [])
    if not callback.data.startswith("check_select_"):
        logger.warning(f"Invalid callback data: {callback.data}")
        return
    try:
        _, idx, _ = callback.data.rsplit("_", 2)
        idx = int(idx)
        if idx >= len(variants):
            logger.warning(f"Invalid variant index: {idx}, variants count: {len(variants)}")
            return
        selected = variants[idx]
        async with aiohttp.ClientSession() as session:
            res = await process_item(session, selected, logger)
            if res:
                await publish_item(session, callback.message.chat.id, res, logger, with_publish_button=True)
            else:
                logger.warning(f"Failed to process selected item: {selected}")
                await callback.message.answer("Не удалось обработать выбранный предмет.")
        await state.clear()
    except Exception as e:
        logger.error(f"Error in check_select callback: {e}")
        await callback.message.answer(f"Ошибка: {e}")
@dp.message(CheckState.waiting_for_query)
async def msg_check_query(message: types.Message, state: FSMContext):
    query = message.text.strip()
    logger.info(f"Received query in waiting_for_query state: {query}")
    await process_check_query(message, query, state)
@dp.message(Command("scan"))
@dp.callback_query(lambda c: c.data == "scan_market")
async def cmd_scan_start(message_or_callback, state: FSMContext):
    global _cache
    _cache.clear()  # Очистка кэша перед сканированием
    logger.info("Cache cleared before scan")
    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.answer()
            chat_id = message_or_callback.message.chat.id
            user_id = message_or_callback.from_user.id
            callback = message_or_callback
        else:
            chat_id = message_or_callback.chat.id
            user_id = message_or_callback.from_user.id
            callback = None
        logger.info(f"Starting scan from user {user_id}")
        await state.set_state(ScanState.selecting_num_items)
        text = "📊 Введите количество предметов для вывода (например, 5):"
        if isinstance(message_or_callback, types.Message):
            await message_or_callback.answer(text)
        else:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_or_callback.message.message_id)
    except Exception as e:
        logger.error(f"Error in cmd_scan_start: {e}")
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(f"Ошибка при старте сканирования: {e}")

@dp.message(ScanState.selecting_num_items)
async def msg_scan_num_items(message: types.Message, state: FSMContext):
    try:
        num_items = int(message.text.strip())
        if num_items <= 0:
            await message.answer("Пожалуйста, введите положительное число.")
            return
        await state.update_data(num_items=num_items)
        await state.set_state(ScanState.selecting_type)
        kb = build_filter_keyboard(FACETS["type"], "scan_type", add_run_button=True)
        await message.answer("📊 Выберите тип предмета для сканирования:", reply_markup=kb)
    except ValueError:
        await message.answer("Пожалуйста, введите число (например, 5).")
    except Exception as e:
        logger.error(f"Error in msg_scan_num_items: {e}")
        await message.answer(f"Ошибка: {e}")

@dp.callback_query(ScanState.selecting_type)
async def cb_scan_type(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        data = callback.data
        if data.startswith("scan_type_page_"):
            page = int(data.split("_")[-1])
            kb = build_filter_keyboard(FACETS["type"], "scan_type", page, add_run_button=True)
            await callback.message.edit_reply_markup(reply_markup=kb)
            return
        if data == "scan_type_skip":
            await state.update_data(type=None)
            await next_level(callback, state, ScanState.selecting_exterior, "exterior")  # Default to exterior if skip
            return
        type_key = data.split("_")[-1]
        type_label = FACETS["type"].get(type_key, "Неизвестно")
        await state.update_data(type=type_key)
        logger.info(f"Selected type: {type_key} ({type_label})")
        
        # Check if the selected type has subcategories
        sub_options = FACETS["subcategory"].get(type_key, {})
        if sub_options:
            # Pass the subcategory dictionary for the selected type
            await state.set_state(ScanState.selecting_subcategory)
            kb = build_filter_keyboard(sub_options, "scan_subcategory", add_run_button=True)
            breadcrumbs = await get_breadcrumbs(state)
            text = f"{breadcrumbs}\n\nВыберите подкатегорию:"
            await callback.message.edit_text(text, reply_markup=kb)
        else:
            # If no subcategories, skip to exterior
            await state.update_data(subcategory=None)
            await next_level(callback, state, ScanState.selecting_exterior, "exterior")
    except Exception as e:
        logger.error(f"Error in cb_scan_type: {e}")
        await callback.message.answer(f"Ошибка: {e}")

@dp.callback_query(ScanState.selecting_subcategory)
async def cb_scan_subcategory(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        data = callback.data
        if data.startswith("scan_subcategory_page_"):
            page = int(data.split("_")[-1])
            type_data = await state.get_data()
            type_key = type_data.get("type")
            sub_options = FACETS["subcategory"].get(type_key, {})
            kb = build_filter_keyboard(sub_options, "scan_subcategory", page, add_run_button=True)
            await callback.message.edit_reply_markup(reply_markup=kb)
            return
        if data == "scan_subcategory_skip":
            await state.update_data(subcategory=None)
            await next_level(callback, state, ScanState.selecting_exterior, "exterior")
            return
        sub_key = data.split("_")[-1]
        type_data = await state.get_data()
        type_key = type_data.get("type")
        sub_label = FACETS["subcategory"].get(type_key, {}).get(sub_key, "Неизвестно")
        await state.update_data(subcategory=sub_key)
        await next_level(callback, state, ScanState.selecting_exterior, "exterior")
    except Exception as e:
        logger.error(f"Error in cb_scan_subcategory: {e}")
        await callback.message.answer(f"Ошибка: {e}")
async def get_breadcrumbs(state: FSMContext):
    data = await state.get_data()
    path = []
    def get_label(facet_name, key):
        if facet_name == 'subcategory':
            type_key = data.get('type')
            return FACETS.get('subcategory', {}).get(type_key, {}).get(key, key)
        return FACETS.get(facet_name, {}).get(key, key)
    if 'type' in data:
        path.append(f"Тип: {get_label('type', data['type'])}")
    if 'subcategory' in data:
        path.append(f"Оружие: {get_label('subcategory', data['subcategory'])}")
    if 'exterior' in data:
        path.append(f"Оформление: {get_label('exterior', data['exterior'])}")
    if 'itemset' in data:
        path.append(f"Набор: {get_label('itemset', data['itemset'])}")
    if 'rarity' in data:
        path.append(f"Редкость: {get_label('rarity', data['rarity'])}")
    if 'quality' in data:
        path.append(f"Качество: {get_label('quality', data['quality'])}")
    return " > ".join(path) if path else ""
async def perform_scan(chat_id: int, state: FSMContext, bot: Bot):
    data = await state.get_data()
    query = data.get('keywords', "")
    num_items = data.get('num_items', 100)  # Получаем num_items из состояния
    facets = {
        "type": data.get("type"),
        "subcategory": data.get("subcategory"),
        "exterior": data.get("exterior"),
        "itemset": data.get("itemset"),
        "rarity": data.get("rarity"),
        "quality": data.get("quality"),
    }
    facets = {k: v for k, v in facets.items() if v and v != 'skip'}
    await bot.send_message(chat_id, f"🔄 Сканирую рынок по выбранным фильтрам. Ищу до {num_items} подходящих предметов...")
    try:
        async with aiohttp.ClientSession() as session:
            vol_threshold, vol_growth_threshold, _ = get_settings()
            selected = await scan_and_select(
                session,
                query=query,
                max_items=5000,
                vol_threshold=vol_threshold,
                vol_growth_threshold=vol_growth_threshold,
                logger=logger,
                num_items=num_items,  # Передаём num_items
                **facets
            )
            if not selected:
                await bot.send_message(chat_id, "❌ Ничего не найдено по критериям.")
                await state.clear()
                return
            # Ограничиваем количество отправляемых предметов
            for r in selected[:num_items]:
                await publish_item(session, chat_id, r, logger, with_publish_button=True)
                await asyncio.sleep(1)
            await bot.send_message(chat_id, f"✅ Готово! Отправлено {min(len(selected), num_items)} предметов из {len(selected)} найденных. Выберите, что опубликовать в канал.")
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await bot.send_message(chat_id, f"❌ Ошибка: {e}")
    finally:
        await state.clear()

async def next_level(callback: types.CallbackQuery, state: FSMContext, next_state: State, next_filter: str):
    try:
        breadcrumbs = await get_breadcrumbs(state)
        options = FACETS.get(next_filter, {})
        kb = build_filter_keyboard(options, f"scan_{next_filter}", add_run_button=True)
        text = f"{breadcrumbs}\n\nВыберите {next_filter.replace('_', ' ').capitalize()}:"
        await state.set_state(next_state)
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error in next_level: {e}")
        await callback.message.answer(f"Ошибка перехода: {e}")

@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    vol, volgr, schedule = get_settings(message.from_user.id)
    await message.answer(f"Текущие настройки:\nВолатильность ≥ {vol}%\nРост объёма ≥ {volgr}%\nВремя сканирования: {schedule}")

@dp.callback_query(ScanState.selecting_exterior)
async def cb_scan_exterior(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        data = callback.data
        if data.startswith("scan_exterior_page_"):
            page = int(data.split("_")[-1])
            kb = build_filter_keyboard(FACETS["exterior"], "scan_exterior", page, add_run_button=True)
            await callback.message.edit_reply_markup(reply_markup=kb)
            return
        if data == "scan_exterior_skip":
            await state.update_data(exterior=None)
            await next_level(callback, state, ScanState.selecting_itemset, "itemset")
            return
        ext_key = data.split("_")[-1]
        ext_label = FACETS["exterior"].get(ext_key, "Неизвестно")
        await state.update_data(exterior=ext_key)
        await next_level(callback, state, ScanState.selecting_itemset, "itemset")
    except Exception as e:
        logger.error(f"Error in cb_scan_exterior: {e}")
        await callback.message.answer(f"Ошибка: {e}")
@dp.callback_query(ScanState.selecting_itemset)
async def cb_scan_itemset(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        data = callback.data
        if data.startswith("scan_itemset_page_"):
            page = int(data.split("_")[-1])
            kb = build_filter_keyboard(FACETS["itemset"], "scan_itemset", page, add_run_button=True)
            await callback.message.edit_reply_markup(reply_markup=kb)
            return
        if data == "scan_itemset_skip":
            await state.update_data(itemset=None)
            await next_level(callback, state, ScanState.selecting_rarity, "rarity")
            return
        set_key = data.split("_")[-1]
        set_label = FACETS["itemset"].get(set_key, "Неизвестно")
        await state.update_data(itemset=set_key)
        await next_level(callback, state, ScanState.selecting_rarity, "rarity")
    except Exception as e:
        logger.error(f"Error in cb_scan_itemset: {e}")
        await callback.message.answer(f"Ошибка: {e}")
@dp.callback_query(ScanState.selecting_rarity)
async def cb_scan_rarity(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        data = callback.data
        if data.startswith("scan_rarity_page_"):
            page = int(data.split("_")[-1])
            kb = build_filter_keyboard(FACETS["rarity"], "scan_rarity", page, add_run_button=True)
            await callback.message.edit_reply_markup(reply_markup=kb)
            return
        if data == "scan_rarity_skip":
            await state.update_data(rarity=None)
            await next_level(callback, state, ScanState.selecting_quality, "quality")
            return
        rarity_key = data.split("_")[-1]
        rarity_label = FACETS["rarity"].get(rarity_key, "Неизвестно")
        await state.update_data(rarity=rarity_key)
        await next_level(callback, state, ScanState.selecting_quality, "quality")
    except Exception as e:
        logger.error(f"Error in cb_scan_rarity: {e}")
        await callback.message.answer(f"Ошибка: {e}")
@dp.callback_query(ScanState.selecting_quality)
async def cb_scan_quality(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        data = callback.data
        if data.startswith("scan_quality_page_"):
            page = int(data.split("_")[-1])
            kb = build_filter_keyboard(FACETS["quality"], "scan_quality", page, add_run_button=True)
            await callback.message.edit_reply_markup(reply_markup=kb)
            return
        if data == "scan_quality_skip":
            await state.update_data(quality=None)
            await start_keywords(callback, state)
            return
        quality_key = data.split("_")[-1]
        quality_label = FACETS["quality"].get(quality_key, "Неизвестно")
        await state.update_data(quality=quality_key)
        await start_keywords(callback, state)
    except Exception as e:
        logger.error(f"Error in cb_scan_quality: {e}")
        await callback.message.answer(f"Ошибка: {e}")
async def start_keywords(callback: types.CallbackQuery, state: FSMContext):
    breadcrumbs = await get_breadcrumbs(state)
    await state.set_state(ScanState.selecting_keywords)
    text = f"{breadcrumbs}\n\nВведите ключевые слова (или 'none' для без):"
    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="🚀 Запустить скан", callback_data="scan_run"))
    kb.adjust(1) # Меньше кнопок
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
@dp.message(ScanState.selecting_keywords)
async def msg_scan_keywords(message: types.Message, state: FSMContext, bot: Bot):
    query = message.text.strip().lower()
    if query == "none":
        query = ""
    await state.update_data(keywords=query)
    await perform_scan(message.chat.id, state, bot)
@dp.callback_query(lambda c: c.data == "scan_run")
async def cb_scan_run(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(keywords="")
    await perform_scan(callback.message.chat.id, state, bot)
@dp.callback_query(lambda c: c.data == "set_thresholds")
async def cb_set_thresholds(callback: types.CallbackQuery):
    await callback.answer()
    logger.info("Received set_thresholds callback")
    await callback.message.answer("Отправь /set с волатильностью и ростом объема, например: /set 20 50")
@dp.callback_query(lambda c: c.data == "check_specific")
async def cb_check_specific(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        logger.info("Received check_specific callback")
        await state.set_state(CheckState.waiting_for_query)
        await callback.message.answer("Введите название скина, оружия, стикера или другого предмета (например, 'Redline', 'AK-47', 'Sticker Holo'):")
    except Exception as e:
        logger.error(f"Error in cb_check_specific: {e}")
        await callback.message.answer(f"Ошибка: {e}")
@dp.callback_query(lambda c: c.data.startswith("publish_"))
async def cb_publish_to_channel(callback: types.CallbackQuery):
    await callback.answer()
    market_hash_name = callback.data.split("_", 1)[1]
    logger.info(f"Publishing to channel: {market_hash_name}")
    async with aiohttp.ClientSession() as session:
        res = await process_item(session, market_hash_name, logger)
        if res:
            await publish_item(session, CHANNEL_ID, res, logger, with_publish_button=False)
            await callback.message.answer("Опубликовано в канал!")
        else:
            await callback.message.answer("Ошибка при публикации.")
async def main():
    logger.info("Starting bot polling")
    init_db()
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