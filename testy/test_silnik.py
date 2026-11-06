import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import narzedzie as N  # noqa: E402
import ustawienia as U  # noqa: E402
from fast_flights.model import Airport, CarbonEmission, Flights, SimpleDatetime, SingleFlight  # noqa: E402
from zrodla import google, itaka, rainbow  # noqa: E402
from zrodla.wspolne import Odcinek, Podroz, Wynik, wczytaj_okna  # noqa: E402

DZIS = dt.date(2026, 11, 4)
D = dt.date
K = N.ustawienia({k: getattr(U, k) for k in dir(U) if k.isupper()})


def lot(cena, *odcinki, linie=("LOT",)):
    segs = [SingleFlight(Airport(a, a), Airport(b, b), SimpleDatetime(d1, t1), SimpleDatetime(d2, t2), m, "787")
            for a, b, d1, t1, d2, t2, m in odcinki]
    return Flights("x", cena, list(linie), segs, CarbonEmission(0, 0))


BEZ = lot(4900, ("WAW", "BKK", (2027, 2, 13), (14, 45), (2027, 2, 14), (7, 5), 620))
FRA = lot(3600, ("WAW", "FRA", (2027, 2, 13), (7, 0), (2027, 2, 13), (9, 0), 120),
          ("FRA", "BKK", (2027, 2, 13), (11, 0), (2027, 2, 14), (5, 0), 660), linie=("Lufthansa",))
DOH = lot(2800, ("WAW", "DOH", (2027, 2, 13), (7, 0), (2027, 2, 13), (15, 0), 360),
          ("DOH", "BKK", (2027, 2, 13), (17, 0), (2027, 2, 14), (5, 0), 400), linie=("Qatar",))
DLUGA = lot(2500, ("WAW", "PEK", (2027, 2, 13), (7, 0), (2027, 2, 13), (23, 0), 600),
            ("PEK", "BKK", (2027, 2, 14), (9, 0), (2027, 2, 14), (13, 0), 300))


def kryteria(**zmiany):
    return N.ustawienia({**{k: getattr(K, k) for k in vars(K)}, **zmiany})


def test_zakresy_dat():
    okna = wczytaj_okna(K, DZIS)
    assert [len(o.pary(DZIS)) for o in okna] == [28, 36]
    assert all(o.noce(w, r) >= 8 for o in okna for w, r in o.pary(DZIS))
    assert len(wczytaj_okna(K, D(2027, 2, 15))[0].pary(D(2027, 2, 15))) == 10


def test_nowe_kryteria_dat():
    k = kryteria(PRZYLOT_NASTEPNEGO_DNIA=False, MIN_NOCY_NA_MIEJSCU=7, MAKS_NOCY_NA_MIEJSCU=10,
                 DNI_WYLOTU=["sob"], OKNA=[{"nazwa": "Majówka", "od": "2027-04-24", "do": "2027-05-09"}])
    pary = wczytaj_okna(k, DZIS)[0].pary(DZIS)
    assert pary == [(D(2027, 4, 24), D(2027, 5, d)) for d in (1, 2, 3, 4)] + [(D(2027, 5, 1), D(2027, 5, 8)),
                                                                             (D(2027, 5, 1), D(2027, 5, 9))]


def test_filtry_przesiadek_i_linii():
    assert google.ocen(BEZ, K)["bezposredni"]
    o = google.ocen(FRA, K)
    assert o["przesiadki"] == [["FRA", 120]] and o["czas"] == 900 and o["linie"] == ["Lufthansa"]
    assert google.ocen(DOH, K) is None and google.ocen(DLUGA, K) is None
    assert google.ocen(FRA, kryteria(WYKLUCZONE_LINIE=["lufthansa"])) is None
    assert google.ocen(FRA, kryteria(MIN_PRZESIADKA_GODZ=3)) is None
    assert google.ocen(BEZ, kryteria(PREFEROWANE_LINIE=["LOT"]))["opis"].startswith("★")


def test_google_zbieranie_i_cele(monkeypatch):
    monkeypatch.setattr(google.time, "sleep", lambda s: None)
    monkeypatch.setattr(google.Pobieracz, "szukaj", lambda self, q: [BEZ, FRA, DOH])
    okna = wczytaj_okna(K, DZIS)
    w = google.pobierz(okna, K, DZIS, log=lambda *a: None)
    assert w.status == "ok" and w.zapytania == 128 + 60
    assert w.podroze[0].czas_tam and w.podroze[0].przes_pow is None
    k2 = kryteria(CELE_DODATKOWE=["DMK"])
    assert len(google.zadania(okna, k2, DZIS)) == 2 * (128 + 60)


def test_google_zapasowy_posrednik(monkeypatch):
    monkeypatch.setattr(google.time, "sleep", lambda s: None)
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", "x")
    p = google.Pobieracz()
    monkeypatch.setattr(p, "_bezposrednio", lambda q: (_ for _ in ()).throw(AttributeError("zgoda")))
    monkeypatch.setattr(p, "_przez_posrednika", lambda q: [BEZ])
    for _ in range(4):
        assert p.szukaj(None) == [BEZ]
    assert p.tryb == "pośrednik"


TEKST_RAINBOW = ("Wylot sob. 26 gru / 3 440 zł niedz. 27 gru / 3200 zł czw. 31 gru / 2600 zł "
                 "Wylot 26.12.2026: 3 440 zł/os. Katowice 15:30 Bangkok 07:40 "
                 "Powrót niedz. 03 sty / 2 100 zł niedz. 10 sty / 2300 zł")


def test_czytanie_czarterow():
    wyl, pow_ = rainbow.podziel(TEKST_RAINBOW)
    assert rainbow.lista_cen(wyl, DZIS)[D(2026, 12, 26)] == 3440
    assert rainbow.lista_cen(pow_, DZIS) == {D(2027, 1, 3): 2100, D(2027, 1, 10): 2300}
    assert rainbow.lotnisko_wylotu(TEKST_RAINBOW, D(2026, 12, 26), K.NAZWY_LOTNISK) == "KTW"
    assert itaka.terminy("28.12 - 05.01.2027 (8 dni) od 5 996 zł") == {(D(2026, 12, 28), D(2027, 1, 5)): 5996}


def strona_google(payload) -> str:
    import json
    return ("<html><script class=\"ds:1\">AF_initDataCallback({key: 'ds:1', hash: '2', data:"
            + json.dumps(payload) + ", sideChannel: {}});</script></html>")


def wynik_google(cena):
    seg = [None] * 22
    seg[3], seg[4], seg[5], seg[6] = "WAW", "Warszawa", "Bangkok", "BKK"
    seg[8], seg[10], seg[11], seg[17], seg[20], seg[21] = [14, 45], [7, 5], 620, "787", [2027, 2, 13], [2027, 2, 14]
    lot = [None] * 23
    lot[0], lot[1], lot[2], lot[22] = "LO", ["LOT"], [seg], [None] * 7 + [500, 520]
    return [lot, [[None, cena]] if cena else []]


def test_google_odporny_odczyt():
    # Trasa bez lotów: strona bez listy linii (payload[7]) – wcześniej IndexError, teraz „brak lotów”.
    with pytest.raises(google.FlightsNotFound):
        google.parse(strona_google([None, None, None, [None], None, None, None, [None, []]]))
    # Jeden wynik bez ceny nie psuje pozostałych.
    loty = google.parse(strona_google([None, None, None, [[wynik_google(4900), wynik_google(None)]],
                                       None, None, None, [None, []]]))
    assert [l.price for l in loty] == [4900]
    assert google.ocen(loty[0], K)["bezposredni"]
    assert google.ocen(loty[0], K)["rozklad"] == [["WAW", "14:45", "BKK", "07:05", 1]]
    assert google.ocen(FRA, K)["rozklad"] == [["WAW", "07:00", "FRA", "09:00", 0], ["FRA", "11:00", "BKK", "05:00", 1]]
    with pytest.raises(ValueError):
        google.parse("<html>okno zgody</html>")


# Prawdziwe fragmenty stron (listopad 2026): Rainbow po kliknięciu dnia, Itaka – lista ofert.
RAINBOW_2026 = """Wylot
Pt. 12 lut / 1720 zł
Sob. 13 lut / 2340 zł
Niedz. 14 lut / 2680 zł

Katowice (KTW)

18:00

Bangkok (BKK)

10:05

Bagaż 20 kg + 5 kg

2340 zł/os.

Warszawa Chopin (WAW)

14:45

Bangkok (BKK)

07:05

Bagaż 23 kg + 8 kg

2520 zł/os.
Powrót
Niedz. 21 lut / 3559 zł
Niedz. 28 lut / 3509 zł

Bangkok (BKK)

12:00

Katowice (KTW)

17:50

Bagaż 20 kg + 5 kg

3559 zł/os.
Ważne informacje
Sprawdź szczegóły lotów
Wylot 13.02.2027: 2 340 zł/os.
Powrót 21.02.2027: 3 559 zł/os."""

ITAKA_2026 = """23 oferty
Sortuj:
Najniższa cena
Wylot: poniedziałek, 28 gru
dane linii
Warszawa-Okęcie 19:30
(WAW)
10 godz. 20 min.
Bangkok 11:50
(BKK)
Powrót: wtorek, 5 sty
dane linii
Bangkok 13:45
(BKK)
11 godz. 50 min.
Warszawa-Okęcie 19:35
(WAW)
szczegóły lotu
6 496 zł
/os.
Rezerwuj
Wylot: poniedziałek, 4 sty
dane linii
Warszawa-Okęcie 19:30
(WAW)
Powrót: wtorek, 12 sty
dane linii
Bangkok 13:45
(BKK)
szczegóły lotu
5 996 zł
/os.
Rezerwuj
z 2
Kontakt"""


def test_rainbow_uklad_2026():
    wyl, pow_ = rainbow.podziel(RAINBOW_2026)
    assert rainbow.lista_cen(wyl, DZIS) == {D(2027, 2, 12): 1720, D(2027, 2, 13): 2340, D(2027, 2, 14): 2680}
    assert rainbow.lista_cen(pow_, DZIS) == {D(2027, 2, 21): 3559, D(2027, 2, 28): 3509}
    assert rainbow.karty(RAINBOW_2026, K.NAZWY_LOTNISK) == [
        ("KTW", 2340, [["KTW", "18:00", "BKK", "10:05", 1]]), ("WAW", 2520, [["WAW", "14:45", "BKK", "07:05", 1]])]
    assert rainbow.godziny_powrotu(RAINBOW_2026) == [["BKK", "12:00", "KTW", "17:50", 0]]
    assert rainbow.lotnisko_wylotu(RAINBOW_2026, D(2027, 2, 13), K.NAZWY_LOTNISK) == "KTW"
    assert rainbow.lista_cen("Sob. 26 GRU / 3 440 zł", DZIS) == {D(2026, 12, 26): 3440}
    # Rainbow sprzedaje te ceny tylko w parze: wylot + powrót = jedna podróż czarterowa, bez łączenia z innymi.
    kod, cena, godz_tam = rainbow.karty(RAINBOW_2026, K.NAZWY_LOTNISK)[0]
    podr = rainbow.pary(K, kod, D(2027, 2, 13), cena, godz_tam, rainbow.lista_cen(pow_, DZIS),
                        rainbow.godziny_powrotu(RAINBOW_2026))
    assert [(p.rodzaj, p.wylot, p.powrot, p.cena, p.dwa_bilety) for p in podr] == [
        ("czarter", D(2027, 2, 13), D(2027, 2, 21), 2340 + 3559, False),
        ("czarter", D(2027, 2, 13), D(2027, 2, 28), 2340 + 3509, False)]
    assert podr[0].rozklad_pow == [["BKK", "12:00", "KTW", "17:50", 0]] and podr[1].rozklad_pow is None
    okno = wczytaj_okna(kryteria(OKNA=[{"nazwa": "Luty", "od": "2027-02-12", "do": "2027-02-28"}]), DZIS)[0]
    lista = N.podroze_w_oknie(K, okno, {"rainbow": Wynik("rainbow", podroze=podr), "google": Wynik("google", odcinki=[
        Odcinek("google", False, "powrot", "KTW", D(2027, 2, 21), 1000, "x", True, "g", cel="BKK")])}, DZIS)
    assert {p.rodzaj for p in lista} == {"czarter"}    # brak „czarter tam, rejsowy z powrotem”


def test_itaka_uklad_2026():
    assert itaka.terminy(ITAKA_2026, DZIS) == {(D(2026, 12, 28), D(2027, 1, 5)): 6496,
                                               (D(2027, 1, 4), D(2027, 1, 12)): 5996}
    assert itaka.STRONY.search(ITAKA_2026).group(1) == "2"
    assert itaka.godziny(ITAKA_2026, DZIS)[(D(2026, 12, 28), D(2027, 1, 5))] == (
        [["WAW", "19:30", "BKK", "11:50", 1]], [["BKK", "13:45", "WAW", "19:35", 0]])
    assert itaka.godziny(ITAKA_2026, DZIS)[(D(2027, 1, 4), D(2027, 1, 12))] == (None, None)   # niepełna karta
    assert itaka.czasy(ITAKA_2026, DZIS)[(D(2026, 12, 28), D(2027, 1, 5))] == (620, 710)


def test_google_drugi_krok_powroty(monkeypatch):
    import base64
    from fast_flights.pb.flights_pb2 import Info
    monkeypatch.setattr(google.time, "sleep", lambda s: None)
    q = google.zapytanie(K, "WAW", "BKK", D(2027, 2, 14), D(2027, 2, 24))
    k2 = google.Krok2(q, [["WAW", "2027-02-14", "ZRH", "LX", "1349"], ["ZRH", "2027-02-14", "BKK", "LX", "180"]])
    surowe = base64.b64decode(k2.tfs)
    info = Info.FromString(surowe)
    assert [d.from_airport.airport for d in info.data] == ["WAW", "BKK"]   # kolejność kierunków zachowana
    assert b"1349" in info.data[0].SerializeToString() and b"1349" not in info.data[1].SerializeToString()
    assert "tfs=" in k2.url() and k2.params()["curr"] == "PLN"

    def lot_pow(cena, *odc, linie=("Austrian",)):
        return lot(cena, *odc, linie=linie)
    dobry = lot_pow(4697, ("BKK", "VIE", (2027, 2, 24), (23, 50), (2027, 2, 25), (5, 25), 695),
                    ("VIE", "WAW", (2027, 2, 25), (8, 10), (2027, 2, 25), (9, 25), 75))
    za_dluga_przesiadka = lot_pow(4500, ("BKK", "VIE", (2027, 2, 24), (8, 0), (2027, 2, 24), (14, 0), 660),
                                  ("VIE", "WAW", (2027, 2, 24), (22, 0), (2027, 2, 24), (23, 15), 75))

    class Pob:
        def __init__(self, odp):
            self.odp = odp

        def szukaj(self, q):
            return self.odp

    def bilet():
        p = Podroz("google", "rejsowy", "WAW", "WAW", D(2027, 2, 14), D(2027, 2, 24), 4697, "przez ZRH", False,
                   ["g1"], cel="BKK", linie=["SWISS"], przes_tam=[["ZRH", 120]], przes_pow=None, czas_tam=780)
        p.krok2 = (q, [["WAW", "2027-02-14", "ZRH", "LX", "1349"]])
        return p

    w = Wynik("google", podroze=[bilet()])
    google.dopasuj_powroty(w, Pob([za_dluga_przesiadka, dobry]), K, log=lambda *a: None)
    p = w.podroze[0]
    assert p.cena == 4697 and p.przes_pow == [["VIE", 165]] and p.linie == ["SWISS", "Austrian"]
    assert p.rozklad_pow == [["BKK", "23:50", "VIE", "05:25", 1], ["VIE", "08:10", "WAW", "09:25", 1]]
    assert p.linki[0].startswith("https://www.google.com/travel/flights/search?") and "krok2" not in vars(p)
    w2 = Wynik("google", podroze=[bilet()])
    google.dopasuj_powroty(w2, Pob([za_dluga_przesiadka]), K, log=lambda *a: None)
    assert w2.podroze == []          # żaden powrót nie spełnia kryteriów → bilet odrzucony


def test_google_warunki_dla_powrotu():
    # Limity podróży i przesiadek idą do Google dla OBU kierunków (powrót wybiera się w drugim kroku).
    assert google.filtry(K) == {"max_duration_minutes": 17 * 60, "max_layover_minutes": 4 * 60}
    assert google.filtry(kryteria(MIN_PRZESIADKA_GODZ=1.5))["min_layover_minutes"] == 90
    q = google.zapytanie(K, "WAW", "BKK", D(2026, 12, 26), D(2027, 1, 4))
    info = q.pb() if hasattr(q, "pb") else None
    if info is not None:
        assert [d.max_duration_minutes for d in info.data] == [1020, 1020]
        assert [d.max_layover_minutes for d in info.data] == [240, 240]
    okno = wczytaj_okna(K, DZIS)[0]
    p = Podroz("google", "rejsowy", "WAW", "WAW", D(2026, 12, 27), D(2027, 1, 6), 5100, "x", True, ["g"],
               przes_pow=None, czas_tam=620)
    assert N.jako_dane(p, okno, K)["powrot_limit"] == {"czas": 1020, "przesiadka": 240, "przesiadek": 1}
    assert N.jako_dane(wyniki_przykladowe()["itaka"].podroze[0], okno, K)["powrot_limit"] is None


def wyniki_przykladowe():
    def o(zr, cz, k, l, d, c, b=True, linie=None):
        return Odcinek(zr, cz, k, l, d, c, zr, b, f"https://{zr}", cel="BKK", linie=linie or [zr],
                       przesiadki=[] if b else [["HEL", 110]], czas_min=None if cz else (620 if b else 800))
    return {
        "google": Wynik("google", podroze=[
            Podroz("google", "rejsowy", "WAW", "WAW", D(2026, 12, 27), D(2027, 1, 6), 5100, "LOT", True, ["g"],
                   cel="BKK", linie=["LOT"], czas_tam=620, przes_pow=None),
            Podroz("google", "rejsowy", "WAW", "WAW", D(2026, 12, 27), D(2027, 1, 6), 4100, "przez HEL", False, ["g"],
                   cel="BKK", linie=["Finnair"], przes_tam=[["HEL", 110]], czas_tam=800, przes_pow=None),
        ], odcinki=[
            o("google", False, "powrot", "KTW", D(2027, 1, 5), 2000, False, ["Lufthansa"]),
            o("google", False, "tam", "WAW", D(2026, 12, 26), 2500),
            o("google", False, "powrot", "WAW", D(2027, 1, 5), 2600),
        ]),
        "rainbow": Wynik("rainbow", odcinki=[
            o("rainbow", True, "tam", "KTW", D(2026, 12, 26), 3440),
            o("rainbow", True, "powrot", "KTW", D(2027, 1, 5), 2300),
            o("rainbow", True, "powrot", "KTW", D(2027, 1, 3), 1500),
            o("rainbow", True, "tam", "?", D(2026, 12, 31), 2600),
        ]),
        "itaka": Wynik("itaka", podroze=[
            Podroz("itaka", "czarter", "WAW", "WAW", D(2026, 12, 28), D(2027, 1, 5), 5996, "Itaka", True, ["i"])]),
    }


def test_laczenie_i_zasady():
    okno = wczytaj_okna(K, DZIS)[0]
    lista = N.podroze_w_oknie(K, okno, wyniki_przykladowe(), DZIS)
    opisy = {(p.rodzaj, p.lotnisko_wylotu, p.cena) for p in lista}
    assert ("czarter", "KTW", 5740) in opisy and ("mieszany", "KTW", 5440) in opisy and ("rejsowy", "WAW", 5100) in opisy
    mieszany = next(p for p in lista if p.rodzaj == "mieszany")
    assert mieszany.linie == ["rainbow", "Lufthansa"] and mieszany.przes_pow == [["HEL", 110]]
    assert not any(p.cena == 5996 for p in lista)
    assert [p.cena for p in N.prawie(okno, wyniki_przykladowe())] == [5996]


def test_polecam():
    okno = wczytaj_okna(K, DZIS)[0]
    lista = N.podroze_w_oknie(K, okno, wyniki_przykladowe(), DZIS)
    assert N.polecam(K, lista) is None
    p, powod = N.polecam(kryteria(DOPLATA_ZA_BEZPOSREDNI=1000), lista)
    assert p.bezposredni and p.cena == 5100 and "1 000 zł drożej" in powod
    p, powod = N.polecam(kryteria(PREFEROWANE_LOTNISKO="KTW", DOPLATA_ZA_PREFEROWANE_LOTNISKO=1500), lista)
    assert p.lotnisko_wylotu == "KTW" and p.cena == 5440


def test_analiza_dla_aplikacji():
    okna = wczytaj_okna(K, DZIS)
    wyn = wyniki_przykladowe()
    wyn["itaka"].status, wyn["itaka"].uwaga = "błąd", "nie odczytano terminów"
    historia = [{"data": "2026-11-03", "okno": "Święta i Nowy Rok", "kategoria": "najtaniej", "cena": 4300},
                {"data": "2026-10-27", "okno": "Święta i Nowy Rok", "kategoria": "najtaniej", "cena": 4500}]
    zdrowie = N.aktualizuj_zdrowie({"itaka": {"problemy_z_rzedu": 2}}, wyn, DZIS)
    w = N.przeanalizuj(kryteria(BUDZET_MAKS=5500, WYSYLAJ="spadek"), okna, wyn, DZIS, historia, zdrowie)
    o = w["najnowsze"]["okna"][0]
    assert o["kategorie"][0]["cena"] == 4100 and o["kategorie"][0]["trend"]["poprzednio"] == 4300
    assert all(p["cena"] <= 5500 for p in o["polaczenia"]) and len(o["polaczenia"]) == o["liczba"]
    assert {"noce", "linie", "czas_tam", "przes_tam"} <= set(o["polaczenia"][0])
    assert w["mail"]["wyslij"] and w["mail"]["temat"].startswith("UWAGA")
    assert "Święta od 4 100 zł ▼200 zł" in w["mail"]["temat"]
    assert w["najnowsze"]["okna"][1]["kategorie"] == [] and w["historia_dzis"][0]["cena"] == 4100
    w2 = N.przeanalizuj(kryteria(BUDZET_MAKS=3000), okna, wyniki_przykladowe(), DZIS, [], {})
    assert w2["najnowsze"]["okna"][0]["poza_budzetem"]["cena"] == 4100
    import json
    json.dumps(w)   # dane muszą dać się wysłać do aplikacji
