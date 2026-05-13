- aplikacjia front
- core/backend
- testy jednostkowe
- testy integracyjne (symulacja sygnałów serial i sprawdzanie z expected values w bazie)


/frontend
/frontend/tests

/backend
/backend/tests

<!-- root directory for all api files -->
/backend/api


<!-- root directory for all core app file -->
/backend/core



Testowanie:
- unit testy; osobno dla frontu backendu itd
- integracyjne:
    - konfiguracja testowa obejmuje:
        opis obiektu: silosy, mierniki, itd
        scenariusze: zdarzenia na obiekcie
        oczekiwania: oczekiwane wyniki uruchomienia programu (odpowiednie rekordy w bazie)
    - przebieg testów:
        na podstawie pliku konfiguracyjnego zostaje odpalony kontener z programem
        kontener z symulacją danych z portów szeregowych i kontener z bazą danych
        po zakończeniu symulacji danz bazy porównywane są z oczekiwanymi i generowany jest raport testowy



wymagania do testowania:

zdarzenia tego samego typu nie mogą na siebie zachodzić, różnego typu tak

jeżeli dwa zbiorniki są pod tym samym miernikiem (serial outputem) to nie mogą mieć zdarzeń tego samego typu w tym samym czasie
np. out out | X
    in  in  | X
    out in  | ok

output:





config testy integracyjne



*serial_reader*
```
event_detector

while 1:
	snapshot = read_data()
	
	event_detector.notify(data=snapshot)
	
```

event_detector
```
old_data

norify(data):
    # json to obj

    for pin, value in data:
        if value != old_data[pin]
            # pop event
            # IN/OUT = ?
            # target_status = value == 1 ? start : end
            # pin = pin
            event(target_status, pin)
```

```

# map all pins to theri tanks
pin2tank = []

event(target_status, pin):
    tank = pin2tank[pin]
    measurement = serail_reader.get_measurement_data(
        tank.port
    )

    if target_status == 1   # -> start
        tank.set_event_start(pin, measurement)
    else:    
        tank.set_event_stop(pin, measurement)
        db.save(
            tank.get_event(pin), tank.id
        )
        tank.clear(pin)

```