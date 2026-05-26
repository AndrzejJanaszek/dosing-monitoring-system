### Opis obiektu:
N `silosów` --> N `mierników` mierzących ich zawartość \
*`silos` może być podzielony na poł - dwa `zbiorniki`
czyli liczba `zbiorników` = <N, 2N>

na każdy `zbiornik` przypadają dwa `sygnały cyfrowe` (0 lub 1), od teraz nazywane `sygnałami DR` od dispense/refil, które określają czy aktualnie nastepuje `dozowanie` lub `uzupełnienie` (zbiornika).

`Arduino` przyjmuje `sygnały DR` przetwarza je na JSON: który każdemu pinowi przypisuje wartość 0/1.
```json
{
    // "pin": "value",
    "0": "0",
    "1": "0",
    // ...
    "2": "1",
} 
```
`Arduino` wysyła tego JSON'a przez USB do `komputera docelowego`, który zawiera `oprogramowanie główne/zasadnicze`.

Dane z `mierników` wysyłane po RS232 do `komputera docelowego` (pośredniczą w tym przejściówki RS232-USB aby przekonwertować sygnał).

`Komputer docelowy` ma zatem:
- podpięte peryferia (monitor, myszka, klawiatura)
- połączenie USB z `arduino`
- oraz połaczenia z `miernikami` po RS232 przez przejściówki. Najprawdopodobniej przez HUB usb.

### Funkcjonalności

`System` odpowiedzialny jest za:
- cykliczne zapisywanie danych z `mierników` (danych liczbowych o zawartosci zbiornika)
- zapisywanie informacji o `zdarzeniach` czyli dozowaniach i uzupełnieniach (`dispense`, `refil`)
- wyświetlanie danych w czasie rzeczywistym w `widoku głównym`. \
**Dane:** 
    - aktualne rzeczywiste wskazania z mierników dla zbiorników
    - ostatnie `zdarzenia`
    - ostatnia/aktualna gruszka jeżeli jest taka opcja włączona (`dozowania` przypadające na tę gruszkę)
    - wartości teoretyczne - wylczone na podstawie zdarzeń i punktu odniesienia (ustalonej wartości zbiornika)
- możliwość analizy danych w `widoku analizy` \
Analiza `danych cyklicznych` jak i `zdarzeń` - odpowiednie filtrowanie, po dacie zbiornikach itd., wykresy dla tych danych jak oraz forma tabelaryczna.
- analizę kolizji `zdarzeń`. \
kolizja to nałożenie się na siebie obu `zdarzeń` na jednym zbiorniku - jednoczesne odsypywanie i zasypywanie. \
Ze względu na teoretycznie względnie jednostajną szybkość odsypywanie istnieje możliwość wyliczenia teoretyczniej wartości odsypanej oraz zasypanej. Mając czasy rozpoczęcia i zakończenia obu zdarzeń i `średnią szybkość odsypwania`* w danym zbiorniku jesteśmy w stanie policzyć ile zostało odsypane a co za tym idzie ile zasypano materiału. Oba takie zdarzenia musza zostac oznaczone jako `kolizja`. Oprócz standardowego zapisanie ich danych pomiarowcyh dodatkowo zapisujemy dane policzone - teoretyczne. \
 \
 *`średnia szybkość odsypywania` - średnia z ostatnich N pomiarów **bezkolizyjnych**

### Konfiguracja

`Konfiguracja systemu` odbywa się poprzez plik konfiguracyjny, w którym ustawiane są fizyczne zalezności obiektu, jak i stałe typu czas cyklicznego zapisu.

Przypisanie danych z miernika (danego serial portu) do zbiornika odbywa się poprzez zadanie portu fizycznego.

TODO \
opcja 1: \
zdefiniowanie osobno zbiorników i osbno serial portów i połaczenie ich zaleznością. Wtedy dla przypadku w którym dwa zbiorniki są w jednym silosie i podsługują się wskazaniami z jednego miernika, nie trzeba się powtarzać w przypisywaniu portu, i programowo nie trzeba osobno sprawdzać czy zbiorniki mają przypisany ten sam port.

### Architektura (CORE'u)

Program rozbity jest na moduły:
- db_manager - połaczenie i wykonywanie zapytań
- serial_manager - połączenia serial portu, odczytywanie i zapisywanie ich snapshotów - udostępnienie api do odczytywania tych snapshotów.
- observer (todo nazwa) - obserwuje dane JSON z Arduino i jeżeli zmieni się stan - zajdzie zdarzenie - zaczyna je obsugiwać (w zależności od typu zdarzenia odczytanie danych i lub zapis do bazy, ewentulne wyliczenia dla kolizji) [*być może tylko deleguje obsługę]
- API - api dla frontednu umożliwiające analizę danych i podpięcie się do strumieniowania wskazań rzeczywistych zbiorników.








# opis 

schemat obiektu (zbiorniki, pc, arduino połączenia)

schemat `zbiornik == silos` i `zbiornik =/= silos`




-----------------------------------------

Obrazek:
połaczenia silosów mierników arduino i pc

Obrazek:
jeden silos może mieć w sobie dwa zbiorniki - przypadek 1 silos 2 zbiorniki 1 miernik



Zdania systemu:
- cykliczne zapisywanie stanu zbiorników
- zapisywanie informacji o zdarzeniach (odsypywanie, zasypywanie)
- Wyświetlanie danych w czasie rzeczywistym ()
- ... itd są na gorze wypisane trzeba pprzepisać

problemy:
- Jeden silos może być dwoma zbiornikami
- Doprowadzenie do łatwego wdrażania systemu (przygotowanie maszyny, instalacja oprogramowania, konfiguracja) 
- identyfikacja urzadzeń (miernikow) 
























zdarzenia
wskazania rzeczywiste
wskazania przeliczone
gruszka
komputer docelowy






---
### Opracowanie systemu monitorującego zbiorniki/silosy na betoniarni. 
Obejmuje:
- zapis cykliczny wskazań z silosów
- zapis zdarzeń (odyspywanie, zasypywanie)
- widok główny:
    - akutalne wskazania rzeczywiste oraz przeliczone
    - ostatnie zdarzenia (per zbiornik) 
    - aktualną/ostatnią gruszkę jeżeli jest taka opcja dostępna i właczona
- widok analizy - do analizy danych (możliwośc odpowiedniego sortowania itd.)

*Ostatnia gruszka* - być może zostanie dodana opcja, która zapisuje i wyświetla dane o ostatniej gruszcze (betoniarce). 
Czujnik/i będą wykrywały czy pojazd podjechał w odpowiednie miejsce i jeżeli tam się znajduje to dozowania które się odbywaja w tym czasie będą zaliczane do tego pojazdu. Jeżeli odjedzie to taka grupa odsypów będzie zakończona i będzie wyświetlać się do rozpoczęcia kolejnej.

```
Pomiar:
- czas
- wartosc
```

```
zdarzenie:
- typ (IN,OUT)
- pomiar początek i koniec
- czy kolizja
- itd
```
---

### Po co?
Program da możliwośc diagnozy wagi oraz obiektu poprzez dostęp do zapisywanych danych.
Dzięki zapisowi cyklicznemu z mierników będzie można przeanalizować jak waga zachowuje się w czasie (np. analiza zmiany wskazań od zmiany temperatury w czasie dnia).
Dzięki zapisowi zdarzeń bedzie można potencjalnie wykryć wcześniej wadę wagi, czy fizyczną usterkę obiektu poprzez porównanie danych zapisanych przez program do wartości, które powinny być w teorii np.:
- powinni przywieźć 40 ton cementu a system pokazuje że zasypane zostało 35 ton. (być może waga nie działa prawidłowo, być może ktoś próbował oszukać betoniarnię na zakup cementu)
- załóżmy, że średnio na gruszkę powinniśmy sypać 5 ton cementu, zrobiliśmy w dzień 10 gruszek i okazuje się że z wyliczeń dozowaliśmy nie 50 a 60 ton (być może problem z wagą a być może problem z mechanizmem dozowania - np. zepsuta śruba odsypu)

W przypadku faktycznej awarii mechanizmu pozwoliłoby to prawdopodobnie wykryć taką awarię o wiele wcześniej niż bez tego systemu monitorującego, co mogłoby zaoszczędzić dziesiatki czy setki tysięcy złotych.
np. Zamiast zorientować się że mechanizm dozowania psuje się, w momencie kiedy zbiornik jest pusty, lub jest w nim np. 20t zamiast 40t co oznaczałoby że problem występuje już dłuższy czas, instniałaby możliwość zaobserwowania tego problemu wcześniej.


---

Opis obiektu i zasady działania systemu monitorującego:

Na każdy silos przypada miernik, który wysyła wskazania (masę zawartości silosu) po RS232. 
Na każdy zbiornik (może się zdarzyć, że jeden silos ma w sobie dwa zbiorniki) przypadają dwa sygnały cyfrowe których wartość świadczy o stanie (aktywny - 1, nieaktywny - 0) odpowiedniego zdarzenia (odsypu lub zasypu).

Za odczyt sygnałów cyfrowych odpowiada arduino, które następnie wysyła w formacie json te dane do komputera docelowego po USB.

Komputer docelowy odpowiedzialny jest za odczyt danych z mierników (po RS232 - zastosowanie przejściówki RS232-USB) oraz arduino. Komputer docelowy przetwarza te dane, zapisuje i umożliwia ich analizę.

Program ma działać jak usługa systemowa startujaca automatycznie po włączeniu maszyny.

---

Problemy:
---
2 zbiorniki w jedyn silosie (dane z tego samego miernika - ten sam port szeregowy).
Założenie - zdarzenia tego samego typu nie mogą dziać się jednocześnie na dwóch.

przykład ( zbiornik lewy (L) i prawy (P) )
L zasyp - P odsyp   |   moze być
L odsyp - P odsyp   |   NIE może być

---
Odpowiednia niezawodność i obsługa błędów

--- 
(nice to have)
Naprawialność i konfigurowalność zdalna (na tyle na ile jest to możliwe)

---
Względnie łatwa wdrażalność. 
System napisany na tyle konfigurowalnie aby można było łatwo dostosować go do nowego obiektu lub jego rozszerzenia (np. o kolejny zbiornik)

Wzglednie proste i automatyczne wdrażanie - zautomatyzowany proces stawiania nowej maszyny:

automatycznie (lub pół automatycznie):
- instalacja systemu operacyjnego
- instalacja zależności (najprawdopodobniej docker)
- instalacja programu

Manualnie:
- konfiguracja systemu pod dany obiekt

---
Poprawna identyfikacja mierników
- 1 po fizycznym porcie USB w maszynie (komputerze docelowym)
- 2 po numerze wysyłanym przez miernik razem z danymi
- 3 (odrzucony) identyfikacja po numerze zapisanym w przejściówce

---
W momencie kolizji przeliczanie wartości teoretycznych, czyli na podstawie średniej szybkości dozowania w danym zbiorniku.
Jeżeli dozowanie i zasyp kolidują to róznica wskazania końcowego i początkowego nie będzie prawdziwą wartością dozowaną/zasypaną.
Na podstawie czasu odsypu i średniej szybkości odsypu można wyliczyć teoretyczną odsypaną wartość, a co za tym idzie również wartość zasypaną.

Średnia prędkość odsypu będzie najprawdopodobniej wyznaczana z ostatnich N odsypów z brakiem kolizji.