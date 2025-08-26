import sqlite3
import aiohttp
import requests
from handlers.config import  get_server_data
from client.add_client import login
from db.db import get_server_ids_as_list
from dotenv import load_dotenv
import os
from log import logger

load_dotenv()

USERSDATABASE = os.getenv("USERSDATABASE")
SERVEDATABASE = os.getenv("SERVEDATABASE")

async def scheduled_delete_clients():
    """
    Запускает процесс планировщика для удаления отключенных клиентов с нескольких серверов.

    Получает список серверов, а затем для каждого сервера выполняет:
    - Логин на сервер с использованием учетных данных.
    - Получение списка отключенных клиентов.
    - Удаление этих клиентов с сервера и из базы данных.

    Логирует результаты выполнения для каждого сервера и возможные ошибки.
    """
    try:
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

                deleted_clients = await delete_depleted_clients(server_data['delete_depleted_clients_url'], session_id)
                results.append(f"Сервер {server_data['name']}: {deleted_clients}")
            except Exception as e:
                results.append(f"❌ Ошибка при удалении клиентов на сервере {server_data['name']}: {str(e)}")

        logger.info("\n".join(results)) 
    except Exception as e:
        logger.error(f"Ошибка в процессе планировщика: {e}")


async def get_inactive_clients(list_clients_url, session_id):
    """
    Получает список отключенных клиентов с сервера и удаляет их из базы данных.
    """
    conn = sqlite3.connect(USERSDATABASE)
    cursor = conn.cursor()

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 YaBrowser/24.7.0.0 Safari/537.36',
        'Cookie': f'3x-ui={session_id}'
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(list_clients_url, headers=headers) as response:
            if response.status == 200:
                try:
                    response_data = await response.json()
                    clients = response_data.get('obj', [])

                    if isinstance(clients, list):
                        disabled_emails = [
                            client['email'] 
                            for inbound in clients 
                            for client in inbound.get('clientStats', []) 
                            if not client.get('enable', True)
                        ]
                        
                        if disabled_emails:
                            for email in disabled_emails:
                                cursor.execute('DELETE FROM user_emails WHERE email = ?', (email,))
                            conn.commit()
                            return f"Подписка истекла у: {', '.join(disabled_emails)}. Отключенные email удалены из базы данных."
                        else:
                            return "Нет клиентов."
                    else:
                        return "Ожидался список клиентов, но ответ имеет другой формат."
                except ValueError:
                    return "Ответ от API не в формате JSON."
            else:
                return f"Ошибка при получении списка клиентов: статус {response.status}"

    conn.close()

async def delete_depleted_clients(delete_url, session_id):
    """
    Удаляет отключенных клиентов с сервера.
    """
    headers = {
        'Accept': 'application/json',
        'Cookie': f'3x-ui={session_id}'
    }
    try:
        response = requests.post(delete_url, headers=headers)
        if response.status_code == 200:
            deleted_clients = response.json().get('deleted_clients', [])           
            if deleted_clients:
                return f"✅ Отключенные клиенты успешно удалены: {', '.join(deleted_clients)}."
            else:
                return "✅ Отключенные клиенты успешно удалены:."
        else:
            return "❌ Не удалось удалить отключенных клиентов."
    except Exception as e:
        logger.error(f"Ошибка при удалении клиентов: {e}")
        return "❌ Произошла ошибка при удалении клиентов."
