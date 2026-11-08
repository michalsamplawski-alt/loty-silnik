"""Czartery Itaki (sam przelot, sprzedawany w obie strony) – z każdego lotniska, z którego lata Itaka.

Itaka lata w poniedziałki, powrót we wtorek tydzień lub dwa później – dlatego zapisujemy
też terminy krótsze o jedną noc od wymaganej, żeby raport mógł je pokazać jako „prawie”.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import czartery
from .wspolne import MIESIACE, Podroz, Wynik, rok_dla_miesiaca

MIES = "|".join(MIESIACE)
# Obecny układ: „Wylot: poniedziałek, 4 sty … Powrót: wtorek, 12 sty … 5 996 zł /os.” (bez roku).
WZOR_KARTY = re.compile(
    rf"Wylot:\s*[^\d,]+,\s*(\d{{1,2}})\s+({MIES})\b(?:(?!Wylot:).)*?"
    rf"Powrót:\s*[^\d,]+,\s*(\d{{1,2}})\s+({MIES})\b(?:(?!Wylot:).)*?(\d{{1,2}}\s?\d{{3}})\s?zł",
    re.S | re.I)
STRONY = re.compile(r"^\s*z\s+(\d{1,2})\s*$", re.M)
MAKS_STRON = 8
# Starszy układ: „28.12 - 05.01.2027 (8 dni) od 5 996 zł”.
WZOR = re.compile(
    r"(\d{1,2})\.(\d{2})(?:\.(\d{4}))?\s*[-–]\s*(\d{1,2})\.(\d{2})\.(\d{4})"
    r"(?:(?!\d{1,2}\.\d{2}\.\d{4}).){0,160}?(?:od\s*)?(\d{1,2}\s?\d{3})\s?zł",
    re.S)
OPIS = "czarter Itaka (LOT, bez przesiadek)"


GODZINA_PORT = re.compile(r"(\d{1,2}:\d{2})\s*\(([A-Z]{3})\)")   # „Warszawa-Okęcie 19:30 (WAW)”


def _rozklad(fragment: str) -> list | None:
    """Odcinki z kolejnych par „godzina (KOD)”: [[skąd, odlot, dokąd, przylot, dni], …]."""
    pary = [(g.zfill(5), k) for g, k in GODZINA_PORT.findall(fragment)]
    if len(pary) < 2:
        return None
    odcinki, dni = [], 0
    for (g1, k1), (g2, k2) in zip(pary[::2], pary[1::2]):
        dni += 1 if g2 < g1 else 0
        odcinki.append([k1, g1, k2, g2, dni])
    return odcinki


CZAS_LOTU = re.compile(r"(\d{1,2})\s*godz\.(?:\s*(\d{1,2})\s*min)?")   # „10 godz. 20 min.”


def _czas(fragment: str) -> int | None:
    m = CZAS_LOTU.search(fragment)
    return int(m.group(1)) * 60 + int(m.group(2) or 0) if m else None


def godziny(tekst: str, dzis: dt.date | None = None) -> dict[tuple[dt.date, dt.date], tuple]:
    """{(wylot, powrót): (rozkład tam, rozkład powrotu)} z ofert w obecnym układzie strony."""
    return {k: (tam, pow_) for k, _, tam, pow_, _, _ in _oferty(tekst, dzis or dt.date.today())}


def czasy(tekst: str, dzis: dt.date | None = None) -> dict[tuple[dt.date, dt.date], tuple]:
    """{(wylot, powrót): (minut lotu tam, minut lotu z powrotem)}."""
    return {k: (ct, cp) for k, _, _, _, ct, cp in _oferty(tekst, dzis or dt.date.today())}


def _oferty(tekst: str, dzis: dt.date):
    for t in WZOR_KARTY.finditer(tekst):
        d1, m1, d2, m2, cena = t.groups()
        m1, m2 = MIESIACE[m1.lower()], MIESIACE[m2.lower()]
        try:
            wylot = dt.date(rok_dla_miesiaca(m1, dzis), m1, int(d1))
            powrot = dt.date(wylot.year + (1 if m2 < m1 else 0), m2, int(d2))
        except ValueError:
            continue
        if not 4 <= (powrot - wylot).days <= 30:
            continue
        tam, _, pow_ = t.group(0).partition("Powrót:")
        yield (wylot, powrot), int(re.sub(r"\D", "", cena)), _rozklad(tam), _rozklad(pow_), _czas(tam), _czas(pow_)


def terminy(tekst: str, dzis: dt.date | None = None) -> dict[tuple[dt.date, dt.date], int]:
    dzis = dzis or dt.date.today()
    wyniki: dict[tuple[dt.date, dt.date], int] = {}
    for klucz, c, *_ in _oferty(tekst, dzis):
        wyniki[klucz] = min(c, wyniki.get(klucz, c))
    for t in WZOR.finditer(tekst):
        d1, m1, r1, d2, m2, r2, cena = t.groups()
        try:
            powrot = dt.date(int(r2), int(m2), int(d2))
            rok1 = int(r1) if r1 else (powrot.year if int(m1) <= int(m2) else powrot.year - 1)
            wylot = dt.date(rok1, int(m1), int(d1))
        except ValueError:
            continue
        if not 4 <= (powrot - wylot).days <= 30:
            continue
        c = int(re.sub(r"\D", "", cena))
        wyniki[(wylot, powrot)] = min(c, wyniki.get((wylot, powrot), c))
    return wyniki


def _czytaj(s, url: str) -> str:
    s.goto(url, wait_until="domcontentloaded", timeout=60000)
    s.wait_for_timeout(4000)
    for _ in range(5):                       # dociągnij leniwie ładowane terminy
        s.mouse.wheel(0, 3000)
        s.wait_for_timeout(700)
    return s.inner_text("body")


def _teksty_stron(U, log=print) -> list[tuple[str, str, str]]:
    """[(adres, kod lotniska docelowego, tekst wszystkich stron wyników), …] dla każdego kierunku."""
    from playwright.sync_api import sync_playwright

    from .rainbow import _zamknij_okno_ciasteczek
    wynik = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        s = b.new_page(locale="pl-PL", viewport={"width": 1400, "height": 2400})
        html_listy = None
        if czartery.auto(U):
            try:
                s.goto(czartery.ITAKA_LISTA, wait_until="domcontentloaded", timeout=60000)
                _zamknij_okno_ciasteczek(s)
                s.wait_for_timeout(2000)
                html_listy = s.content()
            except Exception as e:
                log(f"Itaka: nie udało się pobrać listy kierunków ({type(e).__name__}) – tylko adres z kryteriów")
        adresy = czartery.itaka_adresy(html_listy, U, log)
        if not adresy:
            b.close()
            return []
        log(f"Itaka: kierunki do sprawdzenia: {', '.join(a.rstrip('/').rsplit('/', 1)[-1] for a, _ in adresy)}")
        if html_listy is None:
            s.goto(adresy[0][0], wait_until="domcontentloaded", timeout=60000)
            _zamknij_okno_ciasteczek(s)
        for adres, cel in adresy:
            try:
                teksty = [_czytaj(s, adres)]
                stron = int(m.group(1)) if (m := STRONY.search(teksty[0])) else 1
                znak = "&" if "?" in adres else "?"
                for nr in range(2, min(stron, MAKS_STRON) + 1):   # kolejne strony wyników: ?page=2, 3…
                    teksty.append(_czytaj(s, f"{adres}{znak}page={nr}"))
                wynik.append((adres, cel, "\n".join(teksty)))
            except Exception as e:
                log(f"Itaka {adres}: błąd {type(e).__name__}: {e}")
        b.close()
    return wynik


def podroze_ze_strony(tekst: str, adres: str, cel: str, U, dzis: dt.date) -> list[Podroz]:
    """Podróże z jednej strony kierunku – lotnisko wylotu i docelowe z kart lotu (Itaka lata z wielu miast)."""
    najlepsze: dict[tuple, tuple] = {}
    for (w, r), c, tam, pow_, ct, cp in _oferty(tekst, dzis):
        skad = tam[0][0] if tam else U.ITAKA_LOTNISKO
        dokad = tam[-1][2] if tam else cel
        klucz = (skad, dokad, w, r)
        if klucz not in najlepsze or c < najlepsze[klucz][0]:
            najlepsze[klucz] = (c, tam, pow_, ct, cp)
    if not najlepsze:   # starszy układ strony – bez kart, tylko daty i ceny
        for (w, r), c in terminy(tekst, dzis).items():
            najlepsze[(U.ITAKA_LOTNISKO, cel, w, r)] = (c, None, None, None, None)
    wynik = []
    for (skad, dokad, w, r), (c, tam, pow_, ct, cp) in najlepsze.items():
        if w <= dzis or skad not in set(U.LOTNISKA_WYLOTU) | {U.ITAKA_LOTNISKO}:
            continue
        wynik.append(Podroz("itaka", "czarter", skad, skad, w, r, c, OPIS, True, [adres], cel=dokad,
                            linie=["Itaka (czarter LOT)"], rozklad_tam=tam, rozklad_pow=pow_,
                            czas_tam=ct, czas_pow=cp))
    return wynik


def pobierz(okna, U, dzis: dt.date, test: bool = False, log=print) -> Wynik | None:
    try:
        strony = _teksty_stron(U, log)
    except Exception as e:
        return Wynik("itaka", zapytania=1, status="błąd", uwaga=f"{type(e).__name__}: {e}")
    if not strony:
        log("Itaka: brak czarterów do lotnisk docelowych tego wyjazdu")
        return None
    wynik = Wynik("itaka", zapytania=len(strony))
    jest: dict[tuple, Podroz] = {}   # ten sam lot z kilku stron (np. „bangkok” i „warszawa-do-bangkok”) – raz
    for adres, cel, tekst in strony:
        podroze = podroze_ze_strony(tekst, adres, cel, U, dzis)
        log(f"Itaka {adres.rstrip('/').rsplit('/', 1)[-1]}: odczytano {len(terminy(tekst, dzis))} terminów, "
            f"z Twoich lotnisk: {len(podroze)}")
        if terminy(tekst, dzis) or "Wylot:" in tekst or "ofert" in tekst.lower():
            wynik.udane += 1
        for p in podroze:
            klucz = (p.lotnisko_wylotu, p.cel, p.wylot, p.powrot)
            if klucz not in jest or p.cena < jest[klucz].cena:
                jest[klucz] = p
    wynik.podroze = list(jest.values())
    if not wynik.udane:
        wynik.status, wynik.uwaga = "błąd", "nie odczytano terminów (zmiana strony?)"
    return wynik


def zrzut(U, katalog: Path) -> None:
    katalog.mkdir(parents=True, exist_ok=True)
    (katalog / "itaka.txt").write_text("\n\n".join(t for _, _, t in _teksty_stron(U)), encoding="utf-8")
