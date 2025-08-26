from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import Router, types
import string
import aiosqlite
import asyncio
import random
from log import logger
from client.menu import get_back_button
from handlers.states import PromoCodeState
from buttons.client import BUTTON_TEXTS
from dotenv import load_dotenv
import os
from client.text import REF_TEXT
from datetime import datetime, timedelta

load_dotenv()

SUPPORT = os.getenv("SUPPORT")

USERSDATABASE = os.getenv("USERSDATABASE")
router = Router()


async def get_user_data(telegram_id: int) -> tuple:
    """
    Получает данные пользователя из базы данных.
    """
    async with aiosqlite.connect(USERSDATABASE) as conn:
        async with conn.execute("""
            SELECT referral_code, referral_count, promo_code, sum_my, sum_ref
            FROM users
            WHERE telegram_id = ?
        """, (telegram_id,)) as cursor:
            return await cursor.fetchone()


async def update_user_referral_code(telegram_id: int, referral_code: str) -> None:
    """
    Обновляет реферальный код пользователя в базе данных.
    """
    async with aiosqlite.connect(USERSDATABASE) as conn:
        await conn.execute("""
            UPDATE users SET referral_code = ? WHERE telegram_id = ?
        """, (referral_code, telegram_id))
        await conn.commit()


async def referral_info(callback_query: types.CallbackQuery, bot, state: FSMContext):
    """
    Отображает информацию о реферальной программе и промокодах.
    """
    from pay.prices import get_price_with_referral_info

    telegram_id = callback_query.from_user.id
    user_data = await get_user_data(telegram_id)

    if user_data:
        referral_code, referral_count, user_promo_code, sum_my, sum_ref = user_data

        if referral_code is None:
            referral_code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            await update_user_referral_code(telegram_id, referral_code)

        bot_username = (await bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={referral_code}"
        share_link = f"https://t.me/share/url?url={referral_link}"

        # Получаем скидку и цену
        expiry_time = 30 
        price, total_discount, referral_count = get_price_with_referral_info(expiry_time, telegram_id, user_promo_code)

        # 🔽 Форматируем текст с полной статистикой
        formatted_ref_text = REF_TEXT.format(
            referral_link=referral_link,
            total_discount=total_discount,
            sum_my=sum_my,
            sum_ref=sum_ref
        )

        referral_button = InlineKeyboardBuilder()
        referral_button.add(
            InlineKeyboardButton(text=BUTTON_TEXTS["support"], url=SUPPORT),
            InlineKeyboardButton(text=BUTTON_TEXTS["main_menu"], callback_data="main_menu")
        )

        await bot.edit_message_text(
            chat_id=callback_query.from_user.id,
            message_id=callback_query.message.message_id,
            text=formatted_ref_text,
            parse_mode="HTML",
            reply_markup=referral_button.adjust(1).as_markup()
        )
    else:
        await bot.edit_message_text(
            chat_id=callback_query.from_user.id,
            message_id=callback_query.message.message_id,
            text="❌ Пользователь не найден в базе данных."
        )


@router.callback_query(lambda c: c.data == "enter_promo_code")
async def enter_promo_code_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает запрос на ввод промокода.
    """
    try:
        keyboard = InlineKeyboardBuilder().add(
            InlineKeyboardButton(text=BUTTON_TEXTS["cancel"], callback_data="cancel_promo_code")
        )
        
        # Удаляем предыдущее сообщение с кнопкой "Ввести промокод"
        await callback_query.message.delete()
        
        # Отправляем новое сообщение с запросом промокода
        sent_message = await callback_query.message.answer(
            text="🎟️ Пожалуйста, введите промокод:",
            reply_markup=keyboard.adjust(1).as_markup()
        )
        
        # Сохраняем ID сообщения для последующего удаления
        await state.update_data(sent_message_id=sent_message.message_id)
        
        # Устанавливаем состояние ожидания промокода
        await state.set_state(PromoCodeState.WaitingForPromoCode)
        
        # Отвечаем на callback, чтобы убрать "часики" в кнопке
        await callback_query.answer()
        
    except Exception as e:
        logger.error(f"Error in enter_promo_code_handler: {e}")
        await callback_query.answer("❌ Произошла ошибка, попробуйте позже", show_alert=True)


@router.message(PromoCodeState.WaitingForPromoCode)
async def process_promo_code(message: types.Message, state: FSMContext):
    """
    Обрабатывает введённый промокод.
    """
    try:
        promo_code = message.text.strip()
        user_id = message.from_user.id
        
        # Сохраняем ID входящего сообщения для возможного удаления
        await state.update_data(input_message_id=message.message_id)
        
        async with aiosqlite.connect(USERSDATABASE) as conn:
            # Проверяем промокод в базе
            async with conn.execute("""
                SELECT id, discount, days, is_active
                FROM promo_codes
                WHERE code = ?
            """, (promo_code,)) as cursor:
                promo_data = await cursor.fetchone()

            if not promo_data:
                await handle_promo_code_error(message, state, "❌ Промокод не найден.")
                return

            promo_id, discount, days, is_active = promo_data

            if not is_active:
                await handle_promo_code_error(message, state, "❌ Этот промокод не активен.")
                return

            # Проверяем, использовал ли пользователь уже этот промокод
            async with conn.execute("""
                SELECT COUNT(*)
                FROM used_promo_codes
                WHERE promo_code = ? AND user_id = (SELECT id FROM users WHERE telegram_id = ?)
            """, (promo_code, user_id)) as cursor:
                already_used = (await cursor.fetchone())[0]

            if already_used > 0:
                await handle_promo_code_error(message, state, "❌ Вы уже использовали этот промокод.")
                return

            # Получаем текущую подписку пользователя
            async with conn.execute("""
                SELECT subscription_end FROM users WHERE telegram_id = ?
            """, (user_id,)) as cursor:
                subscription_end = await cursor.fetchone()
                current_end = datetime.strptime(subscription_end[0], "%Y-%m-%d %H:%M:%S") if subscription_end and subscription_end[0] else datetime.now()

            # Вычисляем новую дату окончания подписки
            new_end = current_end + timedelta(days=days) if current_end > datetime.now() else datetime.now() + timedelta(days=days)

            # Обновляем данные пользователя
            await conn.execute("""
                INSERT INTO used_promo_codes (user_id, promo_code)
                VALUES ((SELECT id FROM users WHERE telegram_id = ?), ?)
            """, (user_id, promo_code))
            
            await conn.execute("""
                UPDATE users
                SET promo_code = ?,
                    promo_code_usage = 0,
                    subscription_end = ?,
                    subscription_active = 1
                WHERE telegram_id = ?
            """, (promo_code, new_end.strftime("%Y-%m-%d %H:%M:%S"), user_id))
            
            await conn.commit()

            # Формируем сообщение об успехе
            success_msg = (
                f"✅ Промокод успешно применен!\n\n"
                f"🔹 Скидка: {discount}%\n"
                f"🔹 Подписка продлена на {days} дней\n"
                f"🔹 Новая дата окончания: {new_end.strftime('%d.%m.%Y %H:%M')}"
            )
            
            await handle_promo_code_success(message, state, success_msg)
            
    except Exception as e:
        logger.error(f"Error processing promo code: {e}")
        await message.answer("❌ Произошла ошибка при обработке промокода")
    finally:
        await state.clear()


async def handle_promo_code_error(message: types.Message, state: FSMContext, error_msg: str):
    """
    Обрабатывает ошибку применения промокода.
    """
    try:
        data = await state.get_data()
        
        # Удаляем предыдущие сообщения
        if 'sent_message_id' in data:
            try:
                await message.bot.delete_message(message.chat.id, data['sent_message_id'])
            except:
                pass
        
        if 'input_message_id' in data:
            try:
                await message.bot.delete_message(message.chat.id, data['input_message_id'])
            except:
                pass
        
        # Отправляем сообщение об ошибке
        await message.answer(error_msg, reply_markup=get_back_button())
        
    except Exception as e:
        logger.error(f"Error in handle_promo_code_error: {e}")
        await message.answer("❌ Произошла ошибка", reply_markup=get_back_button())


async def handle_promo_code_success(message: types.Message, state: FSMContext, success_message: str):
    """
    Обрабатывает успешное применение промокода.
    """
    state_data = await state.get_data()
    await delete_message_if_exists(message, state_data.get('sent_message_id'))
    await delete_message_if_exists(message, state_data.get('input_message_id'))

    await message.answer(success_message, reply_markup=get_back_button())


async def delete_message_if_exists(message: types.Message, message_id: int):
    """
    Удаляет сообщение, если оно существует.
    """
    if message_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")