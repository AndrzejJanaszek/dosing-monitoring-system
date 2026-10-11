import threading
from typing import Optional
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

        self.batch_update_event = threading.Event() # todo VVV
        # ma się zmianiać (ustawiać) po dodaniu gruszki
        # lub dozowania do gruszki

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

    def get_measurements(
            self, 
            tank_id: Optional[int] = None, 
            from_date: Optional[str] = None, 
            to_date: Optional[str] = None):
        """
        Pobiera pomiary z tabeli measurements z opcjonalnymi filtrami:
        - tank_id: int
        - from_date: str w formacie 'YYYY-MM-DD' lub 'YYYY-MM-DD HH:MM:SS'
        - to_date: str w formacie 'YYYY-MM-DD' lub 'YYYY-MM-DD HH:MM:SS'
        Zwraca listę słowników: [{"id":..., "value":..., "timestamp":..., "tank_id":...}, ...]
        """
        query = """
                SELECT m.id, m.value, m.timestamp, m.tank_id, t.tank_name
                FROM `akces-dms`.`measurements` AS m
                JOIN `akces-dms`.`tanks` AS t ON m.tank_id = t.id
                WHERE 1=1
            """
        params = []

        if tank_id is not None:
            query += " AND tank_id = %s"
            params.append(tank_id)

        if from_date is not None:
            query += " AND timestamp >= %s"
            params.append(from_date)

        if to_date is not None:
            query += " AND timestamp <= %s"
            params.append(to_date)

        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()

        return results

    def get_dosages(
        self,
        tank_id: Optional[int] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        is_collision: Optional[bool] = None
    ):
        """
        Pobiera dane z tabeli dosing_events z opcjonalnymi filtrami:
        - tank_id: int
        - from_date: str w formacie 'YYYY-MM-DD' lub 'YYYY-MM-DD HH:MM:SS'
        - to_date: str w formacie 'YYYY-MM-DD' lub 'YYYY-MM-DD HH:MM:SS'
        - is_collision: bool
        Zwraca listę słowników z wszystkimi kolumnami z dosing_events.
        """
        query = """
            SELECT d.id,
                d.value_start,
                d.value_end,
                d.timestamp_start,
                d.timestamp_end,
                d.is_collision,
                d.value_difference,
                d.collision_value_difference,
                d.time_difference,
                d.dosing_speed_factor,
                d.tank_id,
                d.type,
                t.tank_name
            FROM `akces-dms`.`dosing_events` AS d
            JOIN `akces-dms`.`tanks` AS t ON d.tank_id = t.id
            WHERE 1=1
        """
        params = []

        if tank_id is not None:
            query += " AND d.tank_id = %s"
            params.append(tank_id)

        if from_date is not None:
            query += " AND d.timestamp_start >= %s"
            params.append(from_date)

        if to_date is not None:
            query += " AND d.timestamp_end <= %s"
            params.append(to_date)

        if is_collision is not None:
            query += " AND d.is_collision = %s"
            params.append(is_collision)

        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()

        return results

    def get_batches(
        self,
        tank_id: Optional[int] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ):
        """
        Pobiera wszystkie batche (gruszki) z listą powiązanych dozowań.
        Każde dozowanie zawiera nazwę zbiornika.
        Opcjonalne filtry: tank_id, from_date, to_date
        """
        query = """
        SELECT 
            b.id AS batch_id,
            b.timestamp_start AS batch_start,
            b.timestamp_end AS batch_end,
            d.id AS dosage_id,
            d.value_start,
            d.value_end,
            d.timestamp_start AS dosage_start,
            d.timestamp_end AS dosage_end,
            d.is_collision,
            d.value_difference,
            d.collision_value_difference,
            d.time_difference,
            d.dosing_speed_factor,
            d.tank_id,
            d.type,
            t.tank_name
        FROM `akces-dms`.`batches` AS b
        LEFT JOIN `akces-dms`.`batch_dosing_event` AS bde ON b.id = bde.batch_id
        LEFT JOIN `akces-dms`.`dosing_events` AS d ON bde.dosing_event_id = d.id
        LEFT JOIN `akces-dms`.`tanks` AS t ON d.tank_id = t.id
        WHERE 1=1
        """
        params = []

        if tank_id is not None:
            query += " AND d.tank_id = %s"
            params.append(tank_id)

        if from_date is not None:
            query += " AND b.timestamp_start >= %s"
            params.append(from_date)

        if to_date is not None:
            query += " AND b.timestamp_end <= %s"
            params.append(to_date)

        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()

        # agregacja po batch_id
        batches = {}
        for row in results:
            batch_id = row["batch_id"]
            if batch_id not in batches:
                batches[batch_id] = {
                    "id": batch_id,
                    "timestampStart": row["batch_start"],
                    "timestampEnd": row["batch_end"],
                    "dosages": []
                }

            if row["dosage_id"] is not None:  # tylko jeśli istnieje dozowanie
                dosage = {
                    "id": row["dosage_id"],
                    "valueStart": row["value_start"],
                    "valueEnd": row["value_end"],
                    "timestampStart": row["dosage_start"],
                    "timestampEnd": row["dosage_end"],
                    "isCollision": bool(row["is_collision"]),
                    "valueDifference": row["value_difference"],
                    "collisionValueDifference": row["collision_value_difference"],
                    "timeDifference": row["time_difference"],
                    "dosingSpeedFactor": row["dosing_speed_factor"],
                    "tankId": row["tank_id"],
                    "tankName": row["tank_name"],
                    "type": row["type"]
                }
                batches[batch_id]["dosages"].append(dosage)

        return list(batches.values())

    def get_last_batch(self):
        """
        Zwraca ostatnią gruszkę z listą powiązanych dozowań.
        """
        # 1. Pobierz ostatnią gruszkę
        query_batch = """
        SELECT id, timestamp_start AS batch_start, timestamp_end AS batch_end
        FROM `akces-dms`.`batches`
        ORDER BY timestamp_start DESC
        LIMIT 1
        """
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(query_batch)
        batch_row = cursor.fetchone()
        if not batch_row:
            cursor.close()
            return None

        batch_id = batch_row["id"]
        batch = {
            "id": batch_id,
            "timestampStart": batch_row["batch_start"],
            "timestampEnd": batch_row["batch_end"],
            "dosages": []
        }

        # 2. Pobierz powiązane dozowania wraz z nazwami zbiorników
        query_dosages = """
        SELECT 
            d.id AS dosage_id,
            d.value_start,
            d.value_end,
            d.timestamp_start AS dosage_start,
            d.timestamp_end AS dosage_end,
            d.is_collision,
            d.value_difference,
            d.collision_value_difference,
            d.time_difference,
            d.dosing_speed_factor,
            d.tank_id,
            d.type,
            t.tank_name
        FROM `akces-dms`.`batch_dosing_event` AS bde
        JOIN `akces-dms`.`dosing_events` AS d ON bde.dosing_event_id = d.id
        JOIN `akces-dms`.`tanks` AS t ON d.tank_id = t.id
        WHERE bde.batch_id = %s
        """
        cursor.execute(query_dosages, (batch_id,))
        dosages_rows = cursor.fetchall()
        cursor.close()

        for row in dosages_rows:
            dosage = {
                "id": row["dosage_id"],
                "valueStart": row["value_start"],
                "valueEnd": row["value_end"],
                "timestampStart": row["dosage_start"],
                "timestampEnd": row["dosage_end"],
                "isCollision": bool(row["is_collision"]),
                "valueDifference": row["value_difference"],
                "collisionValueDifference": row["collision_value_difference"],
                "timeDifference": row["time_difference"],
                "dosingSpeedFactor": row["dosing_speed_factor"],
                "tankId": row["tank_id"],
                "tankName": row["tank_name"],
                "type": row["type"]
            }
            batch["dosages"].append(dosage)

        return batch

    def close(self):
        """Zamknięcie połączenia z bazą."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("Połączenie z MySQL zamknięte")

database_manager = __DatabaseManager()