import aiosqlite
import uuid
from aiogram import types, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton
from aiogram.enums.parse_mode import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup
from aiogram.filters.command import Command
from datetime import datetime
from log import logger
from dotenv import load_dotenv
import os
from admin.notify import notify_admins, notify_referral_chat
from bot import bot
from client.info import show_instructions, show_prices, show_server_info, show_router_instructions
from client.pers_account import process_email_for_all_servers
from client.menu import get_main_menu, main_menu
from db.db import get_emails_from_database, get_user_referral_code, increment_referral_clicks
from client.add_client import start_add_client
from client.referral import referral_info
from buttons.client import BUTTON_TEXTS
from client.menu import get_cabinet_menu
from pay.prices import get_test_menu
from pay.prices import get_subscription_one
from pay.prices import get_subscription_one_device
from pay.prices import get_subscription_one_ios
from pay.prices import get_subscription_one_android
from pay.prices import get_subscription_one_macos
from pay.prices import get_subscription_one_windows
from pay.prices import get_trial_device
from pay.prices import get_trial_ios
from pay.prices import get_trial_android
from pay.prices import get_trial_macos
from pay.prices import get_trial_windows
from client.menu import get_instructions_menu
#from client.text import MENU_TEXT
load_dotenv()

router = Router()
USERSDATABASE = os.getenv("USERSDATABASE")


async def delete_previous_message(chat_id: int, message_id: int):
    """    
    Удаляет предыдущее сообщение. при нажатии на кнопки.
    """
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")


async def handle_user_registration(
    conn: aiosqlite.Connection,  # Добавлен параметр соединения
    telegram_id: int, 
    username: str, 
    telegram_link: str, 
    referral_code: str, 
    referred_by_code: str, 
    entry_date: str
):
    """
    Регистрирует пользователя в базе данных.
    :param conn: Активное соединение с базой данных
    :param referred_by_code: реферальный код пригласившего (например, из ссылки)
    """
    async with conn.cursor() as cursor:
        # Проверка существования пользователя
        await cursor.execute(
            "SELECT referral_code, referred_by, referrer_code FROM users WHERE telegram_id = ?", 
            (telegram_id,)
        )
        user_data = await cursor.fetchone()

        if user_data:
            # Обновляем данные существующего пользователя
            await cursor.execute(
                """UPDATE users 
                SET username = ?, 
                    telegram_link = ?,
                    entry_date = ?
                WHERE telegram_id = ?""", 
                (username, telegram_link, entry_date, telegram_id)
            )
        else:
            # Получаем данные пригласившего по его реферальному коду
            referrer_id = None
            if referred_by_code:
                await cursor.execute(
                    "SELECT telegram_id FROM users WHERE referral_code = ?", 
                    (referred_by_code,)
                )
                result = await cursor.fetchone()
                referrer_id = result[0] if result else None

            # Вставка нового пользователя
            await cursor.execute(
                """INSERT INTO users 
                (telegram_id, username, telegram_link, referral_code, referral_count, referred_by, referrer_code, entry_date)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)""",
                (telegram_id, username, telegram_link, referral_code, referrer_id, referred_by_code, entry_date)
            )

            # Если пользователь пришел по реферальной ссылке, сохраняем связь в referral_links
            if referred_by_code:
                await cursor.execute(
                    """INSERT INTO referral_links 
                    (referrer_code, invited_user_id) 
                    VALUES (?, ?)""",
                    (referred_by_code, telegram_id)
                )
            
            await notify_admins(telegram_id, referral_code, username, telegram_link)

            # 🔔 Если пришёл от eb1a1788 — отправляем в дополнительный чат
            if referred_by_code == "eb1a1788":
                await notify_referral_chat(telegram_id, username, telegram_link)

        await conn.commit()

@router.message(Command("start"))
async def start(message: types.Message):
    telegram_id = message.from_user.id
    logger.info(f"Пользователь {telegram_id} нажал /start")

    try:
        await delete_previous_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    referred_by_code = None
    if message.text.startswith("/start"):
        parts = message.text.split()
        if len(parts) > 1:
            referred_by_code = parts[1]

    async with aiosqlite.connect("users.db", timeout=30) as conn:
        if referred_by_code:
            await increment_referral_clicks(referred_by_code, conn)
            
            cursor = await conn.execute(
                "SELECT 1 FROM referral_links WHERE invited_user_id = ?",
                (telegram_id,)
            )
            if not await cursor.fetchone():
                await conn.execute(
                    "INSERT INTO referral_links (referrer_code, invited_user_id) VALUES (?, ?)",
                    (referred_by_code, telegram_id)
                )
                await conn.commit()

        # Регистрация/обновление пользователя
        user_referral_code = await get_user_referral_code(telegram_id, conn) or str(uuid.uuid4())[:8]
        username = message.from_user.first_name or "Без имени"
        telegram_link = f"https://t.me/{message.from_user.username}" if message.from_user.username else None
        entry_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            await handle_user_registration(
                conn=conn,  # Передаем соединение
                telegram_id=telegram_id,
                username=username,
                telegram_link=telegram_link,
                referral_code=user_referral_code,
                referred_by_code=referred_by_code,
                entry_date=entry_date
            )
        except Exception as e:
            logger.error(f"Ошибка при регистрации пользователя: {e}")

    await main_menu(message)

@router.callback_query(lambda c: c.data == "main_menu")
async def handle_main_menu(callback_query: types.CallbackQuery):
    """
    Отменяет действие и возвращает в главное меню.
    """
    user = callback_query.from_user
    name = user.first_name or "друг"

    text = (
        f"Привет, {name}!\n\n"
        "Готов пользоваться VPN без лишних заморочек?\n\n"
    )

    await callback_query.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=get_main_menu(callback_query)
    )
    await callback_query.answer()



@router.callback_query(lambda query: query.data == "cancel")
async def cancel_action(callback_query: types.CallbackQuery, state: FSMContext):
    """Отмена действия и возврат в главное меню."""
    data = await state.get_data()
    sent_message_id = data.get('sent_message_id')
    try:
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
    except Exception as e:
        logger.error(f"Ошибка при отмене действия: {e}")
        await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text="Не удалось отменить покупку. Выберите действие:",
            reply_markup=get_main_menu(callback_query)
        )
    await state.clear()
    await callback_query.answer()


@router.callback_query(lambda c: c.data == "cabinet")
async def handle_get_config(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на вход в личный кабинет.
    """
    telegram_id = callback_query.from_user.id
    emails = await get_emails_from_database(telegram_id)
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["extend_subscription_subscr"], callback_data="buy_vpn"))
    keyboard.add(InlineKeyboardButton(text=BUTTON_TEXTS["previous"], callback_data="main_menu"))

    if emails:
        all_responses = []
        for email in emails:
            response = await process_email_for_all_servers(callback_query, email)
            if response:
                all_responses.append(response)
        full_response = "\n\n".join(all_responses)

        if full_response:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                text=full_response,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard.as_markup()
            )
        else:
            await bot.edit_message_text(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                text="❌ Не удалось найти активные конфигурации.",
                reply_markup=keyboard.as_markup()
            )
    else:
        await bot.edit_message_text(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            text="❌ Не удалось найти ваши конфигурации.",
            reply_markup=keyboard.as_markup()
        )


@router.callback_query(lambda c: c.data == "prices")
async def handle_prices(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение цен.
    """
    await show_prices(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "instructions")
async def handle_server_info(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение клавиатуры с 3 кнопками.
    """

    await callback_query.message.edit_text(
        text="Выберите операционную систему для получения 📖 инструкций:",
        reply_markup=get_instructions_menu()
    )

# Обработчики для каждой из кнопок
@router.callback_query(lambda c: c.data == "ios_instructions")
async def handle_ios_instructions(callback_query: types.CallbackQuery):
    await show_instructions(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "android_instructions")
async def handle_android_instructions(callback_query: types.CallbackQuery):
    await show_instructions(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "macos_instructions")
async def handle_macos_instructions(callback_query: types.CallbackQuery):
    await show_instructions(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "windows_instructions")
async def handle_windows_instructions(callback_query: types.CallbackQuery):
    await show_instructions(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "about_server")
async def handle_server_info(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение информации о сервере.
    """
    await show_server_info(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "setings_router")
async def handle_setings_router(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение информации о настройке роутера.
    """
    await show_router_instructions(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "advantages")
async def handle_advantages(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение информации о преимуществах.
    """
    await show_router_instructions(callback_query)
    await callback_query.answer()

@router.callback_query(lambda c: c.data == "buy_vpn")
async def handle_buy_vpn(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос на покупку VPN.
    """
    await start_add_client(callback_query, state)
    await callback_query.answer()


@router.callback_query(lambda c: c.data == "referal")
async def referal(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос на отображение реферальной информации.
    """
    try:
        await referral_info(callback_query, bot, state)
    except Exception as e:
        logger.error(f"Ошибка в обработчике рефералов: {e}")


@router.callback_query(lambda c: c.data == "get_cabinet")
async def cabinet_menu(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text="📄 Личный кабинет. Выберите действие:",
        reply_markup=get_cabinet_menu()
    )

@router.callback_query(lambda c: c.data == "pay_menu")
async def test_menu(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text="💳 Приобрести подписку",
        reply_markup=get_test_menu()
    )

@router.callback_query(lambda c: c.data == "one_m_menu")
async def subscription_one(callback_query: types.CallbackQuery):
    text, markup = get_subscription_one()
    
    await callback_query.message.edit_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )



@router.callback_query(lambda c: c.data == "one_m_device")
async def subscription_one_device(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("<b>Какое у вас устройство?</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_one_device()
    )

@router.callback_query(lambda c: c.data == "one_m_ios")
async def subscription_one_ios(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>v2RayTun</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_one_ios()
    )

@router.callback_query(lambda c: c.data == "one_m_android")
async def subscription_one_android(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>v2RayTun</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_one_android()
    )

@router.callback_query(lambda c: c.data == "one_m_macos")
async def subscription_one_macos(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>v2RayTun</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_one_macos()
    )

@router.callback_query(lambda c: c.data == "one_m_windows")
async def subscription_one_windows(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>Karing</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_one_windows()
    )

"""меню для пробной подписки"""

@router.callback_query(lambda c: c.data == "trial_device")
async def trial_one_device(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("<b>Какое у вас устройство?</b>"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_trial_device()
    )

@router.callback_query(lambda c: c.data == "trial_ios")
async def subscription_one_ios(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>v2RayTun</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_trial_ios()
    )

@router.callback_query(lambda c: c.data == "trial_android")
async def trial_android(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>v2RayTun</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_trial_android()
    )

@router.callback_query(lambda c: c.data == "trial_macos")
async def trial_macos(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>v2RayTun</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_trial_macos()
    )

@router.callback_query(lambda c: c.data == "trial_windows")
async def trial_windows(callback_query: types.CallbackQuery):
    """
    Обрабатывает запрос на отображение личного кабинета пользователя.
    """
    await callback_query.message.edit_text(
        text=("Для наших ключей мы используем приложение <b>Karing</b>, которое вы можете скачать по кнопке ниже👇"),
        parse_mode=ParseMode.HTML,
        reply_markup=get_trial_windows()
    )

"""end меню для пробной подписки"""
