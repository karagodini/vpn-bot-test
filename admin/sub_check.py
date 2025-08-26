
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
    Проверяет подписку клиента и отправляет уведомления о сроке действия подписки.
    Учитываются условия бесплатной подписки и наличие оплаты.
    """
    expiry_time = client.get('expiryTime')
    email = client.get('email')
    telegram_id = client.get('tgId')

    if not telegram_id:
        logger.warning(f"Telegram ID не найден для клиента {email}")
        return

    # Получаем has_trial и sum_my из базы данных
    async with aiosqlite.connect("users.db") as conn:
        async with conn.execute(
            "SELECT has_trial, sum_my FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if result is None:
                logger.warning(f"Пользователь с Telegram ID {telegram_id} не найден в базе.")
                return
            has_trial, sum_my = result

    # Логика отправки уведомлений
    if sum_my == 0:
        logger.info(f"Пропускаем уведомление для {email}: пользователь ещё не платил")
        return

    if expiry_time is not None:
        expiry_date = datetime.fromtimestamp(expiry_time / 1000).date()

        if expiry_time < 0:
            logger.info(f"Пропускаем клиента {email}, срок подписки истек.")
            return

        logger.info(f"Дата окончания подписки для {email}: {expiry_date}")

        if current_date >= expiry_date:
            await send_subscription_notification(
                telegram_id,
               f"Хэй, на связи MoyVPN!\n\nТвоя подписка, c логином {email}, закончилась.\n\n Но, мы видели, ты уже оценил наш щит от слежки и блокировок.\n\nНе тормози — за 80 рублей в месяц ты получаешь:\n— неограниченный доступ к любой информации и сайтам\n— защиту трафика, даже в открытом Wi-Fi\n— скорость, которую не режут\n\nЭто как кофе на вынос — только для твоей безопасности и удобства!",
                InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription_subscr"], callback_data="extend_subscription")
            )
        else:
            for days_left in [3, 2, 1]:
                if current_date + td(days=days_left) == expiry_date:
                    notification_text = (
                        #f"Приветствую ❗️\nДо окончания подписки, c логином:{email}, {days_left} {get_days_word(days_left)} ⏳"
			f"Хай! Это не СПАМ-сообщение ‼️\n\n⏳ До окончания вашей подписки {email} осталось {days_left} {get_days_word(days_left)}!\n\nЧтобы не остаться без любимых сайтов и приложений — продлите подписку заранее!\n\nВсего 80 рублей за месяц — надёжный VPN всегда под рукой.\n\nПродлите свою подписку заранее и пользуйтесь без перебоев!"
                    )
                    await send_subscription_notification(
                        telegram_id,
                        notification_text,
                        InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription"], callback_data="extend_subscription")
                    )


async def send_subscription_notification(telegram_id, notification_text, button=None):
    """
    Отправляет уведомление клиенту через Telegram.
    Формирует и отправляет сообщение с опциональной кнопкой.
    """
    try:
        keyboard = InlineKeyboardBuilder().add(button) if button else None
        await bot.send_message(telegram_id, notification_text, reply_markup=keyboard.as_markup())
        logger.info(f"Уведомление отправлено пользователю с ID {telegram_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {telegram_id}: {e}")

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
