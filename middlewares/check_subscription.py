import os
from datetime import datetime
import uuid
from typing import Callable, Awaitable, Dict, Any

from aiogram import BaseMiddleware, Router
from aiogram.types import Message, CallbackQuery, Update, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from buttons.client import BUTTON_TEXTS
from client.menu import main_menu


load_dotenv()

router = Router()

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()

    async def is_subscribed(self, user_id: int, bot) -> bool:
        """Проверяет подписку пользователя на канал."""
        try:
            chat_member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
            return chat_member.status in ["member", "administrator", "creator"]
        except Exception as e:
            print(f"Ошибка при проверке подписки: {e}")
            return False

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery | Update,
        data: Dict[str, Any],
    ) -> Any:
        """Проверяет подписку и регистрирует пользователя перед выполнением хендлера."""
        bot = data["bot"]
        
        # Определяем user_id
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        # ✅ Сначала регистрируем пользователя (даже если он не подписан)
        from client.dp_menu import handle_user_registration
        from db.db import get_user_referral_code

        telegram_id = event.from_user.id
        username = event.from_user.first_name or "Без имени"
        telegram_link = f"https://t.me/{event.from_user.username}" if event.from_user.username else None
        referral_code = await get_user_referral_code(telegram_id) or str(uuid.uuid4())[:8]
        entry_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        referred_by = None

        # Если сообщение содержит реферальный код
        if isinstance(event, Message) and event.text and len(event.text.split()) > 1:
            referred_by = event.text.split()[1]

        await handle_user_registration(telegram_id, username, telegram_link, referral_code, referred_by, entry_date)

        # ✅ Теперь проверяем подписку
        if await self.is_subscribed(user_id, bot):
            return await handler(event, data)

        # ❌ Пользователь не подписан — отправляем сообщение с кнопками, но он уже в БД
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=BUTTON_TEXTS["sub"], url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton(text=BUTTON_TEXTS["check_sub"], callback_data="check_subscription")]
            ]
        )

        text = "⚠️ Для использования бота подпишитесь на канал!\n"
        if isinstance(event, CallbackQuery):
            await bot.send_message(event.from_user.id, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)
        elif isinstance(event, Message):
            await bot.send_message(event.chat.id, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=keyboard)

        return  # 🚫 Не передаём управление дальше, если пользователь не подписан


@router.callback_query(lambda c: c.data == "check_subscription")
async def check_subscription(callback_query: CallbackQuery):
    """Проверяет подписку при нажатии кнопки 'Проверить подписку'."""
    bot = callback_query.bot
    user_id = callback_query.from_user.id

    if await SubscriptionMiddleware().is_subscribed(user_id, bot):
        await callback_query.answer("✅ Вы подписаны на канал!")
        await main_menu(callback_query.message)
    else:
        await callback_query.answer("❌ Вы не подписаны на канал. Пожалуйста, подпишитесь.")
