import asyncio
import aiosqlite
import re, uuid
from datetime import datetime, timedelta
from uuid import uuid4
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.utils import markdown as md
from aiogram import Router, F
from aiogram.enums.parse_mode import ParseMode

from bot import bot
from log import logger
from client.add_client import (
    add_client, 
    generate_config_from_pay, 
    login, 
    send_config_from_state
)
from db.db import (
    handle_database_operations, 
    insert_or_update_user, 
    update_user_trial_status,
    update_sum_my,
    update_sum_ref,
    add_free_days
)
from handlers.config import get_server_data
from handlers.select_server import get_optimal_server
from handlers.states import AddClient
from pay.prices import *
from pay.payments import (
    check_payment_yookassa, 
    create_payment_yookassa, 
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

from pay.promocode import log_promo_code_usage
from pay.pay_metod import PAYMENT_METHODS
from client.menu import get_main_menu
from client.add_client import generate_login
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
import os
from db.db import ServerDatabase
load_dotenv()


SERVEDATABASE = os.getenv("SERVEDATABASE")
server_db = ServerDatabase(SERVEDATABASE)


PASS2 = os.getenv("PASS2")

YOOMONEY_CARD = int(os.getenv("YOOMONEY_CARD"))

EMAIL = os.getenv("EMAIL")
FIRST_CHECK_DELAY = int(os.getenv("FIRST_CHECK_DELAY", 15))
SUBSEQUENT_CHECK_INTERVAL = int(os.getenv("SUBSEQUENT_CHECK_INTERVAL", 30))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", 15))
FREE_DAYS = os.getenv("FREE_DAYS")

router = Router()

purchase_tasks = {}

def is_valid_email(email: str) -> bool:
    """
    Проверяет, является ли строка действительным адресом электронной почты с помощью регулярного выражения.

    Функция использует регулярное выражение для проверки соответствия строки формату стандартного адреса
    электронной почты (например, example@domain.com). Возвращает `True`, если адрес соответствует формату,
    и `False` в противном случае.
    """
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None

@router.message(AddClient.WaitingForPayment, AddClient.WaitingForExpiryTime)
async def handle_invalid_message(message: types.Message, state: FSMContext):
    """
    Удаляет сообщение и отправляет напоминание в зависимости от текущего состояния пользователя.

    Функция выполняет проверку текущего состояния пользователя в процессе подписки и реагирует на сообщение,
    отправленное пользователем. В случае неверного или неподобающего сообщения, оно будет удалено, и будет отправлено
    напоминание или уточнение о том, что нужно сделать дальше, в зависимости от состояния (например, требуется 
    ввести дату окончания подписки или выбрать способ оплаты).
    """
    await message.delete()

    current_state = await state.get_state()
    reminder_message = None

    if current_state == AddClient.WaitingForPayment.state:
        reminder_message = await message.answer("Пожалуйста, завершите оплату или нажмите ❌ Отмена.")
    elif current_state == AddClient.WaitingForExpiryTime.state:
        reminder_message = await message.answer("Пожалуйста, нажмите на соответствующие кнопки в чате или нажмите ❌ Отмена.")

    await asyncio.sleep(5)

    if reminder_message:
        await reminder_message.delete()


@router.callback_query(lambda query: query.data == "trial_1")
async def process_trial_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает пробную подписку, обновляет состояние, выбирает сервер и добавляет клиента.
    """
    telegram_id = callback_query.from_user.id
    
    if not has_active_subscription(telegram_id):
        current_time = datetime.utcnow()
        expiry_timestamp = current_time + timedelta(days=TRIAL)
        expiry_time = int(expiry_timestamp.timestamp() * 1000)

        name = generate_login(telegram_id)
        
        await state.update_data(
            expiry_time=expiry_time
        )
        server_selection = "random"
        await update_user_trial_status(telegram_id)

        selected_server = await get_optimal_server(server_selection, server_db)
        logger.info(f"Выбранный сервер: {selected_server}")
        
        server_id = selected_server
        server_data = await get_server_data(selected_server)
        logger.info(f"Данные сервера: {server_data}")
        country_name = server_data.get('name') if server_data else "🎲 Рандомная страна"
        if not server_data:
            await bot.send_message(callback_query.from_user.id, "❌ Неверный выбор сервера.")
            return

        try:
            session_id = await login(server_data['login_url'], {
                "username": server_data['username'],
                "password": server_data['password']
            })
            inbound_ids = server_data['inbound_ids']
            await add_client(name, expiry_time, inbound_ids, telegram_id, server_data['add_client_url'], server_data['login_url'], {
                "username": server_data['username'],
                "password": server_data['password']
            })

            await state.update_data(
                email=name,
                client_id=telegram_id,
                login_data={"username": server_data['username'], "password": server_data['password']},
                selected_country_name=country_name,
                server_ip=server_data['server_ip'],
                config_client_url=server_data['config_client_url'],
                inbound_ids=server_data['inbound_ids'],
                login_url=server_data['login_url'],
                sub_url=server_data['sub_url'],
                json_sub=server_data['json_sub']
            )

            userdata, config, config2, config3 = await generate_config_from_pay(telegram_id, name, state)
            await send_config_from_state(callback_query.message, state, telegram_id=callback_query.from_user.id, edit=True)

            await state.clear()

            user_id = await insert_or_update_user(telegram_id, name, server_id)

        except Exception as e:
            logger.error(f"Произошла ошибка: {e}")
            await bot.send_message(callback_query.from_user.id, "❌ Произошла ошибка. Попробуйте снова.")

    else:
        await callback_query.message.edit_text(
            "⚠ У вас уже есть активная подписка. Оформить пробную подписку можно только один раз.",
            reply_markup=get_main_menu(callback_query)
        )

    await callback_query.answer()

@router.callback_query(lambda query: query.data == "trial_go")
async def trial_go(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает пробную подписку, обновляет состояние, выбирает сервер и добавляет клиента.
    """

    text = (
            "<b>Готов к максимальной скорости интернета с</b> @vpnmoy? 🚀\n\n"
            "— Минимальная стоимость подписки без скрытых платежей\n"
            "— Работа всех сервисов <b>Рунета</b> без отключения <b>VPN</b>\n"
            "— Подключение <b>5 устройств</b> на один ключ.\n\n"
            "Подходит для всех устройств: <b>от смартфонов до смарт-телевизоров.</b>"
        )

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="trial_1"),
        InlineKeyboardButton(text=BUTTON_TEXTS["promocode"], callback_data="enter_promo_code")
    )

    await callback_query.message.edit_text(
        text=text,
        reply_markup=keyboard.adjust(1).as_markup(),
        parse_mode="HTML"
    )

    await callback_query.answer()

@router.callback_query(lambda c: c.data in [str(ONE_M), str(THREE_M), str(ONE_YEAR)])
async def ask_to_confirm_tariff(callback_query: types.CallbackQuery, state: FSMContext):
    expiry_time = int(callback_query.data)
    await state.update_data(pending_expiry_time=expiry_time)

    text = (
            "<b>Готов к максимальной скорости интернета с</b> @vpnmoy? 🚀\n\n"
            "— Минимальная стоимость подписки без скрытых платежей\n"
            "— Работа всех сервисов <b>Рунета</b> без отключения <b>VPN</b>\n"
            "— Подключение <b>5 устройств</b> на один ключ.\n\n"
            "Подходит для всех устройств: <b>от смартфонов до смарт-телевизоров.</b>"
        )

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        types.InlineKeyboardButton(text=BUTTON_TEXTS["key"], callback_data="confirm_expiry_time"),
        InlineKeyboardButton(text=BUTTON_TEXTS["promocode"], callback_data="enter_promo_code")
    )

    await callback_query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard.adjust(1).as_markup())
    await callback_query.answer()

@router.callback_query(F.data == "confirm_expiry_time")
async def confirmed_expiry_time(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    expiry_time = data.get("pending_expiry_time")

    if not expiry_time:
        await callback_query.answer("Ошибка: тариф не выбран.", show_alert=True)
        return

    telegram_id = callback_query.from_user.id
    name = generate_login(telegram_id)
    email = "default@mail.ru"
    #selected_server = 2
    user_promo_code = None

    selected_server = await get_optimal_server("random", server_db)
    logger.info(f"Автоматически выбран сервер для платной подписки: {selected_server}")

    # Проверка результата
    if isinstance(selected_server, str) and "занят" in selected_server:
        await callback_query.answer("❌ Все серверы в этой группе заняты. Попробуйте позже.", show_alert=True)
        return
    if not selected_server or not str(selected_server).isdigit():
        await callback_query.answer("❌ Не удалось выбрать сервер.", show_alert=True)
        return

    selected_server = int(selected_server)

    await state.update_data({
        "expiry_time": expiry_time,
        "email": email,
        "name": name,
        "selected_server": selected_server,
        "user_promo_code": user_promo_code,
        "sent_message_id": callback_query.message.message_id,  # нужно для редактирования
    })

    # Получаем данные о сервере
    server_data = await get_server_data(selected_server)
    if not server_data:
        await callback_query.message.answer("❌ Сервер не найден.")
        return

    await state.update_data({
        "selected_country_name": server_data.get("name"),
        "login_data": {"username": server_data['username'], "password": server_data['password']},
        "server_ip": server_data['server_ip'],
        "config_client_url": server_data['config_client_url'],
        "inbound_ids": server_data['inbound_ids'],
        "login_url": server_data['login_url'],
        "sub_url": server_data['sub_url'],
        "json_sub": server_data['json_sub'],
    })

    # Устанавливаем состояние, необходимое для следующего хендлера
    await state.set_state(AddClient.WaitingForPaymentMethod)

    # Создаем "искусственный" callback с нужным data
    fake_callback = types.CallbackQuery(
        id=callback_query.id,
        from_user=callback_query.from_user,
        chat_instance=callback_query.chat_instance,
        message=callback_query.message,
        data="payment_method_yookassa"
    )

    await handle_payment_method_selection(fake_callback, state)



    
@router.callback_query(lambda query: query.data.isdigit(), AddClient.WaitingForExpiryTime)
async def process_paid_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает подписку на платный тариф, выбирает сервер и отправляет информацию о цене и скидке.

    Функция обрабатывает выбор пользователя, желающего оформить подписку на платный тариф. Включает этапы 
    выбора сервера, вычисления итоговой стоимости, применения скидок, если таковые есть, и отправки пользователю
    информации о цене и условиях подписки.
    """
    data = callback_query.data
    telegram_id = callback_query.from_user.id
    expiry_time = int(data.split("_")[0])

    logger.info(f"Получен expiry_time: {expiry_time}")

    await state.update_data(
        expiry_time=expiry_time
    )
    
    data = await state.get_data()

    sent_message_id = data['sent_message_id']
    server_selection = data['selected_country_id']
    country_name = data['selected_country_name']
    logger.info(f"Selected country ID retrieved: {server_selection}, Country name: {country_name}")

    logger.info(f"Данные из состояния: {data}")

    conn_users = sqlite3.connect(USERSDATABASE)
    cursor_users = conn_users.cursor()

    cursor_users.execute(""" 
        SELECT promo_code 
        FROM users 
        WHERE telegram_id = ? 
    """, (telegram_id,))
    user_promo_code = cursor_users.fetchone()

    if user_promo_code and user_promo_code[0]:
        user_promo_code = user_promo_code[0]
    else:
        user_promo_code = None

    cursor_users.close()
    conn_users.close()

    price, total_discount, referral_count = get_price_with_referral_info(expiry_time, telegram_id, user_promo_code)
    expiry_time_description = get_expiry_time_description(expiry_time)

    message_text = (
        f"✅ Вы выбрали подключение на: {expiry_time_description}.\n"
        f"🌍 Страна: {country_name}.\n" 
        f"💵 Цена: {price}.\n"
        f"👥 Количество приглашенных пользователей: {referral_count}.\n"
        f"🎁 Ваша скидка: {total_discount}%.\n\n"
        "📧 Пожалуйста, введите ваш email для отправки чека, либо нажмите 'Продолжить без email':"
    )

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["without_mail"], callback_data="continue_without_email"),
        InlineKeyboardButton(text=BUTTON_TEXTS["promocode"], callback_data="enter_promo_code"),
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel")
    )

    sent_message = await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=sent_message_id,
        text=message_text,
        reply_markup=keyboard.adjust(1).as_markup()
    )

    optimal_server = await get_optimal_server(server_selection, server_db)

    if optimal_server == "Сервер полностью занят, попробуйте позже":
        keyboard = InlineKeyboardBuilder()
        keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
        )
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=sent_message_id,
            text="Извините, выбранный сервер полностью занят. Пожалуйста, попробуйте выбрать другой сервер позже.",
        reply_markup=keyboard.adjust(1).as_markup()
        )
        logger.warning("Сервер полностью занят")
        return 

    logger.info(f"Оптимальный сервер: {optimal_server}")

    await state.update_data(
        selected_server=optimal_server,
        sent_message_id=sent_message.message_id,
        user_promo_code=user_promo_code 
    )
    
    await state.set_state(AddClient.WaitingForEmail)
    logger.info("Переход в состояние WaitingForEmail")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "continue_without_email", AddClient.WaitingForEmail)
@router.message(AddClient.WaitingForEmail)
async def handle_email_or_continue(callback: types.CallbackQuery | types.Message, state: FSMContext):
    """
    Обрабатывает введенный email или продолжение без email, обновляет состояние и предоставляет выбор способов оплаты.
    """
    email = None

    if isinstance(callback, types.CallbackQuery):
        email = EMAIL
        user_id = callback.from_user.id
        chat_id = user_id
        sent_message_id = (await state.get_data()).get('sent_message_id')
    elif isinstance(callback, types.Message):
        email = callback.text

        if not is_valid_email(email):
            await callback.delete()
            invalid_email_msg = await callback.answer("Пожалуйста, введите корректный email.")
            await asyncio.sleep(2)
            await invalid_email_msg.delete()
            return

        await callback.delete()
        user_id = callback.from_user.id
        chat_id = user_id
        sent_message_id = (await state.get_data()).get('sent_message_id')

    await state.update_data(email=email)

    payment_methods_keyboard = InlineKeyboardBuilder()

    payment_method_text = "⚙️ <b>Выберите способ оплаты:</b>\n\n"
    
    for method, details in PAYMENT_METHODS.items():
        if details["enabled"]:
            payment_methods_keyboard.add(InlineKeyboardButton(
                text=details["text"],
                callback_data=details["callback_data"]
            ))
            payment_method_text += details["description"] + "\n"

    payment_methods_keyboard.add(InlineKeyboardButton(
        text=BUTTON_TEXTS["cancel"], callback_data="cancel"
    ))

    if sent_message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message_id,
            text=payment_method_text,
            parse_mode='HTML',
            reply_markup=payment_methods_keyboard.adjust(1).as_markup()
        )
    else:
        sent_message = await bot.send_message(
            chat_id=chat_id,
            text=payment_method_text,
            parse_mode='HTML',
            reply_markup=payment_methods_keyboard.adjust(1).as_markup()
        )
        await state.update_data(sent_message_id=sent_message.message_id)

    await state.set_state(AddClient.WaitingForPaymentMethod)


@router.callback_query(lambda c: c.data.startswith("payment_method_"), AddClient.WaitingForPaymentMethod)
async def handle_payment_method_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор метода оплаты от пользователя.
    
    После выбора метода оплаты формируется соответствующая ссылка на платеж и отправляется
    пользователю с кнопками для подтверждения оплаты или отмены.
    """
    payment_method = callback_query.data.split("_")[2]
    await state.update_data(payment_method=payment_method)
    payment_url = None
    payment_id = None
    data = await state.get_data()
    user_promo_code = data['user_promo_code']
    name = "MoyServise"
    email = data['email']
    expiry_time = data['expiry_time']
    user_id = callback_query.from_user.id

    # Логируем все полученные данные
    logger.info(
        f"📥 Получены данные из состояния (user_id={user_id}):\n"
        f"   → user_promo_code: '{user_promo_code}'\n"
        f"   → name: '{name}'\n"
        f"   → email: '{email}'\n"
        f"   → expiry_time: {expiry_time} ({get_expiry_time_description(expiry_time)})\n"
        f"   → final_price будет рассчитана на основе этих данных"
    )

    price_info = get_price_with_referral_info(expiry_time, user_id, user_promo_code)
    final_price = int(price_info[0])

    if payment_method == "yookassa":
        payment_url, payment_id = create_payment_yookassa(final_price, user_id, name, expiry_time, email)
        logger.info(f"DEBUG: юкасса - {payment_url}, payment_id - {payment_id}")
    elif payment_method == "yoomoney":
        label = str(uuid.uuid4()) 
        payment_url, payment_id = create_yoomoney_invoice(final_price, YOOMONEY_CARD, label)
        logger.info(f"DEBUG: юмани - {payment_url}, payment_id - {payment_id}")
    elif payment_method == "robokassa":
        payment_url, payment_id = create_payment_robokassa(final_price, user_id, name, expiry_time, email)
        logger.info(f"DEBUG: робокасса - {payment_url}, payment_id - {payment_id}")
    elif payment_method == "cryptobot":
        payment_url, payment_id = await create_payment_cryptobot(final_price, user_id)
        logger.info(f"DEBUG: криптобот - {payment_url}, payment_id - {payment_id}")
    elif payment_method == "cloudpay":
        invoice_id = str(uuid4())
        payment_url, payment_id = await create_cloudpayments_invoice(final_price, user_id, invoice_id)
        logger.info(f"DEBUG: cloudpay - {payment_url}, payment_id - {payment_id}")
    elif payment_method == "tgpay":
        sent_message = await bot.edit_message_text(
            chat_id=callback_query.from_user.id,
            message_id=callback_query.message.message_id,
            text="🔄 Создаем платеж...",
            parse_mode='HTML'
        )
        await asyncio.sleep(2)
        await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

        await create_payment_tgpay(final_price, user_id, name, expiry_time, payment_type="initial_payment", pay_currency="tgpay")
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

        await create_payment_tgpay(final_price, user_id, name, expiry_time, payment_type="initial_payment", pay_currency="xtr")
        return       
    if payment_method != "tgpay" and (not payment_url or not payment_id):
        await callback_query.answer("❌ Не удалось создать ссылку для оплаты. Пожалуйста, попробуйте снова.")
        return
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["pay"], url=payment_url),
        #InlineKeyboardButton(text=BUTTON_TEXTS["check_pay"], callback_data=f"check_payment:{payment_id}:{payment_method}"),
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="bay_cancel")
    )
    payment_text = (
        f"💳 <b>Оплата подписки</b> на <b>{get_expiry_time_description(expiry_time)}</b>\n\n"
        "⚠️ <i>Если передумали или выбрали не то, не оплачивайте, а просто нажмите 'Отмена'.</i>\n\n"
    )
    if email != EMAIL:
        payment_text += f""

    try:
        sent_message_id = (await state.get_data()).get('sent_message_id')
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
            await state.update_data(sent_message_id=sent_message.message_id)
        await state.update_data(payment_id=payment_id, final_price=final_price)
    except Exception as e:
        logger.error(f"Ошибка при отправке или редактировании сообщения: {e}")

    asyncio.create_task(start_payment_status_check(callback_query, state, payment_id, payment_method))
    await state.set_state(AddClient.WaitingForPayment)


async def start_payment_status_check(callback_query: types.CallbackQuery, state: FSMContext, payment_id: str, payment_method: str):
    """
    Начинает асинхронную проверку статуса платежа, периодически проверяя завершение оплаты.

    Эта функция будет выполняться в фоновом режиме, пытаясь проверить статус платежа через
    выбранный метод оплаты (Юкасса, Робокасса и т.д.) и обновлять статус в случае успешной
    оплаты или по истечении максимального времени ожидания.
    """
    task_id = f"{callback_query.from_user.id}_{payment_id}"
    try:
        attempts = 0
        purchase_tasks[task_id] = asyncio.current_task()
    
        await asyncio.sleep(FIRST_CHECK_DELAY)

        while attempts < MAX_ATTEMPTS:
            if payment_method == "yookassa":
                payment_check = await check_payment_yookassa(payment_id)
                if payment_check:
                    await finalize_payment(callback_query, state)
                    return
            elif payment_method == "yoomoney":
                payment_check = await check_yoomoney_payment_status(payment_id)
                if payment_check:
                    await finalize_payment(callback_query, state)
                    return
            elif payment_method == "robokassa":
                password2 = PASS2
                payment_check_result = await check_payment_robokassa(payment_id, password2)
                if payment_check_result == "100":
                    await finalize_payment(callback_query, state)
                    return
            elif payment_method == "cryptobot":
                payment_check_result = await check_payment_cryptobot(payment_id)
                if payment_check_result:
                    await finalize_payment(callback_query, state)
                    return
            elif payment_method == "cloudpay":
                payment_check_result = await check_payment_cloud(payment_id)
                if payment_check_result:
                    await finalize_payment(callback_query, state)
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
        purchase_tasks.pop(task_id, None)
        

async def process_successful_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает успешный платёж с защитой от ошибок и дублирования.
    """
    telegram_id = callback_query.from_user.id
    task_id = f"{telegram_id}_{data.get('payment_id')}"

    if task_id in purchase_tasks:
        logger.warning(f"Повторный вызов платежа {task_id}")
        return
    purchase_tasks[task_id] = True

    try:
        data = await state.get_data()
        final_price = data.get("final_price")
        name = data['name']
        expiry_days = data['expiry_time']
        current_time = datetime.utcnow()
        expiry_timestamp = current_time + timedelta(days=expiry_days)
        expiry_time = int(expiry_timestamp.timestamp() * 1000)

        selected_server = data['selected_server']
        server_data = await get_server_data(selected_server)
        if not server_data:
            await callback_query.answer("Ошибка: сервер не найден.")
            return

        # === 1. Вход в 3x UI ===
        session_id = await login(server_data['login_url'], {
            "username": server_data['username'],
            "password": server_data['password']
        })
        if not session_id:
            raise Exception("Не удалось войти в 3x UI")

        # === 2. Добавляем клиента ===
        await add_client(
            name, expiry_time, server_data['inbound_ids'], telegram_id,
            server_data['add_client_url'], server_data['login_url'],
            {"username": server_data['username'], "password": server_data['password']}
        )

        # === 3. Генерируем конфиг и отправляем сразу ===
        await state.update_data(
            email=name,
            client_id=telegram_id,
            server_ip=server_data['server_ip'],
            config_client_url=server_data['config_client_url'],
            json_sub=server_data['json_sub'],
            sub_url=server_data['sub_url'],
            login_data={"username": server_data['username'], "password": server_data['password']},
            user_promo_code=data.get('user_promo_code')
        )

        userdata, config, config2, config3 = await generate_config_from_pay(telegram_id, name, state)
        approx_months = round(expiry_days / 30)
        tickets_msg = {1: "1 билет", 3: "3 билета", 12: "12 билетов"}.get(approx_months)

        await send_config_from_state(callback_query.message, state, telegram_id, edit=False, tickets_message=tickets_msg)

        # === 4. Обновляем БД ===
        await handle_database_operations(telegram_id, name, expiry_time)
        await insert_or_update_user(telegram_id, name, selected_server)
        await log_promo_code_usage(telegram_id, data.get('user_promo_code'))
        await update_sum_my(telegram_id, final_price)
        await update_sum_ref(telegram_id, final_price)

        # === 5. Награда за оплату (билеты) ===
        insert_count = {1: 1, 3: 3, 12: 12}.get(approx_months, 0)
        if insert_count > 0:
            user = callback_query.from_user
            telegram_ref = f"https://t.me/{user.username}" if user.username else user.first_name
            async with aiosqlite.connect("users.db") as conn:
                await conn.execute('PRAGMA busy_timeout = 5000')  # Защита от блокировок
                await conn.executemany(
                    "INSERT INTO referal_tables (telegram_user) VALUES (?)",
                    [(telegram_ref,)] * insert_count
                )
                await conn.commit()

        # === 6. Добавляем бесплатные дни (например, +3 за первую оплату) ===
        await add_free_days(telegram_id, FREE_DAYS)

        await state.clear()

    except Exception as e:
        logger.error(f"Ошибка при обработке платежа для {telegram_id}: {e}", exc_info=True)
        try:
            await callback_query.message.answer("Произошла ошибка. Напишите в поддержку.")
        except:
            pass
    finally:
        purchase_tasks.pop(task_id, None)


async def handle_payment_check(callback_query: types.CallbackQuery, payment_id: str, payment_method: str):
    """
    Проверяет статус платежа, используя указанный метод оплаты.

    Проверка статуса платежа зависит от выбранного метода (например, Юкасса, Робокасса и т.д.)
    """
    if payment_method == "yookassa":
        return await check_payment_yookassa(payment_id)
    elif payment_method == "robokassa":
        password2 = PASS2
        return await check_payment_robokassa(payment_id, password2) == "100"
    elif payment_method == "yoomoney":
        return await check_yoomoney_payment_status(payment_id)
    elif payment_method == "cryptobot":
        return await check_payment_cryptobot(payment_id)
    elif payment_method == "cloudpay":
        return await check_payment_cloud(payment_id)
    return False


@router.callback_query(lambda query: query.data.startswith("check_payment:"), AddClient.WaitingForPayment)
async def check_payment_status(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос от пользователя для проверки статуса платежа.

    Функция проверяет статус платежа по предоставленному `payment_id` и `payment_method`. 
    Если платеж завершен, вызывается функция для обработки успешного платежа. Если платеж не 
    был завершен, пользователю выводится сообщение о необходимости повторной попытки.
    """
    try:
        payment_data = callback_query.data.split(":")
        payment_id = payment_data[1]
        payment_method = payment_data[2]

        if not await handle_payment_check(callback_query, payment_id, payment_method):
            await callback_query.answer("❌ Платеж не был завершен. Пожалуйста, проверьте и попробуйте снова.")
            return

        task_id = f"{callback_query.from_user.id}_{payment_id}"
        if task_id in purchase_tasks:
            task = purchase_tasks.pop(task_id)
            task.cancel()
            logger.info(f"Задача {task_id} была успешно отменена вручную.")

        await process_successful_payment(callback_query, state)
    except Exception as e:
        logger.error(f"Ошибка при ручной проверке платежа: {e}")

        
async def finalize_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Завершает процесс обработки успешного платежа и выполняет необходимые действия.

    Функция вызывает обработку успешного платежа, добавляя клиента, генерируя конфигурацию
    и выполняя другие шаги, такие как сохранение данных о платеже и пользователе в базе данных.
    """
    await process_successful_payment(callback_query, state)
    
    
@router.callback_query(lambda c: c.data == "bay_cancel")
async def handle_cancel_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает отмену платежа от пользователя.

    При отмене платежа, задача по его обработке отменяется, и пользователю отправляется
    сообщение об отмене. Если платеж уже завершен, отменить его невозможно.
    """
    try:
        data = await state.get_data()
        sent_message_id = data.get('sent_message_id')
        payment_id = data.get('payment_id')
        payment_method = data.get('payment_method')

        if not payment_id:
            await callback_query.answer("❌ Не удалось найти платежный процесс. Пожалуйста, попробуйте снова.")
            return

        is_payment_completed = await handle_payment_check(callback_query, payment_id, payment_method)
        if is_payment_completed:
            await callback_query.answer("❌ Платеж завершен. Отмена невозможна, нажмите кнопку, Проверить оплату")
            return

        task_id = f"{callback_query.from_user.id}_{payment_id}"
        if task_id in purchase_tasks:
            task = purchase_tasks.pop(task_id)
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
