# Этот файл содержит функции обработки предмета, построения подписи и публикации в Telegram.

import html
import re
import os
import json
import urllib.parse
import pandas as pd
import asyncio
from io import BytesIO
from aiogram import types
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from analysis import df_from_pricehistory, analyze_dataframe, plot_price_week, plot_volume_week, plot_orders_histogram, parse_price_string
from api import get_priceoverview, get_pricehistory, get_itemordershistogram, get_nameid_and_russian_name
from database import save_price_history
from search import find_english_hash_name
from config import APP_ID, HISTORY_DAYS, semaphore, CURRENCY, bot  # Добавили bot
import logging
logger = logging.getLogger("steam_screener")

def html_escape(s: str) -> str:
    return html.escape(s)

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
            sell_match = re.search(r"(\d+)", so)
            buy_match = re.search(r"(\d+)", bo)
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
        if res.get("image_url"):
            async with session.get(res["image_url"]) as r:
                if r.status == 200:
                    data = await r.read()
                    fn = f"img_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
                    with open(fn, "wb") as f:
                        f.write(data)
                    temp_files.append(fn)
                    media.append(types.InputMediaPhoto(media=types.FSInputFile(fn), caption=caption_html, parse_mode=ParseMode.HTML))
                    logger.info(f"Item image added for {res['item']}")
        
        price_buf = plot_price_week(res.get("df", pd.DataFrame()), f"Изменение цены за {HISTORY_DAYS} дней — {res['russian_name']}", logger)
        if price_buf:
            fn = f"price_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
            with open(fn, "wb") as f:
                f.write(price_buf.read())
            temp_files.append(fn)
            media.append(types.InputMediaPhoto(media=types.FSInputFile(fn)))
            logger.info(f"Price plot added for {res['item']}")
        
        volume_buf = plot_volume_week(res.get("df", pd.DataFrame()), f"Объём продаж за {HISTORY_DAYS} дней — {res['russian_name']}", logger)
        if volume_buf:
            fn = f"vol_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
            with open(fn, "wb") as f:
                f.write(volume_buf.read())
            temp_files.append(fn)
            media.append(types.InputMediaPhoto(media=types.FSInputFile(fn)))
            logger.info(f"Volume plot added for {res['item']}")
        
        histogram_buf = plot_orders_histogram(res.get("histogram", {}), f"Гистограмма заказов — {res['russian_name']}", logger=logger)
        if histogram_buf:
            fn = f"hist_{re.sub(r'[^0-9A-Za-z]', '_', res['item'])}.PNG"
            with open(fn, "wb") as f:
                f.write(histogram_buf.read())
            temp_files.append(fn)
            media.append(types.InputMediaPhoto(media=types.FSInputFile(fn)))
            logger.info(f"Histogram plot added for {res['item']}")
        
        kb = None
        if with_publish_button:
            kb_builder = InlineKeyboardBuilder()
            kb_builder.add(types.InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data=f"publish_{res['item']}"))
            kb = kb_builder.as_markup()
        
        if media:
            sent_messages = await bot.send_media_group(chat_id=chat_id, media=media[:10])
            if with_publish_button and sent_messages:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Хотите опубликовать в канал?",
                    reply_markup=kb,
                    reply_to_message_id=sent_messages[0].message_id
                )
            logger.info(f"Media group sent for {res['item']} to {chat_id}")
        else:
            await bot.send_message(chat_id, caption_html, parse_mode=ParseMode.HTML, reply_markup=kb)
            logger.info(f"Text sent for {res['item']} to {chat_id}")
            
    except Exception as e:
        logger.exception(f"Error publishing item {res['item']}: {e}")
        await bot.send_message(chat_id, f"Ошибка при публикации: {e}", parse_mode=ParseMode.HTML)
    finally:
        for fpath in temp_files:
            try:
                os.remove(fpath)
                logger.debug(f"Removed temporary file: {fpath}")
            except Exception as e:
                logger.warning(f"Failed to remove temporary file {fpath}: {e}")