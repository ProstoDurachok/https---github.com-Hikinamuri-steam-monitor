# Этот файл содержит функции анализа данных: парсинг цен, создание DataFrame, анализ, построение графиков.

import re
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime, timedelta
import pytz
from config import HISTORY_DAYS
import logging
logger = logging.getLogger("steam_screener")

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