import aiosqlite

async def get_server_data(server_selection):
    """
    Получает данные о сервере из базы данных по выбранному ID сервера.

    Функция выполняет запрос к базе данных, чтобы извлечь информацию о сервере, включая общие настройки и URL-адреса для различных операций.
    Возвращает словарь с данными о сервере, включая стандартные и кастомизированные URL.

    Аргументы:
        server_selection (int): ID выбранного сервера, данные о котором необходимо получить.

    Возвращает:
        dict: Словарь с данными о сервере, включая информацию о сервере и сформированные URL для различных операций.
              Если сервер с данным ID не найден, возвращается None.
    """
    async with aiosqlite.connect("servers.db") as connection:
        cursor = await connection.execute("SELECT * FROM servers WHERE id = ?", (server_selection,))
        server_row = await cursor.fetchone()

        if not server_row:
            return None

        columns = ["id", "total_slots", "name", "username", "password", "server_ip",
                   "base_url", "subscription_base", "sub_url", "json_sub", "inbound_ids"]
        server = dict(zip(columns, server_row))

        server["inbound_ids"] = list(map(int, server["inbound_ids"].split(","))) if server["inbound_ids"] else []

        common_urls = {
            "add_client_url": "/panel/api/inbounds/addClient",
            "config_client_url": "/panel/api/inbounds/get",
            "delete_depleted_clients_url": "/panel/inbound/delDepletedClients/-1",
            "list_clients_url": "/panel/inbound/list",
            "update_url": "/panel/api/inbounds/updateClient",
            "delete_client_url": "/panel/api/inbounds/"
        }

        server_data = {
            **server,
            **{key: f"{server['base_url']}{value}" for key, value in common_urls.items()},
            **{key: f"{server['subscription_base']}{value}" for key, value in {
                "sub_url": server["sub_url"],
                "json_sub": server["json_sub"]
            }.items()},
            "login_url": f"{server['base_url']}/login",
            "server": server['base_url']
        }

        return server_data
