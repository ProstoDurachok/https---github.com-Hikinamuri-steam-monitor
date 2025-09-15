import json
import re
import urllib.parse
from bs4 import BeautifulSoup
import asyncio
import logging
from database import save_item, conn, cursor
from cache import cache_get, cache_set
from config import APP_ID, DB_FILE, REQUEST_DELAY, MAX_PAGES
from filters import FACETS
from steam_helpers import safe_get, get_next_cookie, get_next_proxy

logger = logging.getLogger("steam_screener")

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
    query = query.replace("'", "").replace('"', '')  # Очистка запроса от кавычек
    cache_key = f"search_{query}_{json.dumps(facets, sort_keys=True)}_{limit}"
    cached = cache_get(cache_key)
    if cached:
        logger.debug(f"Returning cached results for key: {cache_key}")
        return cached
    results = []
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
        cache_set(cache_key, results)
        logger.debug(f"Returning {len(results)} results for query: {query}")
        return results

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