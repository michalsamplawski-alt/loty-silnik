# KRYTERIA WYSZUKIWANIA – wszystko, co decyduje o tym, czego szukamy, jest w tym pliku.

# Zakresy dat: wylot najwcześniej "od", powrót najpóźniej "do".
# Sprawdzane są WSZYSTKIE kombinacje wylotu i powrotu w zakresie, które dają
# co najmniej MIN_NOCY_NA_MIEJSCU nocy w Tajlandii.
OKNA = [
    {"nazwa": "Święta i Nowy Rok", "krotko": "Święta", "od": "2026-12-26", "do": "2027-01-10"},
    {"nazwa": "Luty", "krotko": "Luty", "od": "2027-02-12", "do": "2027-02-28"},
]

# Przylot do Bangkoku jest dzień po wylocie z Polski, więc powrót najwcześniej
# (MIN_NOCY_NA_MIEJSCU + 1) dni po wylocie. 8 nocy = co najmniej 8 pełnych dni na miejscu.
MIN_NOCY_NA_MIEJSCU = 8

LOTNISKA_WYLOTU = ["WAW", "KTW"]
POWROT_NA_INNE_LOTNISKO = False   # True = dopuszczaj np. wylot z KTW i powrót do WAW
CEL = "BKK"

LICZBA_OSOB = 1                   # ceny zawsze za osobę; przy więcej niż 1 raport pokaże też sumę
BAGAZ_REJESTROWANY = 0            # 1 = w lotach rejsowych dolicz opłatę za walizkę (czartery mają ją w cenie)

# Loty z przesiadką
MAKS_PRZESIADEK = 1
MAKS_PRZESIADKA_GODZ = 4          # dłuższe przesiadki są pomijane
MAKS_CZAS_PODROZY_GODZ = 17       # cała podróż w jedną stronę
WYKLUCZONE_PRZESIADKI = [         # Bliski Wschód – pomijane
    "DXB", "DWC", "SHJ", "AUH", "DOH", "BAH", "KWI", "MCT", "RUH", "JED", "DMM",
    "MED", "AMM", "TLV", "BEY", "CAI", "IKA", "BGW", "EBL",
]
OZNACZ_PRZESIADKI = {"IST": "Stambuł", "SAW": "Stambuł"}   # dopuszczone, ale oznaczone

# Gdy najniższa cena (za osobę, w obie strony) spadnie do tej kwoty – w temacie maila "OKAZJA".
CENA_DOCELOWA = None              # np. 3500

ILE_W_RAPORCIE = 5                # ile najtańszych terminów pokazać w każdym zakresie

# Źródła danych
ZRODLA = {"google": True, "rainbow": True, "itaka": True}
SPRAWDZAJ_W_JEDNA_STRONE = True   # osobne bilety tam i z powrotem – potrzebne do łączenia z czarterem
PRZERWA_SEK = (1.5, 4.0)          # odstęp między zapytaniami do Google

RAINBOW_URL = "https://r.pl/bilety-czarterowe/tajlandia/bangkok"
ITAKA_URL = "https://www.itaka.pl/bilety-lotnicze/warszawa-do-bangkok/"
ITAKA_LOTNISKO = "WAW"

NAZWY_LOTNISK = {
    "Warszawa": "WAW", "Katowice": "KTW", "Poznań": "POZ", "Kraków": "KRK", "Gdańsk": "GDN",
    "Wrocław": "WRO", "Rzeszów": "RZE", "Łódź": "LCJ", "Lublin": "LUB", "Bydgoszcz": "BZG",
    "Szczecin": "SZZ",
}
