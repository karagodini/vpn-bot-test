import sqlite3
from log import logger
from dotenv import load_dotenv
import os
load_dotenv()

SERVEDATABASE = os.getenv("SERVEDATABASE")

def get_servers():
    """
    Получение списка всех серверов из базы данных.

    Выполняет запрос к базе данных и возвращает список серверов с их ID и именами.
    """
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        query = "SELECT id, name FROM servers"
        cursor.execute(query)
        servers = cursor.fetchall()
        connection.close()
        return servers
    except Exception as e:
        print(f"Ошибка при получении данных о серверах: {e}")
        return []


def update_server_data(server_id, field, new_value):
    """
    Обновление данных о сервере.
    Обновляет указанный параметр сервера по его ID.
    """
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        query = f"UPDATE servers SET {field} = ? WHERE id = ?"
        cursor.execute(query, (new_value, server_id))
        connection.commit()
        connection.close()
        return True
    except Exception as e:
        print(f"Ошибка при обновлении данных сервера: {e}")
        return False


def get_full_server_info():
    """
    Получение полной информации о всех серверах из базы данных.
    Выполняет запрос к базе данных и возвращает полные данные о серверах.
    """
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM servers")
        result = cursor.fetchall()
        connection.close()
        if result:
            return [
                {
                    "id": row[0],
                    "total_slots": row[1],
                    "name": row[2],
                    "username": row[3],
                    "password": row[4],
                    "server_ip": row[5],
                    "base_url": row[6],
                    "subscription_base": row[7],
                    "sub_url": row[8],
                    "json_sub": row[9],
                    "inbound_ids": row[10]
                }
                for row in result
            ]
        else:
            return []
    except Exception as e:
        print(f"Ошибка при получении информации о серверах: {e}")
        return []


def get_server_groups():
    """
    Получение информации о кластерах (группах серверов) из базы данных.
    Выполняет запрос к базе данных и возвращает список групп серверов с их ID.
    """
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM server_groups")
        result = cursor.fetchall()
        connection.close()
        if result:
            return [
                {
                    "group_name": row[0],
                    "server_ids": row[1]
                }
                for row in result
            ]
        else:
            return []
    except Exception as e:
        print(f"Ошибка при получении информации о кластерах: {e}")
        return []


def update_server_ids_in_db(server_ids):
    """
    Обновление списка server_ids в базе данных.
    Эта функция обновляет или вставляет новый список server_ids в таблицу базы данных.
    """
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        cursor.execute('SELECT COUNT(*) FROM server_ids')
        record_count = cursor.fetchone()[0]

        if record_count == 0:
            cursor.execute(
                'INSERT INTO server_ids (server_ids) VALUES (?)',
                (','.join(map(str, server_ids)),)
            )
        else:
            cursor.execute(
                'UPDATE server_ids SET server_ids = ?',
                (','.join(map(str, server_ids)),)
            )

        connection.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении server_ids в базе данных: {e}")
    finally:
        connection.close()


def delete_server(server_id):
    """
    Удаление сервера по ID из базы данных.
    """
    try:
        connection = sqlite3.connect(SERVEDATABASE)
        cursor = connection.cursor()
        query = "DELETE FROM servers WHERE id = ?"
        cursor.execute(query, (server_id,))
        connection.commit()
        connection.close()
        return True
    except Exception as e:
        print(f"Ошибка при удалении сервера: {e}")
        return False


def get_current_server_ids():
    """
    Получение текущих ID серверов из базы данных.
    Возвращает список серверных ID, хранящихся в таблице `server_ids`.
    """
    connection = sqlite3.connect(SERVEDATABASE)
    cursor = connection.cursor()

    cursor.execute("SELECT server_ids FROM server_ids LIMIT 1")
    result = cursor.fetchone()

    connection.close()
    if result and result[0]:
        return result[0].split(",")
    return []
