from dotenv import load_dotenv
import os
from bot import bot
import aiosqlite
from log import logger

load_dotenv()

ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
USERSDATABASE = os.getenv("USERSDATABASE")

GROUP_CHAT_ID = -4924146649  # обязательно с минусом!

async def notify_admins(telegram_id: int, referral_code: str, username: str, telegram_link: str):
    """
    Улучшенная функция уведомления админов с обработкой ошибок
    Продолжает выполнение даже при недоступности чата
    """
    try:
        # Формируем сообщение
        user_mention = f"<a href='{telegram_link}'>{username or 'Пользователь'}</a>"
        
        message_text = (
            "✨ У вас новый пользователь! ✨\n"
            f"👤 Пользователь: {user_mention}\n"
            f"🆔 Telegram ID: <code>{telegram_id}</code>\n"
            f"🏷 Реферальный код: <code>{referral_code}</code>"
        )

        # Пытаемся отправить в группу (с обработкой ошибок)
        try:
            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"Уведомление отправлено в группу {GROUP_CHAT_ID}")
        except Exception as group_error:
            logger.error(f"Ошибка отправки в группу {GROUP_CHAT_ID}: {str(group_error)}")
            
            # Пытаемся отправить в fallback чат или логировать
            try:
                await bot.send_message(
                    chat_id=telegram_id,  # Или другой резервный чат
                    text=f"Не удалось отправить уведомление в группу: {str(group_error)}",
                    parse_mode="HTML"
                )
            except:
                logger.warning("Не удалось отправить сообщение об ошибке")

    except Exception as e:
        logger.error(f"Критическая ошибка в notify_admins: {str(e)}")
        # Продолжаем выполнение несмотря на ошибку


REFERRAL_CHAT_ID = -1003045150256

async def notify_referral_chat(telegram_id: int, username: str, telegram_link: str):
    """
    Отправляет уведомление в специальный чат, если пользователь пришёл от eb1a1788
    """
    try:
        user_mention = f"<a href='{telegram_link}'>{username or 'Пользователь'}</a>"
        message_text = (
            "🎯 <b>Новый пользователь через eb1a1788!</b>\n"
            f"👤 Пользователь: {user_mention}\n"
            f"🆔 Telegram ID: <code>{telegram_id}</code>\n"
        )

        try:
            await bot.send_message(
                chat_id=REFERRAL_CHAT_ID,
                text=message_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"✅ Уведомление отправлено в REFERRAL_CHAT_ID: {REFERRAL_CHAT_ID}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в REFERRAL_CHAT_ID: {str(e)}")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в notify_referral_chat: {str(e)}")