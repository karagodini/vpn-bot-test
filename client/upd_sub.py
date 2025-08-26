import asyncio, json, requests, time, uuid
from datetime import datetime as dt
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import ClientSession, TCPConnector
from aiogram import Router, F
from uuid import uuid4
from aiogram.enums.parse_mode import ParseMode
from bot import bot
from log import logger
from client.menu import get_main_menu, get_back_button
from db.db import Database, get_emails_from_database, get_server_id, update_sum_my, update_sum_ref, add_free_days, get_db_connection
from handlers.config import get_server_data
from pay.prices import *
from pay.payments import (
    create_payment_yookassa,
    check_payment_yookassa, 
    create_paymentupdate, 
    create_payment_robokassa, 
    check_payment_robokassa, 
    create_payment_cryptobot, 
    check_payment_cryptobot, 
    create_payment_tgpay, 
    create_cloudpayments_invoice, 
    check_payment_cloud,
    create_yoomoney_invoice,
    check_yoomoney_payment_status
)
from pay.process_bay import is_valid_email
from db.db import  handle_database_operations
from handlers.states import UpdClient
from pay.promocode import log_promo_code_usage
from pay.pay_metod import PAYMENT_METHODS
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
from admin.notify import GROUP_CHAT_ID
import os

load_dotenv()

EMAIL = os.getenv("EMAIL")
YOOMONEY_CARD = int(os.getenv("YOOMONEY_CARD"))

FIRST_CHECK_DELAY = int(os.getenv("FIRST_CHECK_DELAY", 15))
SUBSEQUENT_CHECK_INTERVAL = int(os.getenv("SUBSEQUENT_CHECK_INTERVAL", 30))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 15))

PASS2 = os.getenv("PASS2")
SERVEDATABASE = os.getenv("SERVEDATABASE")
FREE_DAYS = os.getenv("FREE_DAYS")
ENABLE_FREE_UPD = os.getenv("ENABLE_FREE_UPD")

router = Router()

async def gather_in_chunks(tasks, chunk_size):
    """
    Разбивает список задач на части и выполняет их параллельно.

    - Разделяет список задач на небольшие группы и выполняет их асинхронно.
    - Возвращает объединённые результаты выполнения задач.
    """
    results = []
    for i in range(0, len(tasks), chunk_size):
        chunk = tasks[i:i + chunk_size]
        results.extend(await asyncio.gather(*chunk))
    return results


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

@router.callback_query(lambda callback_query: callback_query.data == "extend_subscription")
async def handle_get_config2(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос пользователя на продление подписки, проверяя наличие конфигураций для пользователя.

    - Извлекает логин пользователя из базы данных.
    - Получает информацию о подписках пользователя.
    - Отображает информацию о текущих подписках с возможностью их продления.
    - Добавляет кнопки для продления подписки с выбором логина подписки.
    """
    telegram_id = callback_query.from_user.id
    logger.info(f"DEBUG: Используется telegram_id {telegram_id}")

    emails = await get_emails_from_database(telegram_id)
    if not emails:
        logger.error(f"DEBUG: Не найдено email для telegram_id {telegram_id}")
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))
        keyboard.adjust(1)
        await callback_query.message.edit_text(
            "❌ Не удалось найти ваши конфигурации.",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
        return

    responses = await gather_in_chunks([from_upd_sub(email) for email in emails], chunk_size=10)
    keyboard = InlineKeyboardBuilder()
    full_response = []

    # Кнопки продления подписки
    for email, response in zip(emails, responses):
        if response:
            full_response.append(response)
            if "📅 <b>Подписка действует до</b>:" in response:
                keyboard.add(InlineKeyboardButton(
                    text=f"🔑 Продлить подписку",
                    callback_data=f"extend_subscription_{email}"
                ))

    keyboard.adjust(1)  # <--- Важно: 1 колонка для подписок

    if full_response:
        response_text = "\n\n".join(full_response)

        # Клавиатура инструкций (отдельный builder с 2 колонками)
        instruction_keyboard = InlineKeyboardBuilder()
        instruction_keyboard.add(
            InlineKeyboardButton(text="🍏 IOS", callback_data="show_instruction_ios"),
            InlineKeyboardButton(text="📱 Android", callback_data="show_instruction_android"),
            InlineKeyboardButton(text="💻 MacOS", callback_data="show_instruction_macos"),
            InlineKeyboardButton(text="🖥 Windows", callback_data="show_instruction_windows"),
        )
        instruction_keyboard.adjust(2)  # <--- Важно: 2 колонки для инструкций

        # Кнопка main_menu (отдельный builder с 1 колонкой)
        main_menu_keyboard = InlineKeyboardBuilder()
        main_menu_keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu")
        )
        main_menu_keyboard.adjust(1)  # <--- Важно: 1 колонка

        # Собираем всё
        keyboard.attach(instruction_keyboard)
        keyboard.attach(main_menu_keyboard)

        await callback_query.message.edit_text(
            response_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    else:
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))
        keyboard.adjust(1)
        await callback_query.message.edit_text(
            "❌ Не удалось найти активных подписок.",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )

    await state.update_data(emails=emails)

@router.callback_query(lambda c: c.data.startswith("show_instruction_ios"))
async def process_instruction_callback_ios(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://apps.apple.com/app/id6476628951'>v2RayTun</a></b> из Appstore\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее\n\n"
        "3️⃣ Перейдите в приложение <b>v2RayTun</b>, нажмите на плюсик в правом верхнем углу "
        "-> \"Добавить из буфера\" и активируйте VPN"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/MoyVPN-na-IOS-v2RayTun-04-28")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith("show_instruction_android"))
async def process_instruction_callback_android(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://play.google.com/store/apps/details?id=com.v2raytun.android&pli=1'>v2Box</a></b> из Google Play\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее\n\n"
        "3️⃣ Перейдите в приложение <b>v2Box</b>, нажмите на плюсик в правом верхнем углу "
        "-> \"Добавить из буфера\" и активируйте VPN"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/MoyVPN-na-Android-04-28")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith("show_instruction_macos"))
async def process_instruction_callback_macos(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://apps.apple.com/app/id6476628951'>v2RayTun</a></b> из Appstore\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее\n\n"
        "3️⃣ Перейдите в приложение <b>v2RayTun</b>, нажмите на плюсик в правом верхнем углу "
        "-> \"Добавить из буфера\" и активируйте VPN"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/MoyVPN-na-MacOS-v2RayTun-04-28")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith("show_instruction_windows"))
async def process_instruction_callback_windows(callback_query: types.CallbackQuery, state: FSMContext):

    instruction_text = (
        "1️⃣ Скачайте приложение <b><a href='https://hiddify.com/'>Hiddify</a></b>\n\n"
        "2️⃣ Скопируйте ссылку, нажав на нее\n\n"
        "3️⃣ Перейдите в приложение <b>Hiddify</b>, нажмите на плюсик в правом верхнем углу "
        "-> \"Добавить из буфера\" и активируйте VPN"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Пошаговая инструкция", url="https://telegra.ph/Instrukciya-po-ustanovke-Hiddify-ot-MoyVPN-08-19")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")]
    ])


    # Отправляем новое сообщение, не удаляя старое
    await callback_query.message.answer(
        instruction_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback_query.answer()


async def from_upd_sub(email: str):
    """
    Получает информацию о подписках пользователя по логину и серверу, а также выводит данные о текущих подписках.

    - Извлекает данные серверов и идентификаторов клиентов из базы данных.
    - Выполняет запросы к серверам для получения информации о подписках пользователя.
    - Формирует ответ с информацией о подписке или сообщением об ошибке.
    """
    server_ids = await get_server_id(SERVEDATABASE)
    db = Database(USERSDATABASE)
    client_ids = await db.get_ids_by_email(email)

    if not client_ids:
        return f"❌ Не удалось найти клиента с email: {email}"
    responses = await gather_in_chunks(
        [sub_server(server_id, client_id, email) for client_id in client_ids for server_id in server_ids], 
        chunk_size=5
    )
    return "\n\n".join(filter(None, responses)) if responses else f"❌ Прошлая конфигурация уже недоступна для {email}."

async def sub_server(server_id, client_id, email):
    """
    Подключает клиента к серверу и получает информацию о подписке пользователя.

    - Авторизует пользователя на сервере и получает данные о подписке.
    - Если подписка активна, возвращает информацию о сроке действия и config.
    """
    server_data = await get_server_data(server_id)
    if not server_data:
        return ""
    try:
        expiry_text = await sub_client(client_id, email, server_data)
        if expiry_text:
            # Получаем config из таблицы user_configs
            conn = await get_db_connection()
            config = "❗ Config не найден"
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT config FROM user_configs WHERE email = ?
                    """,
                    (email,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    config = row[0]
            except Exception as e:
                logger.error(f"[sub_server] Ошибка при получении config: {e}")
                config = "❗ Ошибка получения config"
            finally:
                conn.close()

            return (
                f"👤 <b>Ваш айди</b>: {email}\n"
                f"{expiry_text}\n\n"
                f"🔑 <b>Ваш ключ</b>:\n\n<pre><code>{config}</code></pre>\n"
                f"*нажмите, что бы скопировать☝️\n\n"
                f"🚨 <b>Тех поддержка</b>: @moy_help\n\n"
                f"<b>Инструкция для каждого устройства по кнопке ниже</b> 👇"
            )
    except Exception as e:
        logger.error(f"Ошибка при подключении к серверу {server_id}: {e}")
    return ""



async def sub_client(client_id, email, server_data):
    """
    Авторизует клиента на сервере и получает данные о подписке.

    Отправляет запрос на сервер для получения информации о подписке.
    Если подписка активна, возвращает срок действия подписки.
    """
    LOGIN_DATA = {
        "username": server_data["username"],
        "password": server_data["password"],
    }
    async with ClientSession(connector=TCPConnector(limit=100)) as session:
        login_response = await session.post(server_data["login_url"], json=LOGIN_DATA)
        if login_response.status != 200:
            logger.error("Ошибка входа: " + await login_response.text())
            return None

        all_inbound_ids = server_data.get("inbound_ids", [])
        tasks = [fetch_inbound_data(session, inbound_id, email, server_data) for inbound_id in all_inbound_ids]
        results = await asyncio.gather(*tasks)
        return next((result for result in results if result), None)


async def fetch_inbound_data(session, inbound_id, email, server_data):
    """
    Получает данные inbound для заданного ID и проверяет статус подписки клиента.

    Эта функция извлекает данные конфигурации inbound для указанного inbound ID
    с сервера и проверяет, существует ли клиент с указанным логином в конфигурации.
    Если клиент найден, функция возвращает срок действия подписки или соответствующее
    сообщение в зависимости от статуса подписки.
    """
    inbound_url = f"{server_data['config_client_url']}/{inbound_id}"
    inbound_response = await session.get(inbound_url, headers={'Accept': 'application/json'})
    if inbound_response.status != 200:
        logger.error(f"Ошибка получения inbound ID {inbound_id}: {await inbound_response.text()}")
        return None

    inbound_data = await inbound_response.json()
    if inbound_data.get('obj') is None:
        logger.error(f"Нет данных для inbound ID {inbound_id}")
        return None

    clients = json.loads(inbound_data['obj']['settings']).get('clients', [])
    client = next((client for client in clients if client['email'] == email), None)
    if not client:
        return None
    expiry_time = int(client['expiryTime'])
    if expiry_time < 0:
        return "✅ Активируйте конфигурацию в приложении."
    return f"📅 <b>Подписка действует до</b>: {dt.fromtimestamp(expiry_time / 1000).strftime('%Y-%m-%d')}"


@router.callback_query(lambda c: c.data.startswith('extend_subscription_'))
async def process_extension(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос на продление подписки, предлагает бесплатное продление (если доступно) или покупку.
    """
    email = callback_query.data.split("_", 2)[-1]
    await state.update_data(selected_email=email)
    telegram_id = callback_query.from_user.id
    
    db = Database(USERSDATABASE)
    free_days = db.get_free_days_by_telegram_id(telegram_id)
    is_free_extension_enabled = ENABLE_FREE_UPD.lower() == "true"
    keyboard = InlineKeyboardBuilder()
    
    if free_days > 0 and is_free_extension_enabled:
        keyboard.add(InlineKeyboardButton(text="Продлить бесплатно", callback_data=f"extend_free_{email}"))
    
    keyboard.add(InlineKeyboardButton(text="Купить подписку", callback_data=f"extend_paid_{email}"))
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))
    keyboard.adjust(1)

    if free_days > 0 and is_free_extension_enabled:
        message_text = f"🎉 У вас есть <b>{int(free_days)} бесплатных дней</b>! Вы можете продлить подписку бесплатно."
    else:
        message_text = "Вы можете выбрать один из платных вариантов продления подписки."

    try:
        sent_message = await callback_query.message.edit_text(
            message_text,
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
        await state.update_data(sent_message_id=sent_message.message_id)
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
    
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('extend_free_'))
async def process_free(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает бесплатное продление подписки, если у пользователя есть доступные дни.
    """    
    email = callback_query.data.split("_", 2)[-1]
    await state.update_data(selected_email=email)

    telegram_id = callback_query.from_user.id
    await state.update_data(selected_email=email)

    db = Database(USERSDATABASE)
    free_days = db.get_free_days_by_telegram_id(telegram_id)
    logger.info(f"Количество бесплатных дней для {telegram_id}: {free_days}")
    payment_methods_keyboard = InlineKeyboardBuilder()
    payment_methods_keyboard.add(InlineKeyboardButton(
            text=BUTTON_TEXTS["previous"], callback_data="main_menu"
        ))
    update_response = await update_client_subscription(telegram_id, email, free_days)
    if free_days > 0:
        new_free_days = free_days - free_days
        db.update_free_days_by_telegram_id(telegram_id, new_free_days)
        logger.info(f"Обновлено количество бесплатных дней для {telegram_id}: {new_free_days}")

    if free_days > 0:
        message_text = f"🎉 Ваши бесплатные дни использованы!\nПодписка на <b>{email}</b> была успешно продлена на <b>{int(free_days)}</b> дня(ей)."
    else:
        message_text = f"🔔 Подписка для клиента с email <b>{email}</b> была успешно продлена. Спасибо за использование наших услуг!"
    try:
        await callback_query.message.edit_text(
            message_text,
            reply_markup=payment_methods_keyboard.adjust(1).as_markup(),
            parse_mode="HTML"
        )
        logger.info(f"Подписка для клиента с email {email} была продлена на {free_days} дней.")
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
    
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('extend_paid_'))
async def process_paid(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Показывает пользователю варианты платного продления подписки на разные сроки.
    """
    email = callback_query.data.split("_", 2)[-1]
    await state.update_data(selected_email=email)

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["one_m"], callback_data=f"extend_31_{email}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["three_m"], callback_data=f"extend_93_{email}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["twelve_m"], callback_data=f"extend_365_{email}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu")
    ).adjust(2)

    try:
        sent_message = await callback_query.message.edit_text(
            f"На сколько месяцев вы хотите продлить подписку для {email}?",
            reply_markup=keyboard.as_markup()
        )
        await state.update_data(sent_message_id=sent_message.message_id)
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
    
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('extend_'))
async def process_month_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор пользователя по продолжительности продления подписки.
    - Извлекает выбранное количество месяцев для продления.
    - Сохраняет данные о выбранной продолжительности и логине в состоянии.
    - Отправляет сообщение с запросом ввести email или предлагает продолжить без email.
    """
    data = callback_query.data.split('_')
    if len(data) != 3 or not data[1].isdigit():
        await callback_query.answer("Некорректный формат данных. Попробуйте ещё раз.", show_alert=True)
        return

    months = int(data[1])
    name = data[2]
    logger.info(f"DEBUG: Выбрано {months} дня(ей) для {name}")

    # Здесь установим цену в зависимости от выбранного тарифа
    if months == 31:
        price = "80.00"  # Цена для 1 месяца
    elif months == 93:
        price = "200.00"  # Цена для 3 месяцев
    elif months == 365:
        price = "750.00"  # Цена для 12 месяцев
    else:
        price = "80.00"  # По умолчанию

    # Сохраняем цену в состоянии
    await state.update_data(selected_months=months)
    await state.update_data(name=name)
    await state.update_data(email="default@mail.ru")
    await state.update_data(price=price)  # Добавляем цену в state
    await callback_query.answer()

    cancel_keyboard = InlineKeyboardBuilder()
    cancel_keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["without_mail"], callback_data="continue_without_email"),
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel")
    )

    state_data = await state.get_data()

    # Сразу идём к оплате
    await process_yookassa(callback_query, state)
    return

    

@router.callback_query(lambda c: c.data == "continue_without_email", UpdClient.WaitingForEmail)
@router.message(UpdClient.WaitingForEmail)
async def handle_email_or_continue(callback: types.CallbackQuery | types.Message, state: FSMContext):
    #await state.set_state(UpdClient.WaitingForEmail)
    email = None
    user_id = None
    name = (await state.get_data()).get('selected_email')

    if isinstance(callback, types.CallbackQuery):
        email = EMAIL
        user_id = callback.from_user.id
        chat_id = user_id
        sent_message_id = (await state.get_data()).get('sent_message_id')
    elif isinstance(callback, types.Message):
        email = callback.text

        if not is_valid_email(email):
            invalid_email_msg = await callback.answer("Пожалуйста, введите корректный email.")
            await callback.delete()
            await asyncio.sleep(2)
            await invalid_email_msg.delete()
            return

        await callback.delete()
        user_id = callback.from_user.id
        chat_id = user_id
        sent_message_id = (await state.get_data()).get('sent_message_id')

    await state.update_data(email=email)
    await state.update_data(name=name)

    # Создаём клавиатуру с одной кнопкой "Юкасса" и кнопкой "Назад"
    payment_methods_keyboard = InlineKeyboardBuilder()
    payment_methods_keyboard.add(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["yokassa"],
            callback_data="payment_method_yookassa"
        )
    )
    payment_methods_keyboard.add(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["previous"],
            callback_data="main_menu"
        )
    )

    payment_method_text = (
        "⚙️ Выберите способ оплаты для продления подписки:\n\n"
        "💳 <b>Юкасса:</b> Оплата банковскими картами и электронными кошельками."
    )

    if sent_message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message_id,
                text=payment_method_text,
                parse_mode='HTML',
                reply_markup=payment_methods_keyboard.adjust(1).as_markup()
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=payment_method_text,
                parse_mode='HTML',
                reply_markup=payment_methods_keyboard.adjust(1).as_markup()
            )
            await state.update_data(sent_message_id=sent_message.message_id)
    else:
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=payment_method_text,
            parse_mode='HTML',
            reply_markup=payment_methods_keyboard.adjust(1).as_markup()
        )
        await state.update_data(sent_message_id=sent_message.message_id)

    await state.set_state(UpdClient.WaitingForPaymentMethod)

@router.callback_query(lambda c: c.data == "payment_method_yookassa")
async def process_yookassa(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    chat_id = callback.from_user.id
    email = data.get("email")
    name = data.get("name")
    expiry_time = data.get("expiry_time")  # убедись, что это значение было установлено ранее
    amount = data.get("price") or "80.00"  # Получаем цену из state или задаем дефолтную

    try:
        payment_url, payment_id = create_payment_yookassa(amount, chat_id, name, expiry_time, email)

        # Сохраняем payment_id в state или БД, если потом нужно будет проверять статус
        await state.update_data(payment_id=payment_id)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)
            ]]
        )

        await bot.send_message(
            chat_id=chat_id,
            text="Перейдите по ссылке ниже для оплаты подписки:",
            reply_markup=keyboard
        )

        await state.set_state(UpdClient.WaitingForPaymentMethod)
        await state.set_state(UpdClient.WaitingForPayment)
        asyncio.create_task(start_payment_status_update(callback, state, payment_id, "yookassa"))

    except Exception as e:
        import traceback
        error_text = f"❗ Ошибка при создании платежа:\n{str(e)}\n\n{traceback.format_exc()}"
        logger.error(error_text)
        await bot.send_message(chat_id=chat_id, text=error_text[:4000])  # Ограничим до 4000 символов




@router.callback_query(lambda c: c.data.startswith("payment_method_"))
async def handle_payment_method_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор способа оплаты от клиента.
    Устанавливает состояние ожидания выбора способа оплаты и генерирует соответствующую ссылку для оплаты.
    """
    await state.set_state(UpdClient.WaitingForPaymentMethod)

    payment_method = callback_query.data.split("_")[2]
    await state.update_data(payment_method=payment_method)
    data = await state.get_data()
    name = data.get("name")
    email = data.get("email")
    user_id = callback_query.from_user.id
    months = data.get("selected_months", 1)
    expiry_time = {
        31: ONE_M,
        93: THREE_M,
        185: SIX_M,
        365: ONE_YEAR,
    }.get(months, ONE_M)
    conn_users = sqlite3.connect(USERSDATABASE)
    cursor_users = conn_users.cursor()

    cursor_users.execute("""
        SELECT promo_code
        FROM users
        WHERE telegram_id = ?
    """, (user_id,))
    user_promo_code = cursor_users.fetchone()

    if user_promo_code and user_promo_code[0]:
        user_promo_code = user_promo_code[0]
    else:
        user_promo_code = None
        
    price_info = get_price_with_referral_info(expiry_time, user_id, user_promo_code)
    final_price = int(price_info[0])
    try:
        if payment_method == "yookassa":
            payment_url, payment_id = create_paymentupdate(final_price, user_id, email)
        elif payment_method == "yoomoney":
            label = str(uuid.uuid4()) 
            payment_url, payment_id = create_yoomoney_invoice(final_price, YOOMONEY_CARD, label)
            logger.info(f"DEBUG: юмани - {payment_url}, payment_id - {payment_id}")
        elif payment_method == "robokassa":
            payment_url, payment_id = create_payment_robokassa(final_price, user_id, name, expiry_time, email)
        elif payment_method == "cryptobot":
            payment_url, payment_id = await create_payment_cryptobot(final_price, user_id)
        elif payment_method == "cloudpay":
            invoice_id = str(uuid4())
            payment_url, payment_id = await create_cloudpayments_invoice(final_price, user_id, invoice_id)
        elif payment_method == "tgpay":
            sent_message = await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=callback_query.message.message_id,
                text="🔄 Создаем платеж...",
                parse_mode='HTML'
            )
            await asyncio.sleep(2)
            await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

            await create_payment_tgpay(final_price, user_id, name, expiry_time, payment_type="subscription_renewal", pay_currency="tgpay")
            return
        elif payment_method == "star":
            sent_message = await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=callback_query.message.message_id,
                text="🔄 Создаем платеж...",
                parse_mode='HTML'
            )
            await asyncio.sleep(2)
            await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

            await create_payment_tgpay(final_price, user_id, name, expiry_time, payment_type="subscription_renewal", pay_currency="xtr")
            return
        else:
            await callback_query.answer("❌ Неизвестный способ оплаты.")
            return

        keyboard = InlineKeyboardBuilder()

        keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["pay"], url=payment_url),
            InlineKeyboardButton(text=BUTTON_TEXTS["check_pay"], callback_data=f"find_payment:{payment_id}:{payment_method}"),
            InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="upd_cancel")
        )
        payment_text = (
            f"💳 <b>Продление подписки</b>, количество дней: <b>{months}</b>\n\n"
            f"Стоимость со скидкой: <b>{final_price} ₽</b>\n\n"
            "⚠️ <i>Если передумали или выбрали не то, не оплачивайте, а просто нажмите 'Отмена'.</i>\n\n"
        )
        if email != EMAIL:
            payment_text += f"📧 Чек будет отправлен на указанный адрес электронной почты: {email}"

        sent_message_id = data.get('sent_message_id')
        if sent_message_id:
            await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=sent_message_id,
                text=payment_text,
                parse_mode='HTML',
                reply_markup=keyboard.adjust(2).as_markup()
            )
        else:
            sent_message = await bot.send_message(
                chat_id=callback_query.from_user.id,
                text=payment_text,
                parse_mode='HTML',
                reply_markup=keyboard.adjust(2).as_markup()
            )
            await state.update_data(sent_message_id=sent_message.message_id, user_promo_code=user_promo_code)
        await state.update_data(payment_id=payment_id, final_price=final_price)
        await state.set_state(UpdClient.WaitingForPayment)
        asyncio.create_task(start_payment_status_update(callback_query, state, payment_id, payment_method))
        
    except Exception as e:
        logger.error(f"Ошибка при обработке платежа: {e}")
        await callback_query.answer("❌ Произошла ошибка при создании платежа. Попробуйте позже.")


async def check_payment_status_common(payment_id: str, payment_method: str) -> bool:
    """
    Проверяет статус платежа по различным методам.
    """
    try:
        if payment_method == "yookassa":
            return await check_payment_yookassa(payment_id)
        elif payment_method == "yoomoney":
            return await check_yoomoney_payment_status(payment_id)
        elif payment_method == "robokassa":
            password2 = PASS2
            result = await check_payment_robokassa(payment_id, password2)
            return result == "100"
        elif payment_method == "cryptobot":
            return await check_payment_cryptobot(payment_id)
        elif payment_method == "cloudpay":
            return await check_payment_cloud(payment_id)
        else:
            logger.error(f"Неизвестный метод оплаты: {payment_method}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при проверке платежа ({payment_method}): {e}")
        return False
    

async def finalize_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает завершение подписки и обновление данных клиента в базе.
    """
    try:
        data = await state.get_data()
        name = data.get("name")
        final_price = data.get("price")
        months = data.get("selected_months")
        user_promo_code = data.get("user_promo_code")
        telegram_id = callback_query.from_user.id

        # Обновление подписки
        await update_client_subscription(telegram_id, name, months)
        await handle_database_operations(telegram_id, name, months)
        await log_promo_code_usage(telegram_id, user_promo_code)
        await update_sum_my(telegram_id, float(final_price))
        await update_sum_ref(telegram_id, final_price)
        await add_free_days(telegram_id, FREE_DAYS)

        # Отправка первого сообщения о продлении подписки
        await callback_query.message.edit_text(
            text=f"✅ Подписка продлена на {months} день(ней)!",
            parse_mode='HTML',
            reply_markup=get_back_button()  # Кнопка "назад"
        )

        # Убираем старую кнопку "перейти к оплате" и все связанные с ней элементы
        #await callback_query.message.edit_message_reply_markup(reply_markup=None)  # Удаляем все кнопки

        # После этого снова устанавливаем нужную кнопку
        #await callback_query.message.edit_message_reply_markup(reply_markup=get_back_button())  # Только кнопка "назад"
        #await callback_query.message.answer("✅ Подписка успешно продлена!")

        # Очистка состояния FSM
        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка при обновлении подписки: {e}")
        await callback_query.answer("Произошла ошибка при обновлении подписки. Пожалуйста, попробуйте позже.")


        
renewal_tasks = {}

async def start_payment_status_update(callback_query: types.CallbackQuery, state: FSMContext, payment_id: str, payment_method: str):
    """
    Начинает асинхронную проверку статуса платежа, периодически проверяя завершение оплаты.

    Эта функция будет выполняться в фоновом режиме, пытаясь проверить статус платежа через
    выбранный метод оплаты (Юкасса, Робокасса и т.д.) и обновлять статус в случае успешной
    оплаты или по истечении максимального времени ожидания.
    """
    task_id = f"{callback_query.from_user.id}_{payment_id}"
    try:
        attempts = 0
        renewal_tasks[task_id] = asyncio.current_task()

        await asyncio.sleep(FIRST_CHECK_DELAY)

        while attempts < MAX_ATTEMPTS:
            payment_check = await check_payment_status_common(payment_id, payment_method)
            if payment_check:
                await finalize_subscription(callback_query, state)
                return

            attempts += 1
            logger.info(f"Попытка {attempts}: Платеж не завершен, ждем {SUBSEQUENT_CHECK_INTERVAL} секунд")
            await asyncio.sleep(SUBSEQUENT_CHECK_INTERVAL)

        await callback_query.answer("❌ Платеж не был завершен в установленное время.")
    except asyncio.CancelledError:
        logger.info(f"Задача {task_id} была отменена.")
    except Exception as e:
        logger.error(f"Ошибка при автоматической проверке платежа: {e}")
    finally:
        renewal_tasks.pop(task_id, None)

@router.callback_query(lambda c: c.data.startswith("find_payment:"), UpdClient.WaitingForPayment)
async def check_payment_status(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос клиента для проверки статуса оплаты по идентификатору платежа.
    """
    try:
        payment_data = callback_query.data.split(':')
        if len(payment_data) < 3:
            await callback_query.answer("Некорректные данные. Пожалуйста, попробуйте снова.")
            return

        payment_id = payment_data[1]
        payment_method = payment_data[2]

        payment_check = await check_payment_status_common(payment_id, payment_method)
        if not payment_check:
            await callback_query.answer("❌ Платеж не был завершен. Пожалуйста, проверьте и попробуйте снова.")
            return

        await finalize_subscription(callback_query, state)

        task_id = f"{callback_query.from_user.id}_{payment_id}"
        if task_id in renewal_tasks:
            task = renewal_tasks.pop(task_id)
            task.cancel()
            logger.info(f"Задача {task_id} была успешно отменена вручную.")
    except Exception as e:
        logger.error(f"Ошибка при проверке платежа: {e}")
        await callback_query.answer("Произошла ошибка при проверке платежа. Пожалуйста, попробуйте позже.")

async def create_update_data(client_id, email, new_expiry_time, client, INBOUND_ID, UPDATE_CLIENT):
    """
    Создает данные для обновления подписки клиента на сервере.
    """
    return {
        "id": INBOUND_ID,
        "settings": json.dumps({
            "clients": [{
                "id": f"{client_id}",
                "email": email,
                "expiryTime": new_expiry_time,
                "enable": client.get('enable', True),
                "tgId": client.get('tgId', ''),
                "limitIp": client.get('limitIp', 3),
                "subId": client.get('subId', ''),
                "flow": 'xtls-rprx-vision',
                "reset": 0
            }]
        }, indent=4)
    }

async def update_client_subscription(telegram_id, email, days):
    """
    Обновляет подписку клиента на всех серверах, используя дни.
    """
    server_ids = await get_server_id(SERVEDATABASE)
    full_response = []
    for server_id in server_ids:
        server_data = await get_server_data(server_id)
        if not server_data:
            continue
        LOGIN_URL = server_data.get('login_url')
        CONFIG_CLIENT_URL = server_data.get('config_client_url')
        INBOUND_IDS = server_data.get('inbound_ids')
        UPDATE_CLIENT = server_data.get('update_url')
        if not LOGIN_URL:
            continue
        email = email
        session = requests.Session()
        login_response = session.post(LOGIN_URL, json={'username': server_data['username'], 'password': server_data['password']})
        if login_response.status_code != 200:
            continue
        for INBOUND_ID in INBOUND_IDS:
            try:
                inbound_url = f"{CONFIG_CLIENT_URL}/{INBOUND_ID}"
                inbound_response = session.get(inbound_url, headers={'Accept': 'application/json'})
                if inbound_response.status_code != 200:
                    continue
                inbound_data = inbound_response.json().get('obj')
                if inbound_data is None:
                    continue

                settings = json.loads(inbound_data['settings'])
                client = next((client for client in settings['clients'] if client['email'] == email), None)
                if not client:
                    continue
                client_id = client['id']
                client_expiry_time = client.get('expiryTime', 0)
                current_time_ms = int(time.time() * 1000)
                
                if client_expiry_time < current_time_ms:
                    # Если срок подписки истек, то добавляем дни к текущему времени
                    new_expiry_time = current_time_ms + (days * 24 * 60 * 60 * 1000)  # дни в миллисекундах
                else:
                    # Если срок подписки не истек, добавляем дни к текущему времени подписки
                    new_expiry_time = int(client_expiry_time) + (days * 24 * 60 * 60 * 1000)  # дни в миллисекундах
                
                logger.info(f"Найден клиент с email {email} на сервере {server_id}. Срок действия подписки: {client_expiry_time}.")
                logger.info(f"Обновляем подписку для клиента с email {email} на сервере {server_id}, новый срок окончания: {new_expiry_time}.")
                
                update_data = await create_update_data(client_id, email, new_expiry_time, client, INBOUND_ID, UPDATE_CLIENT)
                headers = {'Accept': 'application/json'}
                response = session.post(f"{UPDATE_CLIENT}/{client_id}", json=update_data, headers=headers)
                logger.info(f"Данные, отправляемые в POST-запросе: {json.dumps(update_data, indent=2)}")
                
                if response.status_code == 200:
                    full_response.append(f"Подписка для клиента с email {email} успешно продлена на сервере {server_id}.")
                    await send_telegram_message(telegram_id, "✅ Ваша подписка успешно обновлена.")
		    
		    # Отправка уведомления в группу
                    user = await bot.get_chat(telegram_id)
                    full_name = user.full_name or f"Пользователь {telegram_id}"
                    user_link = f"<a href='tg://user?id={telegram_id}'>{full_name}</a>"
                    expiry_time_description = time.strftime('%d.%m.%Y %H:%M', time.localtime(new_expiry_time / 1000))  # читаемый срок действия
                    userdata = f"ID: {telegram_id}"
                    email_raw = email

                    await bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=(
                            f"📩 <b>Пользователь</b> {user_link} продлил подписку до <b>{expiry_time_description}</b>\n"
                            f"👤 {userdata}\n"
                            f"📧 Email: <code>{email_raw}</code>"
                        ),
                        parse_mode=ParseMode.HTML
                    )
                else:
                    full_response.append(f"Ошибка продления подписки для клиента с email {email} на сервере {server_id}. Ответ: {response.text}")
            except Exception as e:
                logger.error(f"Ошибка при обработке сервера {server_id}: {e}")
                continue
    if full_response:
        return "\n".join(full_response)
    else:
        return "❌ Ошибка продления подписки для клиента. Проверьте логин, данные или сервер."

# Функция отправки сообщения
async def send_telegram_message(telegram_id, message):
    try:
        await bot.send_message(chat_id=telegram_id, text=message)
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения в Telegram: {e}")

@router.callback_query(lambda c: c.data == "upd_cancel")
async def handle_cancel_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос клиента на отмену текущего платежа.
    """
    try:
        data = await state.get_data()
        sent_message_id = data.get('sent_message_id')
        payment_id = data.get('payment_id')
        payment_method = data.get('payment_method')

        if not payment_id:
            await callback_query.answer("❌ Не удалось найти платежный процесс. Пожалуйста, попробуйте снова.")
            return

        is_payment_completed = await check_payment_status_common(payment_id, payment_method)
        if is_payment_completed:
            await callback_query.answer("❌ Платеж завершен. Отмена невозможна, нажмите кнопку, Проверить оплату")
            return

        task_id = f"{callback_query.from_user.id}_{payment_id}"
        if task_id in renewal_tasks:
            task = renewal_tasks.pop(task_id)
            task.cancel()
            logger.info(f"Задача {task_id} была успешно отменена вручную.")
            await callback_query.answer("❌ Оплата была отменена.")
        else:
            await callback_query.answer("❌ Задача не найдена. Возможно, платеж уже завершен.")

        if sent_message_id:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=sent_message_id,
                text="❌ Действие отменено.",
                reply_markup=get_main_menu(callback_query)
            )
        else:
            await bot.send_message(
                chat_id=callback_query.message.chat.id,
                text="Нет активной покупки. Выберите опцию:",
                reply_markup=get_main_menu(callback_query)
            )

        await state.clear()
        await callback_query.answer()

    except Exception as e:
        logger.error(f"Ошибка при отмене платежа: {e}")
        await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="Не удалось отменить покупку. Попробуйте снова.",
            reply_markup=get_main_menu(callback_query)
        )


from aiogram import Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
dp = Dispatcher()
REFERRAL_CHAT_ID = -1003045150256
@router.message(Command("test_chats"))
async def test_chats(message: Message):
    try:
        await bot.send_message(GROUP_CHAT_ID, "✅ Тест: бот видит GROUP_CHAT_ID")
        await message.answer("✅ Сообщение в GROUP_CHAT_ID отправлено")
    except Exception as e:
        await message.answer(f"❌ Ошибка в GROUP_CHAT_ID: {e}")

    try:
        await bot.send_message(REFERRAL_CHAT_ID, "✅ Тест: бот видит REFERRAL_CHAT_ID")
        await message.answer("✅ Сообщение в REFERRAL_CHAT_ID отправлено")
    except Exception as e:
        await message.answer(f"❌ Ошибка в REFERRAL_CHAT_ID: {e}")

from aiogram import Router, types
from aiogram.filters import Command
import aiosqlite

router = Router()

# ID пользователя, по которому проверяем рефералов
TARGET_USER_ID = 1311997119
DB_PATH = "database.db"  # ← Укажи правильный путь к твоему .db файлу

@router.message(Command("ref_freez"))
async def cmd_ref_freez(message: types.Message):
    # Проверяем, что команда вызвана в личных сообщениях (не в группе)
    if message.chat.type != "private":
        await message.answer("❗ Эта команда доступна только в личных сообщениях с ботом.")
        return

    

    try:
        # Подключаемся к базе данных
        async with aiosqlite.connect(DB_PATH) as db:
            # Запрос: количество рефералов
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by = ?", (TARGET_USER_ID,)
            ) as cursor:
                count_row = await cursor.fetchone()
                count_referrals = count_row[0] if count_row else 0

            # Запрос: сумма sum_my
            async with db.execute(
                "SELECT COALESCE(SUM(sum_my), 0) FROM users WHERE referred_by = ?", (TARGET_USER_ID,)
            ) as cursor:
                sum_row = await cursor.fetchone()
                total_sum = sum_row[0] if sum_row else 0.0

        # Формируем и отправляем ответ в личные сообщения
        await message.answer(
            f"🔐 <b>Реферальная статистика для ID {TARGET_USER_ID}:</b>\n\n"
            f"👥 Всего рефералов: <b>{count_referrals}</b>\n"
            f"💰 Сумма (sum_my): <b>{total_sum:.2f}</b>",
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка при работе с базой данных:\n{e}")