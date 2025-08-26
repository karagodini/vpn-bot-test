
from datetime import datetime, timedelta
import json
from aiogram import types, Router
from aiogram.types import ContentType
from aiogram.fsm.context import FSMContext
from bot import dp, bot
from log import logger
from client.add_client import (
    add_client,
    generate_config_from_pay,
    login,
    send_config_from_state,
)
from db.db import (
    handle_database_operations,
    insert_or_update_user,
    update_sum_my,
    update_sum_ref
)
from pay.promocode import log_promo_code_usage
from client.upd_sub import update_client_subscription
from client.menu import get_back_button
from handlers.config import get_server_data

router = Router()

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Подтверждает предварительный платеж перед его обработкой.""" 
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(lambda message: message.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment_handler(message: types.Message, state: FSMContext):
    """Обрабатывает успешный платеж, определяет его тип и вызывает нужный обработчик."""
    try:
        payload = json.loads(message.successful_payment.invoice_payload)
        payment_type = payload.get("payment_type")
        currency = message.successful_payment.currency
        amount = message.successful_payment.total_amount / 100 
        if currency == "XTR":
            amount = amount * 2.3
        logger.info(f"Платеж в {currency} на сумму {amount} ({payment_type})")
        if payment_type == "initial_payment":
            await first_add_client(message, state, amount)
        elif payment_type == "subscription_renewal":
            await update_client(message, state, amount)
        else:
            await message.reply("Неизвестный тип платежа. Свяжитесь с поддержкой.")
    except Exception as e:
        logger.error(f"Ошибка обработки платежа: {e}")
        await message.reply("Произошла ошибка при обработке платежа. Пожалуйста, свяжитесь с поддержкой.")


async def update_client(message: types.Message, state: FSMContext, amount: float):
    """Продлевает подписку пользователя, обновляет данные в БД и логирует использование промокода."""
    try:
        data = await state.get_data()
        name = data.get("name")
        final_price = amount
        months = data.get("selected_months")
        user_promo_code = data.get("user_promo_code")
        telegram_id = message.from_user.id
        await update_client_subscription(telegram_id, name, months)
        await handle_database_operations(telegram_id, name, months)
        await log_promo_code_usage(telegram_id, user_promo_code)
        await update_sum_my(telegram_id, final_price)
        await update_sum_ref(telegram_id, final_price)
        await message.answer(
            text=f"✅ Подписка продлена на {months} месяц(а)!",
            parse_mode='HTML',
            reply_markup=get_back_button()
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при обновлении подписки: {e}")
        await message.answer("Произошла ошибка при обновлении подписки. Пожалуйста, попробуйте позже.")


async def first_add_client(message: types.Message, state: FSMContext, amount: float):
    """Добавляет нового клиента, создает конфигурацию и обновляет данные в БД."""  
    try:
        data = await state.get_data()
        user_promo_code = data.get('user_promo_code')
        final_price = amount
        name = data['name']
        current_time = datetime.utcnow()
        expiry_timestamp = current_time + timedelta(days=data['expiry_time'])
        expiry_time = int(expiry_timestamp.timestamp() * 1000)

        selected_server = data['selected_server']
        telegram_id = message.from_user.id
        server_data = await get_server_data(selected_server)
        session_id = await login(server_data['login_url'], {
            "username": server_data['username'],
            "password": server_data['password']
        })
        add_client_result = await add_client(
            name, expiry_time, server_data['inbound_ids'], telegram_id,
            server_data['add_client_url'], server_data['login_url'], 
            {"username": server_data['username'], "password": server_data['password']}
        )

        await state.update_data(
            email=name,
            client_id=telegram_id,
            login_data={"username": server_data['username'], "password": server_data['password']},
            server_ip=server_data['server_ip'],
            config_client_url=server_data['config_client_url'],
            inbound_ids=server_data['inbound_ids'],
            login_url=server_data['login_url'],
            sub_url=server_data['sub_url'],
            json_sub=server_data['json_sub'],
            user_promo_code=user_promo_code
        )

        userdata, config, config2, config3 = await generate_config_from_pay(telegram_id, name, state)
        await send_config_from_state(message, state, telegram_id=message.from_user.id, edit=False)  
        await handle_database_operations(telegram_id, name, expiry_time)
        await insert_or_update_user(telegram_id, name, selected_server)
        await log_promo_code_usage(telegram_id, user_promo_code)
        await update_sum_my(telegram_id, final_price)
        await update_sum_ref(telegram_id, final_price)
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обработке платежа: {e}")
        return    
    