
import sqlite3
from log import logger
from dotenv import load_dotenv
import os
import aiosqlite
from bot import bot
from client.notify_client import notify_user_about_free_days

load_dotenv()

USERSDATABASE = os.getenv("USERSDATABASE")

class ServerDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.connection = sqlite3.connect(db_path)
        self.cursor = self.connection.cursor()

    def setup_tables_serv(self):
        """Создание таблиц servers и server_ids, если они еще не существуют."""
        try:
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY,
                    total_slots INTEGER,
                    name TEXT,
                    username TEXT,
                    password TEXT,
                    server_ip TEXT,
                    base_url TEXT,
                    subscription_base TEXT,
                    sub_url TEXT,
                    json_sub TEXT,
                    inbound_ids TEXT
                )
            ''')
            self.connection.commit()

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_ids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_ids TEXT
                )
            ''')
            self.connection.commit()
            
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS server_groups (
                    group_name TEXT PRIMARY KEY,
                    server_ids TEXT
                )
            ''')
            self.connection.commit() 
        except Exception as e:
            logger.error(f"Ошибка при создании таблиц: {e}")

    def add_server(self, server_data):
        """Добавление данных о сервере в таблицу servers."""
        try:
            self.cursor.execute('''
                INSERT INTO servers (
                    id, total_slots, name, username, password, 
                    server_ip, base_url, subscription_base, sub_url, json_sub, inbound_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                server_data["id"],
                server_data["total_slots"],
                server_data["name"],
                server_data["username"],
                server_data["password"],
                server_data["server_ip"],
                server_data["base_url"],
                server_data["subscription_base"],
                server_data["subscription_urls"]["sub_url"],
                server_data["subscription_urls"]["json_sub"],
                ";".join(map(str, server_data["inbound_ids"]))
            ))
            self.connection.commit()
        except Exception as e:
            logger.error(f"Ошибка при добавлении сервера: {e}")

    def close(self):
        """Закрытие соединения с базой данных."""
        if self.connection:
            self.connection.close()


class Database:
    def __init__(self, db_path):
        self.connection = sqlite3.connect(db_path)
        self.cursor = self.connection.cursor()

    def setup_tables(self):

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                entry_date TEXT,
                telegram_link TEXT,
                referral_code TEXT,
                referred_by INTEGER,
                referral_count INTEGER,
                has_trial BOOLEAN DEFAULT 0,  -- Флаг: 0 - не получал пробную подписку, 1 - получал
                promo_code TEXT,                  -- Промокод, который использовал пользователь
                promo_code_usage INTEGER DEFAULT 0,  -- Использовал или нет
                FOREIGN KEY (referred_by) REFERENCES users(id)
            )
        ''')
        try:
            self.cursor.execute("ALTER TABLE users ADD COLUMN sum_ref REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass 
        try:
            self.cursor.execute("ALTER TABLE users ADD COLUMN sum_my REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass 
        try:
            self.cursor.execute("ALTER TABLE users ADD COLUMN free_days REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass 
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT,
                id_server INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,            -- Уникальный промокод
                discount INTEGER,            -- Процент скидки (например, 10, 20, 30)
                is_active BOOLEAN DEFAULT 1   -- Флаг активности
            )
        ''') 
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS used_promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                promo_code TEXT,
                usage_date TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        self.connection.commit()

    async def get_ids_by_email(self, email):
        query = """
            SELECT user_id, id_server
            FROM user_emails
            WHERE email = ?
        """
        self.cursor.execute(query, (email,))
        return [(row[0], row[1]) for row in self.cursor.fetchall()]
    
    def get_free_days_by_telegram_id(self, telegram_id):
        query = "SELECT free_days FROM users WHERE telegram_id = ?"
        self.cursor.execute(query, (telegram_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        return 0 
    
    def update_free_days_by_telegram_id(self, telegram_id, new_free_days):
        query = "UPDATE users SET free_days = ? WHERE telegram_id = ?"
        self.cursor.execute(query, (new_free_days, telegram_id))
        self.connection.commit()
        
    def close(self):
        self.cursor.close()
        self.connection.close()

async def get_email_from_usersdatabase(client_id):
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT email FROM users WHERE id=?", (client_id,))
    result = cursor.fetchone()
    
    conn.close()
    
    if result:
        return result[0]
    else:
        return None
    

async def get_emails_from_database(telegram_id):
    """
    Получает список логинов пользователя из базы данных по его Telegram ID.

    Функция выполняет запрос к базе данных, чтобы получить ID пользователя по его Telegram ID. 
    Затем извлекает все логины подписок, связанные с этим пользователем, и возвращает их в виде списка.

    Аргументы:
        telegram_id (int): Telegram ID пользователя, чьи логины подписок необходимо получить.

    Возвращает:
        list: Список строк, содержащих логины подписок, связанных с пользователем.
              Если пользователь с данным Telegram ID не найден, возвращается пустой список.
    """
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id FROM users WHERE telegram_id = ?
    """, (telegram_id,))
    user_id_result = cursor.fetchone()
    
    if user_id_result:
        user_id = user_id_result[0]

        cursor.execute("""
            SELECT email FROM user_emails WHERE user_id = ?
        """, (user_id,))
        emails = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return [email[0] for email in emails]
    else:
        cursor.close()
        conn.close()
        return []


async def handle_database_operations(telegram_id: int, name: str, expiry_time: int):
    """
    Выполняет операции с базой данных: добавление пользователя, логин подписки, 
    обработка рефералов и обновление счетчиков.
    """
    conn_users = None
    cursor_users = None

    try:
        conn_users = sqlite3.connect(USERSDATABASE)
        cursor_users = conn_users.cursor()
        cursor_users.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        user_id_result = cursor_users.fetchone()

        if user_id_result:
            user_id = user_id_result[0]
        else:
            cursor_users.execute("INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,))
            user_id = cursor_users.lastrowid
        cursor_users.execute("""
            SELECT 1 FROM user_emails 
            WHERE user_id = ? AND email = ?
        """, (user_id, name))
        email_exists = cursor_users.fetchone()
        cursor_users.execute("SELECT referred_by FROM users WHERE id = ?", (user_id,))
        referred_by_result = cursor_users.fetchone()

        if referred_by_result and referred_by_result[0]:
            referred_by_id = referred_by_result[0]
            cursor_users.execute("SELECT id FROM users WHERE telegram_id = ?", (referred_by_id,))
            referrer_id_result = cursor_users.fetchone()

            if referrer_id_result:
                referrer_id = referrer_id_result[0]
                cursor_users.execute(
                    "UPDATE users SET referral_count = referral_count + 1 WHERE id = ?", 
                    (referrer_id,)
                )
                logger.info(f"Засчитан реферал для {referred_by_id} от {telegram_id}")
            else:
                logger.error(f"Реферальный код {referred_by_id} не найден.")
        else:
            logger.info("Реферальный код для текущего пользователя не найден или пуст.")
        conn_users.commit()
    except Exception as e:
        logger.error(f"Ошибка работы с базой данных: {e}")
    finally:
        if cursor_users:
            cursor_users.close()
        if conn_users:
            conn_users.close()


async def get_db_connection():
    """Возвращает подключение к базе данных"""
    return sqlite3.connect(USERSDATABASE)


async def execute_query(query, params=None, fetch=False):
    """Выполняет запрос к базе данных и возвращает результат"""
    try:
        conn = await get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        if fetch:
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Ошибка при выполнении запроса: {e}")
    finally:
        conn.close()

async def save_config_to_new_table(email, config3):
    conn_users = await get_db_connection()
    try:
        cursor = conn_users.cursor()
        cursor.execute(
            """
            INSERT INTO user_configs (email, config) VALUES (?, ?)
            """,
            (email, config3)
        )
        conn_users.commit()
        logger.info(f"[save_config_to_new_table] Добавлен email {email} с config")
    except Exception as e:
        logger.error(f"[save_config_to_new_table] Ошибка при добавлении: {e}")
    finally:
        conn_users.close()



#from trial
async def update_user_trial_status(telegram_id: int) -> bool:
    """
    Полностью переработанная функция обновления trial статуса
    Возвращает True если обновление прошло успешно
    """
    conn = None
    try:
        # Создаем новое подключение (не используем execute_query)
        conn = await get_db_connection()
        cursor = conn.cursor()
        
        # 1. Проверяем существует ли пользователь
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        if not cursor.fetchone():
            logger.error(f"Пользователь {telegram_id} не найден")
            return False
        
        # 2. Проверяем текущий статус trial
        cursor.execute("SELECT has_trial FROM users WHERE telegram_id = ?", (telegram_id,))
        current_status = cursor.fetchone()[0]
        
        if current_status == 1:
            logger.info(f"Пользователь {telegram_id} уже имеет trial")
            return False
        
        # 3. Выполняем обновление
        cursor.execute("UPDATE users SET has_trial = 1 WHERE telegram_id = ?", (telegram_id,))
        conn.commit()  # Явный коммит!
        
        # 4. Проверяем что обновилось
        cursor.execute("SELECT has_trial FROM users WHERE telegram_id = ?", (telegram_id,))
        updated_status = cursor.fetchone()[0]
        
        if updated_status != 1:
            logger.error(f"Статус не обновился для {telegram_id}")
            return False
            
        logger.info(f"Успешно обновили trial статус для {telegram_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении trial: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()


async def insert_or_update_user(telegram_id, email, server_id):
    """
    Вставляет или обновляет пользователя и его данные электронной почты в базе данных.

    Функция проверяет, существует ли пользователь с указанным Telegram ID. Если такой пользователь существует,
    проверяет, есть ли у него запись с данным логином подписки и server_id. Если записи нет, то добавляется новая. Если пользователя
    не существует, создается новый пользователь с заданным Telegram ID, и добавляется запись в таблицу user_emails.

    Аргументы:
        telegram_id (int): Telegram ID пользователя.
        email (str): Логин подписки пользователя.
        server_id (str): ID сервера, с которым связан пользователь.

    Возвращает:
        int: ID пользователя, для которого была выполнена вставка или обновление.
    """
    conn_users = await get_db_connection()
    try:
        cursor_users = conn_users.cursor()

        # Проверяем, существует ли пользователь с данным telegram_id
        cursor_users.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        user_id_result = cursor_users.fetchone()

        if user_id_result:
            user_id = user_id_result[0]

            # Проверяем, существует ли запись с указанным email и server_id для данного пользователя
            cursor_users.execute(
                "SELECT 1 FROM user_emails WHERE user_id = ? AND email = ? AND id_server = ?", 
                (user_id, email, server_id)
            )
            if not cursor_users.fetchone():
                # Если такой записи нет, добавляем новую
                cursor_users.execute(
                    "INSERT INTO user_emails (user_id, email, id_server) VALUES (?, ?, ?)",
                    (user_id, email, server_id)
                )
        else:
            # Если пользователя не существует, создаём нового
            cursor_users.execute("INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,))
            user_id = cursor_users.lastrowid

            # Добавляем запись в user_emails
            cursor_users.execute(
                "INSERT INTO user_emails (user_id, email, id_server) VALUES (?, ?, ?)",
                (user_id, email, server_id)
            )

        # Фиксируем изменения в базе данных
        conn_users.commit()
        return user_id
    finally:
        conn_users.close()


async def get_server_ids_as_list(SERVEDATABASE):
    """Получение server_ids из таблицы server_ids как списка."""
    try:

        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        cursor.execute('SELECT server_ids FROM server_ids ORDER BY id DESC LIMIT 1')
        result = cursor.fetchone()

        connection.close()
        if result:
            return result[0].split(',')
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении server_ids: {e}")
        return []


async def get_server_id(SERVEDATABASE):
    """Получение server_id из таблицы servers в виде строки '1,2,3'."""
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        cursor.execute('SELECT id FROM servers ORDER BY id ASC')
        result = cursor.fetchall()       
        connection.close()
       
        if result:
            return ",".join(str(row[0]) for row in result)
        return ""
    except Exception as e:
        logger.error(f"Ошибка при получении server_ids: {e}")
        return ""
    
   
async def emails_from_smena_servera(telegram_id):
    """
    Получает список логинов подписок и server_id для заданного Telegram ID.
    """
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()
    
    try:
        # Получаем ID пользователя по telegram_id
        cursor.execute("""
            SELECT id FROM users WHERE telegram_id = ?
        """, (telegram_id,))
        user_id_result = cursor.fetchone()
        
        if user_id_result:
            user_id = user_id_result[0]

            # Получаем email и server_id из таблицы user_emails
            cursor.execute("""
                SELECT email, id_server FROM user_emails WHERE user_id = ?
            """, (user_id,))
            emails_with_servers = cursor.fetchall()

            return [
                {"email": email, "server_id": server_id}
                for email, server_id in emails_with_servers
            ]
        else:
            return []
    except Exception as e:
        logger.error(f"Ошибка при получении данных из базы: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

async def update_sum_my(telegram_id, amount):
    db_path = USERSDATABASE
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE users SET sum_my = sum_my + ? WHERE telegram_id = ?
            """,
            (amount, telegram_id)
        )
        await db.commit()
    
    # Синхронизация после изменения
    await sync_referral_amounts()

        
        
async def update_sum_ref(telegram_id, amount):
    """Обновляет поле sum_ref у пригласившего пользователя и добавляет username обоих в referal_tables."""
    db_path = USERSDATABASE
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT referred_by, username FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row and row[0]:
            referred_by_id = row[0]
            invited_username = row[1] or f"id:{telegram_id}"

            # Получаем username пригласившего
            async with db.execute(
                "SELECT username FROM users WHERE telegram_id = ?", (referred_by_id,)
            ) as ref_cursor:
                ref_row = await ref_cursor.fetchone()
                ref_username = ref_row[0] if ref_row and ref_row[0] else f"id:{referred_by_id}"

            logger.info(f"Пользователь {referred_by_id} пригласил {telegram_id}. Сумма к прибавлению: {amount}")

            # Обновляем сумму
            await db.execute(
                "UPDATE users SET sum_ref = sum_ref + ? WHERE telegram_id = ?",
                (amount, referred_by_id)
            )

            # ✅ Вставляем обоих в referal_tables
            await db.executemany(
                "INSERT INTO referal_tables (telegram_user) VALUES (?)",
                [(invited_username,), (ref_username,)]
            )

            await db.commit()
            logger.info(f"Обновлена сумма для {referred_by_id} и добавлены пользователи в referal_tables.")
        else:
            logger.warning(f"Пользователь {telegram_id} не имеет реферера или он не найден.") 


async def add_free_days(telegram_id, FREE_DAYS):
    """Добавляет дней и отправляет сообщение пригласившему."""
    db_path = USERSDATABASE
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT referred_by FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row and row[0]:
            referred_by_id = row[0]
            logger.info(f"Пользователь {referred_by_id} пригласил пользователя {telegram_id}. Прибавляется: {FREE_DAYS}")
            await db.execute(
                "UPDATE users SET free_days = free_days + ? WHERE telegram_id = ?",
                (FREE_DAYS, referred_by_id)
            )
            await db.commit()
            await notify_user_about_free_days(referred_by_id, FREE_DAYS, bot)

            logger.info(f"Обновлена сумма для пользователя {referred_by_id}. бесплатных дней: {FREE_DAYS}")
        else:
            logger.warning(f"Пользователь {telegram_id} не имеет реферера или реферер не найден.")


async def get_user_referral_code(
    telegram_id: int, 
    conn: aiosqlite.Connection  # Принимаем соединение извне
) -> str | None:
    """Получает реферальный код пользователя, если он уже зарегистрирован.
    
    Args:
        telegram_id: ID пользователя в Telegram
        conn: Активное соединение с базой данных (передается из вызывающего кода)
    
    Returns:
        Реферальный код (str) или None, если пользователь не найден
    """
    async with conn.execute(
        "SELECT referral_code FROM users WHERE telegram_id = ?", 
        (telegram_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None

#все рефералы
def init_referal_table():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            code TEXT UNIQUE,
            clicks INTEGER DEFAULT 0,
            telegram_id INTEGER,
            amount REAL
        )
    ''')
    conn.commit()
    conn.close()

async def increment_referral_clicks(code: str, conn: aiosqlite.Connection):
    """
    Увеличивает счётчик кликов по реферальной ссылке:
    - В таблице referals (если есть)
    - В таблице users (для владельца кода)
    :param code: Реферальный код
    :param conn: Активное соединение с базой данных
    """
    try:
        # Увеличиваем clicks в таблице referals (если запись есть)
        await conn.execute(
            "UPDATE referals SET clicks = clicks + 1 WHERE code = ?", 
            (code,)
        )

        # Увеличиваем clicks в таблице users для владельца реферального кода
        await conn.execute(
            "UPDATE users SET clicks = clicks + 1 WHERE referral_code = ?", 
            (code,)
        )

        # COMMIT делается вне функции (в вызывающем коде)
    except Exception as e:
        logger.error(f"Ошибка при увеличении счётчика кликов для кода {code}: {e}")
        raise

async def get_referral_info_by_code(code: str):
    async with aiosqlite.connect("users.db") as conn:
        cursor = await conn.execute("SELECT name, code, clicks FROM referals WHERE code = ?", (code,))
        referral = await cursor.fetchone()
    return referral  # (name, code, clicks)

async def add_purchase(referral_code: str, amount: float):
    async with aiosqlite.connect("users.db") as conn:
        cursor = await conn.execute(
            "UPDATE referals SET amount = amount + ? WHERE code = ?",
            (amount, referral_code)
        )
        await conn.commit()

async def sync_referral_amounts():
    async with aiosqlite.connect(USERSDATABASE) as db:
        await db.execute("""
            UPDATE referals
            SET amount = (
                SELECT COALESCE(SUM(u.sum_my), 0)
                FROM referral_links rl
                JOIN users u ON rl.invited_user_id = u.telegram_id
                WHERE rl.referrer_code = referals.code
            )
        """)
        await db.commit()

async def clean_referal_table():
    """Очищает таблицу referal_tables по заданной логике."""
    async with aiosqlite.connect("users.db") as db:
        async with db.execute("""
            SELECT telegram_user, COUNT(*) as count
            FROM referal_tables
            GROUP BY telegram_user
        """) as cursor:
            rows = await cursor.fetchall()

        for telegram_user, count in rows:
            if count == 1:
                await db.execute("""
                    DELETE FROM referal_tables
                    WHERE telegram_user = ?
                    LIMIT 1
                """, (telegram_user,))
            elif count >= 2:
                await db.execute("""
                    DELETE FROM referal_tables
                    WHERE id IN (
                        SELECT id FROM referal_tables
                        WHERE telegram_user = ?
                        LIMIT 1
                    )
                """, (telegram_user,))
        
        await db.commit()