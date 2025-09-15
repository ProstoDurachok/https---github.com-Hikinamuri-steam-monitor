# Этот файл содержит функции для запросов к Steam API: цены, история, гистограмма, листинг.

import json
import re
import urllib.parse
from bs4 import BeautifulSoup
import asyncio
from steam_helpers import safe_get, get_next_cookie, get_next_proxy
from config import APP_ID, CURRENCY, USE_THIRD_PARTY, THIRD_PARTY_KEY, MAX_RETRIES, semaphore
import logging
logger = logging.getLogger("steam_screener")

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