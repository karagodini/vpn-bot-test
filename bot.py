"""
Модуль инициализации бота и диспетчера.

Этот модуль загружает токен бота из переменных окружения,
создает экземпляр бота и диспетчера с использованием `aiogram`.

"""

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import os
from middlewares.check_subscription import SubscriptionMiddleware

# Загружаем переменные окружения
load_dotenv()

# Получаем токен бота из .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
ENABLE_SUBSCRIPTION = os.getenv("ENABLE_SUBSCRIPTION") == 'True'
# Создаем экземпляр бота
bot = Bot(
    token=BOT_TOKEN
)

# Создаем диспетчер с хранилищем состояний в памяти
dp = Dispatcher(storage=MemoryStorage())

if ENABLE_SUBSCRIPTION:
    dp.callback_query.middleware(SubscriptionMiddleware())
    dp.message.middleware(SubscriptionMiddleware())