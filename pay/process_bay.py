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
    logger.info(f"Пользователь {telegram_id} начал процесс получения пробной подписки.")

    # Проверка активной подписки
    if not has_active_subscription(telegram_id):
        logger.info(f"Пользователь {telegram_id} не имеет активной подписки. Продолжаем обработку пробной версии.")
        
        try:
            # Этап 1: Рассчитываем срок действия подписки
            current_time = datetime.utcnow()
            expiry_timestamp = current_time + timedelta(days=TRIAL)
            expiry_time = int(expiry_timestamp.timestamp() * 1000)
            logger.debug(f"Рассчитано время окончания подписки: {expiry_timestamp} (timestamp: {expiry_time})")

            # Этап 2: Генерация логина
            name = generate_login(telegram_id)
            logger.info(f"Сгенерирован логин для пользователя {telegram_id}: {name}")

            # Этап 3: Обновление состояния FSM
            await state.update_data(expiry_time=expiry_time)
            logger.debug(f"Состояние FSM обновлено: expiry_time={expiry_time}")

            # Этап 4: Обновление статуса пробной подписки в БД
            await update_user_trial_status(telegram_id)
            logger.info(f"Статус пробной подписки обновлён для пользователя {telegram_id}")

            # Этап 5: Выбор сервера
            server_selection = "random"
            selected_server = await get_optimal_server(server_selection, server_db)
            logger.info(f"Выбранный сервер: {selected_server}")
            
            if not selected_server:
                logger.error(f"Не удалось выбрать сервер для пользователя {telegram_id}")
                await bot.send_message(callback_query.from_user.id, "❌ Не удалось выбрать сервер. Попробуйте позже.")
                await callback_query.answer()
                return

            # Этап 6: Получение данных сервера
            server_data = await get_server_data(selected_server)
            logger.info(f"Получены данные сервера: {selected_server}")
            if not server_data:
                logger.error(f"Данные сервера {selected_server} не найдены.")
                await bot.send_message(callback_query.from_user.id, "❌ Не удалось получить данные сервера.")
                await callback_query.answer()
                return

            country_name = server_data.get('name', "🎲 Рандомная страна")
            logger.info(f"Определено имя страны для конфига: {country_name}")

            # Этап 7: Авторизация на сервере
            logger.info(f"Начало авторизации на сервере {server_data['login_url']}")
            session_id = await login(server_data['login_url'], {
                "username": server_data['username'],
                "password": server_data['password']
            })
            if not session_id:
                logger.error(f"Авторизация не удалась на сервере {server_data['login_url']}")
                await bot.send_message(callback_query.from_user.id, "❌ Не удалось авторизоваться на сервере.")
                await callback_query.answer()
                return
            logger.info(f"Авторизация успешна на сервере {selected_server}")

            # Этап 8: Добавление клиента
            inbound_ids = server_data['inbound_ids']
            logger.info(f"Добавление клиента {name} на сервер {selected_server} с inbound_ids: {inbound_ids}")
            await add_client(
                name, expiry_time, inbound_ids, telegram_id,
                server_data['add_client_url'], server_data['login_url'],
                {"username": server_data['username'], "password": server_data['password']}
            )
            logger.info(f"Клиент {name} успешно добавлен на сервер {selected_server}")

            # Этап 9: Сохранение данных в FSM
            await state.update_data(
                email=name,
                client_id=telegram_id,
                login_data={"username": server_data['username'], "password": server_data['password']},
                selected_country_name=country_name,
                server_ip=server_data['server_ip'],
                config_client_url=server_data['config_client_url'],
                inbound_ids=inbound_ids,
                login_url=server_data['login_url'],
                sub_url=server_data['sub_url'],
                json_sub=server_data['json_sub']
            )
            logger.debug("Данные пользователя сохранены в FSM.")

            # Этап 10: Генерация конфигурации
            logger.info(f"Генерация конфигурации для пользователя {telegram_id}")
            userdata, config, config2, config3 = await generate_config_from_pay(telegram_id, name, state)
            logger.info(f"Конфигурация успешно сгенерирована для {name}")

            # Этап 11: Отправка конфига
            logger.info(f"Отправка конфигурации пользователю {telegram_id}")
            await send_config_from_state(callback_query.message, state, telegram_id=callback_query.from_user.id, edit=True)

            # Этап 12: Очистка состояния
            await state.clear()
            logger.debug("Состояние FSM очищено.")

            # Этап 13: Сохранение пользователя в БД
            user_id = await insert_or_update_user(telegram_id, name, selected_server)
            logger.info(f"Пользователь {telegram_id} сохранён в базе данных с user_id={user_id}")

            logger.info(f"Пробная подписка успешно оформлена для пользователя {telegram_id}")

        except Exception as e:
            logger.exception(f"Ошибка при оформлении пробной подписки для пользователя {telegram_id}: {e}")
            await bot.send_message(callback_query.from_user.id, "❌ Произошла ошибка. Попробуйте снова.")

    else:
        logger.warning(f"Пользователь {telegram_id} попытался получить пробную подписку, но уже имеет активную.")
        await callback_query.message.edit_text(
            "⚠ У вас уже есть активная подписка. Оформить пробную подписку можно только один раз.",
            reply_markup=get_main_menu(callback_query)
        )

    await callback_query.answer()
    logger.info(f"Обработка callback_query для пользователя {telegram_id} завершена.")

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
    logger.info(f"Пользователь {callback_query.from_user.id} подтвердил срок действия подписки.")

    # Этап 1: Получение данных из состояния
    data = await state.get_data()
    expiry_time = data.get("pending_expiry_time")

    if not expiry_time:
        logger.warning(f"Пользователь {callback_query.from_user.id} пытается подтвердить, но expiry_time не найден в состоянии.")
        await callback_query.answer("Ошибка: тариф не выбран.", show_alert=True)
        return

    logger.debug(f"Получен pending_expiry_time: {expiry_time} для пользователя {callback_query.from_user.id}")

    telegram_id = callback_query.from_user.id
    name = generate_login(telegram_id)
    email = "default@mail.ru"
    user_promo_code = None

    # Этап 2: Выбор оптимального сервера
    logger.info(f"Начало выбора оптимального сервера для пользователя {telegram_id} (режим 'random')")
    selected_server = await get_optimal_server("random", server_db)

    if isinstance(selected_server, str):
        if "занят" in selected_server.lower():
            logger.warning(f"Все серверы заняты. Ответ от get_optimal_server: {selected_server}")
            await callback_query.answer("❌ Все серверы в этой группе заняты. Попробуйте позже.", show_alert=True)
            return
        else:
            logger.warning(f"Получена строка от get_optimal_server, но не 'занят': {selected_server}")
            await callback_query.answer("❌ Не удалось выбрать сервер.", show_alert=True)
            return
    elif not selected_server:
        logger.error(f"get_optimal_server вернул None или пустое значение для пользователя {telegram_id}")
        await callback_query.answer("❌ Не удалось выбрать сервер.", show_alert=True)
        return

    # Этап 3: Проверка и преобразование ID сервера
    if not str(selected_server).isdigit():
        logger.error(f"Некорректный формат ID сервера: {selected_server} (тип: {type(selected_server)})")
        await callback_query.answer("❌ Не удалось выбрать сервер.", show_alert=True)
        return

    selected_server = int(selected_server)
    logger.info(f"Выбран сервер с ID: {selected_server} для пользователя {telegram_id}")

    # Этап 4: Сохранение данных в FSM
    await state.update_data({
        "expiry_time": expiry_time,
        "email": email,
        "name": name,
        "selected_server": selected_server,
        "user_promo_code": user_promo_code,
        "sent_message_id": callback_query.message.message_id,
    })
    logger.debug(f"Состояние FSM обновлено: expiry_time={expiry_time}, name={name}, selected_server={selected_server}")

    # Этап 5: Получение данных сервера
    logger.info(f"Запрос данных сервера с ID {selected_server}")
    server_data = await get_server_data(selected_server)

    if not server_data:
        logger.error(f"Данные сервера с ID {selected_server} не найдены.")
        await callback_query.message.answer("❌ Сервер не найден.")
        return

    logger.info(f"Получены данные сервера: {server_data['name']} ({server_data['server_ip']})")

    # Этап 6: Сохранение данных сервера в FSM
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
    logger.debug(f"Данные сервера сохранены в FSM: {server_data['name']}")

    # Этап 7: Установка состояния
    await state.set_state(AddClient.WaitingForPaymentMethod)
    logger.info(f"Состояние пользователя {telegram_id} установлено: WaitingForPaymentMethod")

    # Этап 8: Имитация выбора метода оплаты
    logger.info(f"Имитация выбора метода оплаты: YooKassa для пользователя {telegram_id}")
    fake_callback = types.CallbackQuery(
        id=callback_query.id,
        from_user=callback_query.from_user,
        chat_instance=callback_query.chat_instance,
        message=callback_query.message,
        data="payment_method_yookassa"
    )

    try:
        await handle_payment_method_selection(fake_callback, state)
        logger.info(f"Успешно вызван handle_payment_method_selection для пользователя {telegram_id}")
    except Exception as e:
        logger.exception(f"Ошибка при вызове handle_payment_method_selection для пользователя {telegram_id}: {e}")
        await callback_query.message.answer("❌ Произошла ошибка при обработке оплаты. Попробуйте позже.")

    # Этап 9: Подтверждение callback
    await callback_query.answer()
    logger.info(f"Callback подтверждён для пользователя {telegram_id}. Процесс выбора подписки завершён.")



    
@router.callback_query(lambda query: query.data.isdigit(), AddClient.WaitingForExpiryTime)
async def process_paid_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает подписку на платный тариф, выбирает сервер и отправляет информацию о цене и скидке.

    Функция обрабатывает выбор пользователя, желающего оформить подписку на платный тариф. Включает этапы 
    выбора сервера, вычисления итоговой стоимости, применения скидок, если таковые есть, и отправки пользователю
    информации о цене и условиях подписки.
    """
    logger.info(f"Пользователь {callback_query.from_user.id} начал обработку платной подписки.")

    data = callback_query.data
    telegram_id = callback_query.from_user.id

    # Этап 1: Извлечение и проверка expiry_time
    try:
        expiry_time = int(data)
        logger.info(f"Извлечён срок подписки (expiry_time): {expiry_time} секунд для пользователя {telegram_id}")
    except ValueError:
        logger.error(f"Некорректные данные callback.data: {data} от пользователя {telegram_id}")
        await callback_query.answer("❌ Ошибка: неверный формат данных.", show_alert=True)
        return

    # Этап 2: Сохранение expiry_time в состояние
    await state.update_data(expiry_time=expiry_time)
    logger.debug(f"Состояние FSM обновлено: expiry_time={expiry_time}")

    # Этап 3: Получение данных из состояния
    state_data = await state.get_data()
    logger.debug(f"Данные из FSM: {state_data}")

    sent_message_id = state_data.get('sent_message_id')
    server_selection = state_data.get('selected_country_id')
    country_name = state_data.get('selected_country_name')

    if not sent_message_id or not server_selection:
        logger.error(f"Отсутствуют необходимые данные в FSM: sent_message_id={sent_message_id}, selected_country_id={server_selection}")
        await callback_query.answer("❌ Ошибка: данные не найдены. Начните сначала.", show_alert=True)
        return

    logger.info(f"Используется: sent_message_id={sent_message_id}, selected_country_id={server_selection}, страна={country_name}")

    # Этап 4: Получение промокода пользователя из БД
    logger.info(f"Запрос промокода пользователя {telegram_id} из базы данных.")
    conn_users = sqlite3.connect(USERSDATABASE)
    cursor_users = conn_users.cursor()

    try:
        cursor_users.execute("""
            SELECT promo_code 
            FROM users 
            WHERE telegram_id = ? 
        """, (telegram_id,))
        result = cursor_users.fetchone()
        user_promo_code = result[0] if result and result[0] else None
        logger.info(f"Промокод пользователя {telegram_id}: {user_promo_code}")
    except Exception as e:
        logger.exception(f"Ошибка при получении промокода из БД для пользователя {telegram_id}: {e}")
        user_promo_code = None
    finally:
        cursor_users.close()
        conn_users.close()

    # Этап 5: Расчёт цены и скидки
    logger.info(f"Расчёт цены для пользователя {telegram_id} с expiry_time={expiry_time}, промокод={user_promo_code}")
    price, total_discount, referral_count = get_price_with_referral_info(expiry_time, telegram_id, user_promo_code)
    expiry_time_description = get_expiry_time_description(expiry_time)

    logger.info(f"Цена: {price}, Скидка: {total_discount}%, Приглашённых: {referral_count}")

    # Этап 6: Формирование сообщения
    message_text = (
        f"✅ Вы выбрали подключение на: {expiry_time_description}.\n"
        f"🌍 Страна: {country_name}.\n"
        f"💵 Цена: {price}.\n"
        f"👥 Количество приглашенных пользователей: {referral_count}.\n"
        f"🎁 Ваша скидка: {total_discount}%.\n\n"
        "📧 Пожалуйста, введите ваш email для отправки чека, либо нажмите 'Продолжить без email':"
    )

    # Этап 7: Создание клавиатуры
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["without_mail"], callback_data="continue_without_email"),
        InlineKeyboardButton(text=BUTTON_TEXTS["promocode"], callback_data="enter_promo_code"),
        InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel")
    )
    logger.debug("Клавиатура для ввода email создана.")

    # Этап 8: Редактирование сообщения
    try:
        sent_message = await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=sent_message_id,
            text=message_text,
            reply_markup=keyboard.adjust(1).as_markup()
        )
        logger.info(f"Сообщение с ID {sent_message_id} успешно отредактировано.")
    except Exception as e:
        logger.error(f"Не удалось отредактировать сообщение: {e}")
        await callback_query.answer("❌ Не удалось обновить сообщение.", show_alert=True)
        return

    # Этап 9: Выбор оптимального сервера
    logger.info(f"Начало выбора оптимального сервера для страны с ID {server_selection}")
    optimal_server = await get_optimal_server(server_selection, server_db)

    if optimal_server == "Сервер полностью занят, попробуйте позже":
        logger.warning(f"Сервер для страны {server_selection} полностью занят.")
        busy_keyboard = InlineKeyboardBuilder()
        busy_keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
        )
        try:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=sent_message_id,
                text="Извините, выбранный сервер полностью занят. Пожалуйста, попробуйте выбрать другой сервер позже.",
                reply_markup=busy_keyboard.adjust(1).as_markup()
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения о занятом сервере: {e}")
        return

    if not optimal_server:
        logger.error(f"get_optimal_server вернул None для страны {server_selection}")
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=sent_message_id,
            text="❌ Не удалось выбрать сервер. Попробуйте позже."
        )
        return

    logger.info(f"Оптимальный сервер выбран: {optimal_server}")

    # Этап 10: Обновление состояния и переход к следующему шагу
    await state.update_data(
        selected_server=optimal_server,
        sent_message_id=sent_message.message_id,
        user_promo_code=user_promo_code
    )
    logger.debug(f"Состояние обновлено: selected_server={optimal_server}, user_promo_code={user_promo_code}")

    await state.set_state(AddClient.WaitingForEmail)
    logger.info(f"Пользователь {telegram_id} переведён в состояние WaitingForEmail")

    await callback_query.answer()
    logger.info(f"Callback от пользователя {telegram_id} успешно обработан.")

@router.callback_query(lambda c: c.data == "continue_without_email", AddClient.WaitingForEmail)
@router.message(AddClient.WaitingForEmail)
async def handle_email_or_continue(callback: types.CallbackQuery | types.Message, state: FSMContext):
    """
    Обрабатывает введенный email или продолжение без email, обновляет состояние и предоставляет выбор способов оплаты.
    """
    logger.info(f"Начата обработка email (или продолжение без него) для пользователя.")

    email = None
    user_id = None
    chat_id = None
    sent_message_id = None

    # Этап 1: Определение типа входящего объекта (CallbackQuery или Message)
    if isinstance(callback, types.CallbackQuery):
        logger.info(f"Получен callback: пользователь {callback.from_user.id} выбрал 'Продолжить без email'")
        email = EMAIL  # Предполагается, что EMAIL — это глобальная константа вроде "no_email@service.com"
        user_id = callback.from_user.id
        chat_id = user_id
        state_data = await state.get_data()
        sent_message_id = state_data.get('sent_message_id')
        logger.debug(f"CallbackQuery: email установлен как {email}, sent_message_id={sent_message_id}")

    elif isinstance(callback, types.Message):
        logger.info(f"Получено сообщение с email от пользователя {callback.from_user.id}")
        email = callback.text.strip()
        user_id = callback.from_user.id
        chat_id = user_id
        state_data = await state.get_data()
        sent_message_id = state_data.get('sent_message_id')

        # Этап 2: Валидация email
        if not is_valid_email(email):
            logger.warning(f"Некорректный email от пользователя {user_id}: '{email}'")
            await callback.delete()
            invalid_email_msg = await callback.answer("Пожалуйста, введите корректный email.")
            await asyncio.sleep(2)
            try:
                await invalid_email_msg.delete()
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение с ошибкой email: {e}")
            return
        else:
            logger.info(f"Корректный email получен от пользователя {user_id}: {email}")

        # Удаляем сообщение с email для конфиденциальности
        try:
            await callback.delete()
            logger.debug(f"Сообщение с email от пользователя {user_id} удалено.")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение с email: {e}")

    # Этап 3: Сохранение email в FSM
    await state.update_data(email=email)
    logger.info(f"Email '{email}' сохранён в состоянии для пользователя {user_id}")

    # Этап 4: Формирование клавиатуры выбора способа оплаты
    logger.info(f"Формирование клавиатуры выбора способа оплаты для пользователя {user_id}")
    payment_methods_keyboard = InlineKeyboardBuilder()
    payment_method_text = "⚙️ <b>Выберите способ оплаты:</b>\n\n"

    available_methods = 0
    for method, details in PAYMENT_METHODS.items():
        if details["enabled"]:
            payment_methods_keyboard.add(InlineKeyboardButton(
                text=details["text"],
                callback_data=details["callback_data"]
            ))
            payment_method_text += details["description"] + "\n"
            available_methods += 1
            logger.debug(f"Добавлен активный способ оплаты: {method}")

    if available_methods == 0:
        logger.warning("Нет доступных способов оплаты. Пользователь будет уведомлён.")
        error_text = "❌ К сожалению, все способы оплаты временно недоступны. Попробуйте позже."
        if sent_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=sent_message_id,
                    text=error_text
                )
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}")
                await bot.send_message(chat_id, error_text)
        else:
            await bot.send_message(chat_id, error_text)
        return

    # Добавление кнопки отмены
    payment_methods_keyboard.add(InlineKeyboardButton(
        text=BUTTON_TEXTS["cancel"],
        callback_data="cancel"
    ))

    # Этап 5: Отправка или редактирование сообщения
    try:
        if sent_message_id:
            logger.info(f"Редактирование существующего сообщения с ID {sent_message_id}")
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message_id,
                text=payment_method_text,
                parse_mode='HTML',
                reply_markup=payment_methods_keyboard.adjust(1).as_markup()
            )
        else:
            logger.info(f"Отправка нового сообщения с выбором способа оплаты (sent_message_id не найден)")
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=payment_method_text,
                parse_mode='HTML',
                reply_markup=payment_methods_keyboard.adjust(1).as_markup()
            )
            await state.update_data(sent_message_id=sent_message.message_id)
            logger.debug(f"Новое сообщение отправлено с ID: {sent_message.message_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке/редактировании сообщения с методами оплаты: {e}", exc_info=True)
        await bot.send_message(chat_id, "❌ Произошла ошибка при отображении способов оплаты. Попробуйте позже.")
        return

    # Этап 6: Установка следующего состояния
    await state.set_state(AddClient.WaitingForPaymentMethod)
    logger.info(f"Пользователь {user_id} переведён в состояние WaitingForPaymentMethod")

    # Подтверждение callback (если это callback)
    if isinstance(callback, types.CallbackQuery):
        await callback.answer()
        logger.debug(f"Callback от пользователя {user_id} подтверждён.")


@router.callback_query(lambda c: c.data.startswith("payment_method_"), AddClient.WaitingForPaymentMethod)
async def handle_payment_method_selection(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор метода оплаты от пользователя.
    
    После выбора метода оплаты формируется соответствующая ссылка на платеж и отправляется
    пользователю с кнопками для подтверждения оплаты или отмены.
    """
    logger.info(f"Пользователь {callback_query.from_user.id} начал выбор способа оплаты.")

    # Этап 1: Извлечение метода оплаты
    try:
        payment_method = callback_query.data.split("_", 2)[2]  # Чтобы корректно обработать например "payment_method_tgpay"
        logger.info(f"Извлечён способ оплаты: '{payment_method}'")
    except IndexError:
        logger.error(f"Некорректный формат callback_data: {callback_query.data}")
        await callback_query.answer("❌ Ошибка: неверный способ оплаты.", show_alert=True)
        return

    # Сохраняем метод оплаты в FSM
    await state.update_data(payment_method=payment_method)
    logger.debug(f"Состояние FSM обновлено: payment_method={payment_method}")

    # Этап 2: Получение данных из состояния
    data = await state.get_data()
    user_promo_code = data.get('user_promo_code')
    name = "MoyServise"
    email = data.get('email')
    expiry_time = data.get('expiry_time')
    user_id = callback_query.from_user.id

    if not expiry_time:
        logger.error(f"Пользователь {user_id}: expiry_time не найден в состоянии.")
        await callback_query.answer("❌ Ошибка: срок подписки не указан.", show_alert=True)
        return

    # Логируем все полученные данные
    logger.info(
        f"📥 Получены данные из состояния (user_id={user_id}):\n"
        f"   → user_promo_code: '{user_promo_code}'\n"
        f"   → name: '{name}'\n"
        f"   → email: '{email}'\n"
        f"   → expiry_time: {expiry_time} ({get_expiry_time_description(expiry_time)})\n"
        f"   → payment_method: {payment_method}"
    )

    # Этап 3: Расчёт финальной цены
    try:
        price_info = get_price_with_referral_info(expiry_time, user_id, user_promo_code)
        final_price = int(price_info[0])
        logger.info(f"Рассчитана цена подписки: {final_price} RUB (user_id={user_id})")
    except Exception as e:
        logger.exception(f"Ошибка при расчёте цены для пользователя {user_id}: {e}")
        await callback_query.answer("❌ Не удалось рассчитать стоимость подписки.", show_alert=True)
        return

    # Этап 4: Генерация платежа в зависимости от метода
    payment_url = None
    payment_id = None

    try:
        if payment_method == "yookassa":
            logger.info(f"Генерация платежа через ЮKassa для пользователя {user_id}")
            payment_url, payment_id = create_payment_yookassa(final_price, user_id, name, expiry_time, email)
            logger.info(f"ЮKassa: payment_url={payment_url}, payment_id={payment_id}")

        elif payment_method == "yoomoney":
            label = str(uuid.uuid4())
            logger.info(f"Генерация платежа через YooMoney (label={label}) для пользователя {user_id}")
            payment_url, payment_id = create_yoomoney_invoice(final_price, YOOMONEY_CARD, label)
            logger.info(f"YooMoney: payment_url={payment_url}, payment_id={payment_id}")

        elif payment_method == "robokassa":
            logger.info(f"Генерация платежа через Robokassa для пользователя {user_id}")
            payment_url, payment_id = create_payment_robokassa(final_price, user_id, name, expiry_time, email)
            logger.info(f"Robokassa: payment_url={payment_url}, payment_id={payment_id}")

        elif payment_method == "cryptobot":
            logger.info(f"Генерация платежа через CryptoBot для пользователя {user_id}")
            payment_url, payment_id = await create_payment_cryptobot(final_price, user_id)
            logger.info(f"CryptoBot: payment_url={payment_url}, payment_id={payment_id}")

        elif payment_method == "cloudpay":
            invoice_id = str(uuid.uuid4())
            logger.info(f"Генерация платежа через CloudPayments (invoice_id={invoice_id}) для пользователя {user_id}")
            payment_url, payment_id = await create_cloudpayments_invoice(final_price, user_id, invoice_id)
            logger.info(f"CloudPayments: payment_url={payment_url}, payment_id={payment_id}")

        elif payment_method == "tgpay":
            logger.info(f"Подготовка платежа через Telegram Stars (tgpay) для пользователя {user_id}")
            sent_message = await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=callback_query.message.message_id,
                text="🔄 Создаем платеж...",
                parse_mode='HTML'
            )
            await asyncio.sleep(2)
            await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

            await create_payment_tgpay(
                final_price, user_id, name, expiry_time,
                payment_type="initial_payment",
                pay_currency="tgpay"
            )
            logger.info(f"Платёж через Telegram Stars (tgpay) успешно инициирован для пользователя {user_id}")
            return  # Завершаем здесь, так как не нужна кнопка оплаты

        elif payment_method == "star":
            logger.info(f"Подготовка платежа через Telegram Stars (XTR) для пользователя {user_id}")
            sent_message = await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=callback_query.message.message_id,
                text="🔄 Создаем платеж...",
                parse_mode='HTML'
            )
            await asyncio.sleep(2)
            await bot.delete_message(chat_id=callback_query.from_user.id, message_id=sent_message.message_id)

            await create_payment_tgpay(
                final_price, user_id, name, expiry_time,
                payment_type="initial_payment",
                pay_currency="xtr"
            )
            logger.info(f"Платёж через Telegram Stars (XTR) успешно инициирован для пользователя {user_id}")
            return

        else:
            logger.warning(f"Неизвестный способ оплаты: {payment_method}")
            await callback_query.answer("❌ Неизвестный способ оплаты.", show_alert=True)
            return

    except Exception as e:
        logger.exception(f"Ошибка при создании платежа через {payment_method} для пользователя {user_id}: {e}")
        await callback_query.answer("❌ Не удалось создать платёж. Попробуйте позже.")
        return

    # Этап 5: Проверка, что payment_url и payment_id созданы (кроме tgpay/star)
    if payment_method not in ["tgpay", "star"]:
        if not payment_url or not payment_id:
            logger.error(f"Не удалось создать платёж: payment_url={payment_url}, payment_id={payment_id}, method={payment_method}")
            await callback_query.answer("❌ Не удалось создать ссылку для оплаты. Попробуйте снова.")
            return
        else:
            logger.info(f"Платёж успешно создан: URL={payment_url}, ID={payment_id}")

    # Этап 6: Формирование клавиатуры
    logger.debug(f"Формирование клавиатуры для пользователя {user_id}")
    keyboard = InlineKeyboardBuilder()
    if payment_method not in ["tgpay", "star"]:
        keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["pay"], url=payment_url),
            # InlineKeyboardButton(text=BUTTON_TEXTS["check_pay"], callback_data=f"check_payment:{payment_id}:{payment_method}"),
            InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="bay_cancel")
        )
    else:
        keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="bay_cancel")
        )

    # Этап 7: Формирование текста сообщения
    payment_text = (
        f"💳 <b>Оплата подписки</b> на <b>{get_expiry_time_description(expiry_time)}</b>\n\n"
        "⚠️ <i>Если передумали или выбрали не то, не оплачивайте, а просто нажмите 'Отмена'.</i>\n\n"
    )
    if email and email != EMAIL:
        payment_text += f"📧 Чек будет отправлен на: <code>{email}</code>\n\n"

    # Этап 8: Отправка или редактирование сообщения
    try:
        sent_message_id = data.get('sent_message_id')
        if sent_message_id:
            logger.info(f"Редактирование сообщения с ID {sent_message_id}")
            await bot.edit_message_text(
                chat_id=callback_query.from_user.id,
                message_id=sent_message_id,
                text=payment_text,
                parse_mode='HTML',
                reply_markup=keyboard.adjust(2).as_markup()
            )
        else:
            logger.info(f"Отправка нового сообщения (sent_message_id не найден)")
            sent_message = await bot.send_message(
                chat_id=callback_query.from_user.id,
                text=payment_text,
                parse_mode='HTML',
                reply_markup=keyboard.adjust(2).as_markup()
            )
            await state.update_data(sent_message_id=sent_message.message_id)
            logger.debug(f"Новое сообщение отправлено с ID: {sent_message.message_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке/редактировании сообщения с платёжной ссылкой: {e}", exc_info=True)
        await callback_query.answer("❌ Не удалось отправить платёжное сообщение.", show_alert=True)
        return

    # Этап 9: Сохранение ID платежа и цены в FSM
    if payment_method not in ["tgpay", "star"]:
        await state.update_data(payment_id=payment_id, final_price=final_price)
        logger.info(f"Данные платежа сохранены в FSM: payment_id={payment_id}, final_price={final_price}")

    # Этап 10: Запуск фоновой проверки статуса оплаты
    if payment_method not in ["tgpay", "star"]:
        logger.info(f"Запуск фоновой проверки статуса оплаты для payment_id={payment_id}, метод={payment_method}")
        asyncio.create_task(start_payment_status_check(callback_query, state, payment_id, payment_method))
    else:
        logger.info(f"Платёж через {payment_method} не требует фоновой проверки (обрабатывается через Telegram API)")

    # Этап 11: Установка состояния
    await state.set_state(AddClient.WaitingForPayment)
    logger.info(f"Пользователь {user_id} переведён в состояние WaitingForPayment")

    # Подтверждение callback
    await callback_query.answer()
    logger.info(f"Callback от пользователя {user_id} обработан и подтверждён.")


async def start_payment_status_check(callback_query: types.CallbackQuery, state: FSMContext, payment_id: str, payment_method: str):
    """
    Начинает асинхронную проверку статуса платежа, периодически проверяя завершение оплаты.

    Эта функция будет выполняться в фоновом режиме, пытаясь проверить статус платежа через
    выбранный метод оплаты (Юкасса, Робокасса и т.д.) и обновлять статус в случае успешной
    оплаты или по истечении максимального времени ожидания.
    """
    user_id = callback_query.from_user.id
    task_id = f"{user_id}_{payment_id}"
    
    logger.info(
        f"🟢 Запущена фоновая проверка статуса платежа:\n"
        f"   → user_id: {user_id}\n"
        f"   → payment_id: {payment_id}\n"
        f"   → payment_method: {payment_method}\n"
        f"   → task_id: {task_id}\n"
        f"   → Максимум попыток: {MAX_ATTEMPTS}, Первое ожидание: {FIRST_CHECK_DELAY} сек"
    )

    try:
        # Сохраняем задачу в глобальном словаре для возможной отмены
        purchase_tasks[task_id] = asyncio.current_task()
        logger.debug(f"Задача {task_id} добавлена в список активных проверок оплаты.")

        # Первая задержка перед первой проверкой
        logger.info(f"Первая задержка: ожидание {FIRST_CHECK_DELAY} секунд перед первой проверкой...")
        await asyncio.sleep(FIRST_CHECK_DELAY)

        attempts = 0

        # Основной цикл проверок
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            logger.info(f"🔄 Попытка {attempts}/{MAX_ATTEMPTS} проверки статуса платежа {payment_id} (метод: {payment_method})")

            payment_check_result = None

            try:
                if payment_method == "yookassa":
                    logger.debug(f"Проверка статуса платежа через ЮKassa: payment_id={payment_id}")
                    payment_check_result = await check_payment_yookassa(payment_id)
                    if payment_check_result:
                        logger.info(f"✅ Платёж через ЮKassa (ID: {payment_id}) подтверждён.")
                        await finalize_payment(callback_query, state)
                        return

                elif payment_method == "yoomoney":
                    logger.debug(f"Проверка статуса платежа через YooMoney: payment_id={payment_id}")
                    payment_check_result = await check_yoomoney_payment_status(payment_id)
                    if payment_check_result:
                        logger.info(f"✅ Платёж через YooMoney (ID: {payment_id}) подтверждён.")
                        await finalize_payment(callback_query, state)
                        return

                elif payment_method == "robokassa":
                    logger.debug(f"Проверка статуса платежа через Robokassa: payment_id={payment_id}")
                    password2 = PASS2
                    payment_check_result = await check_payment_robokassa(payment_id, password2)
                    if payment_check_result == "100":
                        logger.info(f"✅ Платёж через Robokassa (ID: {payment_id}) завершён (статус: {payment_check_result}).")
                        await finalize_payment(callback_query, state)
                        return
                    else:
                        logger.debug(f"Robokassa: статус платежа {payment_id} = {payment_check_result} (ожидается '100')")

                elif payment_method == "cryptobot":
                    logger.debug(f"Проверка статуса платежа через CryptoBot: payment_id={payment_id}")
                    payment_check_result = await check_payment_cryptobot(payment_id)
                    if payment_check_result:
                        logger.info(f"✅ Платёж через CryptoBot (ID: {payment_id}) подтверждён.")
                        await finalize_payment(callback_query, state)
                        return

                elif payment_method == "cloudpay":
                    logger.debug(f"Проверка статуса платежа через CloudPayments: payment_id={payment_id}")
                    payment_check_result = await check_payment_cloud(payment_id)
                    if payment_check_result:
                        logger.info(f"✅ Платёж через CloudPayments (ID: {payment_id}) подтверждён.")
                        await finalize_payment(callback_query, state)
                        return

                else:
                    logger.warning(f"Неизвестный метод оплаты в фоновой проверке: {payment_method}")
                    break  # Прерываем цикл, если метод не поддерживается

            except Exception as e:
                logger.error(
                    f"❌ Ошибка при проверке платежа {payment_id} через {payment_method} (попытка {attempts}): {e}",
                    exc_info=True
                )
                # Не выходим, продолжаем попытки

            # Логируем результат проверки
            if not payment_check_result:
                logger.info(
                    f"⏳ Платёж {payment_id} ещё не оплачен (метод: {payment_method}). "
                    f"Ожидание {SUBSEQUENT_CHECK_INTERVAL} секунд перед следующей попыткой..."
                )
            else:
                logger.debug(f"Платёж {payment_id} не подтверждён на попытке {attempts}")

            # Задержка перед следующей попыткой
            await asyncio.sleep(SUBSEQUENT_CHECK_INTERVAL)

        # Если все попытки исчерпаны
        logger.warning(f"⏰ Исчерпано {MAX_ATTEMPTS} попыток проверки платежа {payment_id}. Платёж не завершён.")
        try:
            await callback_query.answer("❌ Платеж не был завершен в установленное время.", show_alert=True)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление о просрочке платежа: {e}")

    except asyncio.CancelledError:
        logger.info(f"🛑 Задача {task_id} была отменена (asyncio.CancelledError).")
        # Задача была отменена (например, принудительно), это нормально

    except Exception as e:
        logger.exception(f"💥 Критическая ошибка в фоновой проверке платежа {task_id}: {e}")

    finally:
        # Удаляем задачу из списка активных
        if task_id in purchase_tasks:
            removed_task = purchase_tasks.pop(task_id, None)
            logger.debug(f"Задача {task_id} удалена из списка активных проверок оплаты.")
        else:
            logger.debug(f"Задача {task_id} не найдена в списке активных — возможно, уже была удалена.")

        logger.info(f"🔴 Фоновая проверка платежа завершена: user_id={user_id}, payment_id={payment_id}, method={payment_method}")
        

async def process_successful_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает успешный платёж с защитой от ошибок и дублирования.
    """
    telegram_id = callback_query.from_user.id
    data = await state.get_data()
    payment_id = data.get('payment_id')
    task_id = f"{telegram_id}_{payment_id}"

    # Этап 1: Защита от дублирования
    if task_id in purchase_tasks:
        logger.warning(f"🚫 Повторный вызов обработки платежа {task_id}. Запрос проигнорирован.")
        return

    purchase_tasks[task_id] = True
    logger.info(
        f"🟢 Начата обработка успешного платежа:\n"
        f"   → user_id: {telegram_id}\n"
        f"   → task_id: {task_id}\n"
        f"   → payment_id: {payment_id}\n"
        f"   → final_price: {data.get('final_price')} RUB"
    )

    try:
        # Этап 2: Получение данных из состояния
        final_price = data.get("final_price")
        name = data.get('name')
        expiry_days = data.get('expiry_time')  # Это количество дней, например 30, 90, 365
        selected_server = data.get('selected_server')

        if not all([name, expiry_days, selected_server]):
            logger.error(f"❌ Отсутствуют критические данные в состоянии для пользователя {telegram_id}")
            await callback_query.message.answer("❌ Ошибка: повреждены данные заказа. Обратитесь в поддержку.")
            return

        logger.info(f"Данные платежа: имя={name}, срок={expiry_days} дней, сервер={selected_server}")

        # Этап 3: Расчёт времени окончания подписки
        current_time = datetime.utcnow()
        expiry_timestamp = current_time + timedelta(days=expiry_days)
        expiry_time = int(expiry_timestamp.timestamp() * 1000)
        logger.info(f"Рассчитано время окончания подписки: {expiry_timestamp} (timestamp: {expiry_time})")

        # Этап 4: Получение данных сервера
        server_data = await get_server_data(selected_server)
        if not server_data:
            logger.error(f"❌ Сервер с ID {selected_server} не найден.")
            await callback_query.answer("Ошибка: сервер не найден.")
            return
        logger.info(f"Получены данные сервера: {server_data['name']} ({server_data['server_ip']})")

        # === 1. Вход в 3x UI ===
        logger.info(f"🔐 Вход в панель управления сервера: {server_data['login_url']}")
        session_id = await login(server_data['login_url'], {
            "username": server_data['username'],
            "password": server_data['password']
        })
        if not session_id:
            logger.error(f"❌ Не удалось авторизоваться на сервере {server_data['server_ip']}")
            raise Exception("Не удалось войти в 3x UI")

        logger.info(f"✅ Успешная авторизация на сервере {server_data['name']}")

        # === 2. Добавляем клиента ===
        inbound_ids = server_data['inbound_ids']
        logger.info(f"➕ Добавление клиента на сервер: {name}, expiry_time={expiry_time}, inbounds={inbound_ids}")
        await add_client(
            name, expiry_time, inbound_ids, telegram_id,
            server_data['add_client_url'], server_data['login_url'],
            {"username": server_data['username'], "password": server_data['password']}
        )
        logger.info(f"✅ Клиент {name} успешно добавлен на сервер {server_data['name']}")

        # === 3. Генерация и отправка конфигурации ===
        logger.info(f"⚙️ Генерация конфигурации для пользователя {telegram_id}")
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
        approx_months = max(1, round(expiry_days / 30))  # минимум 1 месяц
        tickets_msg = {1: "1 билет", 3: "3 билета", 12: "12 билетов"}.get(approx_months)

        logger.info(f"📤 Отправка конфигурации пользователю {telegram_id} (билеты: {tickets_msg})")
        await send_config_from_state(callback_query.message, state, telegram_id, edit=False, tickets_message=tickets_msg)

        # === 4. Обновление баз данных ===
        logger.info(f"💾 Начало обновления баз данных для пользователя {telegram_id}")
        await handle_database_operations(telegram_id, name, expiry_time)
        await insert_or_update_user(telegram_id, name, selected_server)
        await log_promo_code_usage(telegram_id, data.get('user_promo_code'))
        await update_sum_my(telegram_id, final_price)
        await update_sum_ref(telegram_id, final_price)
        logger.info(f"✅ Все основные записи в БД успешно обновлены")

        # === 5. Начисление билетов за оплату ===
        insert_count = {1: 1, 3: 3, 12: 12}.get(approx_months, 0)
        if insert_count > 0:
            user = callback_query.from_user
            telegram_ref = f"https://t.me/{user.username}" if user.username else user.first_name
            logger.info(f"🎟️ Начисление {insert_count} билетов пользователю {telegram_id} через реферальную таблицу")
            try:
                async with aiosqlite.connect("users.db") as conn:
                    await conn.execute('PRAGMA busy_timeout = 5000')
                    await conn.executemany(
                        "INSERT INTO referal_tables (telegram_user) VALUES (?)",
                        [(telegram_ref,)] * insert_count
                    )
                    await conn.commit()
                logger.info(f"✅ Успешно вставлено {insert_count} записей в referal_tables для {telegram_ref}")
            except Exception as e:
                logger.error(f"❌ Ошибка при вставке билетов в referal_tables: {e}", exc_info=True)

        # === 6. Добавление бесплатных дней (например, +3 за первую оплату) ===
        if FREE_DAYS > 0:
            logger.info(f"🎁 Добавление {FREE_DAYS} бесплатных дней за первую оплату")
            await add_free_days(telegram_id, FREE_DAYS)
            logger.info(f"✅ Бесплатные дни успешно добавлены пользователю {telegram_id}")

        # Этап финализации
        await state.clear()
        logger.info(f"🧹 Состояние FSM очищено для пользователя {telegram_id}")

        # Финальное логирование успеха
        logger.info(
            f"🎉 Успешно завершена обработка платежа:\n"
            f"   → Пользователь: {telegram_id}\n"
            f"   → Подписка: {expiry_days} дней\n"
            f"   → Сервер: {server_data['name']}\n"
            f"   → Сумма: {final_price} RUB\n"
            f"   → Билеты начислены: {insert_count}\n"
            f"   → Бесплатные дни: {FREE_DAYS}"
        )

    except Exception as e:
        logger.error(
            f"💥 Критическая ошибка при обработке платежа для пользователя {telegram_id} (task_id={task_id}): {e}",
            exc_info=True
        )
        try:
            await callback_query.message.answer("Произошла ошибка. Напишите в поддержку.")
        except Exception as send_error:
            logger.debug(f"Не удалось отправить сообщение пользователю {telegram_id}: {send_error}")

    finally:
        # Удаление задачи из глобального пула
        if task_id in purchase_tasks:
            del purchase_tasks[task_id]
            logger.debug(f"🗑️ Задача {task_id} удалена из purchase_tasks")
        else:
            logger.debug(f"⚠️ Задача {task_id} не найдена в purchase_tasks при очистке")


async def handle_payment_check(callback_query: types.CallbackQuery, payment_id: str, payment_method: str):
    """
    Проверяет статус платежа, используя указанный метод оплаты.

    Проверка статуса платежа зависит от выбранного метода (например, Юкасса, Робокасса и т.д.)
    """
    user_id = callback_query.from_user.id
    logger.info(
        f"🔍 Начата проверка статуса платежа:\n"
        f"   → user_id: {user_id}\n"
        f"   → payment_id: {payment_id}\n"
        f"   → payment_method: {payment_method}"
    )

    try:
        if payment_method == "yookassa":
            logger.info(f"💳 Проверка платежа через ЮKassa (ID: {payment_id})")
            result = await check_payment_yookassa(payment_id)
            if result:
                logger.info(f"✅ Платёж через ЮKassa (ID: {payment_id}) подтверждён.")
            else:
                logger.debug(f"⏳ Платёж через ЮKassa (ID: {payment_id}) ещё не оплачен.")
            return result

        elif payment_method == "robokassa":
            logger.info(f"💳 Проверка платежа через Robokassa (ID: {payment_id})")
            password2 = PASS2
            result = await check_payment_robokassa(payment_id, password2)
            if result == "100":
                logger.info(f"✅ Платёж через Robokassa (ID: {payment_id}) успешно оплачен (статус: {result}).")
            else:
                logger.debug(f"❌ Статус платежа Robokassa: {result} (ожидается '100')")
            return result == "100"

        elif payment_method == "yoomoney":
            logger.info(f"💳 Проверка платежа через YooMoney (ID: {payment_id})")
            result = await check_yoomoney_payment_status(payment_id)
            if result:
                logger.info(f"✅ Платёж через YooMoney (ID: {payment_id}) подтверждён.")
            else:
                logger.debug(f"⏳ Платёж через YooMoney (ID: {payment_id}) ещё не оплачен.")
            return result

        elif payment_method == "cryptobot":
            logger.info(f"💳 Проверка платежа через CryptoBot (ID: {payment_id})")
            result = await check_payment_cryptobot(payment_id)
            if result:
                logger.info(f"✅ Платёж через CryptoBot (ID: {payment_id}) подтверждён.")
            else:
                logger.debug(f"⏳ Платёж через CryptoBot (ID: {payment_id}) ещё не оплачен.")
            return result

        elif payment_method == "cloudpay":
            logger.info(f"💳 Проверка платежа через CloudPayments (ID: {payment_id})")
            result = await check_payment_cloud(payment_id)
            if result:
                logger.info(f"✅ Платёж через CloudPayments (ID: {payment_id}) подтверждён.")
            else:
                logger.debug(f"⏳ Платёж через CloudPayments (ID: {payment_id}) ещё не оплачен.")
            return result

        else:
            logger.warning(f"⚠️ Неизвестный метод оплаты при проверке: {payment_method}")
            return False

    except Exception as e:
        logger.error(
            f"❌ Ошибка при проверке статуса платежа {payment_id} (метод: {payment_method}, user_id: {user_id}): {e}",
            exc_info=True
        )
        return False


@router.callback_query(lambda query: query.data.startswith("check_payment:"), AddClient.WaitingForPayment)
async def check_payment_status(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос от пользователя для проверки статуса платежа.

    Функция проверяет статус платежа по предоставленному `payment_id` и `payment_method`. 
    Если платеж завершен, вызывается функция для обработки успешного платежа. Если платеж не 
    был завершен, пользователю выводится сообщение о необходимости повторной попытки.
    """
    user_id = callback_query.from_user.id
    logger.info(f"Пользователь {user_id} инициировал ручную проверку статуса платежа.")

    try:
        # Этап 1: Парсинг данных из callback_data
        payment_data = callback_query.data.split(":", 2)  # Ограничиваем на 3 части
        if len(payment_data) < 3:
            logger.error(f"Некорректный формат callback_data: {callback_query.data}")
            await callback_query.answer("❌ Ошибка: повреждённые данные запроса.", show_alert=True)
            return

        payment_id = payment_data[1]
        payment_method = payment_data[2]

        logger.info(
            f"Ручная проверка платежа:\n"
            f"   → user_id: {user_id}\n"
            f"   → payment_id: {payment_id}\n"
            f"   → payment_method: {payment_method}"
        )

        # Этап 2: Проверка статуса платежа
        logger.info(f"Запуск проверки статуса платежа {payment_id} через метод '{payment_method}'")
        is_paid = await handle_payment_check(callback_query, payment_id, payment_method)

        if not is_paid:
            logger.info(f"Платёж {payment_id} ещё не оплачен (метод: {payment_method})")
            await callback_query.answer("❌ Платеж не был завершен. Пожалуйста, проверьте и попробуйте снова.", show_alert=True)
            return
        else:
            logger.info(f"✅ Платёж {payment_id} успешно подтверждён через {payment_method}. Запуск обработки...")

        # Этап 3: Отмена фоновой проверки (если есть)
        task_id = f"{user_id}_{payment_id}"
        if task_id in purchase_tasks:
            task = purchase_tasks.pop(task_id)
            task.cancel()
            logger.info(f"🛑 Фоновая задача проверки платежа {task_id} была отменена вручную после успешной оплаты.")
        else:
            logger.debug(f"ℹ️ Фоновая задача для {task_id} не найдена — возможно, уже завершена или не запускалась.")

        # Этап 4: Обработка успешного платежа
        logger.info(f"Запуск обработки успешного платежа для пользователя {user_id}")
        await process_successful_payment(callback_query, state)

        # Этап 5: Подтверждение callback
        await callback_query.answer()
        logger.info(f"✅ Ручная проверка платежа завершена успешно для пользователя {user_id}")

    except Exception as e:
        logger.error(
            f"💥 Ошибка при ручной проверке платежа для пользователя {user_id}:\n"
            f"   → Ошибка: {e}\n"
            f"   → Данные callback: {callback_query.data}",
            exc_info=True  # Полная трассировка стека
        )
        try:
            await callback_query.answer("❌ Произошла ошибка при проверке платежа. Обратитесь в поддержку.", show_alert=True)
        except Exception as inner_e:
            logger.debug(f"Не удалось отправить ответ пользователю {user_id}: {inner_e}")

        
async def finalize_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Завершает процесс обработки успешного платежа и выполняет необходимые действия.

    Функция вызывает обработку успешного платежа, добавляя клиента, генерируя конфигурацию
    и выполняя другие шаги, такие как сохранение данных о платеже и пользователе в базе данных.
    """
    user_id = callback_query.from_user.id
    logger.info(
        f"🏁 Начат процесс завершения платежа:\n"
        f"   → Пользователь: {user_id}\n"
        f"   → Chat ID: {callback_query.message.chat.id}\n"
        f"   → Message ID: {callback_query.message.message_id}"
    )

    try:
        # Получаем данные из состояния для логирования контекста
        data = await state.get_data()
        payment_id = data.get('payment_id')
        payment_method = data.get('payment_method')
        final_price = data.get('final_price')
        expiry_time = data.get('expiry_time')

        logger.info(
            f"📊 Данные платежа перед обработкой:\n"
            f"   → payment_id: {payment_id}\n"
            f"   → method: {payment_method}\n"
            f"   → сумма: {final_price} RUB\n"
            f"   → срок подписки: {expiry_time} дней"
        )

        # Вызов основной функции обработки успешного платежа
        logger.info(f"🔄 Запуск process_successful_payment для пользователя {user_id}")
        await process_successful_payment(callback_query, state)

        logger.info(f"✅ Платёж для пользователя {user_id} успешно завершён и обработан.")

    except Exception as e:
        logger.error(
            f"💥 Ошибка при завершении платежа для пользователя {user_id}:\n"
            f"   → Ошибка: {e}",
            exc_info=True
        )
        try:
            await callback_query.message.answer(
                "❌ Произошла ошибка при завершении оплаты. Обратитесь в поддержку."
            )
        except Exception as send_error:
            logger.debug(f"Не удалось отправить сообщение об ошибке пользователю {user_id}: {send_error}")
    
    
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
