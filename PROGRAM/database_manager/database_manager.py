import mysql.connector
from mysql.connector import Error

from models.dosage_event import DosageEvent
from models.measurement import Measurement

class __DatabaseManager:
    def __init__(self):
        self.host = None
        self.user = None
        self.password = None
        self.database = None
        self.connection = None

    def setup_configuration(self, host="localhost", user="root", password="", database="dosing-rs"):
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

    def save_measurement(self, data: Measurement, tank_name: str):
        """
        Zapis pojedynczego pomiaru (mock).
        :param data: Measurement
        """
        print("\ntank_name: ", tank_name)
        print(f"[MOCK] Zapis pomiaru: {data}")
        print()

    def save_dosage(self, data: DosageEvent, tank_name: str):
        """
        Zapis pojedynczego dozowania (mock).
        :param data: DosageEvent
        """
        print("\ntank_name: ", tank_name)
        data.print_state()
        print()

    def close(self):
        """Zamknięcie połączenia z bazą."""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("Połączenie z MySQL zamknięte")

database_manager = __DatabaseManager()