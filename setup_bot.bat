@echo off
chcp 65001

echo ✅ Создаём виртуальное окружение для SteamBot...
python -m venv SteamBot

echo ✅ Активируем виртуальное окружение...
call SteamBot\Scripts\activate

echo ✅ Обновляем pip...
python -m pip install --upgrade pip

echo ✅ Устанавливаем зависимости...
pip install aiogram==3.* requests matplotlib pandas numpy==2.2.5 beautifulsoup4

echo ✅ Проверяем установку...
python -c "import aiogram, requests, matplotlib, pandas, numpy, bs4; print('Все библиотеки установлены')"

echo ✅ Готово! Чтобы запустить бота, активируйте окружение:
echo call SteamBot\Scripts\activate
echo python 1.py

pause