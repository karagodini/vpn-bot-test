"""
Основной модуль для запуска Telegram-бота.

Этот файл инициализирует и запускает бота, а также настраивает команды по умолчанию и инициализирует базы данных.
"""

from aiogram.types import BotCommand, BotCommandScopeDefault
from bot import dp, bot
import client.pers_account
from log import logger
import asyncio, os
import pay.process_bay
import client.dp_menu
import client.upd_sub
import admin.admin
from middlewares import check_subscription
from admin.sheduler import start_scheduler
from db.db import Database, ServerDatabase, init_referal_table
from admin import admin, add_servers
from client import dp_menu, upd_sub, referral, smena_servera
from pay import process_bay, tgpay
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

# Переменные для подключения к базам данных и идентификаторам администраторов
USERSDATABASE = os.getenv("USERSDATABASE")
SERVEDATABASE = os.getenv("SERVEDATABASE")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))

# Подключение роутеров для различных модулей
dp.include_routers(dp_menu.router, 
                   process_bay.router, 
                   upd_sub.router, 
                   referral.router, 
                   admin.router, 
                   add_servers.router, 
                   smena_servera.router, 
                   tgpay.router,
                   check_subscription.router)

async def set_default_commands():
    """
    Устанавливает команды по умолчанию для бота.

    Функция настраивает базовые команды, которые будут доступны пользователям.
    """
    commands = [
        BotCommand(command='start', description='Перезапустить бота')
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

async def on_startup():
    """
    Выполняется при запуске бота.

    Функция инициализирует базы данных, запускает планировщик задач и выводит информацию о боте и администраторах.
    В случае ошибки логируется информация и отправляется сообщение администраторам.
    """
    logger.info("🚀 Бот запускается...")
    try:
        # Инициализация базы данных пользователей и серверов
        user_db = Database(USERSDATABASE)
        server_db = ServerDatabase(SERVEDATABASE)
        user_db.setup_tables()
        server_db.setup_tables_serv()

        init_referal_table()

        logger.info("✅ Базы данных успешно инициализированы.")
        
        # Запуск планировщика задач
        await start_scheduler()
        
        # Получение информации о боте
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        logger.info(f"🔑 Логин бота: @{bot_username}")
        
        # Логирование администраторов
        logger.info(f"😎 Администраторы бота: {', '.join(map(str, ADMIN_IDS))}")
        logger.info("🥳 Бот запущен и готов к работе")
        
        # Отправка сообщений администраторам
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "✅ Базыss данных успешно инициализированы.\n"
                    f"🔑 Логин бота: @{bot_username}\n"
                    f"😎 Администраторы бота: {', '.join(map(str, ADMIN_IDS))}\n\n"
                    "🥳 Бот запущен и готов к работе",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка при отправке сообщения администратору {admin_id}: {e}")

        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}", exc_info=True)
    finally:
        logger.info("🛑 Бот остановлен.")


async def main():
    """
    Главная функция для запуска бота.

    Выполняет удаление webhook (если был установлен), устанавливает команды и запускает основные процессы бота.
    """
    await bot.delete_webhook(drop_pending_updates=True)  # Удаление ожидания новых обновлений
    await set_default_commands()  # Установка команд по умолчанию
    await on_startup()  # Запуск бота

if __name__ == "__main__":
    asyncio.run(main())  # Запуск главной функции через asyncio

