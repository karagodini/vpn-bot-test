"""
Модуль для управления административными функциями бота в Telegram, включая:
- Панель администратора с различными функциями (рассылка сообщений, работа с промокодами, статистика).
- Обработчики команд и запросов от администраторов для выполнения задач, таких как создание и удаление промокодов, удаление клиентов, резервное копирование данных и перезапуск бота.
- Обработка рассылки сообщений всем пользователям бота, включая текст, изображения, документы и другие виды контента.
- Функции для создания резервных копий базы данных и отправки их администраторам.
- Функции для работы с промокодами: добавление, удаление и отображение активных промокодов.
- Взаимодействие с базой данных для выполнения операций с пользователями и промокодами.
- Реализация состояния для контроля процесса рассылки и работы с промокодами через FSM (Finite State Machine) в библиотеке aiogram.

Основные компоненты:
1. Панель администратора, доступная только для пользователей с правами администратора.
2. Механизм рассылки сообщений и файлов всем пользователям.
3. Функции для добавления и удаления промокодов с возможностью подтверждения операций через inline-кнопки.
4. Статистика по пользователям и рефералам.
5. Перезагрузка бота и создание резервных копий базы данных.
"""

import sqlite3, asyncio, os, shutil, aiosqlite
from datetime import datetime
from aiogram import types
import io
import pandas as pd
from aiogram.enums.parse_mode import ParseMode
from aiogram.types import InlineKeyboardButton
from aiogram.types import CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime
from db.db import Database, get_server_ids_as_list
from aiogram.types.input_file import FSInputFile
from aiogram import Router, F
from aiogram.types import ContentType, Message
from aiogram.fsm.state import State, StatesGroup
import random
import string
import logging
import aiohttp
import json
from db.db import get_referral_info_by_code
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)

from log import logger
from admin.delete_clients import get_inactive_clients, delete_depleted_clients
from bot import bot
from client.add_client import login
from handlers.config import get_server_data
from admin.sub_check import scheduled_check_subscriptions, get_server_ids_as_list_for_days_left
from handlers.states import BroadcastState, AddPromoCodeState, ManagePromoCodeState, ManageServerGroupState
from buttons.admin import BUTTON_TEXTS
from admin.delete_clients import scheduled_delete_clients
from dotenv import load_dotenv
import os

load_dotenv()
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
USERSDATABASE = os.getenv("USERSDATABASE")
SERVEDATABASE = os.getenv("SERVEDATABASE")
DATABASE_PATH = os.getenv("DATABASE_PATH")
BACKUP_DIR = os.getenv("BACKUP_DIR")
router = Router()

@router.message(Command("get_chat_id"))
async def get_chat_id(message: types.Message):
    chat_id = message.chat.id
    await message.answer(f"Chat ID этого чата: `{chat_id}`", parse_mode="Markdown")

@router.callback_query(lambda query: query.data == "cancel_admin")
async def cancel_action(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик для отмены действий в административной панели."""
    data = await state.get_data()
    sent_message_id = data.get('sent_message_id')

    cancel_message = await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=sent_message_id,
        text="❌ Действие отменено."
    )
    
    await asyncio.sleep(0.5)
    await bot.delete_message(
        chat_id=callback_query.message.chat.id,
        message_id=cancel_message.message_id
    )

    await state.clear()
    await callback_query.answer()

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Панель администратора"""
    await message.delete()

    user_id = message.from_user.id
    username = message.from_user.username or "(без имени пользователя)"

    if user_id not in ADMIN_IDS:
        logger.warning(f"Попытка доступа к панели администратора: User ID: {user_id}, Username: {username}")
        return await message.answer("❌ У вас нет доступа к административной панели.")

    logger.info(f"Администратор {username} (ID: {user_id}) открыл панель администратора.")

    keyboard = ReplyKeyboardBuilder()
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["broadcast"]),
        types.KeyboardButton(text=BUTTON_TEXTS["send_message"])
    )
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["add_promo_code"]),
        types.KeyboardButton(text=BUTTON_TEXTS["delete_promo_code"])
    )
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["delete_clients"])
    )
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["top_referrers"]),
        types.KeyboardButton(text=BUTTON_TEXTS["statistics"])
    )
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["work_with_servers"]),
        types.KeyboardButton(text=BUTTON_TEXTS["referrals"])
    )
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["days_sub"]),
        types.KeyboardButton(text=BUTTON_TEXTS["edit_users"])
    )
    keyboard.row(
        types.KeyboardButton(text=BUTTON_TEXTS["backup"]),
        types.KeyboardButton(text=BUTTON_TEXTS["restart_bot"])
    )
    await message.answer(
        "**Панель администратора**\n\n",
        reply_markup=keyboard.as_markup(resize_keyboard=True),
        parse_mode="Markdown"
    )

@router.message(Command("referal"))
async def referal_command(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ У вас нет доступа к этой команде.")

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="📊 Выгрузить рефералов в Excel",
            callback_data="export_referrals"
        )]
    ])

    await message.answer(
        "Админ-панель рефералов:\n\nНажмите кнопку ниже для выгрузки таблицы.",
        reply_markup=keyboard
    )




@router.callback_query(lambda c: c.data == "export_referrals")
async def export_referrals_handler(callback_query: types.CallbackQuery):
    await callback_query.answer("⏳ Подготовка файла...", show_alert=False)

    try:
        async with aiosqlite.connect("users.db") as conn:
            cursor = await conn.execute("SELECT id, telegram_user FROM referal_tables")
            rows = await cursor.fetchall()

        if not rows:
            return await callback_query.message.answer("❌ В таблице нет данных для выгрузки.")

        df = pd.DataFrame(rows, columns=["ID", "Telegram User"])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Referrals')
        output.seek(0)

        file = BufferedInputFile(output.read(), filename="referal_tables.xlsx")
        await callback_query.message.answer_document(file)

    except Exception as e:
        await callback_query.message.answer(f"Ошибка при экспорте: {e}")






class BroadcastState(StatesGroup):
    waiting_for_message = State()
    waiting_for_audience = State()  # Новое состояние для выбора аудитории

@router.message(F.text == BUTTON_TEXTS["send_message"])
async def start_broadcast(message: Message, state: FSMContext):
    """Начало процесса рассылки с выбором аудитории"""
    await message.delete()

    if message.chat.id not in ADMIN_IDS:
        await message.answer("❌ У тебя нет прав для выполнения этой команды.")
        return

    # Создаем клавиатуру для выбора аудитории
    audience_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Пробная подписка", callback_data="broadcast_audience:trial"),
            InlineKeyboardButton(text="Оплаченная подписка", callback_data="broadcast_audience:paid")
        ],
        [
            InlineKeyboardButton(text="Без подписки", callback_data="broadcast_audience:no_sub"),
            InlineKeyboardButton(text="Все пользователи", callback_data="broadcast_audience:all")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")
        ]
    ])

    sent_message = await message.answer(
        "Выберите целевую аудиторию для рассылки:",
        reply_markup=audience_keyboard
    )
    
    await state.update_data(sent_message_id=sent_message.message_id, chat_id=sent_message.chat.id)
    await state.set_state(BroadcastState.waiting_for_audience)

@router.callback_query(BroadcastState.waiting_for_audience, F.data.startswith("broadcast_audience:"))
async def select_audience(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора аудитории"""
    audience_type = callback.data.split(":")[1]
    await state.update_data(audience_type=audience_type)
    
    cancel_button = InlineKeyboardBuilder()
    cancel_button.add(
        InlineKeyboardButton(
            text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin"
        )
    )

    await callback.message.edit_text(
        "Пожалуйста, отправьте сообщение или файл для рассылки:",
        reply_markup=cancel_button.as_markup()
    )
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.answer()

@router.message(F.content_type.in_({'text', 'photo', 'document', 'video', 'audio'}), BroadcastState.waiting_for_message)
async def universe_broadcast(message: Message, state: FSMContext):
    """Рассылка сообщений выбранной аудитории"""
    data = await state.get_data()
    audience_type = data.get("audience_type", "all")
    
    # Формируем SQL запрос в зависимости от выбранной аудитории
    if audience_type == "trial":
        query = "SELECT telegram_id FROM users WHERE has_trial = 1"
    elif audience_type == "paid":
        query = "SELECT telegram_id FROM users WHERE sum_my > 0"
    elif audience_type == "no_sub":
        query = "SELECT telegram_id FROM users WHERE has_trial = 0 AND sum_my = 0"
    else:  # all
        query = "SELECT telegram_id FROM users"

    async with aiosqlite.connect(USERSDATABASE) as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(query)
            users_data = await cursor.fetchall()

    content_type = message.content_type

    if content_type == ContentType.TEXT and message.text == '❌ Отмена':
        await state.clear()
        await message.answer('Рассылка отменена!')
        return

    await state.clear()
    
    audience_name = {
        "trial": "пользователям с пробной подпиской",
        "paid": "пользователям с оплаченной подпиской",
        "no_sub": "пользователям без подписки",
        "all": "всем пользователям"
    }.get(audience_type, "всем пользователям")
    
    await message.answer(f'Начинаю рассылку ({audience_name}) на {len(users_data)} пользователей.')

    good_send, bad_send = await broadcast_message(
        users_data=users_data,
        text=message.text if content_type == ContentType.TEXT else None,
        photo_id=message.photo[-1].file_id if content_type == ContentType.PHOTO else None,
        document_id=message.document.file_id if content_type == ContentType.DOCUMENT else None,
        video_id=message.video.file_id if content_type == ContentType.VIDEO else None,
        audio_id=message.audio.file_id if content_type == ContentType.AUDIO else None,
        caption=message.caption,
        content_type=content_type
    )

    def pluralize_users(count):
        if 11 <= count % 100 <= 19:
            return "пользователей"
        if count % 10 == 1:
            return "пользователь"
        if 2 <= count % 10 <= 4:
            return "пользователя"
        return "пользователей"

    await message.answer(
        f"Рассылка ({audience_name}) завершена.\n"
        f"Сообщение получило: <b>{good_send}</b> {pluralize_users(good_send)}.\n"
        f"Не получили: <b>{bad_send}</b> {pluralize_users(bad_send)}.",
        parse_mode="HTML"
    )


async def broadcast_message(users_data, text=None, photo_id=None, document_id=None, video_id=None, audio_id=None, caption=None, content_type=None):
    """
    Функция для рассылки сообщений с учетом типа контента.
    """
    successful, failed = 0, 0

    for user in users_data:
        user_id = user[0]
        try:
            if content_type == ContentType.TEXT:
                await bot.send_message(user_id, text)
            elif content_type == ContentType.PHOTO:
                await bot.send_photo(user_id, photo_id, caption=caption)
            elif content_type == ContentType.DOCUMENT:
                await bot.send_document(user_id, document_id, caption=caption)
            elif content_type == ContentType.VIDEO:
                await bot.send_video(user_id, video_id, caption=caption)
            elif content_type == ContentType.AUDIO:
                await bot.send_audio(user_id, audio_id, caption=caption)

            successful += 1
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
            failed += 1

    return successful, failed

@router.message(F.text == BUTTON_TEXTS["broadcast"])
async def check_subscription_command(message: types.Message):
    """Проверяет подписки всех пользователей и уведомляет их о необходимости продлить подписку."""
    await message.delete()
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У тебя нет прав для выполнения этой команды.")
        return
    await scheduled_check_subscriptions()
    await message.answer("Проверка подписок завершена.")


@router.message(F.text == BUTTON_TEXTS["statistics"])
@router.message(Command("stats"))
async def show_statistics(message: types.Message):
    """Показывает статистику по пользователям и конкретному пользователю, если передан ID."""
    await message.delete()

    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой функции.")
        return

    # Получаем аргументы команды (/stats <telegram_id>)
    args = message.text.split()
    user_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()

    if user_id:
        cursor.execute(
            """
            SELECT telegram_link, telegram_id, referral_count, sum_my, sum_ref, entry_date
            FROM users WHERE telegram_id = ?
            """,
            (user_id,)
        )
        user_data = cursor.fetchone()

        if user_data:
            telegram_link, telegram_id, referral_count, sum_my, sum_ref, entry_date = user_data
            user_stats_text = (
                f"📊 <b>Статистика пользователя</b>\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Ссылка на телеграм:</b> {telegram_link or 'N/A'}\n"
                f"🆔 <b>Telegram ID:</b> <code>{telegram_id}</code>\n"
                f"🗓 <b>Последний вход:</b> {entry_date or 'N/A'}\n\n"
                f"👥 <b>Рефералов:</b> {referral_count}\n"
                f"💰 <b>Потратил сам:</b> {sum_my or 0} ₽\n"
                f"💸 <b>Рефералы потратили:</b> {sum_ref or 0} ₽\n"
            )
            await message.answer(user_stats_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        else:
            await message.answer("⚠️ Пользователь не найден в базе.")

    else:
        # Общие статистики
        cursor.execute("SELECT COUNT(*) FROM users")
        total_bot_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE sum_my != 0")
        total_bot_userssum = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM user_emails")
        total_clients = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE has_trial = 1")
        users_with_trial = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE has_trial = 0 OR sum_my = 0")
        users_bez_podpiski = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE promo_code_usage > 0")
        users_with_promo = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(referral_count) FROM users")
        total_referrals = cursor.fetchone()[0] or 0

        cursor.execute("SELECT MIN(entry_date), MAX(entry_date) FROM users")
        first_user_date, last_user_date = cursor.fetchone()

        # Формируем основную часть статистики
        stats_text = (
            "📊 <b>Общая статистика</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 <b>Всего пользователей бота:</b> {total_bot_users}\n"
            f"👥 <b>Всего клиентов (подписок):</b> {total_bot_users}\n"
            f"🎁 <b>Пробные подписки:</b> {users_with_trial}\n"
            f"👥 <b>Оплаченые подписки:</b> {total_bot_userssum}\n"
            f"👥 <b>Без подписки:</b> {users_bez_podpiski}\n"
            f"🏷 <b>Пользователей с промокодами:</b> {users_with_promo}\n\n"
            f"👥 <b>Общее количество рефералов:</b> {total_referrals}\n"
            f"📈 <b>Среднее рефералов на пользователя:</b> {total_referrals / total_bot_users if total_bot_users else 0:.2f}\n"
            f"🗓 <b>Первый пользователь:</b> {first_user_date or 'N/A'}\n"
            f"🗓 <b>Последний пользователь:</b> {last_user_date or 'N/A'}\n\n"
        )

        # Отправляем итоговое сообщение
        await message.answer(stats_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    # Закрываем соединение
    cursor.close()
    conn.close()


@router.message(F.text == BUTTON_TEXTS["top_referrers"])
@router.message(Command("top"))
async def show_top_referrers(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} запросил топ рефоводов")

    # Проверка, является ли пользователь админом
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой функции.")
        return

    await message.delete()

    # Проверка существования файла БД
    if not os.path.exists(USERSDATABASE):
        logger.error("Файл базы данных не найден")
        await message.answer("⚠️ Файл базы данных не найден.")
        return

    try:
        conn = sqlite3.connect(USERSDATABASE)
        cursor = conn.cursor()
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        await message.answer("⚠️ Не удалось подключиться к базе данных.")
        return

    try:
        # Проверка, существует ли таблица users
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        if not cursor.fetchone():
            await message.answer("⚠️ Таблица 'users' не найдена.")
            return

        # Запрос топ-100 рефоводов
        cursor.execute("""
            SELECT 
                telegram_link, 
                telegram_id, 
                referral_count, 
                sum_my, 
                sum_ref 
            FROM users 
            WHERE referral_count > 0 
            ORDER BY referral_count DESC 
            LIMIT 100
        """)
        top_referrers = cursor.fetchall()

        if not top_referrers:
            await message.answer("🤷‍♂️ Пока нет ни одного рефовода.")
            return

        # Формируем сообщение
        text = "🏆 <b>Топ-100 рефоводов</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━\n"

        for i, (telegram_link, telegram_id, referral_count, sum_my, sum_ref) in enumerate(top_referrers, 1):
            link = telegram_link or f"<a href='tg://user?id={telegram_id}'>Пользователь {i}</a>"
            sum_my_display = sum_my or 0
            sum_ref_display = sum_ref or 0
            text += (
                f"{i}. {link} (<code>{telegram_id}</code>) — "
                f"{referral_count} реф., "
                f"потратил {sum_my_display} ₽, "
                f"рефералы — {sum_ref_display} ₽\n"
            )

        await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        logger.info(f"Отправлен топ-100 рефоводов (найдено: {len(top_referrers)})")

    except Exception as e:
        logger.error(f"Ошибка при выводе топа рефоводов: {e}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при получении топа рефоводов.")

    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass


@router.message(F.text == BUTTON_TEXTS["delete_clients"])
async def cmd_delete_clients(message: types.Message):
    await message.delete()
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У тебя нет прав для выполнения этой команды.")
        return

    await message.answer("🔄 Начинаем удаление отключенных клиентов...")

    server_ids = await get_server_ids_as_list(SERVEDATABASE)
    results = []

    for server_selection in server_ids:
        server_data = await get_server_data(server_selection)
        
        if not server_data:
            results.append(f"❌ Неверный выбор сервера: {server_selection}.")
            continue

        try:
            session_id = await login(server_data['login_url'], {
                "username": server_data['username'],
                "password": server_data['password']
            })

            inactive_clients = await get_inactive_clients(server_data['list_clients_url'], session_id)
            results.append(f"Сервер {server_data['name']}:\n{inactive_clients}")
            await scheduled_delete_clients()
            deleted_clients = await delete_depleted_clients(server_data['delete_depleted_clients_url'], session_id)
            results.append(f"Сервер {server_data['name']}: {deleted_clients}")
        except Exception as e:
            results.append(f"❌ Ошибка при удалении клиентов на сервере {server_data['name']}: {str(e)}")

    await message.answer("\n".join(results))


@router.message(F.text == BUTTON_TEXTS["restart_bot"])
async def restart_bot(message: types.Message):
    """Перезапуск бота."""
    await message.delete()
    await message.answer(
        "🔄 Перезапускаю бота...\n"
        "⏳ Пожалуйста, подождите...",
        parse_mode=ParseMode.HTML
    )

    restart_command = ['sudo', 'systemctl', 'restart', 'bot.service']

    await asyncio.create_subprocess_exec(
        *restart_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )


@router.message(F.text == BUTTON_TEXTS["backup"])
async def create_backup(message: types.Message):
    """Создает бекап базы данных и отправляет его админу."""
    await message.delete()
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды.")
        return

    backup_filename = f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        shutil.copy(DATABASE_PATH, backup_path)
        logger.info(f"Бекап базы данных создан: {backup_path}")
        await message.answer_document(
            document=FSInputFile(backup_path),
            caption=f"💾 Резервная копия базы данных: `{backup_filename}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при создании бекапа: {e}", exc_info=True)
        await message.answer("❌ Ошибка при создании бекапа базы данных. Попробуйте позже.")
    finally:
        if os.path.exists(backup_path):
            os.remove(backup_path)
            logger.info(f"Временный файл бекапа удален: {backup_path}")
            

class AddPromoCodeState(StatesGroup):
    WaitingForCode = State()
    WaitingForDiscount = State()
    WaitingForDays = State()  # Новое состояние для ввода дней

@router.message(F.text == BUTTON_TEXTS["add_promo_code"])
async def start_adding_promo_code(message: types.Message, state: FSMContext):
    """Начинает процесс добавления нового промокода, отображая список активных промокодов."""
    await message.delete()
    try:
        db = Database(USERSDATABASE) 
        db.cursor.execute('''SELECT code, discount, days FROM promo_codes WHERE is_active = 1''')
        promo_codes = db.cursor.fetchall()

        keyboard = InlineKeyboardBuilder()
        keyboard.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_admin")
        )

        if promo_codes:
            promo_codes_list = "\n".join(
                [f"🤑 Промокод: {promo_code[0]} - Скидка: {promo_code[1]}% - Дней: {promo_code[2]}" 
                 for promo_code in promo_codes]
            )
            sent_message = await message.answer(
                f"Существующие промокоды:\n{promo_codes_list}\n\nВведите уникальный промокод:",
                reply_markup=keyboard.adjust(1).as_markup()
            )
        else:
            sent_message = await message.answer(
                "Нет активных промокодов. Введите уникальный промокод:",
                reply_markup=keyboard.adjust(1).as_markup()
            )

        await state.set_state(AddPromoCodeState.WaitingForCode)
        await state.update_data(sent_message_id=sent_message.message_id, chat_id=sent_message.chat.id)

    except Exception as e:
        await message.answer(f"❌ Ошибка при получении промокодов: {e}")

@router.message(AddPromoCodeState.WaitingForCode)
async def process_promo_code(message: types.Message, state: FSMContext):
    """Обрабатывает введённый промокод и запрашивает процент скидки."""
    promo_code = message.text.strip()
    if not promo_code:
        await message.answer("Промокод не может быть пустым. Попробуйте еще раз.")
        return
        
    await state.update_data(promo_code=promo_code)
    await message.answer("Введите процент скидки (например, 10 для 10%):")
    await state.set_state(AddPromoCodeState.WaitingForDiscount)

@router.message(AddPromoCodeState.WaitingForDiscount)
async def process_discount(message: types.Message, state: FSMContext):
    """Обрабатывает введённую скидку и запрашивает количество дней."""
    try:
        discount = int(message.text)
        if not (0 < discount <= 100):
            raise ValueError("Скидка должна быть от 1 до 100")
            
        await state.update_data(discount=discount)
        await message.answer("Введите количество дней действия подписки:")
        await state.set_state(AddPromoCodeState.WaitingForDays)
        
    except ValueError:
        await message.answer("Введите корректный процент скидки (целое число от 1 до 100).")

@router.message(AddPromoCodeState.WaitingForDays)
async def process_days(message: types.Message, state: FSMContext):
    """Обрабатывает введённое количество дней и сохраняет промокод."""
    try:
        days = int(message.text)
        if days <= 0:
            raise ValueError("Количество дней должно быть положительным числом")
            
        data = await state.get_data()
        promo_code = data["promo_code"]
        discount = data["discount"]

        try:
            db = Database(USERSDATABASE)
            # Обновляем структуру таблицы, если нужно
            try:
                db.cursor.execute("ALTER TABLE promo_codes ADD COLUMN days INTEGER DEFAULT 30")
            except sqlite3.OperationalError:
                pass  # Колонка уже существует
                
            db.cursor.execute('''
                INSERT INTO promo_codes (code, discount, days, is_active)
                VALUES (?, ?, ?, 1)
            ''', (promo_code, discount, days))
            db.connection.commit()
            
            await message.answer(
                f"✅ Промокод '{promo_code}' добавлен успешно!\n"
                f"Скидка: {discount}%\n"
                f"Дней подписки: {days}"
            )
        except sqlite3.IntegrityError:
            await message.answer(f"❌ Промокод '{promo_code}' уже существует!")
        except Exception as e:
            await message.answer(f"❌ Ошибка при добавлении промокода: {e}")
        finally:
            await state.clear()

    except ValueError:
        await message.answer("Введите корректное количество дней (целое положительное число).")

@router.message(F.text == BUTTON_TEXTS["delete_promo_code"])
async def start_deleting_promo_code(message: types.Message):
    """Начинает процесс удаления промокода, отображая список активных промокодов."""
    await message.delete()
    try:
        db = Database(USERSDATABASE)
        db.cursor.execute('''SELECT code, discount FROM promo_codes WHERE is_active = 1''')
        promo_codes = db.cursor.fetchall()

        if promo_codes:
            keyboard = InlineKeyboardBuilder()
            for promo_code in promo_codes:
                keyboard.add(
                    InlineKeyboardButton(
                        text=f"🤑 {promo_code[0]} - {promo_code[1]}%",
                        callback_data=f"delete_{promo_code[0]}"
                    )
                )
            await message.answer("Выберите промокод для удаления:", reply_markup=keyboard.adjust(1).as_markup())
        else:
            await message.answer("❌ Нет активных промокодов для удаления.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении списка промокодов: {e}")


@router.callback_query(lambda c: c.data.startswith("delete_"))
async def confirm_delete_promo_code(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает подтверждение удаления выбранного промокода."""
    promo_code = callback_query.data.split("_")[1]
    await state.update_data(promo_code_to_delete=promo_code)

    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text=BUTTON_TEXTS["confirm_delete"], callback_data="confirm_delete"),
        InlineKeyboardButton(text=BUTTON_TEXTS["no_delete"], callback_data="cancel_admin")
    )

    sent_message = await callback_query.message.edit_text(
        f"Вы уверены, что хотите удалить промокод '{promo_code}'?",
        reply_markup=keyboard.adjust(2).as_markup()
    )
    await state.update_data(sent_message_id=sent_message.message_id, chat_id=callback_query.message.chat.id)
    await state.set_state(ManagePromoCodeState.WaitingForDeleteConfirmation)


@router.callback_query(lambda c: c.data == "confirm_delete")
async def delete_promo_code(callback_query: types.CallbackQuery, state: FSMContext):
    """Удаляет выбранный промокод из базы данных после подтверждения."""
    await state.set_state(ManagePromoCodeState.WaitingForDeleteConfirmation)

    data = await state.get_data()
    promo_code_to_delete = data.get("promo_code_to_delete")
    try:
        db = Database(USERSDATABASE)
        db.cursor.execute('''
            DELETE FROM promo_codes
            WHERE code = ?
        ''', (promo_code_to_delete,))
        db.connection.commit()
        await callback_query.message.edit_text(f"✅ Промокод '{promo_code_to_delete}' успешно удалён!")
    except Exception as e:
        await callback_query.message.edit_text(f"❌ Ошибка при удалении промокода: {e}")
    finally:
        await state.clear()
   
        
@router.message(Command("reset_ref"))
async def reset_referral_sum(message: types.Message):
    """Обнуляет сумму потраченных рефералами (sum_ref) у конкретного пользователя."""
    await message.delete()

    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой функции.")
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("⚠️ Укажите Telegram ID пользователя. Пример:\n<code>/reset_ref 123456789</code>", parse_mode=ParseMode.HTML)
        return

    user_id = int(args[1])

    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_link, sum_ref FROM users WHERE telegram_id = ?", (user_id,))
    user_data = cursor.fetchone()

    if not user_data:
        await message.answer("⚠️ Пользователь не найден в базе.")
    else:
        telegram_link, sum_ref = user_data
        cursor.execute("UPDATE users SET sum_ref = 0 WHERE telegram_id = ?", (user_id,))
        conn.commit()

        await message.answer(
            f"✅ <b>Обнулена реферальная сумма</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Пользователь:</b> {telegram_link or 'N/A'} (<code>{user_id}</code>)\n"
            f"💸 <b>Было списано:</b> {sum_ref or 0} ₽",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

    cursor.close()
    conn.close()
    
    
@router.callback_query(lambda c: c.data == "cluster_delete")
async def start_deleting_server_group(callback_query: types.CallbackQuery):
    """Начинает процесс удаления группы серверов, отображая список групп."""
    await callback_query.message.delete()

    db = Database(SERVEDATABASE)
    try:
        db.cursor.execute('SELECT group_name FROM server_groups')
        server_groups = db.cursor.fetchall()
        db.connection.close()

        if server_groups:
            keyboard = InlineKeyboardBuilder()
            for group in server_groups:
                keyboard.add(
                    InlineKeyboardButton(
                        text=f"🗂 {group[0]}",
                        callback_data=f"cluster_delete_{group[0]}"
                    )
                )
            await callback_query.message.answer(
                "Выберите группу для удаления:",
                reply_markup=keyboard.adjust(1).as_markup()
            )
        else:
            await callback_query.message.answer("❌ Нет доступных групп для удаления.")
    except Exception as e:
        db.connection.close()
        await callback_query.message.answer(f"❌ Ошибка при получении списка групп: {e}")


@router.callback_query(lambda c: c.data.startswith("cluster_delete_"))
async def delete_server_group(callback_query: types.CallbackQuery):
    """Удаляет выбранную группу серверов без подтверждения."""
    group_name = callback_query.data.split("_", 2)[2]

    db = Database(SERVEDATABASE)
    try:
        db.cursor.execute('DELETE FROM server_groups WHERE group_name = ?', (group_name,))
        db.connection.commit()
        db.connection.close()

        await callback_query.message.edit_text(f"✅ Группа серверов '{group_name}' успешно удалена!")
    except Exception as e:
        db.connection.close()
        await callback_query.message.edit_text(f"❌ Ошибка при удалении группы серверов: {e}")

#все рефералы
class AddReferal(StatesGroup):
    waiting_for_name = State()

@router.message(F.text == BUTTON_TEXTS["referrals"])
async def show_referral_options(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.row(
        types.KeyboardButton(text="➕ Добавить реферал"),
        types.KeyboardButton(text="📋 Все рефералы")
    )
    await message.answer("Выберите действие:", reply_markup=kb.as_markup(resize_keyboard=True))

@router.message(F.text == "➕ Добавить реферал")
async def ask_for_referral_name(message: types.Message, state: FSMContext):
    await message.answer("Введите имя для нового реферала:")
    await state.set_state(AddReferal.waiting_for_name)

@router.message(AddReferal.waiting_for_name)
async def create_referral(message: types.Message, state: FSMContext, bot):
    name = message.text.strip()
    user_id = message.from_user.id
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=10))

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO referals (user_id, name, code) VALUES (?, ?, ?)", (user_id, name, code))
    conn.commit()
    conn.close()

    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"

    await message.answer(f"✅ Реферал создан: <b>{name}</b>\nСсылка: {link}", parse_mode="HTML")
    await state.clear()

@router.message(F.text == "📋 Все рефералы")
async def list_all_referrals(message: types.Message):
    user_id = message.from_user.id

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, code FROM referals WHERE user_id = ?", (user_id,))
    referals = cursor.fetchall()
    conn.close()

    if not referals:
        await message.answer("У вас пока нет рефералов.")
        return

    kb = InlineKeyboardBuilder()
    for name, code in referals:
        kb.add(InlineKeyboardButton(text=name, callback_data=f"ref_link:{code}"))

    await message.answer("Ваши рефералы:", reply_markup=kb.adjust(1).as_markup())

@router.callback_query(F.data.startswith("ref_link:"))
async def show_referral_details(callback: types.CallbackQuery):
    code = callback.data.split(":")[1]

    referral = await get_referral_info_by_code(code)
    
    if referral:
        await callback.answer("Загружаем данные…", show_alert=False)
        name, code, clicks = referral

        async with aiosqlite.connect("users.db") as conn:
            # Получаем сумму покупок из таблицы referals
            cursor = await conn.execute(
                "SELECT amount FROM referals WHERE code = ?",
                (code,)
            )
            referral_data = await cursor.fetchone()
            total_amount = referral_data[0] if referral_data else 0

            # Получаем статистику по подпискам
            cursor = await conn.execute("""
                SELECT 
                    SUM(CASE WHEN has_trial = 1 AND (sum_my = 0 OR sum_my IS NULL) THEN 1 ELSE 0 END) as free_subs,
                    SUM(CASE WHEN sum_my > 0 THEN 1 ELSE 0 END) as paid_subs,
                    SUM(CASE WHEN has_trial = 0 AND (sum_my = 0 OR sum_my IS NULL) THEN 1 ELSE 0 END) as no_subs
                FROM users
                WHERE referrer_code = ?
            """, (code,))
            
            stats = await cursor.fetchone()
            free_count = stats[0] or 0
            paid_count = stats[1] or 0
            no_sub_count = stats[2] or 0

        bot_username = (await callback.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={code}"

        await callback.message.edit_text(
            f"<b>👤 Реферал:</b> {name}\n\n"
            f"<b>🔗 Ссылка:</b> <code>{link}</code>\n"
            f"<b>🔗 Реф код:</b> <code>{code}</code>\n"
            f"<b>👣 Переходов:</b> {clicks}\n"
            f"<b>💸 Сумма покупок:</b> {total_amount} руб.\n\n"
            f"<b>📊 Статистика подписок:</b>\n"
            f"• Пробные: {free_count}\n"
            f"• Платные: {paid_count}\n"
            f"• Без подписки: {no_sub_count}",
            parse_mode="HTML",
            reply_markup=create_ref_stats_keyboard()
        )
    else:
        await callback.answer("❌ Реферал не найден.", show_alert=True)



def create_ref_stats_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="refresh_ref_stats")
    return kb.as_markup()

@router.message(F.text == BUTTON_TEXTS["days_sub"])
async def update_all_days_left_on_startup(message: types.Message):
    """
    Обработчик кнопки: синхронизирует days_left в user_configs с данными с серверов.
    """
    # Удаляем сообщение с кнопкой, чтобы не засорять чат
    await message.delete()

    # Отправляем уведомление пользователю
    sent_message = await message.answer(
        "🔄 Начинаю синхронизацию данных с серверов...\n"
        "⏳ Пожалуйста, подождите, это может занять некоторое время.",
        parse_mode=ParseMode.HTML
    )

    logger.info("🔄 [sync_user_configs_with_servers] Начало синхронизации всех email из user_configs...")

    # Шаг 1: Получаем все email из user_configs
    try:
        async with aiosqlite.connect("users.db") as conn:
            async with conn.execute("SELECT email FROM user_configs") as cursor:
                rows = await cursor.fetchall()
                emails = [row[0] for row in rows]
        logger.info(f"📁 Найдено {len(emails)} email'ов в user_configs: {emails}")
    except Exception as e:
        logger.error(f"❌ Ошибка чтения user_configs: {e}")
        await sent_message.edit_text(
            "❌ Ошибка при чтении данных из базы.\n"
            "Подробнее в логах.",
            parse_mode=ParseMode.HTML
        )
        return

    if not emails:
        logger.info("📭 Нет email'ов в user_configs — синхронизация пропущена.")
        await sent_message.edit_text(
            "📭 Нет пользователей для синхронизации.",
            parse_mode=ParseMode.HTML
        )
        return

    # Шаг 2: Получаем список ID серверов
    try:
        server_ids = await get_server_ids_as_list_for_days_left("servers.db")
        if not server_ids:
            logger.warning("📭 Нет серверов для синхронизации.")
            await sent_message.edit_text(
                "📭 Нет доступных серверов для синхронизации.",
                parse_mode=ParseMode.HTML
            )
            return
        logger.info(f"🌐 Найдено {len(server_ids)} серверов: {server_ids}")
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка серверов: {e}")
        await sent_message.edit_text(
            "❌ Ошибка получения списка серверов.",
            parse_mode=ParseMode.HTML
        )
        return

    updated_count = 0

    # Шаг 3: Обрабатываем каждый сервер отдельно
    for server_id in server_ids:
        logger.info(f"🔁 Обработка сервера: ID={server_id}")

        # Получаем данные сервера
        server_data = await get_server_data(server_id)
        if not server_data:
            logger.warning(f"❌ Не удалось получить данные сервера {server_id}")
            continue

        logger.info(f"🌐 Подключаемся к серверу {server_id} ({server_data['name']})")

        # Создаём отдельную сессию для каждого сервера
        async with aiohttp.ClientSession() as session:
            try:
                # Логинимся
                login_data = {
                    "username": server_data["username"],
                    "password": server_data["password"]
                }
                async with session.post(server_data["login_url"], json=login_data) as login_resp:
                    if login_resp.status != 200:
                        text = await login_resp.text()
                        logger.error(f"❌ Ошибка входа на сервер {server_id}: {text}")
                        continue

                    cookies = login_resp.cookies
                    session_id = cookies.get('3x-ui').value
                    if not session_id:
                        logger.error(f"❌ Не получен session_id с сервера {server_id}")
                        continue

                    headers = {'Accept': 'application/json', 'Cookie': f'3x-ui={session_id}'}

                found_any = False  # Флаг: найден ли хоть один email на этом сервере

                # Обрабатываем каждый inbound
                for inbound_id in server_data["inbound_ids"]:
                    url = f"{server_data['config_client_url']}/{inbound_id}"
                    logger.info(f"🔍 Запрашиваем inbound {inbound_id} на сервере {server_id}")

                    try:
                        async with session.get(url, headers=headers) as resp:
                            if resp.status != 200:
                                text = await resp.text()
                                logger.error(f"❌ Ошибка получения inbound {inbound_id}: {text}")
                                continue

                            data = await resp.json()
                            obj = data.get('obj')
                            if not obj:
                                logger.warning(f"⚠️ Пустой obj в ответе inbound {inbound_id}")
                                continue

                            settings = obj.get('settings')
                            if not settings:
                                logger.warning(f"⚠️ Нет settings в inbound {inbound_id}")
                                continue

                            try:
                                clients = json.loads(settings).get('clients', [])
                            except Exception as e:
                                logger.error(f"❌ Ошибка парсинга clients: {e}")
                                continue

                            logger.info(f"📥 Сервер {server_id}, inbound {inbound_id}: получено {len(clients)} клиентов")

                            # Проверяем каждого клиента
                            for client in clients:
                                email = client.get('email')
                                expiry_time = client.get('expiryTime')

                                if not email:
                                    logger.debug(f"🟡 Пропускаем клиента без email: {client}")
                                    continue

                                if email in emails:
                                    found_any = True

                                    # Рассчитываем days_left
                                    if expiry_time is None or expiry_time <= 0:
                                        days_left = -1
                                        status = "не активирована"
                                    else:
                                        expiry_dt = datetime.fromtimestamp(expiry_time / 1000)
                                        days_left = (expiry_dt.date() - datetime.now().date()).days
                                        status = f"осталось {days_left} дн."

                                    logger.info(f"🎯 НАЙДЕН: {email} на сервере {server_id} → expiry_time={expiry_time}, статус: {status}")

                                    # Обновляем в user_configs
                                    try:
                                        async with aiosqlite.connect("users.db") as conn:
                                            await conn.execute(
                                                "UPDATE user_configs SET days_left = ? WHERE email = ?",
                                                (days_left, email)
                                            )
                                            await conn.commit()
                                        logger.info(f"✅ [синхронизация] {email} → days_left = {days_left}")
                                        updated_count += 1
                                    except Exception as e:
                                        logger.error(f"❌ Ошибка обновления {email} в БД: {e}")

                                else:
                                    logger.debug(f"ℹ️ email={email} есть на сервере, но отсутствует в user_configs")

                    except Exception as e:
                        logger.error(f"❌ Ошибка при запросе к inbound {inbound_id}: {e}")

                if not found_any:
                    logger.warning(f"🟡 Ни один из {len(emails)} email'ов НЕ НАЙДЕН на сервере {server_id}")

            except Exception as e:
                logger.error(f"❌ Критическая ошибка при работе с сервером {server_id}: {e}")

    logger.info(f"✅ [sync_user_configs_with_servers] Синхронизация завершена. Обновлено {updated_count} записей.")

    # Отправляем финальное сообщение пользователю
    await sent_message.edit_text(
        f"✅ Синхронизация завершена!\n"
        f"📊 Обновлено записей: <b>{updated_count}</b>\n"
        f"🔍 Проверено email'ов: <b>{len(emails)}</b>\n"
        f"🌐 На {len(server_ids)} серверах.",
        parse_mode=ParseMode.HTML
    )

"""Блок редактирования пользователя"""
class AdminUserSearch(StatesGroup):
    waiting_for_user_identifier = State()

@router.message(F.text == BUTTON_TEXTS["edit_users"])
async def edit_users_handler(message: Message, state: FSMContext):
    """Запрашивает идентификатор пользователя (ID или ссылку)"""
    await message.delete()

    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для доступа к этому разделу.")
        return

    sent_message = await message.answer(
        "🆔 Введите <b>Telegram ID</b> или <b>@username</b> пользователя, с которым хотите работать:"
    )

    await state.update_data(sent_message_id=sent_message.message_id, chat_id=sent_message.chat.id)
    await state.set_state(AdminUserSearch.waiting_for_user_identifier)

@router.message(AdminUserSearch.waiting_for_user_identifier)
async def process_user_identifier(message: Message, state: FSMContext):
    identifier = message.text.strip().lower()

    if not identifier:
        await message.answer("❌ Введите корректный идентификатор.")
        return

    # Извлекаем username
    if identifier.startswith("@"):
        search_username = identifier[1:]
    elif "t.me/" in identifier:
        search_username = identifier.split("t.me/")[-1].split("?")[0]
    else:
        search_username = identifier.strip()

    if not search_username:
        await message.answer("❌ Не удалось извлечь имя пользователя.")
        return

    pattern = f"%t.me/{search_username}%"

    async with aiosqlite.connect("users.db") as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT * FROM users WHERE LOWER(telegram_link) LIKE ?", (pattern,))
        row = await cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            user_data = dict(zip(columns, row))
        else:
            user_data = None

    if not user_data:
        await message.answer(f"❌ Пользователь с ссылкой <code>t.me/{search_username}</code> не найден.", parse_mode="HTML")
        return

    # Сохраняем пользователя
    await state.update_data(target_user=user_data)

    # Краткое сообщение: только Telegram ID и Username
    user_preview = (
        "👤 <b>Выбран пользователь:</b>\n\n"
        f"🔹 <b>Telegram ID:</b> <code>{user_data['telegram_id']}</code>\n"
        f"🔹 <b>Username:</b> @{user_data['username'] or 'не указан'}\n"
    )

    # Кнопки действий
    user_actions_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_TEXTS["info_for_admin"], callback_data="user_info_for_admin")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["prodlit_podpisku"], callback_data="prodlit_podpisku")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["statistics_for_admin"], callback_data="user_stats_for_admin")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["block_user"], callback_data="block_user")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["udalit_user"], callback_data="udalit_user")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")]
    ])

    await message.answer(user_preview, reply_markup=user_actions_keyboard, parse_mode="HTML")
    await state.set_state(None)

@router.callback_query(lambda call: call.data == "user_info_for_admin")
async def user_info_callback_for_admin(call: types.CallbackQuery, state: FSMContext):
    await call.answer()

    data = await state.get_data()
    user_data = data.get("target_user")

    if not user_data:
        await call.message.edit_text("❌ Данные пользователя утеряны. Начните сначала.")
        return

    full_info_text = (
        "📘 <b>Подробная информация о пользователе</b>\n\n"
        f"🔹 <b>ID в БД:</b> {user_data['id']}\n"
        f"🔹 <b>Telegram ID:</b> <code>{user_data['telegram_id']}</code>\n"
        f"🔹 <b>Username:</b> @{user_data['username'] or 'не указан'}\n"
        f"🔹 <b>Ссылка:</b> {user_data['telegram_link'] or 'не указана'}\n"
        f"🔹 <b>Реф. код:</b> <code>{user_data['referral_code']}</code>\n"
        f"🔹 <b>Получал пробную:</b> {'Да' if user_data['has_trial'] else 'Нет'}\n"
        f"🔹 <b>Доход (sum_my):</b> {user_data['sum_my']:.2f} руб.\n"
        f"🔹 <b>Пригласил (referrer_code):</b> {user_data['referrer_code'] or '—'}\n"
        f"🔹 <b>Заблокирован:</b> {'Да' if user_data['is_blocked'] else 'Нет'}\n"
    )

    # Кнопка "Назад" ведёт в главное меню действий
    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_actions")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")]
    ])

    await call.message.edit_text(full_info_text, reply_markup=back_keyboard, parse_mode="HTML")


@router.callback_query(lambda call: call.data == "prodlit_podpisku")
async def prodlit_podpisku(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("💳 Здесь можно продлить подписку.")


@router.callback_query(lambda call: call.data == "user_stats_for_admin")
async def user_stats_callback_for_admin(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("📊 Введите id пользователя для которого хотите посмотреть статистику.")


@router.callback_query(lambda call: call.data == "block_user")
async def block_user(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target_user = data.get("target_user")

    if not target_user:
        await call.answer("❌ Пользователь не выбран.", show_alert=True)
        return

    if target_user['is_blocked']:
        await call.message.edit_text("⚠️ Пользователь уже заблокирован.")
        return

    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, заблокировать", callback_data="confirm_block_user"),
            InlineKeyboardButton(text="❌ Нет", callback_data="cancel_admin")
        ]
    ])

    await call.message.edit_text(
        f"Вы уверены, что хотите заблокировать пользователя:\n"
        f"<b>{target_user['username']}</b> (ID: {target_user['telegram_id']})?",
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(lambda call: call.data == "confirm_block_user")
async def confirm_block_user(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target_user = data.get("target_user")

    async with aiosqlite.connect("users.db") as conn:
        await conn.execute(
            "UPDATE users SET is_blocked = 1 WHERE telegram_id = ?",
            (target_user['telegram_id'],)
        )
        await conn.commit()

    await call.message.edit_text(
        f"✅ Пользователь <code>{target_user['telegram_id']}</code> успешно заблокирован.",
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(lambda call: call.data == "udalit_user")
async def udalit_user(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("🗑️ Вы уверены, что хотите удалить пользователя?")

@router.callback_query(lambda call: call.data == "back_to_actions")
async def back_to_actions(call: types.CallbackQuery, state: FSMContext):
    await call.answer()

    data = await state.get_data()
    user_data = data.get("target_user")

    if not user_data:
        await call.message.edit_text("❌ Пользователь не найден. Начните сначала.")
        return

    user_preview = (
        "👤 <b>Выбран пользователь:</b>\n\n"
        f"🔹 <b>Telegram ID:</b> <code>{user_data['telegram_id']}</code>\n"
        f"🔹 <b>Username:</b> @{user_data['username'] or 'не указан'}\n"
    )

    user_actions_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_TEXTS["info_for_admin"], callback_data="user_info_for_admin")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["prodlit_podpisku"], callback_data="prodlit_podpisku")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["statistics_for_admin"], callback_data="user_stats_for_admin")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["block_user"], callback_data="block_user")],
        [InlineKeyboardButton(text=BUTTON_TEXTS["udalit_user"], callback_data="udalit_user")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")]
    ])

    await call.message.edit_text(user_preview, reply_markup=user_actions_keyboard, parse_mode="HTML")