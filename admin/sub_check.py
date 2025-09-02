
from datetime import datetime, timedelta as td
import aiohttp
import json
import aiosqlite
from handlers.config import get_server_data
from bot import bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from db.db import get_server_ids_as_list
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
import os
from log import logger
load_dotenv()

USERSDATABASE = os.getenv("USERSDATABASE")
SERVEDATABASE = os.getenv("SERVEDATABASE")

async def check_all_user_subscriptions():
    """
    Проверяет все подписки через user_configs.days_left
    и отправляет уведомления пользователям через telegram_id из user_emails.
    """
    logger.info("🔄 Запущена проверка всех подписок по days_left")

    async with aiosqlite.connect("users.db") as conn:
        # Выполняем JOIN всех таблиц
        async with conn.execute("""
            SELECT 
                uc.email,
                uc.days_left,
                u.telegram_id,
                u.notified_after_3_days,
                u.notified_after_7_days
            FROM user_configs uc
            JOIN user_emails ue ON uc.email = ue.email
            JOIN users u ON ue.user_id = u.id
            WHERE u.telegram_id IS NOT NULL
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        logger.info("📭 Нет пользователей для проверки.")
        return

    for email, days_left, telegram_id, notified_3d, notified_7d in rows:
        try:
            # === 1. Уведомления ДО окончания 3 ===
            if days_left == 3:
                await send_subscription_notification(
                    telegram_id,
                    f"🛡 MoyVPN — твой щит истекает через 3 дня\nЛогин: {email}\n\n⏳ Через 3 дня защита отключится — сайты начнут блокироваться, скорость упадёт, а слежка вернётся.\n\n💡 Продли сейчас, чтобы не остаться без защиты даже на минуту.\n\n💳 Всего 90 ₽ / мес — и ты всегда под защитой.",
                    InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")
                )

            # === 2. До окончания (days_left == 2) ===
            elif days_left == 2:
                await send_subscription_notification(
                    telegram_id,
                    f"⚡ MoyVPN: осталось 2 дня до отключения\nЛогин: {email}\n\n⏳ Через 48 часов защита отключится — блокировки вернутся, скорость просядет, а слежка усилится.\n\n📌 Продли сейчас — останешься в сети без перебоев и без лишних настроек.\n\n💳 Всего 90 ₽ / мес — и ни один сайт не заблокируют.",
                    InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")
                )

            # === 2. До окончания (days_left == 1) ===
            elif days_left == 1:
                await send_subscription_notification(
                    telegram_id,
                    f"⛔ Завтра MoyVPN отключится\nЛогин: {email}\n\n⚠️ С завтрашнего дня — сайты под блокировкой, интернет медленный, данные без защиты.\n🔥 Не дай отключить свой VPN — продли сейчас и останься в безопасности.\n\n💳 Всего 90 ₽ / мес — 30 дней свободы и скорости.",
                    InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")
                )

            # === 2. В день окончания (days_left == 0) ===
            elif days_left == -1:
                await send_subscription_notification(
                    telegram_id,
                    f"🚀 MoyVPN снова в строю — для тебя за 90 ₽!\n\n⏳ Подписка {email} уже закончилась.\n\n⚠️ Без VPN: сайты блокируются, игры лагают, слежка усиливается.\n\n🔥 С VPN: полная свобода, скорость, защита данных.\n\n💳 Всего 90 ₽ / мес — это меньше, чем чашка кофе, но даёт тебе интернет без границ.\n\n👉 Продлить за 10 секунд и вернуть свободу!",
                    InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")
                )

            # === 2. В день окончания (days_left == 0) ===
            elif days_left == 0:
                await send_subscription_notification(
                    telegram_id,
                    f"🚀 MoyVPN снова в строю — для тебя за 90 ₽!\n\n⏳ Подписка {email} уже закончилась.\n\n⚠️ Без VPN: сайты блокируются, игры лагают, слежка усиливается.\n\n🔥 С VPN: полная свобода, скорость, защита данных.\n\n💳 Всего 90 ₽ / мес — это меньше, чем чашка кофе, но даёт тебе интернет без границ.\n\n👉 Продлить за 10 секунд и вернуть свободу!",
                    InlineKeyboardButton(text="Продлить подписку", callback_data="extend_subscription")
                )

            # === 3. Через 3 дня после окончания (days_left == -3) и если ещё не отправляли ===
            elif days_left == -3 and not notified_3d:
                await send_subscription_notification(
                    telegram_id,
                    f"Мы скучаем! 🫂\n\nТы пропустил MoyVPN уже 3 дня.\n\nВозьми 3 дня бесплатно — попробуй снова!",
                    InlineKeyboardButton(text="Получить 3 дня бесплатно", callback_data="trial_go")
                )
                await update_notified_flag(telegram_id, "notified_after_3_days")

            # === 4. Через 7 дней после окончания (days_left == -7) и если ещё не отправляли ===
            elif days_left == -7 and not notified_7d:
                await send_subscription_notification(
                    telegram_id,
                    f"📢 MoyVPN ждёт тебя обратно!\nЛогин: {email}\n\n⏳ Уже 3 дня твой интернет без защиты: сайты блокируются, слежка активна, скорость падает.\n\n🔥 Верни свободу и безопасность прямо сейчас — мы дарим тебе 3 дней VPN бесплатно для нового теста подписки.\n\n💳 После теста — всего 90 ₽ / мес, и ты снова с щитом от MoyVPN.",
                    InlineKeyboardButton(text="Попробовать бесплатно", callback_data="trial_7")
                )
                await update_notified_flag(telegram_id, "notified_after_7_days")

            else:
                logger.debug(f"Пропускаем {email}: days_left={days_left}, флаги={notified_3d}/{notified_7d}")

        except Exception as e:
            logger.error(f"❌ Ошибка при обработке пользователя {telegram_id} ({email}): {e}")

async def scheduled_check_subscriptions():
    """
    Запускает проверки подписок для всех клиентов на всех серверах.
    Вызывает функции для проверки истечения подписки, отправки уведомлений
    пользователям без пробной подписки, пользователям с неиспользованным промокодом,
    а также неактивным пользователям.
    """
    await check_subscription_expiry()
    await send_no_trial_broadcast()
    await send_promo_not_used_broadcast()
    await send_inactive_users_broadcast()

async def check_subscription_expiry():
    """
    Проверяет подписки клиентов на всех серверах.
    Для каждого сервера выполняет авторизацию и проверяет срок подписки клиентов.
    Если подписка истекла, отправляется уведомление.
    """
    current_date = datetime.today().date()
    logger.info(f"Текущая дата: {current_date}")

    async with aiohttp.ClientSession() as session:
        for server_id in await get_server_ids_as_list(SERVEDATABASE):
            server_data = await get_server_data(server_id)
            if not server_data:
                logger.error(f"Не удалось получить данные для сервера ID {server_id}")
                continue
            await process_server_subscriptions(server_data, current_date, session)

async def process_server_subscriptions(server_data, current_date, session):
    """
    Авторизуется на сервере и обрабатывает подписки клиентов.
    Проверяет подписки клиентов на сервере и отправляет уведомления, если срок подписки истекает.
    """
    login_data = {
        "username": server_data["username"],
        "password": server_data["password"],
    }

    try:
        async with session.post(server_data["login_url"], json=login_data) as response:
            if response.status != 200:
                logger.error(f"Ошибка входа на сервер {server_data['name']}: {await response.text()}")
                return

            cookies = response.cookies
            session_id = cookies.get('3x-ui').value
            headers = {'Accept': 'application/json', 'Cookie': f'3x-ui={session_id}'}

            logger.info(f"Авторизация на сервере {server_data['name']} успешна.")
            for inbound_id in server_data["inbound_ids"]:
                await process_inbound_clients(inbound_id, server_data, headers, current_date, session)

    except Exception as e:
        logger.error(f"Ошибка при работе с сервером {server_data['name']}: {e}")

async def process_inbound_clients(inbound_id, server_data, headers, current_date, session):
    """
    Обрабатывает данные клиентов для конкретного inbound.
    Проверяет подписки клиентов и отправляет уведомления о скором окончании подписки.
    """
    url = f"{server_data['config_client_url']}/{inbound_id}"
    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                logger.error(f"Ошибка получения данных inbound для ID {inbound_id}: {await response.text()}")
                return

            data = await response.json()
            clients = json.loads(data['obj']['settings']).get('clients', [])
            for client in clients:
                await check_client_subscription(client, current_date)

    except Exception as e:
        logger.error(f"Ошибка при обработке inbound {inbound_id}: {e}")

async def check_client_subscription(client, current_date):
    """
    Проверяет подписку клиента по days_left из user_configs.
    Отправляет уведомления:
    - за 3, 2, 1 день до окончания (days_left = 3,2,1)
    - при days_left = 0 (в день окончания)
    - при days_left = -3, -7 (если ещё не отправляли)
    """
    email = client.get('email')
    telegram_id = client.get('tgId')

    if not telegram_id:
        logger.warning(f"Telegram ID не найден для клиента {email}")
        return

    async with aiosqlite.connect("users.db") as conn:
        # Получаем days_left из user_configs по email
        async with conn.execute(
            "SELECT days_left FROM user_configs WHERE email = ?", (email,)
        ) as cursor:
            result = await cursor.fetchone()
            if result is None:
                logger.warning(f"Конфиг для email {email} не найден в user_configs.")
                return
            days_left = result[0]

        # Получаем флаги уведомлений и has_trial из users
        async with conn.execute(
            "SELECT has_trial, sum_my, notified_after_3_days, notified_after_7_days FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if result is None:
                logger.warning(f"Пользователь с Telegram ID {telegram_id} не найден.")
                return
            has_trial, sum_my, notified_3d, notified_7d = result

    # === 1. Уведомления ДО окончания (за 3, 2, 1 день) ===
    if days_left in [3, 2, 1]:
        await send_subscription_notification(
            telegram_id,
            f"Хай! Это не СПАМ-сообщение ‼️\n\n⏳ До окончания вашей подписки {email} осталось {days_left} {get_days_word(days_left)}!\n\nЧтобы не остаться без любимых сайтов и приложений — продлите подписку заранее!",
            InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription"], callback_data="extend_subscription")
        )

    # === 2. В день окончания (days_left == 0) ===
    elif days_left == 0:
        await send_subscription_notification(
            telegram_id,
            f"Хэй, на связи MoyVPN!\n\nТвоя подписка, c логином {email}, закончилась.\n\nНо ты уже оценил наш щит от слежки и блокировок.\n\nПродли за 90 руб/мес — получи защиту, скорость и свободу!",
            InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription_subscr"], callback_data="extend_subscription")
        )

    # === 3. Через 3 дня после окончания (days_left == -3) и если ещё не отправляли ===
    elif days_left == -3 and not notified_3d:
        await send_subscription_notification(
            telegram_id,
            f"Мы скучаем! 🫂\n\nТы пропустил MoyVPN уже 3 дня.\n\nВозьми 3 дня бесплатно — попробуй снова!",
            InlineKeyboardButton(text="Получить 3 дня бесплатно", callback_data="trial_go")
        )
        await conn.execute("UPDATE users SET notified_after_3_days = 1 WHERE telegram_id = ?", (telegram_id,))
        await conn.commit()

    # === 4. Через 7 дней после окончания (days_left == -7) и если ещё не отправляли ===
    elif days_left == -7 and not notified_7d:
        await send_subscription_notification(
            telegram_id,
            f"Финальный шанс! 🔥\n\nТы давно не заходил.\n\nПопробуй ещё 3 дня бесплатно — вдруг снова понравится?",
            InlineKeyboardButton(text="Попробовать бесплатно", callback_data="trial_go")
        )
        await conn.execute("UPDATE users SET notified_after_7_days = 1 WHERE telegram_id = ?", (telegram_id,))
        await conn.commit()

    else:
        logger.debug(f"Пропускаем уведомление для {email}, days_left = {days_left}")


async def send_subscription_notification(telegram_id, notification_text, button=None):
    try:
        keyboard = InlineKeyboardBuilder().add(button).as_markup() if button else None
        await bot.send_message(telegram_id, notification_text, reply_markup=keyboard)
        logger.info(f"✅ Уведомление отправлено пользователю {telegram_id}")
    except Exception as e:
        logger.error(f"❌ Не удалось отправить сообщение {telegram_id}: {e}")

async def update_notified_flag(telegram_id, column_name):
    """Обновляет флаг (например, notified_after_3_days) в таблице users"""
    async with aiosqlite.connect("users.db") as conn:
        await conn.execute(f"UPDATE users SET {column_name} = 1 WHERE telegram_id = ?", (telegram_id,))
        await conn.commit()
    logger.info(f"📌 Флаг {column_name} установлен для пользователя {telegram_id}")

def get_days_word(days):
    """
    Возвращает правильное слово для дней в зависимости от числа.
    """
    if 5 <= days <= 20 or days % 10 in [0, 5, 6, 7, 8, 9]:
        return 'дней'
    elif days % 10 == 1:
        return 'день'
    else:
        return 'дня'

async def send_no_trial_broadcast():
    """
    Рассылка сообщений пользователям, которые ввели промокод, но не использовали его.
    Сообщает о возможности использования скидки.
    """
    async with aiosqlite.connect(USERSDATABASE) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT u.telegram_id
                FROM users u
                LEFT JOIN user_emails ue ON u.id = ue.user_id
                WHERE u.has_trial = 0 AND ue.user_id IS NULL
                """
            )
            no_trial_users = await cursor.fetchall()

    successful, failed = 0, 0
    no_trial_message = (
        "Здравствуйте!"
        "\n\nМы заметили, что вы еще не подключились к нашему VPN. 😔"
        "\n\nМы понимаем, что настройка может быть чуть сложнее, чем обычно, но поверь, это того стоит! 😉 "
        "\n\nНаш VPN обеспечивает не только высокую скорость и полное отсутствие рекламы, но и отличную надежность."
        "\n\nЕсли у тебя возникли проблемы с подключением, наша команда технической поддержки всегда готова помочь! 🤝"
        "\n\nА еще у нас есть подробные инструкции со скриншотами. "
        "\n\nПросто выбери свое устройство, и мы пришлем тебе руководство по подключению 👇"
    )
    trialBuilder = InlineKeyboardBuilder()
    trialBuilder.add(InlineKeyboardButton(text=BUTTON_TEXTS["trial"], callback_data="trial_1"))

    for (user_id,) in no_trial_users:
        try:
            await bot.send_message(
                user_id,
                no_trial_message,
                reply_markup=trialBuilder.as_markup()
            )
            successful += 1
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
            failed += 1

    logger.info(f"Успешно отправлено сообщений (без пробной подписки): {successful}, не удалось отправить: {failed}")
    
async def send_promo_not_used_broadcast():
    """
    Рассылка сообщений пользователям, которые давно не заходили.
    Сообщает о новых возможностях и призывает вернуться.
    """
    async with aiosqlite.connect(USERSDATABASE) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT telegram_id
                FROM users
                WHERE promo_code IS NOT NULL
                AND promo_code_usage = 0
                AND EXISTS (
                    SELECT 1
                    FROM promo_codes
                    WHERE promo_codes.code = users.promo_code
                )
                """
            )
            promo_not_used_users = await cursor.fetchall()

    successful, failed = 0, 0
    promo_not_used_message = (
        "💡 Вы ввели промокод, но ещё не использовали его. Скорее воспользуйтесь дополнительной скидкой!"
    )
    trial_button_builder = InlineKeyboardBuilder()
    trial_button_builder.add(InlineKeyboardButton(text=BUTTON_TEXTS["buy_vpn"], callback_data="buy_vpn"))

    for (user_id,) in promo_not_used_users:
        try:
            await bot.send_message(
                user_id,
                promo_not_used_message,
                reply_markup=trial_button_builder.as_markup()
            )
            successful += 1
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
            failed += 1

    logger.info(f"Успешно отправлено сообщений (неиспользованный промокод): {successful}, не удалось отправить: {failed}")
    
async def send_inactive_users_broadcast():
    """
    Рассылка сообщений пользователям, которые давно не заходили.
    """
    current_date = datetime.now().date()
    inactive_threshold = current_date - td(days=15)  # Порог для неактивных пользователей (15 дней)

    async with aiosqlite.connect(USERSDATABASE) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT telegram_id
                FROM users
                WHERE entry_date < ?
                """,
                (inactive_threshold.strftime('%Y-%m-%d'),)
            )
            inactive_users = await cursor.fetchall()

    successful, failed = 0, 0
    inactive_message = (
        "Эй! Уже 7 дней без VPN"
        "\nYouTube снова лагает? Discord тормозит? Сайты не открываются?"
        "\n\nДавай сделаем так:"
        "\nОформляешь подписку — а мы даём тебе +7 дней в подарок."
        "\n\nПросто за то, что ты классный."
        "\n\nНажимай — вернём свободу в интернет!"
    )
    for (user_id,) in inactive_users:
        try:
            await bot.send_message(
                user_id,
                inactive_message
            )
            successful += 1
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
            failed += 1

    logger.info(f"Успешно отправлено сообщений (неактивные пользователи): {successful}, не удалось отправить: {failed}")

async def get_server_ids_as_list_for_days_left(db_path):
    """
    Получает список ID всех серверов из таблицы 'servers' в БД.
    """
    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute("SELECT id FROM servers") as cursor:
                rows = await cursor.fetchall()
                server_ids = [row[0] for row in rows]
                logger.info(f"✅ Загружены server_ids из servers: {server_ids}")
                return server_ids
    except Exception as e:
        logger.error(f"❌ Ошибка при получении server_ids из таблицы servers: {e}")
        return []

