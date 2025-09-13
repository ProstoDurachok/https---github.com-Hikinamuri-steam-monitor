import asyncio
import os
import re
import json
import sqlite3
import statistics
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from functools import lru_cache
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from asyncio import Semaphore

load_dotenv()

# ===============================
# Конфигурация (из .env)
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8427688497:AAGkBisiTfJM3RDc8DOG9Kx9l9EnekoFGQk")
STEAM_COOKIE = os.getenv("STEAM_COOKIE", "YOUR_STEAM_COOKIE")
PRICEMPIRE_KEY = os.getenv("PRICEMPIRE_KEY", "YOUR_PRICEMPIRE_KEY")
APP_ID = 730  # CS2
CURRENCY = 37  # KZT (тенге)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1002952911498"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "873939087"))
REQUEST_DELAY = 0.5  # Секунды между запросами
MAX_RETRIES = 3
CACHE_TTL = 14400  # 4 часа
semaphore = Semaphore(20)  # Лимит одновременных запросов

# База данных SQLite (только для настроек)
DB_FILE = "steam_screener.db"
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS settings (user_id INTEGER PRIMARY KEY, volatility FLOAT DEFAULT 10.0, vol_growth FLOAT DEFAULT 20.0, schedule_time TEXT DEFAULT '09:00')''')
conn.commit()

# ===============================
# Вспомогательные функции
# ===============================
def escape_markdown(text):
    """Экранирование специальных символов для MarkdownV2"""
    escape_chars = r'_[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in str(text))

def safe_url_encode(text):
    """Безопасное кодирование URL"""
    return text.replace(' ', '%20').replace('|', '%7C').replace('&', '%26')

# ===============================
# Функции Steam API
# ===============================
@lru_cache(maxsize=1000)
async def cached_get(session, url, params=None, headers=None):
    """Кэшированный асинхронный GET-запрос"""
    try:
        async with session.get(url, params=params, headers=headers, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        print(f"Ошибка запроса для {url}: {e}")
        return {}

async def get_priceoverview(session, appid: int, currency: int, market_hash_name: str):
    url = "https://steamcommunity.com/market/priceoverview/"
    params = {"appid": appid, "currency": currency, "market_hash_name": market_hash_name, "l": "russian"}
    async with semaphore:
        data = await cached_get(session, url, params=params)
        print(f"Priceoverview для {market_hash_name}: {'Success' if data.get('success') else 'Failed'}")
        return data

async def get_pricehistory_steam(session, appid: int, market_hash_name: str, cookie: str):
    url = "https://steamcommunity.com/market/pricehistory/"
    params = {"appid": appid, "market_hash_name": market_hash_name}
    headers = {"Cookie": f"steamLoginSecure={cookie}"}
    for attempt in range(MAX_RETRIES):
        async with semaphore:
            try:
                data = await cached_get(session, url, params=params, headers=headers)
                if data and data.get("prices"):
                    print(f"Steam history для {market_hash_name}: Успех")
                    return data
                print(f"Steam history для {market_hash_name}: Нет данных")
            except Exception as e:
                print(f"Steam history попытка {attempt + 1} для {market_hash_name}: {e}")
                await asyncio.sleep(REQUEST_DELAY)
    print(f"Нет Steam history для {market_hash_name}")
    return None

async def get_pricehistory_pricempire(session, market_hash_name: str):
    if not PRICEMPIRE_KEY or PRICEMPIRE_KEY == "YOUR_PRICEMPIRE_KEY":
        print("Pricempire API ключ отсутствует или недействителен")
        return None
    url = f"https://api.pricempire.com/v4/paid/items/prices?api_key={PRICEMPIRE_KEY}&app_id={APP_ID}&market_hash_name={safe_url_encode(market_hash_name)}&avg=true&median=true"
    async with semaphore:
        try:
            data = await cached_get(session, url)
            print(f"Pricempire history для {market_hash_name}: {'Success' if data else 'Failed'}")
            return data
        except Exception as e:
            print(f"Pricempire history для {market_hash_name}: {e}")
            return None

async def get_pricehistory(session, appid: int, market_hash_name: str, cookie: str):
    history = await get_pricehistory_steam(session, appid, market_hash_name, cookie)
    if not history:
        history = await get_pricehistory_pricempire(session, market_hash_name)
    return history

async def get_item_nameid_and_russian_name(session, appid: int, market_hash_name: str, cookie: str):
    url = f"https://steamcommunity.com/market/listings/{appid}/{safe_url_encode(market_hash_name)}?l=russian"
    headers = {"Cookie": f"steamLoginSecure={cookie}"}
    for attempt in range(MAX_RETRIES):
        async with semaphore:
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    resp.raise_for_status()
                    soup = BeautifulSoup(await resp.text(), 'html.parser')
                    russian_name = soup.find('span', id='largeiteminfo_item_name')
                    russian_name = russian_name.text.strip() if russian_name else market_hash_name
                    script = soup.find('script', string=re.compile('g_rgAssets'))
                    if script:
                        match = re.search(r'g_rgAssets = (.+?);', script.string, re.DOTALL)
                        if match:
                            data = json.loads(match.group(1))
                            if isinstance(data, dict) and str(appid) in data:
                                for context in data.get(str(appid), {}):
                                    assets = data[str(appid)][context]
                                    if isinstance(assets, dict):
                                        for asset in assets.values():
                                            nameid = asset.get('nameid')
                                            if nameid:
                                                return nameid, russian_name
                                    elif isinstance(assets, list):
                                        for item in assets:
                                            nameid = item.get('nameid')
                                            if nameid:
                                                return nameid, russian_name
                    print(f"Нет валидных данных g_rgAssets для {market_hash_name}")
            except Exception as e:
                print(f"Ошибка получения nameid для {market_hash_name}: {e}")
                await asyncio.sleep(REQUEST_DELAY)
    return None, market_hash_name

async def get_histogram(session, appid: int, currency: int, nameid: str, cookie: str):
    url = f"https://steamcommunity.com/market/itemordershistogram?country=RU&language=russian&currency={currency}&item_nameid={nameid}&two_factor=0"
    headers = {"Cookie": f"steamLoginSecure={cookie}"}
    for attempt in range(MAX_RETRIES):
        async with semaphore:
            try:
                data = await cached_get(session, url, headers=headers)
                print(f"Histogram для nameid {nameid}: {'Success' if data else 'Failed'}")
                return data
            except Exception as e:
                print(f"Ошибка получения гистограммы для nameid {nameid}: {e}")
                await asyncio.sleep(REQUEST_DELAY)
    return {}

async def get_item_image(session, appid: int, market_hash_name: str):
    url = f"https://steamcommunity.com/market/listings/{appid}/{safe_url_encode(market_hash_name)}"
    async with semaphore:
        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                soup = BeautifulSoup(await resp.text(), 'html.parser')
                img = soup.find('img', id='largeiteminfo_item_image')
                img_url = img['src'] if img else None
                print(f"Image для {market_hash_name}: {'Success' if img_url else 'Failed'}")
                return img_url
        except Exception as e:
            print(f"Ошибка получения изображения для {market_hash_name}: {e}")
            return None

def parse_date(date_str):
    date_str = date_str.split('+')[0].strip().rstrip(':')
    return pd.to_datetime(date_str, errors='coerce')

async def analyze_item(history: dict, item_name: str, price_data: dict, histogram: dict):
    if not history or not history.get('prices'):
        print(f"Нет валидной истории для {item_name}")
        return None
    df = pd.DataFrame(history['prices'], columns=['timestamp', 'price', 'volume'])
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
    df['timestamp'] = df['timestamp'].apply(parse_date)
    df = df.dropna()
    if df.empty:
        print(f"Пустой датафрейм для {item_name}")
        return None

    prices = df['price'].tolist()
    volumes = df['volume'].tolist()
    avg_price = statistics.mean(prices)
    stdev_price = statistics.pstdev(prices)
    volat_percent = (stdev_price / avg_price) * 100 if avg_price > 0 else 0

    current_volume = int(price_data.get('volume', '0').replace(',', ''))
    current_median = float(price_data.get('median_price', '0 KZT').split()[0].replace(',', '')) if price_data.get('median_price') else 0
    price_growth = ((current_median - prices[-1]) / prices[-1] * 100) if prices and prices[-1] > 0 else 0
    vol_growth = ((current_volume - volumes[-1]) / volumes[-1] * 100) if volumes and volumes[-1] > 0 else 0

    sell_order_count = int(re.search(r'(\d+)', histogram.get('sell_order_summary', '')).group(1)) if histogram.get('sell_order_summary') else 0
    buy_order_count = int(re.search(r'(\d+)', histogram.get('buy_order_summary', '')).group(1)) if histogram.get('buy_order_summary') else 0

    recent_df = df[df['timestamp'] >= datetime.now() - timedelta(hours=24)]
    publications = len(recent_df) if not recent_df.empty else 0

    df['sma_price'] = df['price'].rolling(window=7).mean()

    analysis = {
        "avg_price": round(avg_price, 2),
        "min_price": round(min(prices), 2),
        "max_price": round(max(prices), 2),
        "volatility": round(volat_percent, 2),
        "price_growth": round(price_growth, 2),
        "volume_growth": round(vol_growth, 2),
        "current_volume": current_volume,
        "current_median": current_median,
        "sell_order_count": sell_order_count,
        "buy_order_count": buy_order_count,
        "publications": publications,
        "df": df
    }
    print(f"Анализ для {item_name}: volatility={analysis['volatility']}, volume_growth={analysis['volume_growth']}, publications={analysis['publications']}")
    return analysis

def plot_price_volume(df, item_name):
    if df.empty:
        print(f"Не удалось создать график для {item_name}: пустой датафрейм")
        return None
    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(df['timestamp'], df['price'], color='lime', label='Цена')
    ax1.plot(df['timestamp'], df['sma_price'], color='yellow', label='SMA (7 дней)', linestyle='--')
    ax1.set_ylabel('Цена (KZT)', color='lime')
    ax1.tick_params(axis='y', labelcolor='lime')

    ax2 = ax1.twinx()
    ax2.bar(df['timestamp'], df['volume'], alpha=0.3, color='blue', label='Объём')
    ax2.set_ylabel('Объём', color='blue')
    ax2.tick_params(axis='y', labelcolor='blue')

    plt.title(f"{escape_markdown(item_name)} | {datetime.now().strftime('%Y-%m-%d')}", color='white')
    plt.tight_layout()
    plt.gcf().patch.set_facecolor('black')
    ax1.set_facecolor('black')
    ax2.set_facecolor('black')
    ax1.grid(color='gray')
    file_name = f"{item_name.replace('|', '_').replace(' ', '_')}.png"
    plt.savefig(file_name, facecolor='black')
    plt.close()
    print(f"График сохранён для {item_name}: {file_name}")
    return file_name

# ===============================
# Функции базы данных
# ===============================
def get_user_settings(user_id):
    cursor.execute("SELECT volatility, vol_growth, schedule_time FROM settings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        return row
    else:
        cursor.execute("INSERT INTO settings (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return 10.0, 20.0, '09:00'

def update_user_settings(user_id, volatility=None, vol_growth=None, schedule_time=None):
    if volatility is not None:
        cursor.execute("UPDATE settings SET volatility = ? WHERE user_id = ?", (volatility, user_id))
    if vol_growth is not None:
        cursor.execute("UPDATE settings SET vol_growth = ? WHERE user_id = ?", (vol_growth, user_id))
    if schedule_time is not None:
        cursor.execute("UPDATE settings SET schedule_time = ? WHERE user_id = ?", (schedule_time, user_id))
    conn.commit()

# ===============================
# Функции рынка
# ===============================
async def get_top_items(session, num=100):
    url = f"https://steamcommunity.com/market/search?appid={APP_ID}&l=russian&sort_column=popular&sort_dir=desc&p=1"
    async with semaphore:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                soup = BeautifulSoup(await resp.text(), 'html.parser')
                items = [row.find('span', class_='market_listing_item_name').text.strip()
                         for row in soup.find_all('a', class_='market_listing_row_link')[:num]
                         if row.find('span', class_='market_listing_item_name')]
                print(f"Получено {len(items)} топ-предметов")
                return items
        except Exception as e:
            print(f"Ошибка получения топ-предметов: {e}")
            return []

async def suggest_items(session, query: str):
    url = f"https://steamcommunity.com/market/search?appid={APP_ID}&q={safe_url_encode(query)}"
    async with semaphore:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                soup = BeautifulSoup(await resp.text(), 'html.parser')
                suggestions = [row.find('span', class_='market_listing_item_name').text.strip()
                               for row in soup.find_all('a', class_='market_listing_row_link')[:5]
                               if row.find('span', class_='market_listing_item_name')]
                print(f"Предложения для запроса '{query}': {suggestions}")
                return suggestions
        except Exception as e:
            print(f"Ошибка поиска предметов для {query}: {e}")
            return []

async def suggest_criteria(session):
    items = await get_top_items(session, 10)
    volatilities, vol_growths = [], []
    for item in items:
        price_data = await get_priceoverview(session, APP_ID, CURRENCY, item)
        history = await get_pricehistory(session, APP_ID, item, STEAM_COOKIE)
        if price_data.get("success") and history:
            analysis = await analyze_item(history, item, price_data, {})
            if analysis:
                volatilities.append(analysis['volatility'])
                vol_growths.append(analysis['volume_growth'])
    vol = statistics.median(volatilities) if volatilities else 10.0
    vol_growth = statistics.median(vol_growths) if vol_growths else 20.0
    print(f"Рекомендуемые критерии: volatility={vol}, vol_growth={vol_growth}")
    return round(vol, 1), round(vol_growth, 1)

# ===============================
# Обработка предметов
# ===============================
async def check_items(session, items, vol_threshold, vol_growth_threshold):
    selected = []
    tasks = [process_item(session, item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            print(f"Ошибка обработки: {result}")
            continue
        if result and result['analysis']['volatility'] >= vol_threshold and result['analysis']['volume_growth'] >= vol_growth_threshold:
            selected.append(result)
    selected.sort(key=lambda x: x['analysis']['volume_growth'], reverse=True)
    print(f"Найдено {len(selected)} предметов по критериям volatility≥{vol_threshold}, vol_growth≥{vol_growth_threshold}")
    return selected

async def process_item(session, item):
    async with semaphore:
        try:
            print(f"Обработка предмета: {item}")
            price_data = await get_priceoverview(session, APP_ID, CURRENCY, item)
            if not price_data.get("success"):
                print(f"Нет данных о цене для {item}")
                return None
            history = await get_pricehistory(session, APP_ID, item, STEAM_COOKIE)
            if not history:
                print(f"Нет истории для {item}")
                return None
            nameid, russian_name = await get_item_nameid_and_russian_name(session, APP_ID, item, STEAM_COOKIE)
            histogram = await get_histogram(session, APP_ID, CURRENCY, nameid, STEAM_COOKIE) if nameid else {}
            analysis = await analyze_item(history, item, price_data, histogram)
            if not analysis:
                print(f"Нет анализа для {item}")
                return None
            image_url = await get_item_image(session, APP_ID, item)
            return {
                "russian_name": russian_name or item,
                "analysis": analysis,
                "price_data": price_data,
                "histogram": histogram,
                "item": item,
                "image_url": image_url
            }
        except Exception as e:
            print(f"Ошибка для {item}: {e}")
            return None

async def publish_results(session, target_id, selected, is_channel=False):
    if not selected:
        await bot.send_message(target_id, escape_markdown("ℹ️ Нет предметов, соответствующих критериям."), parse_mode="MarkdownV2")
        return
    await bot.send_message(target_id, escape_markdown(f"🚨 Найдено {len(selected)} предметов (Топ по росту объёма):"), parse_mode="MarkdownV2")
    for res in selected[:10]:
        try:
            russian_name = escape_markdown(res['russian_name'])
            current_median = escape_markdown(f"{res['analysis']['current_median']:,.2f}")
            price_growth = escape_markdown(f"{res['analysis']['price_growth']:+.1f}")
            current_volume = escape_markdown(res['analysis']['current_volume'])
            volume_growth = escape_markdown(f"{res['analysis']['volume_growth']:+.1f}")
            sell_order_count = escape_markdown(res['analysis']['sell_order_count'])
            buy_order_count = escape_markdown(res['analysis']['buy_order_count'])
            publications = escape_markdown(res['analysis']['publications'])
            item_url = f"https://steamcommunity.com/market/listings/{APP_ID}/{safe_url_encode(res['item'])}"

            text = (
                f"**{russian_name}** ([🔗 Steam]({item_url}))\n\n"
                f"💰 Стоимость: {current_median}₸ (24 часа: {price_growth}%)\n"
                f"📈 Объём продаж: {current_volume} (24 часа: {volume_growth}%)\n"
                f"🛒 Лотов на продажу: {sell_order_count}\n"
                f"🛍️ Запросов на покупку: {buy_order_count}\n"
                f"📢 Публикаций за сутки: {publications}"
            )
            print(f"Отправляем сообщение для {russian_name}: {text}")
            await bot.send_message(target_id, text, parse_mode="MarkdownV2")

            # Отправка изображения предмета
            if res['image_url']:
                async with session.get(res['image_url']) as img_resp:
                    if img_resp.status == 200:
                        img_data = await img_resp.read()
                        await bot.send_photo(target_id, photo=img_data)
                    else:
                        print(f"Не удалось загрузить изображение для {russian_name}: HTTP {img_resp.status}")

            # Отправка графика
            img_file = plot_price_volume(res['analysis']['df'], res['russian_name'])
            if img_file:
                with open(img_file, 'rb') as photo:
                    await bot.send_photo(target_id, photo)
                os.remove(img_file)
        except TelegramBadRequest as e:
            print(f"Ошибка отправки сообщения для {res['russian_name']}: {e}")
            await bot.send_message(target_id, escape_markdown(f"❌ Ошибка при отправке данных для {res['russian_name']}: {e}"), parse_mode="MarkdownV2")
        except Exception as e:
            print(f"Неизвестная ошибка для {res['russian_name']}: {e}")
            await bot.send_message(target_id, escape_markdown(f"❌ Неизвестная ошибка для {res['russian_name']}"), parse_mode="MarkdownV2")

# ===============================
# Планировщик
# ===============================
async def daily_scheduler(session):
    while True:
        now = datetime.now()
        for user_id in [row[0] for row in cursor.execute("SELECT user_id FROM settings").fetchall()]:
            vol, vol_growth, sched_time = get_user_settings(user_id)
            sched_hour, sched_min = map(int, sched_time.split(':'))
            if now.hour == sched_hour and now.minute == sched_min:
                items = await get_top_items(session, 100)
                selected = await check_items(session, items, vol, vol_growth)
                await publish_results(session, CHANNEL_ID, selected, is_channel=True)
                await bot.send_message(ADMIN_ID, escape_markdown(f"✅ Ежедневная публикация для {user_id} выполнена."), parse_mode="MarkdownV2")
        await asyncio.sleep(60)

# ===============================
# Обработчики Telegram-бота
# ===============================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="🔧 Установить критерии", callback_data="set_thresholds"))
    kb.add(InlineKeyboardButton(text="🔍 Проверить предметы", callback_data="check_specific"))
    kb.add(InlineKeyboardButton(text="📊 Сканировать топ", callback_data="scan_top"))
    kb.add(InlineKeyboardButton(text="🚀 Проверить топ сейчас", callback_data="check_now"))
    kb.add(InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data="publish_channel"))
    kb.add(InlineKeyboardButton(text="⏰ Расписание", callback_data="set_schedule"))
    kb.add(InlineKeyboardButton(text="💡 Найти предметы", callback_data="suggest_items"))
    kb.add(InlineKeyboardButton(text="📈 Рекомендовать критерии", callback_data="suggest_criteria"))
    kb.adjust(2)
    text = escape_markdown(
        "🚀 **Steam Screener** — твой помощник для анализа рынка Steam! 🎮\n\n"
        "🔍 Проверить предметы: /check <предмет1> <предмет2>...\n"
        "📊 Сканировать топ: /scan <кол-во> (по умолчанию 100)\n"
        "💡 Найти предметы: /suggest <часть названия>\n"
        "📈 Рекомендовать критерии: /suggest_criteria\n"
        "⏰ Расписание: ежедневный скан топ-100 в канал\n\n"
        "Выбери действие или используй /help:"
    )
    print(f"Отправляем сообщение /start: {text}")
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=kb.as_markup())

@dp.message(Command("help"))
async def command_help(message: types.Message):
    text = escape_markdown(
        "📚 **Помощь по Steam Screener**\n\n"
        "/start — Запустить бота\n"
        "/set <волатильность> <рост_объема> — Установить критерии (например, /set 10 20)\n"
        "/check <предмет1> <предмет2> — Проверить предметы\n"
        "/suggest <часть названия> — Найти предметы (например, /suggest AK-47)\n"
        "/scan <кол-во> — Скан топ-предметов (например, /scan 100)\n"
        "/suggest_criteria — Рекомендовать критерии\n"
        "/schedule <HH:MM> — Расписание (например, /schedule 09:00)\n"
        "/stats — Статистика рынка\n\n"
        "📢 Бот ежедневно сканирует топ-100 и публикует в канал."
    )
    await message.answer(text, parse_mode="MarkdownV2")

@dp.callback_query(lambda c: c.data == "set_thresholds")
async def set_thresholds(callback: types.CallbackQuery):
    text = escape_markdown("🔧 Введите критерии: /set <волатильность> <рост_объема>\nПример: /set 10 20")
    await callback.message.answer(text, parse_mode="MarkdownV2")

@dp.message(Command("set"))
async def command_set_thresholds(message: types.Message):
    try:
        args = message.text.split()[1:]
        if len(args) != 2:
            return await message.answer(escape_markdown("❌ Использование: /set <волатильность> <рост_объема>\nПример: /set 10 20"), parse_mode="MarkdownV2")
        vol, vol_growth = map(float, args)
        if vol < 0 or vol_growth < 0:
            return await message.answer(escape_markdown("❌ Значения должны быть неотрицательными."), parse_mode="MarkdownV2")
        update_user_settings(message.from_user.id, volatility=vol, vol_growth=vol_growth)
        await message.answer(escape_markdown(f"✅ Критерии обновлены: волатильность ≥ {vol}%, рост объёма ≥ {vol_growth}%"), parse_mode="MarkdownV2")
    except:
        await message.answer(escape_markdown("❌ Ошибка: введите числа, например /set 10 20"), parse_mode="MarkdownV2")

@dp.callback_query(lambda c: c.data == "check_specific")
async def check_specific(callback: types.CallbackQuery):
    text = escape_markdown("🔍 Введите предметы: /check <предмет1> <предмет2>...\nПример: /check AK-47 | Redline (Field-Tested)")
    await callback.message.answer(text, parse_mode="MarkdownV2")

@dp.message(Command("check"))
async def command_check_specific(message: types.Message):
    args = message.text.split()[1:]
    if not args:
        return await message.answer(escape_markdown("❌ Использование: /check <предмет1> <предмет2>...\nПример: /check AK-47 | Redline (Field-Tested)"), parse_mode="MarkdownV2")
    items = [' '.join(args[i:i+4]) for i in range(0, len(args), 4)]
    vol, vol_growth, _ = get_user_settings(message.from_user.id)
    await message.answer(escape_markdown(f"🔄 Проверяю {len(items)} предметов по критериям: волатильность ≥ {vol}%, рост объёма ≥ {vol_growth}%..."), parse_mode="MarkdownV2")
    async with aiohttp.ClientSession() as session:
        selected = await check_items(session, items, vol, vol_growth)
        await publish_results(session, message.chat.id, selected)

@dp.callback_query(lambda c: c.data == "suggest_items")
async def suggest_items_callback(callback: types.CallbackQuery):
    text = escape_markdown("💡 Введите часть названия: /suggest <часть названия>\nПример: /suggest AK-47")
    await callback.message.answer(text, parse_mode="MarkdownV2")

@dp.message(Command("suggest"))
async def command_suggest(message: types.Message):
    args = message.text.split()[1:]
    if not args:
        return await message.answer(escape_markdown("❌ Использование: /suggest <часть названия>\nПример: /suggest AK-47"), parse_mode="MarkdownV2")
    query = ' '.join(args)
    async with aiohttp.ClientSession() as session:
        suggestions = await suggest_items(session, query)
    if not suggestions:
        return await message.answer(escape_markdown("ℹ️ Ничего не найдено. Попробуйте другое название."), parse_mode="MarkdownV2")
    await message.answer(escape_markdown("💡 Найдены предметы:\n") + "\n".join(escape_markdown(s) for s in suggestions), parse_mode="MarkdownV2")

@dp.callback_query(lambda c: c.data == "suggest_criteria")
async def suggest_criteria_callback(callback: types.CallbackQuery):
    await callback.message.answer(escape_markdown("🔄 Анализирую рынок для рекомендаций..."), parse_mode="MarkdownV2")
    async with aiohttp.ClientSession() as session:
        vol, vol_growth = await suggest_criteria(session)
    await callback.message.answer(escape_markdown(f"📈 Рекомендуемые критерии:\nВолатильность ≥ {vol}%\nРост объёма ≥ {vol_growth}%\nУстановить: /set {vol} {vol_growth}"), parse_mode="MarkdownV2")

@dp.callback_query(lambda c: c.data == "scan_top")
async def scan_top(callback: types.CallbackQuery):
    text = escape_markdown("📊 Введите количество: /scan <кол-во>\nПример: /scan 100")
    await callback.message.answer(text, parse_mode="MarkdownV2")

@dp.message(Command("scan"))
async def command_scan_top(message: types.Message):
    args = message.text.split()[1:]
    num = int(args[0]) if args else 100
    if num <= 0:
        return await message.answer(escape_markdown("❌ Количество должно быть больше 0."), parse_mode="MarkdownV2")
    vol, vol_growth, _ = get_user_settings(message.from_user.id)
    await message.answer(escape_markdown(f"📊 Сканирую топ-{num} предметов по критериям: волатильность ≥ {vol}%, рост объёма ≥ {vol_growth}%..."), parse_mode="MarkdownV2")
    async with aiohttp.ClientSession() as session:
        items = await get_top_items(session, num)
        if not items:
            return await message.answer(escape_markdown("❌ Не удалось получить топ-предметы. Проверьте соединение или API."), parse_mode="MarkdownV2")
        selected = await check_items(session, items, vol, vol_growth)
        await publish_results(session, message.chat.id, selected)

@dp.callback_query(lambda c: c.data == "check_now")
async def check_now(callback: types.CallbackQuery):
    vol, vol_growth, _ = get_user_settings(callback.from_user.id)
    await callback.message.answer(escape_markdown(f"🚀 Проверяю топ-100 по критериям: волатильность ≥ {vol}%, рост объёма ≥ {vol_growth}%..."), parse_mode="MarkdownV2")
    async with aiohttp.ClientSession() as session:
        items = await get_top_items(session, 100)
        if not items:
            return await callback.message.answer(escape_markdown("❌ Не удалось получить топ-предметы. Проверьте соединение или API."), parse_mode="MarkdownV2")
        selected = await check_items(session, items, vol, vol_growth)
        await publish_results(session, callback.message.chat.id, selected)

@dp.callback_query(lambda c: c.data == "publish_channel")
async def publish_channel(callback: types.CallbackQuery):
    vol, vol_growth, _ = get_user_settings(callback.from_user.id)
    await callback.message.answer(escape_markdown("📢 Публикую топ-100 в канал..."), parse_mode="MarkdownV2")
    async with aiohttp.ClientSession() as session:
        items = await get_top_items(session, 100)
        if not items:
            return await callback.message.answer(escape_markdown("❌ Не удалось получить топ-предметы. Проверьте соединение или API."), parse_mode="MarkdownV2")
        selected = await check_items(session, items, vol, vol_growth)
        await publish_results(session, CHANNEL_ID, selected, is_channel=True)

@dp.callback_query(lambda c: c.data == "set_schedule")
async def set_schedule(callback: types.CallbackQuery):
    text = escape_markdown("⏰ Введите время: /schedule <HH:MM>\nПример: /schedule 09:00")
    await callback.message.answer(text, parse_mode="MarkdownV2")

@dp.message(Command("schedule"))
async def command_set_schedule(message: types.Message):
    args = message.text.split()[1:]
    if len(args) != 1:
        return await message.answer(escape_markdown("❌ Использование: /schedule <HH:MM>\nПример: /schedule 09:00"), parse_mode="MarkdownV2")
    schedule_time = args[0]
    try:
        datetime.strptime(schedule_time, "%H:%M")
        update_user_settings(message.from_user.id, schedule_time=schedule_time)
        await message.answer(escape_markdown(f"✅ Расписание обновлено: ежедневно в {schedule_time} (скан топ-100)"), parse_mode="MarkdownV2")
    except:
        await message.answer(escape_markdown("❌ Формат: HH:MM, например /schedule 09:00"), parse_mode="MarkdownV2")

@dp.message(Command("stats"))
async def market_stats(message: types.Message):
    url = "https://steamcommunity.com/market/"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                soup = BeautifulSoup(await resp.text(), 'html.parser')
                stats = soup.find('div', class_='market_statistics')
                stats_text = escape_markdown(stats.text) if stats else "Нет данных"
                await message.answer(escape_markdown(f"📊 Статистика рынка:\n{stats_text}"), parse_mode="MarkdownV2")
        except Exception as e:
            await message.answer(escape_markdown(f"❌ Ошибка получения статистики: {str(e)}"), parse_mode="MarkdownV2")

# ===============================
# Запуск
# ===============================
async def main():
    async with aiohttp.ClientSession() as session:
        asyncio.create_task(daily_scheduler(session))
        await dp.start_polling(bot, handle_signals=True)

if __name__ == "__main__":
    asyncio.run(main())
