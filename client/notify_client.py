from log import logger
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from buttons.client import BUTTON_TEXTS

async def notify_user_about_free_days(telegram_id: int, free_days: int, bot):
    """
    Оповещает пользователя о начисленных бесплатных днях подписки.
    """
    
    message_text = f"🎉 Ваш друг купил подписку, вам начислено <b>{free_days}</b> дня(ей) подписки!\nМожете потратить их в личном кабинете 😉"
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription"], callback_data="extend_subscription")
    )
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=message_text,
            reply_markup=builder.adjust(1).as_markup(),
            parse_mode="HTML"
        )
        logger.info(f"Оповещение отправлено пользователю {telegram_id}: {free_days} дня(ей)")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {telegram_id}: {e}")
