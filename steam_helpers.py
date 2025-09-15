# Этот файл содержит хелперы для работы со Steam: куки, прокси, сессии, безопасные запросы.

import json
import asyncio
import aiohttp
from aiohttp import TCPConnector
import urllib.parse
from config import STEAM_COOKIES, PROXIES, REQUEST_DELAY, RETRY_429_DELAY, MAX_RETRIES
import logging
logger = logging.getLogger("steam_screener")

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
                            # Фикс: используем json.loads(text) вместо resp.json(), чтобы избежать повторного чтения тела
                            return json.loads(text)
                        except json.JSONDecodeError as e:
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