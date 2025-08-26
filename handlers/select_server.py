import requests
from handlers.config import get_server_data
import json
from log import logger
from db.db import ServerDatabase


async def get_optimal_server(selected_server, db: ServerDatabase):
    """
    Получает оптимальный сервер на основе выбранного сервера, сравнивая количество свободных мест.

    Эта функция выполняет запрос к базе данных для получения информации о серверах, сравнивает количество свободных мест на каждом сервере
    и возвращает сервер с наибольшим количеством свободных мест. Если все сервера заняты, возвращается сообщение об этом.
    """
    try:
        db.cursor.execute("SELECT server_ids FROM server_groups WHERE group_name = ?", (selected_server,))
        result = db.cursor.fetchone()
        
        if not result:
            return "Сервер не найден"
        
        servers_to_compare = result[0].split(",")
        
        available_servers = []
        for server_num in servers_to_compare:
            clients_count = await fetch_all_clients(server_num)
            server_data = await get_server_data(server_num)
            if server_data:
                free_slots = max(0, server_data["total_slots"] - clients_count)

                logger.info(f"Сервер {server_num}: Общее количество мест = {server_data['total_slots']}, "
                            f"Занято клиентов = {clients_count}, Свободных мест = {free_slots}")
                
                if free_slots > 0:
                    available_servers.append({
                        "server": server_num,
                        "free_slots": free_slots,
                        "total_slots": server_data["total_slots"]
                    })

        if available_servers:
            optimal_server = max(available_servers, key=lambda x: x["free_slots"], default=None)
            logger.info(f"Оптимальный сервер: {optimal_server['server']} с {optimal_server['free_slots']} свободными местами.")
            return optimal_server['server']
        else:
            logger.warning("В этой локации нет свободных мест")
            return "Сервер полностью занят, попробуйте позже"
    except Exception as e:
        logger.error(f"Ошибка при выборе оптимального сервера: {e}")
        return "Ошибка при обработке запроса"

async def fetch_all_clients(server_selection):
    """
    Получает список всех клиентов на сервере.

    Эта функция выполняет запросы к серверу для получения данных о клиентах, связанных с данным сервером.
    Возвращает количество клиентов на сервере, или сообщение об ошибке в случае неудачи.
    """
    server_data = await get_server_data(server_selection)
    
    if not server_data:
        return 0

    session = requests.Session()
    login_response = session.post(server_data['login_url'], json={
        "username": server_data['username'], 
        "password": server_data['password']
    })

    if login_response.status_code != 200:
        return f"Ошибка входа: {login_response.status_code}"

    clients_list = []
    for inbound_id in server_data["inbound_ids"]:
        try:
            inbound_url = f"{server_data['config_client_url']}/{inbound_id}"
            inbound_response = session.get(inbound_url, headers={'Accept': 'application/json'})
            
            if inbound_response.status_code != 200:
                continue
            inbound_data = inbound_response.json().get('obj', {})
            settings = json.loads(inbound_data.get('settings', '{}'))

            for client in settings.get('clients', []):
                if 'email' in client:
                    clients_list.append(client['email'])
        except Exception as e:
            continue
    return len(clients_list)