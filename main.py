import asyncio
from logging_setup import setup_logging
from database import init_db
from config import BOT_TOKEN
from handlers import dp
from config import bot  # Добавлено для dp.start_polling(bot)
from scan import daily_scheduler_loop
logger = setup_logging()

async def main():
    logger.info("Starting bot polling")
    init_db()
    max_retries = 5
    retry_delay = 5
    for attempt in range(1, max_retries + 1):
        try:
            asyncio.create_task(daily_scheduler_loop())
            await dp.start_polling(bot)  # Теперь bot определён
            break
        except Exception as e:
            logger.error(f"Polling failed, attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached, stopping bot")
                raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception(f"Critical error: {e}")