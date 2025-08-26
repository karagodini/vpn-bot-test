"""
Этот модуль содержит состояния для различных этапов взаимодействия с пользователем в рамках бота.

Каждое состояние представляет собой класс, наследующий от `StatesGroup` библиотеки `aiogram.fsm.state`, который используется для управления различными этапами работы с пользователем. В частности, состояния обрабатывают такие действия, как ввод данных о клиентах, работу с промокодами, подтверждение платежей, управление серверами и многое другое.

Основные классы состояний:

- **TrialPeriodState**: Управление состоянием для обработки периода пробного использования.
- **Database**: Класс для работы с базой данных, получением данных по email.
- **AddClient**: Состояния для добавления нового клиента, включая данные о платеже, сроках и методе оплаты.
- **GetConfig**: Состояния для ввода и получения конфигурации.
- **UpdClient**: Состояния для обновления информации о клиенте.
- **ManagePromoCodeState**: Управление состоянием для удаления промокодов.
- **BroadcastState**: Состояния для отправки широковещательных сообщений.
- **AddPromoCodeState**: Ввод данных для добавления нового промокода.
- **PromoCodeState**: Ввод промокода для использования.
- **AddServerState**: Состояния для добавления нового сервера.
- **ChangeServerIdsState**: Состояния для изменения идентификаторов серверов.
- **EditServerState**: Состояния для редактирования серверных данных.
- **ServerGroupForm**: Состояния для создания и управления группами серверов.
- **ServerStates**: Состояния для обработки информации о сервере и клиентах.

Каждое состояние помогает пользователю пройти через определённые шаги процесса, взаимодействуя с системой в рамках чат-бота.
"""

from aiogram.fsm.state import State, StatesGroup
import sqlite3

class TrialPeriodState(StatesGroup):
    waiting_for_answer = State()

class Database:
    def __init__(self, db_path):
        self.connection = sqlite3.connect(db_path)
        self.cursor = self.connection.cursor()

    def get_ids_by_email(self, email):
        query = """
            SELECT user_id
            FROM user_emails
            WHERE email = ?
        """
        self.cursor.execute(query, (email,))
    
        user_ids = [row[0] for row in self.cursor.fetchall()]

        return user_ids

class AddClient(StatesGroup):
    WaitingForPayment = State()
    WaitingForExpiryTime = State()
    WaitingForCountry = State()
    WaitingForPaymentMethod = State()
    WaitingForEmail = State()

class GetConfig(StatesGroup):
    EmailInput = State()
    
class UpdClient(StatesGroup):
    WaitingForEmail = State()
    WaitingForPayment = State()
    WaitingForPaymentMethod = State()

class ManagePromoCodeState(StatesGroup):
    WaitingForDeleteConfirmation = State()
    
class BroadcastState(StatesGroup):
    waiting_for_message = State()
    confirm_broadcast = State()
    
class AddPromoCodeState(StatesGroup):
    WaitingForCode = State()
    WaitingForDiscount = State()

class PromoCodeState(StatesGroup):
    WaitingForPromoCode = State()
    
class AddServerState(StatesGroup):
    waiting_for_data = State()

class ChangeServerIdsState(StatesGroup):
    waiting_for_server_ids = State()

class EditServerState(StatesGroup):
    waiting_for_param = State()
    
class ServerGroupForm(StatesGroup):
    waiting_for_group_name = State()
    waiting_for_server_ids = State()

class ServerStates(StatesGroup):
    processing_email = State()
    
class ManageServerGroupState(StatesGroup):
    WaitingForCluster = State()
