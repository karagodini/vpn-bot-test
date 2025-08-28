import os
import json
import uuid
import random
import asyncio
import hashlib
import requests
import aiohttp
import yookassa
import urllib.parse
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_UP

from aiogram.types import LabeledPrice
from aiocryptopay import AioCryptoPay, Networks
from yookassa import Payment

from pay.prices import get_expiry_time_description
from log import logger
from dotenv import load_dotenv
from bot import bot

load_dotenv()

ACCOUNT_ID = os.getenv("ACCOUNT_ID")
SECRET_KEY = os.getenv("SECRET_KEY")
PASS1 = os.getenv("PASS1")
RUB_TO_USDT_DEF = int(os.getenv("RUB_TO_USDT_DEF"))
MERCH_LOGIN = os.getenv("MERCH_LOGIN")
CRYPROBOT = os.getenv("CRYPROBOT")
BOT_LINK = os.getenv("BOT_LINK")
PAYMENTS_TOKEN = os.getenv("PAYMENTS_TOKEN")
PUBLIC_ID = os.getenv("PUBLIC_ID")
SECRET_CP = os.getenv("SECRET_CP")
YOMOONEY = os.getenv("YOMOONEY")

yookassa.Configuration.account_id = ACCOUNT_ID
yookassa.Configuration.secret_key = SECRET_KEY

from yoomoney import Client
from yoomoney import Quickpay

def create_yoomoney_invoice(amount: float, receiver: str, label: str, targets: str = "Оплата услуги"):
    """
    Создает платежную ссылку в YooMoney.
    """
    logger.info(
        f"💳 Начато создание счёта в YooMoney:\n"
        f"   → Сумма: {amount} RUB\n"
        f"   → Получатель: {receiver}\n"
        f"   → Метка (label): {label}\n"
        f"   → Назначение: {targets}"
    )

    try:
        quickpay = Quickpay(
            receiver=receiver,
            quickpay_form="shop",
            targets=targets,
            paymentType="SB",  # Можно сделать параметром при необходимости
            sum=amount,
            label=label
        )

        logger.info(
            f"✅ Счёт в YooMoney успешно создан:\n"
            f"   → Ссылка: {quickpay.base_url}\n"
            f"   → Метка: {quickpay.label}"
        )
        return quickpay.base_url, quickpay.label

    except Exception as e:
        logger.error(
            f"❌ Ошибка при создании счёта YooMoney:\n"
            f"   → Метка: {label}\n"
            f"   → Исключение: {e}",
            exc_info=True
        )
        return None, None


async def check_yoomoney_payment_status(payment_id):
    """
    Проверяет статус платежа по метке (label) в YooMoney.
    """
    logger.info(f"🔍 Начата проверка статуса платежа в YooMoney: label={payment_id}")

    try:
        client = Client(YOMOONEY)
        logger.debug(f"Инициализирован клиент YooMoney для проверки платежа: {payment_id}")

        history = client.operation_history(label=payment_id)
        logger.info(f"Получена история операций для метки: {payment_id}. Найдено операций: {len(history.operations)}")

        for operation in history.operations:
            logger.info(
                f"📊 Обнаружена операция:\n"
                f"   → ID: {operation.operation_id}\n"
                f"   → Статус: {operation.status}\n"
                f"   → Сумма: {operation.amount}\n"
                f"   → Дата: {operation.datetime}\n"
                f"   → Метка: {operation.label}"
            )

            if operation.label == payment_id and operation.status == "success":
                logger.info(f"✅ Платёж по метке {payment_id} подтверждён (статус: success)")
                return True

        logger.info(f"⏳ Платёж с меткой {payment_id} не найден или ещё не завершён.")
        return False

    except Exception as e:
        logger.error(
            f"💥 Критическая ошибка при проверке статуса платежа YooMoney (label={payment_id}):\n"
            f"   → Ошибка: {e}",
            exc_info=True
        )
        return False


async def create_payment_tgpay(amount, chat_id, name, expiry_time, payment_type, pay_currency):
    """
    Создает платеж через Telegram Pay или через систему звезд (XTR).
    """
    expiry_time_text = f"{expiry_time} дней"
    
    if pay_currency == "tgpay":
        currency = "rub"
        provider_token = PAYMENTS_TOKEN
        f_amount = int(amount * 100)
    elif pay_currency == "xtr":
        currency = "XTR"
        provider_token = None
        f_amount = int(amount / 2.3)
    else:
        raise ValueError("Неверный тип оплаты. Допустимые значения: 'tgpay', 'xtr'")
    
    invoice_payload = json.dumps({
        "name": name,
        "expiry_time": expiry_time,
        "payment_type": payment_type
    })
    
    await bot.send_invoice(
        chat_id,
        title=f"Подписка для {name} на {expiry_time_text}",
        description=f"Подписка на {expiry_time_text}",
        provider_token=provider_token,
        photo_url="https://www.aroged.com/wp-content/uploads/2022/06/Telegram-has-a-premium-subscription.jpg",
        photo_width=416,
        photo_height=234,
        photo_size=416,
        is_flexible=False,
        currency=currency,
        prices=[LabeledPrice(label=f"Подписка на {expiry_time_text}", amount=f_amount)],
        start_parameter=f"vpn_subscription_{chat_id}_{expiry_time}",
        payload=invoice_payload,
    )


def create_payment_yookassa(amount, chat_id, name, expiry_time, email):
    """
    Создает платеж через YooKassa.
    """
    logger.info(
        f"💳 Начато создание платежа через YooKassa:\n"
        f"   → Сумма: {amount} RUB\n"
        f"   → Пользователь (chat_id): {chat_id}\n"
        f"   → Логин: {name}\n"
        f"   → Срок подписки: {expiry_time} дней\n"
        f"   → Email: {email}"
    )

    try:
        # Генерация уникального ID платежа
        id_key = str(uuid.uuid4())
        logger.debug(f"Сгенерирован уникальный ID платежа: {id_key}")

        # Формируем описание подписки
        expiry_time_text = get_expiry_time_description(expiry_time)
        description = f"Оплата подписки, логин: {name} на {expiry_time_text}"
        logger.info(f"Описание платежа: {description}")

        # Подготовка данных для платежа
        payment_data = {
            "amount": {
                "value": str(float(amount)),
                "currency": "RUB"
            },
            "receipt": {
                "customer": {
                    "email": email
                },
                "items": [
                    {
                        "description": description,
                        "quantity": 1.000,
                        "amount": {
                            "value": str(float(amount)),
                            "currency": "RUB"
                        },
                        "vat_code": 1,
                        "payment_mode": "full_prepayment",
                        "payment_subject": "commodity"
                    }
                ]
            },
            "confirmation": {
                "type": "redirect",
                "return_url": BOT_LINK
            },
            "capture": True,
            "metadata": {
                "chat_id": chat_id,
                "name": name,
                "expiry_time": expiry_time
            },
            "description": description
        }

        logger.debug("Данные платежа сформированы. Отправка запроса в YooKassa...")

        # Создание платежа
        payment = Payment.create(payment_data, id_key)

        confirmation_url = payment.confirmation.confirmation_url
        payment_id = payment.id

        logger.info(
            f"✅ Платёж успешно создан в YooKassa:\n"
            f"   → ID платежа: {payment_id}\n"
            f"   → Ссылка для оплаты: {confirmation_url}\n"
            f"   → Метод подтверждения: redirect"
        )

        return confirmation_url, payment_id

    except Exception as e:
        logger.error(
            f"❌ Ошибка при создании платежа в YooKassa:\n"
            f"   → Пользователь: {chat_id}\n"
            f"   → Сумма: {amount}\n"
            f"   → Исключение: {e}",
            exc_info=True  # Полная трассировка стека
        )
        return None, None

async def check_payment_yookassa(payment_id):
    """
    Проверяет статус платежа в YooKassa.
    """
    logger.info(f"🔍 Начата проверка статуса платежа в YooKassa: payment_id={payment_id}")

    try:
        loop = asyncio.get_event_loop()
        logger.debug(f"Запуск синхронного запроса к YooKassa (Payment.find_one) для payment_id={payment_id}")
        
        payment = await loop.run_in_executor(None, yookassa.Payment.find_one, payment_id)

        if not payment:
            logger.warning(f"❌ Платёж с ID {payment_id} не найден в YooKassa.")
            return False

        logger.info(f"📊 Получен статус платежа {payment_id}: {payment.status}")

        if payment.status == 'succeeded':
            metadata = dict(payment.metadata)
            logger.info(
                f"✅ Платёж {payment_id} успешно завершён.\n"
                f"   → Метаданные: {metadata}"
            )
            return metadata
        elif payment.status == 'pending':
            logger.info(f"⏳ Платёж {payment_id} ещё в статусе 'pending'.")
            return False
        elif payment.status in ('canceled', 'expired'):
            logger.warning(f"🚫 Платёж {payment_id} отменён или просрочен (статус: {payment.status})")
            return False
        else:
            logger.warning(f"⚠️ Неизвестный статус платежа {payment_id}: {payment.status}")
            return False

    except Exception as e:
        logger.error(
            f"💥 Ошибка при проверке платежа {payment_id} в YooKassa:\n"
            f"   → Исключение: {e}",
            exc_info=True
        )
        return False

def create_paymentupdate(amount, chat_id, email):
    """
    Создает платеж для продления подписки через YooKassa.
    """
    logger.info(
        f"💳 Начато создание платежа за продление подписки:\n"
        f"   → Сумма: {amount} RUB\n"
        f"   → Пользователь (chat_id): {chat_id}\n"
        f"   → Email: {email}"
    )

    try:
        # Генерация уникального ID платежа
        id_key = str(uuid.uuid4())
        description = "Продление подписки"
        logger.debug(f"Сгенерирован payment_id: {id_key}")

        # Подготовка данных платежа
        payment_data = {
            "amount": {
                "value": str(float(amount)),
                "currency": "RUB"
            },
            "receipt": {
                "customer": {
                    "email": email
                },
                "items": [
                    {
                        "description": description,
                        "quantity": 1.000,
                        "amount": {
                            "value": str(float(amount)),
                            "currency": "RUB"
                        },
                        "vat_code": 1,
                        "payment_mode": "full_prepayment",
                        "payment_subject": "commodity"
                    }
                ]
            },
            "confirmation": {
                "type": "redirect",
                "return_url": BOT_LINK
            },
            "capture": True,
            "metadata": {
                "chat_id": chat_id,
                "name": description,
            },
            "description": description
        }

        logger.debug("Данные платежа подготовлены. Отправка запроса в YooKassa...")

        # Создание платежа
        payment = Payment.create(payment_data, id_key)

        confirmation_url = payment.confirmation.confirmation_url
        payment_id = payment.id

        logger.info(
            f"✅ Платёж за продление успешно создан:\n"
            f"   → ID платежа: {payment_id}\n"
            f"   → Ссылка для оплаты: {confirmation_url}\n"
            f"   → Метод: redirect → {BOT_LINK}"
        )

        return confirmation_url, payment_id

    except Exception as e:
        logger.error(
            f"❌ Ошибка при создании платежа за продление через YooKassa:\n"
            f"   → Пользователь: {chat_id}\n"
            f"   → Сумма: {amount}\n"
            f"   → Исключение: {e}",
            exc_info=True
        )
        return None, None

#Робокасса
def calculate_signature(merchant_login, amount, invoice_id, password1, receipt_json, shp_params=None):
    """
    Вычисляет цифровую подпись для платежа в Робокассе с учетом Receipt.
    """
    signature_data = f"{merchant_login}:{amount}:{invoice_id}:{receipt_json}:{password1}"
    
    if shp_params:
        for key, value in sorted(shp_params.items()):
            signature_data += f":{key}={value}"
    
    return hashlib.md5(signature_data.encode('utf-8')).hexdigest().upper()

def calculate_signature_check(merchant_login: str, invoice_id: int, password2: str) -> str:
    """Функция для генерации подписи"""
    signature_string = f"{merchant_login}:{invoice_id}:{password2}"
    return hashlib.md5(signature_string.encode()).hexdigest()

def create_payment_robokassa(amount, chat_id, name, expiry_time, email):
    """
    Создает платеж через Робокассу с учетом JSON Receipt.
    """
    merchant_login = MERCH_LOGIN
    password1 = PASS1
    invoice_id = random.randint(1, 2147483647)
    expiry_time_text = get_expiry_time_description(expiry_time)
    description = f"Оплата подписки, логин: {name} на {expiry_time_text}"
    # Дополнительные параметры
    shp_params = {
        'shp_chat_id': chat_id,
        'shp_name': name,
        'shp_expiry_time': expiry_time
    }
    
    # Формируем JSON для Receipt
    receipt = {
        "items": [
            {
                "name": f"Оплата подписки, логин: {name} на {expiry_time} дней",
                "quantity": 1,
                "sum": amount,
                "payment_method": "full_payment",
                "tax": "none"
            }
        ]
    }
    
    receipt_json = json.dumps(receipt, separators=(',', ':'), ensure_ascii=True)  # Генерация JSON в ASCII
    encoded_receipt = urllib.parse.quote(receipt_json)  # Кодирование для URL
    

    signature = calculate_signature(merchant_login, amount, invoice_id, password1, receipt_json, shp_params)
    
    payment_url = (
        f"https://auth.robokassa.ru/Merchant/Index.aspx?"
        f"MerchantLogin={merchant_login}&"
        f"OutSum={amount}&"
        f"InvId={invoice_id}&"
        f"Description={urllib.parse.quote(description)}&"
        f"Receipt={encoded_receipt}&"
        f"SignatureValue={signature}&"
        f"shp_chat_id={shp_params['shp_chat_id']}&"
        f"shp_name={urllib.parse.quote(shp_params['shp_name'])}&"
        f"shp_expiry_time={shp_params['shp_expiry_time']}&"
        f"Email={email}&"
        f"Culture=ru&"
        f"Encoding=utf-8"
    )
    
    return payment_url, invoice_id


async def check_payment_robokassa(invoice_id: int, password2: str) -> str | None:
    """
    Проверяет статус платежа в Робокассе.
    """
    merchant_login = MERCH_LOGIN
    signature = calculate_signature_check(merchant_login, invoice_id, password2)

    url = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt"
    params = {
        "MerchantLogin": merchant_login,
        "InvoiceID": invoice_id,
        "Signature": signature,
    }
    full_url = url + "?" + urllib.parse.urlencode(params)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as response:
                response.raise_for_status()
                response_text = await response.text()
                logger.info(f"Ответ от Robokassa: {response_text}")

                # Разбираем XML-ответ
                root = ET.fromstring(response_text)
                namespace = {"ns": "http://merchant.roboxchange.com/WebService/"}

                result_code_element = root.find("ns:Result/ns:Code", namespaces=namespace)
                if result_code_element is None:
                    logger.error("Элемент <Result><Code> не найден.")
                    return None

                result_code = result_code_element.text

                state_code_element = root.find("ns:State/ns:Code", namespaces=namespace)
                if state_code_element is None:
                    logger.error("Оплата еще не начата!")
                    return None

                state_code = state_code_element.text
                logger.info(f"Результат: result_code={result_code}, state_code={state_code}")

                if result_code == "0" and state_code == "100":
                    return "100"
                elif result_code == "3":
                    logger.warning("Не удалось найти операцию. Платеж не существует.")
                    return "3"
                else:
                    logger.warning(f"Необработанный статус: result_code={result_code}, state_code={state_code}")
                    return None

    except aiohttp.ClientError as e:
        logger.error(f"Ошибка запроса: {e}")
        return None
    except ET.ParseError:
        logger.error("Ошибка: полученный ответ не удалось разобрать как XML.")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return None
    
async def create_payment_cryptobot(amount, chat_id):
    """
    Создает платеж через CryptoBot.
    """
    async with AioCryptoPay(token=CRYPROBOT, network=Networks.MAIN_NET) as crypto:
        try:
            exchange_rates = await crypto.get_exchange_rates()
            RUB_TO_USDT = next(
                (rate.rate for rate in exchange_rates if rate.source == "USDT" and rate.target == "RUB"), 
                RUB_TO_USDT_DEF
            )
            logger.info(f"Текущий курс USDT к рублю: {RUB_TO_USDT}")
        except Exception as e:
            logger.error(f"Ошибка при получении курса, курс: {RUB_TO_USDT_DEF}. Ошибка: {e}")
        try:
            usdt_amount = Decimal(amount) / Decimal(RUB_TO_USDT)
            usdt_amount = usdt_amount.quantize(Decimal("0.01"), rounding=ROUND_UP)

            invoice = await crypto.create_invoice(
                asset="USDT",
                amount=str(usdt_amount),
                description="Оплата подписки",
                fiat=None,
                payload=f"{chat_id}:{int(amount)}",
            )
            payment_url = invoice.bot_invoice_url
            payment_id = invoice.invoice_id
            return payment_url, payment_id
        except Exception as e:
            logger.error(f"Ошибка при создании счета: {e}")
            return None, None


async def check_payment_cryptobot(invoice_id):
    """
    Проверяет статус платежа в CryptoBot.
    """
    logger.info(f"Проверка статуса для счета с ID: {invoice_id}")
    async with AioCryptoPay(token=CRYPROBOT, network=Networks.MAIN_NET) as crypto:
        try:
            logger.debug(f"Отправка запроса для получения информации по счету с ID: {invoice_id}")
            invoices_info = await crypto.get_invoices(invoice_ids=[invoice_id])
            logger.debug(f"Ответ от API: {invoices_info}")
            invoice_info = invoices_info[0] if invoices_info else None

            if invoice_info:
                logger.info(f"Статус счета с ID {invoice_id}: {invoice_info.status}")
                if invoice_info.status == 'paid':
                    logger.info(f"Платеж по счету {invoice_id} успешно завершен.")
                    return True 
                else:
                    logger.warning(f"Платеж по счету {invoice_id} не завершен. Статус: {invoice_info.status}")
                    return False
            else:
                logger.error(f"Счет с ID {invoice_id} не найден.")
                return False
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса счета с ID {invoice_id}: {e}")
            return False


async def create_cloudpayments_invoice(amount, account_id, invoice_id):
    """
    Создает счет для оплаты через CloudPayments.
    """
    payload = {
        "Amount": amount,
        "Currency": "RUB",
        "Description": "Оплата за подписку",
        "RequireConfirmation": False,
        "SendEmail": True,
        "InvoiceId": invoice_id,
        "AccountId": str(account_id),
        "SuccessRedirectUrl": "https://cp.ru",
        "FailRedirectUrl": "https://cp.ru"
    }

    try:
        response = requests.post(
            "https://api.cloudpayments.ru/orders/create",
            json=payload,
            auth=(PUBLIC_ID, SECRET_CP)
        )
        response_data = response.json()

        logger.info("Результат создания счета CloudPayments:")
        logger.info(response_data)

        if not response_data.get("Success"):
            raise ValueError(f"Ошибка CloudPayments API: {response_data.get('Message')}")

        return response_data["Model"]["Url"], invoice_id
    except Exception as e:
        logger.error(f"Ошибка при создании счета: {e}")
        raise


async def check_payment_cloud(invoice_id):
    """
    Проверяет статус платежа в CloudPayments.
    
    """
    if not invoice_id:
        logger.error("Идентификатор платежа не указан.")
        return None

    try:
        payload = {"InvoiceId": invoice_id}
        logger.info("Запрос на проверку статуса платежа в CloudPayments:")
        logger.info(json.dumps(payload, indent=4, ensure_ascii=False))

        response = requests.post(
            "https://api.cloudpayments.ru/payments/find",
            json=payload,
            auth=(PUBLIC_ID, SECRET_CP)
        )
        
        response_data = response.json()

        logger.info("Ответ от CloudPayments:")
        logger.info(json.dumps(response_data, indent=4, ensure_ascii=False))

        if response_data.get("Success"):
            payment_status = response_data["Model"]["Status"]
            amount = float(response_data["Model"]["Amount"])

            if payment_status == "Completed":
                return {
                    "status": payment_status,
                    "amount": amount,
                    "data": response_data["Model"]
                }
            else:
                logger.warning(f"Платеж со статусом: {payment_status}.")
        else:
            logger.error(f"Ошибка CloudPayments: {response_data.get('Message')}")
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса платежа: {e}")
    
    return None
