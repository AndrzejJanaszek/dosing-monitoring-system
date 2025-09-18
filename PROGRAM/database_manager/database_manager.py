import mysql.connector
from mysql.connector import Error

from models.dosage_event import DosageEvent, EventType
from models.measurement import Measurement

class __DatabaseManager:
    def __init__(self):
        self.host = None
        self.user = None
        self.password = None
        self.database = None
        self.connection = None

    def setup_configuration(self, host="", user="", password="", database=""):
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.connection = None

    def connect(self):
        """Nawiązanie połączenia z bazą (z prostą obsługą błędów)."""
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database
            )
            if self.connection.is_connected():
                print("Połączono z MySQL")
        except Error as e:
            print(f"Błąd połączenia z MySQL: {e}")
            self.connection = None

    # todo tank_name zmienic na id i w configu to wpisywać
    # bo w bazie jest dodana relacja tank<->even; tank<->measurement
    def save_measurement(self, data: Measurement, tank_id: int):
        query = """
            INSERT INTO `akces-dms`.`measurements` (value, timestamp, tank_id)
            VALUES (%s, %s, %s)
        """
        values = (data.value, data.time, tank_id)

        with self.connection.cursor() as cursor:
            cursor.execute(query, values)
        self.connection.commit()

        # 
        # debug / mock
        # 
        print("\ntank_id: ", tank_id)
        print(f"[MOCK] Zapis pomiaru: {data}")
        print()

    def save_dosage(self, data: DosageEvent, tank_id: int, event_type_int: int):
        query = """
            INSERT INTO `akces-dms`.`dosing_events`
            (value_start, value_end, timestamp_start, timestamp_end,
            is_collision, value_difference, collision_value_difference,
            time_difference, dosing_speed_factor, tank_id, type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        event_type_name = EventType.IN.name if event_type_int == 0 else EventType.OUT.name

        values = (
            data.measurement_start.value,
            data.measurement_end.value,
            data.measurement_start.time,
            data.measurement_end.time,
            data.isCollision,
            data.value_difference,
            data.collision_difference,
            data.time_difference,
            data.dosing_speed_factor,
            tank_id,
            event_type_name
        )

        with self.connection.cursor() as cursor:
            cursor.execute(query, values)
        self.connection.commit()

        """
        Zapis pojedynczego dozowania (mock).
        :param data: DosageEvent
        """
        print("\ntank_id: ", tank_id)
        print("\nevent_type_int: ", event_type_int)
        print("\nevent_type_name: ", event_type_name)
        data.print_state()
        print()
    
    def save_tanks(self, tanks):
        query = """
            INSERT INTO `akces-dms`.`tanks` (id, tank_name)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE tank_name = VALUES(tank_name)
        """
        values = [(tank["id"], tank["name"]) for tank in tanks]

        with self.connection.cursor() as cursor:
            cursor.executemany(query, values)
        self.connection.commit()

    def get_tanks(self):
        query = "SELECT id, tank_name FROM `akces-dms`.`tanks`"
        with self.connection.cursor(dictionary=True) as cursor:
            cursor.execute(query)
            return cursor.fetchall()

    def get_measurements(self):
        pass

    def get_dosages(self):
        pass

    def get_batches(self):
        pass

    def close(self):
        """Zamknięcie połączenia z bazą."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("Połączenie z MySQL zamknięte")

database_manager = __DatabaseManager()