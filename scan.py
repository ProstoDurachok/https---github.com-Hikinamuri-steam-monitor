# Этот файл содержит функции сканирования рынка и ежедневного планировщика.

import asyncio
from datetime import datetime, timedelta
import pytz
import aiohttp
import logging
from process import process_item, publish_item
from search import search_market_items, update_all_items
from config import semaphore, POST_DELAY, CHANNEL_ID, ADMIN_ID, MAX_PAGES, bot  # Добавили bot
from database import get_settings
logger = logging.getLogger("steam_screener")

async def scan_and_select(session, query="", max_items=100, vol_threshold=20.0, vol_growth_threshold=50.0, logger=logger, num_items=None, **facets):
    logger.info(f"Scanning market: query='{query}', facets={facets}, max_items={max_items}, vol_threshold={vol_threshold}, volume_growth_threshold={vol_growth_threshold}, num_items={num_items}")
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
            if len(tasks) >= semaphore._value:  # Используем значение семафора
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