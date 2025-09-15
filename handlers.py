# Этот файл содержит все хендлеры для Telegram бота: команды, FSM, колбэки.

from aiogram import Bot, types  # Bot для type hints
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage  # Если нужно, но storage теперь в config
import aiohttp
import asyncio
import logging
from search import search_market_items
from process import process_item, publish_item, html_escape
from scan import scan_and_select
from database import get_settings, set_settings
from filters import build_filter_keyboard, FACETS
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, APP_ID, bot, dp  # bot и dp из config
from cache import _cache  # Для очистки кэша
import traceback
logger = logging.getLogger("steam_screener")

class CheckState(StatesGroup):
    waiting_for_query = State()
    selecting_variant = State()

class ScanState(StatesGroup):
    selecting_num_items = State()
    selecting_type = State()
    selecting_subcategory = State()
    selecting_exterior = State()
    selecting_itemset = State()
    selecting_rarity = State()
    selecting_quality = State()
    selecting_keywords = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info("Received /start command")
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="🔧 Критерии", callback_data="set_thresholds"))
    kb.add(InlineKeyboardButton(text="🔍 Проверить предмет", callback_data="check_specific"))
    kb.add(InlineKeyboardButton(text="📊 Скан рынка", callback_data="scan_market"))
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
    logger.info(f"Type of search_market_items: {type(search_market_items)}")
    logger.info(f"Type of process_item: {type(process_item)}")
    logger.info(f"Type of publish_item: {type(publish_item)}")
    await message.answer(f"Ищу варианты для: {html_escape(query)}")
    async with aiohttp.ClientSession() as session:
        try:
            variants = await search_market_items(session, query, limit=20, logger=logger)
            logger.info(f"Received variants: {len(variants)} items: {variants}")
        except Exception as e:
            logger.error(f"Error in search_market_items: {e}\n{traceback.format_exc()}")
            await message.answer(f"Ошибка при поиске: {e}")
            await state.clear()
            return
        if not variants:
            logger.info(f"No variants found for query: {query}")
            await message.answer("Не найдено вариантов. Попробуйте уточнить запрос (например, добавьте 'CS2' или укажите качество).")
            await state.clear()
            return
        if len(variants) == 1:
            try:
                res = await process_item(session, variants[0]["english"], logger)
                if res:
                    await publish_item(session, message.chat.id, res, logger, with_publish_button=True)
                else:
                    logger.warning(f"Failed to process item: {variants[0]['english']}")
                    await message.answer("Не удалось обработать предмет.")
                await state.clear()
            except Exception as e:
                logger.error(f"Error in process_item or publish_item: {e}\n{traceback.format_exc()}")
                await message.answer(f"Ошибка при обработке: {e}")
                await state.clear()
            return
        kb = InlineKeyboardBuilder()
        for i, v in enumerate(variants):
            kb.add(InlineKeyboardButton(text=v["russian"], callback_data=f"check_select_{i}_{query}"))
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
    kb.add(InlineKeyboardButton(text="🚀 Запустить скан", callback_data="scan_run"))
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

async def process_check_query(message: types.Message, query: str, state: FSMContext):
    logger.info(f"Processing check query: {query}")
    logger.info(f"Type of search_market_items: {type(search_market_items)}")
    logger.info(f"Type of process_item: {type(process_item)}")
    logger.info(f"Type of publish_item: {type(publish_item)}")
    await message.answer(f"Ищу варианты для: {html_escape(query)}")
    async with aiohttp.ClientSession() as session:
        try:
            variants = await search_market_items(session, query, limit=20, logger=logger)
            logger.info(f"Received variants: {len(variants)}")
        except Exception as e:
            logger.error(f"Error in search_market_items: {e}\n{traceback.format_exc()}")
            await message.answer(f"Ошибка при поиске: {e}")
            await state.clear()
            return
        if not variants:
            logger.info(f"No variants found for query: {query}")
            await message.answer("Не найдено вариантов. Попробуйте уточнить запрос (например, добавьте 'CS2' или укажите качество).")
            await state.clear()
            return
        if len(variants) == 1:
            try:
                res = await process_item(session, variants[0]["english"], logger)
                if res:
                    await publish_item(session, message.chat.id, res, logger, with_publish_button=True)
                else:
                    logger.warning(f"Failed to process item: {variants[0]['english']}")
                    await message.answer("Не удалось обработать предмет.")
                await state.clear()
            except Exception as e:
                logger.error(f"Error in process_item or publish_item: {e}\n{traceback.format_exc()}")
                await message.answer(f"Ошибка при обработке: {e}")
                await state.clear()
            return
        kb = InlineKeyboardBuilder()
        for i, v in enumerate(variants):
            kb.add(InlineKeyboardButton(text=v["russian"], callback_data=f"check_select_{i}_{query}"))
        kb.adjust(1)
        await message.answer(f"Найдено {len(variants)} вариантов. Выберите:", reply_markup=kb.as_markup())
        await state.update_data(variants=[v["english"] for v in variants])
        await state.set_state(CheckState.selecting_variant)