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
    Добавлено: отображение реферера (кто пригласил)
    """
    try:
        # Формируем ссылку на нового пользователя
        user_mention = f"<a href='{telegram_link}'>{username or 'Пользователь'}</a>"
        
        # 🔍 Поиск реферера: кто пригласил (у кого referral_code == referral_code)
        referrer_info = "не указан"
        async with aiosqlite.connect(USERSDATABASE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT telegram_id, username, telegram_link FROM users WHERE referral_code = ?",
                (referral_code,)
            )
            referrer = await cursor.fetchone()

            if referrer:
                referrer_username = referrer["username"]
                referrer_tg_link = referrer["telegram_link"]

                if referrer_tg_link:
                    referrer_info = f'<a href="{referrer_tg_link}">{referrer_username or "Пользователь"}</a>'
                elif referrer_username:
                    referrer_info = f'<a href="https://t.me/{referrer_username}">@{referrer_username}</a>'
                else:
                    ref_id = referrer["telegram_id"]
                    referrer_info = f'<a href="tg://user?id={ref_id}">Пользователь {ref_id}</a>'
            else:
                referrer_info = "реферер не найден"
            # 🔎 Если реферер не найден в таблице users, ищем в таблице referals по коду
            if referrer_info == "реферер не найден" or referrer_info == "не указан":
                try:
                    cursor_ref = await db.execute(
                        "SELECT name FROM referals WHERE code = ?", 
                        (referral_code,)
                    )
                    ref_data = await cursor_ref.fetchone()
                    if ref_data:
                        referrer_name = ref_data["name"]
                        referrer_info = f"<b>{referrer_name}</b>"
                    # Если и там не найден — оставляем "реферер не найден"
                except Exception as e:
                    logger.warning(f"Ошибка при поиске в таблице referals: {e}")
                    # Оставляем текущее значение referrer_info

        # Формируем сообщение
        message_text = (
            "✨ У вас новый пользователь! ✨\n"
            f"👤 Пользователь: {user_mention}\n"
            f"🆔 Telegram ID: <code>{telegram_id}</code>\n"
            f"🏷 Реферальный код: <code>{referral_code}</code>\n"
            f"👥 Пришёл от: {referrer_info}"
        )

        # Отправляем в группу
        try:
            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=message_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"✅ Уведомление отправлено в группу {GROUP_CHAT_ID}")
        except Exception as group_error:
            logger.error(f"❌ Ошибка отправки в группу {GROUP_CHAT_ID}: {str(group_error)}")
            # Попытка отправить ошибку обратно (опционально)
            try:
                await bot.send_message(
                    chat_id=telegram_id,
                    text=f"⚠️ Не удалось отправить уведомление в группу: {str(group_error)[:200]}...",
                    parse_mode="HTML"
                )
            except:
                logger.warning("⚠️ Не удалось отправить сообщение об ошибке")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в notify_admins: {str(e)}")
        # Функция продолжает работу, не прерывая основной поток


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
