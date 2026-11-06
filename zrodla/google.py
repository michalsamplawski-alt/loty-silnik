"""Loty rejsowe (wszystkie linie) z Google Flights.

Pobieranie dwutorowe:
1. bezpośrednio (za darmo),
2. gdy Google zacznie blokować – automatycznie przez Bright Data (płatne za udane zapytanie,
   ok. 1,5 USD za 1000). Wymaga sekretu BRIGHT_DATA_API_KEY; bez niego działa tylko tor 1.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import time

import json

import primp
from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query
from fast_flights.model import Airport, CarbonEmission, Flights, SimpleDatetime, SingleFlight
from fast_flights.parser import _parse_time
from selectolax.lexbor import LexborHTMLParser

from .wspolne import Odcinek, Podroz, Wynik, godz


def _lot(k) -> Flights | None:
    """Jeden wynik z danych strony; None, gdy niepełny (np. lot bez ceny)."""
    try:
        lot, cena = k[0], k[1][0][1]
        if not cena:
            return None
        odcinki = [SingleFlight(
            from_airport=Airport(code=s[3], name=s[4]), to_airport=Airport(code=s[6], name=s[5]),
            departure=SimpleDatetime(date=tuple(s[20]), time=_parse_time(s[8])),
            arrival=SimpleDatetime(date=tuple(s[21]), time=_parse_time(s[10])),
            duration=s[11], plane_type=s[17]) for s in lot[2]]
        try:
            emisja = CarbonEmission(typical_on_route=lot[22][8], emission=lot[22][7])
        except (IndexError, TypeError):
            emisja = CarbonEmission(0, 0)
        return Flights(type=lot[0], price=cena, airlines=lot[1], flights=odcinki, carbon=emisja)
    except (IndexError, TypeError, KeyError):
        return None


def parse(html: str) -> list[Flights]:
    """Odporny odczyt wyników Google Flights (zamiast fast_flights.parser.parse).

    Biblioteka wywraca się, gdy na trasie nie ma lotów (strona bez listy linii) albo gdy jeden
    z wyników nie ma ceny – wtedy całe zapytanie przepadało. Tu: brak lotów = FlightsNotFound,
    a niepełne wyniki są pomijane pojedynczo. Inne wyjątki = strony nie dało się odczytać.
    """
    skrypt = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if skrypt is None:
        raise ValueError("brak danych wyników na stronie (blokada lub okno zgody?)")
    dane = skrypt.text().split("data:", 1)[1].rsplit(",", 1)[0]
    if dane.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights found; received error")
    payload = json.loads(dane)
    try:
        surowe = payload[3][0]
    except (IndexError, TypeError):
        surowe = None
    if not surowe:
        raise FlightsNotFound("brak lotów na tej trasie")
    return [lot for lot in map(_lot, surowe) if lot]

URL = "https://www.google.com/travel/flights"
# Zgoda na ciasteczka Google – bez niej z europejskiego IP przychodzi okno zgody zamiast wyników.
ZGODA = {"SOCS": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg", "CONSENT": "YES+"}


class Pobieracz:
    def __init__(self) -> None:
        self.klient = primp.Client(impersonate="chrome_145", impersonate_os="macos",
                                   cookie_store=True, timeout=40)
        klucz = os.environ.get("BRIGHT_DATA_API_KEY")
        self.posrednik = (primp.Client(headers={"Authorization": f"Bearer {klucz}"}, timeout=120)
                          if klucz else None)
        self.strefa = os.environ.get("BRIGHT_DATA_ZONE") or "serp_api1"
        self.tryb = "bezpośrednio"
        self.bledy_z_rzedu = 0
        self.uzycia = {"bezpośrednio": 0, "pośrednik": 0}

    def _bezposrednio(self, q):
        return parse(self.klient.get(URL, params=q.params(), cookies=ZGODA).text)

    def _przez_posrednika(self, q):
        odp = self.posrednik.post("https://api.brightdata.com/request",
                                  json={"zone": self.strefa, "url": q.url(), "format": "raw"})
        return parse(odp.text)

    def szukaj(self, q):
        """Lista lotów; FlightsNotFound gdy brak lotów; inny wyjątek gdy nie da się pobrać."""
        ostatni: Exception | None = None
        if self.tryb == "bezpośrednio":
            for proba in range(2):
                try:
                    wynik = self._bezposrednio(q)
                    self.bledy_z_rzedu = 0
                    self.uzycia["bezpośrednio"] += 1
                    return wynik
                except FlightsNotFound:
                    raise
                except Exception as e:      # blokada, okno zgody, zmiana strony, zerwane połączenie
                    ostatni = e
                    time.sleep(4 * (proba + 1))
            self.bledy_z_rzedu += 1
            if self.posrednik is None:
                raise ostatni
            if self.bledy_z_rzedu >= 3:     # Google blokuje – reszta zapytań przez pośrednika
                self.tryb = "pośrednik"
        for _ in range(2):
            try:
                wynik = self._przez_posrednika(q)
                self.uzycia["pośrednik"] += 1
                return wynik
            except FlightsNotFound:
                raise
            except Exception as e:
                ostatni = e
                time.sleep(5)
        raise ostatni


def _godzina(tekst) -> int | None:
    if not tekst:
        return None
    return int(str(tekst).split(":")[0])


def filtry(U) -> dict:
    """Warunki, które Google stosuje osobno do KAŻDEGO kierunku – także do powrotu.

    Przy bilecie w obie strony Google pokazuje tylko lot tam (powrót wybiera się w drugim kroku),
    więc bez tych filtrów cena mogła dotyczyć powrotu z za długą przesiadką lub podróżą.
    Z filtrami cena jest liczona tylko z powrotów spełniających warunki, a link do Google je zachowuje.
    """
    f = {}
    if getattr(U, "MAKS_CZAS_PODROZY_GODZ", None):
        f["max_duration_minutes"] = int(U.MAKS_CZAS_PODROZY_GODZ * 60)
    if getattr(U, "MAKS_PRZESIADKA_GODZ", None):
        f["max_layover_minutes"] = int(U.MAKS_PRZESIADKA_GODZ * 60)
    if getattr(U, "MIN_PRZESIADKA_GODZ", None):
        f["min_layover_minutes"] = int(U.MIN_PRZESIADKA_GODZ * 60)
    return f


def zapytanie(U, skad: str, dokad: str, data: dt.date, powrot: dt.date | None = None):
    """Pierwszy odcinek zaczyna się w `skad`. Godziny wylotu dotyczą tylko odlotu z Polski."""
    od, do = (list(getattr(U, "GODZINY_WYLOTU", None) or []) + [None, None])[:2]
    z_polski = skad in U.LOTNISKA_WYLOTU
    f = filtry(U)
    loty = [FlightQuery(date=data.isoformat(), from_airport=skad, to_airport=dokad,
                        earliest_departure_hour=_godzina(od) if z_polski else None,
                        latest_departure_hour=_godzina(do) if z_polski else None, **f)]
    if powrot:
        loty.append(FlightQuery(date=powrot.isoformat(), from_airport=dokad, to_airport=skad, **f))
    return create_query(
        flights=loty, trip="round-trip" if powrot else "one-way", seat=getattr(U, "KLASA", "economy"),
        passengers=Passengers(adults=1), language="pl", currency="PLN",
        max_stops=U.MAKS_PRZESIADEK, checked_bags=U.BAGAZ_REJESTROWANY,
        hide_separate_and_self_transfer=True,
    )


def ocen(lot, U) -> dict | None:
    """Sprawdza kryteria przesiadek i czasu; zwraca opis lotu albo None."""
    odcinki = lot.flights
    if not odcinki or not lot.price:
        return None
    porty = [o.to_airport.code for o in odcinki[:-1]]
    if any(p in U.WYKLUCZONE_PRZESIADKI for p in porty):
        return None
    nazwy_linii = [a.lower() for a in (lot.airlines or [])]
    if any(w.lower() in a for w in (getattr(U, "WYKLUCZONE_LINIE", None) or []) for a in nazwy_linii):
        return None
    przerwy = []
    for a, b in zip(odcinki, odcinki[1:]):
        przylot = dt.datetime(*a.arrival.date, *a.arrival.time)
        odlot = dt.datetime(*b.departure.date, *b.departure.time)
        przerwy.append(int((odlot - przylot).total_seconds() // 60))
    minimum = (getattr(U, "MIN_PRZESIADKA_GODZ", None) or 0) * 60
    if any(p < max(0, minimum) or p > U.MAKS_PRZESIADKA_GODZ * 60 for p in przerwy):
        return None
    czas = sum(o.duration for o in odcinki) + sum(przerwy)
    if czas > U.MAKS_CZAS_PODROZY_GODZ * 60:
        return None
    if porty:
        trasa = ", ".join(f"przez {p}" + (f" – {U.OZNACZ_PRZESIADKI[p]}" if p in U.OZNACZ_PRZESIADKI else "")
                          + f" ({godz(m)})" for p, m in zip(porty, przerwy))
    else:
        trasa = "bez przesiadek"
    linie = ", ".join(lot.airlines) if lot.airlines else "?"
    ulubione = any(w.lower() in a for w in (getattr(U, "PREFEROWANE_LINIE", None) or []) for a in nazwy_linii)
    return {"cena": int(lot.price), "bezposredni": not porty,
            "opis": ("★ " if ulubione else "") + f"{trasa} · {linie} · {godz(czas)}",
            "linie": list(lot.airlines or []), "przesiadki": [[p, m] for p, m in zip(porty, przerwy)],
            "czas": czas, "rozklad": rozklad(odcinki)}


def rozklad(odcinki) -> list:
    """[[skąd, odlot „HH:MM”, dokąd, przylot „HH:MM”, ile dni po dniu wylotu], …] – czasy lokalne."""
    start = dt.date(*odcinki[0].departure.date)
    wynik = []
    for o in odcinki:
        wynik.append([o.from_airport.code, "%02d:%02d" % tuple(o.departure.time), o.to_airport.code,
                      "%02d:%02d" % tuple(o.arrival.time), (dt.date(*o.arrival.date) - start).days])
    return wynik


def najlepsze(loty, U) -> tuple[dict | None, dict | None]:
    oceny = []
    for lot in loty:
        try:
            o = ocen(lot, U)
        except Exception:
            o = None
        if o:
            oceny.append(o)
    if not oceny:
        return None, None
    bez = [o for o in oceny if o["bezposredni"]]
    return min(oceny, key=lambda o: o["cena"]), (min(bez, key=lambda o: o["cena"]) if bez else None)


def cele(U) -> list[str]:
    lista = [U.CEL] + list(getattr(U, "CELE_DODATKOWE", None) or [])
    return [c for i, c in enumerate(lista) if c and c not in lista[:i]]


def zadania(okna, U, dzis: dt.date, test: bool = False) -> list[tuple]:
    pary = sorted({p for o in okna for p in o.pary(dzis)})
    rt = [("rt", lot, cel, w, r) for (w, r) in pary for cel in cele(U) for lot in U.LOTNISKA_WYLOTU]
    jedna = []
    if U.SPRAWDZAJ_W_JEDNA_STRONE:
        wyloty = sorted({d for o in okna for d in o.wyloty(dzis)})
        powroty = sorted({d for o in okna for d in o.powroty(dzis)})
        jedna = ([("tam", lot, cel, d, None) for cel in cele(U) for lot in U.LOTNISKA_WYLOTU for d in wyloty]
                 + [("powrot", lot, cel, d, None) for cel in cele(U) for lot in U.LOTNISKA_WYLOTU for d in powroty])
    if test:
        return rt[:2] + jedna[:1] + [z for z in jedna if z[0] == "powrot"][:1]
    return rt + jedna


def pobierz(okna, U, dzis: dt.date, test: bool = False, log=print) -> Wynik:
    wynik = Wynik("google")
    pob = Pobieracz()
    lista = zadania(okna, U, dzis, test)
    log(f"Google: {len(lista)} zapytań")
    for i, (typ, lot, cel, d, r) in enumerate(lista, 1):
        if typ == "rt":
            q = zapytanie(U, lot, cel, d, r)
        elif typ == "tam":
            q = zapytanie(U, lot, cel, d)
        else:
            q = zapytanie(U, cel, lot, d)
        wynik.zapytania += 1
        try:
            naj, bez = najlepsze(pob.szukaj(q), U)
            wynik.udane += 1
        except FlightsNotFound:
            naj = bez = None
            wynik.udane += 1
        except Exception as e:
            log(f"  [{i}] {typ} {lot} {d}: NIEUDANE ({type(e).__name__})")
            naj = bez = None
        for o in {id(x): x for x in (naj, bez) if x}.values():
            if typ == "rt":
                wynik.podroze.append(Podroz("google", "rejsowy", lot, lot, d, r, o["cena"], o["opis"],
                                            o["bezposredni"], [q.url()], cel=cel, linie=o["linie"],
                                            przes_tam=o["przesiadki"], przes_pow=None, czas_tam=o["czas"],
                                            rozklad_tam=o["rozklad"]))
            else:
                wynik.odcinki.append(Odcinek("google", False, typ, lot, d, o["cena"], o["opis"],
                                             o["bezposredni"], q.url(), cel=cel, linie=o["linie"],
                                             przesiadki=o["przesiadki"], czas_min=o["czas"],
                                             rozklad=o["rozklad"]))
        if i % 20 == 0:
            log(f"  {i}/{len(lista)} (udane {wynik.udane}, tryb: {pob.tryb})")
        if i < len(lista):
            time.sleep(random.uniform(*U.PRZERWA_SEK))
    if wynik.udane == 0:
        wynik.status = "błąd"
        wynik.uwaga = "Google odrzucił wszystkie zapytania" + (
            "" if pob.posrednik else " (brak zapasowego pośrednika – BRIGHT_DATA_API_KEY)")
    elif wynik.udane < wynik.zapytania:
        wynik.status = "częściowo"
        wynik.uwaga = f"udane {wynik.udane} z {wynik.zapytania}"
    if pob.uzycia["pośrednik"]:
        wynik.uwaga = (wynik.uwaga + "; " if wynik.uwaga else "") + \
            f"przez pośrednika: {pob.uzycia['pośrednik']} zapytań"
    return wynik
