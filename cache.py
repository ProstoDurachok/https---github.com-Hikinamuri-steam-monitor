import time
import logging
from config import CACHE_TTL

logger = logging.getLogger("steam_screener")

_cache = {}

def cache_get(key):
    """Получить данные из кэша, если они не устарели."""
    try:
        entry = _cache.get(key)
        if not entry:
            logger.debug(f"Cache miss for key: {key}")
            return None
        data, ts = entry
        if time.time() - ts > CACHE_TTL:
            logger.debug(f"Cache expired for key: {key}")
            del _cache[key]
            return None
        logger.debug(f"Cache hit for key: {key}")
        return data
    except Exception as e:
        logger.error(f"Error in cache_get: {e}")
        return None

def cache_set(key, data):
    """Сохранить данные в кэш с текущей меткой времени."""
    try:
        _cache[key] = (data, time.time())  # Исправлено time() на time.time()
        logger.debug(f"Cache set for key: {key}")
    except Exception as e:
        logger.error(f"Error in cache_set: {e}")
        raise