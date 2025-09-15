import sqlite3
import time
import logging
from config import DB_FILE

logger = logging.getLogger("steam_screener")

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

def init_db():
    try:
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
            last_updated INTEGER
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
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

def get_settings(user_id=None):
    try:
        if user_id:
            cursor.execute("SELECT volatility, volume_growth, schedule_time FROM settings WHERE user_id=?", (user_id,))
        else:
            cursor.execute("SELECT volatility, volume_growth, schedule_time FROM settings LIMIT 1")
        row = cursor.fetchone()
        return row if row else (20.0, 50.0, '09:00')
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return (20.0, 50.0, '09:00')

def set_settings(user_id, vol, volgr, schedule_time=None):
    try:
        if schedule_time:
            cursor.execute("INSERT OR REPLACE INTO settings (user_id, volatility, volume_growth, schedule_time) VALUES (?, ?, ?, ?)", 
                          (user_id, vol, volgr, schedule_time))
        else:
            cursor.execute("INSERT OR REPLACE INTO settings (user_id, volatility, volume_growth) VALUES (?, ?, ?)", 
                          (user_id, vol, volgr))
        conn.commit()
        logger.info(f"Settings saved for user_id {user_id}: volatility={vol}, volume_growth={volgr}")
    except Exception as e:
        logger.error(f"Error setting settings: {e}")
        raise

def save_item(item_name, russian_name, english_hash, category, subcategory):
    try:
        cursor.execute(
            """
            INSERT OR REPLACE INTO items (item_name, russian_name, english_hash, category, subcategory, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item_name, russian_name, english_hash, category, subcategory, int(time.time()))  # Исправлено time() на time.time()
        )
        conn.commit()
        logger.info(f"Saved item: {english_hash}, category: {category}, subcategory: {subcategory}")
    except Exception as e:
        logger.error(f"Error saving item {english_hash}: {e}")
        raise

def save_price_history(item_name, timestamp, price, volume):
    try:
        cursor.execute(
            """
            INSERT OR IGNORE INTO price_history (item_name, timestamp, price, volume)
            VALUES (?, ?, ?, ?)
            """,
            (item_name, timestamp, price, volume)
        )
        conn.commit()
        logger.info(f"Saved price history for {item_name} at {timestamp}")
    except Exception as e:
        logger.error(f"Error saving price history for {item_name}: {e}")
        raise