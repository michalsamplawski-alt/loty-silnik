"""Czartery Rainbow (sam przelot).

Strona pokazuje listę dni wylotu z ceną. Lotnisko wylotu i ceny powrotów pojawiają się
dopiero po kliknięciu dnia – dlatego używamy przeglądarki (Playwright), która klika
każdy dzień z Twoich zakresów i odczytuje lotnisko oraz powroty.
Gdy przeglądarka zawiedzie, tryb awaryjny czyta samą listę wylotów (bez lotniska i powrotów).
"""
from __future__ import annotations

import datetime as dt
import html as html_mod
import re
from pathlib import Path

from .wspolne import MIESIACE, SKROTY_MIESIECY, Odcinek, Wynik, rok_dla_miesiaca

DZIEN_TYG = r"(?:pon|pn|wt|śr|czw|pt|sob|niedz|ndz|nd)\.?"
MIES = "|".join(MIESIACE)
# Bez rozróżniania wielkości liter: strona wielką literą pokazuje dni tygodnia („Sob. 26 gru”).
WZOR_POZYCJI = re.compile(
    rf"{DZIEN_TYG}\s+(\d{{1,2}})\s+({MIES})\b\D{{0,15}}?(\d{{1,2}}\s?\d{{3}})\s?zł", re.I)
KOD_LOTNISKA = re.compile(r"\(([A-Z]{3})\)")
OPIS = "czarter Rainbow (LOT, bez przesiadek)"


def tekst_z_html(strona: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", strona)))


def lista_cen(tekst: str, dzis: dt.date) -> dict[dt.date, int]:
    ceny: dict[dt.date, int] = {}
    for t in WZOR_POZYCJI.finditer(tekst):
        mies = MIESIACE[t.group(2).lower()]
        try:
            d = dt.date(rok_dla_miesiaca(mies, dzis), mies, int(t.group(1)))
        except ValueError:
            continue
        cena = int(re.sub(r"\D", "", t.group(3)))
        ceny[d] = min(cena, ceny.get(d, cena))
    return ceny


def podziel(tekst: str) -> tuple[str, str]:
    """(część z wylotami, część z powrotami) – granicą jest nagłówek „Powrót” po liście wylotów."""
    pierwsza = WZOR_POZYCJI.search(tekst)
    if not pierwsza:
        return "", ""
    granica = tekst.find("Powrót", pierwsza.start())
    if granica == -1:
        return tekst, ""
    return tekst[:granica], tekst[granica:]


WZOR_KARTY = re.compile(r"\(([A-Z]{3})\)(?:(?!zł/os).)*?(\d{1,2}\s?\d{3}|\d{3})\s?zł/os", re.S)


def karty(tekst: str, nazwy: dict[str, str]) -> list[tuple[str, int]]:
    """Loty wybranego dnia: [(polskie lotnisko, cena za osobę), …] z kart pod listą dni wylotu."""
    wyloty = podziel(tekst)[0]
    pozycje = list(WZOR_POZYCJI.finditer(wyloty))
    if not pozycje:
        return []
    polskie = set(nazwy.values())
    wynik: list[tuple[str, int]] = []
    for k in WZOR_KARTY.finditer(wyloty[pozycje[-1].end():]):
        if k.group(1) in polskie and k.group(1) not in [x for x, _ in wynik]:
            wynik.append((k.group(1), int(re.sub(r"\D", "", k.group(2)))))
    return wynik


def lotnisko_wylotu(tekst: str, data: dt.date, nazwy: dict[str, str]) -> str | None:
    """Lotnisko wybranego lotu.

    Obecny układ: pod listą dni wylotu karta lotu „Poznań (POZ) 16:45 Bangkok (BKK) …”.
    Starszy układ: opis „Wylot 26.12.2026 … Katowice 15:30 → Bangkok”.
    """
    wyloty = podziel(tekst)[0]
    pozycje = list(WZOR_POZYCJI.finditer(wyloty))
    if pozycje:
        polskie = set(nazwy.values())
        for kod in KOD_LOTNISKA.findall(wyloty[pozycje[-1].end():]):
            if kod in polskie:
                return kod
    for znacznik in (f"Wylot {data:%d.%m.%Y}", f"{data:%d.%m.%Y}"):
        i = tekst.find(znacznik)
        if i != -1:
            fragment = tekst[i:i + 400]
            trafienia = [(fragment.find(n), kod) for n, kod in nazwy.items() if n in fragment]
            if trafienia:
                return min(trafienia)[1]
    return None


ODMOWA = ("Odrzuć", "Tylko niezbędne", "Tylko wymagane", "Nie zgadzam")
ZGODA = ("Akceptuj", "Zgadzam", "Zaakceptuj")
USUN_OKNO_ZGODY = """() => {
  let n = 0;
  document.querySelectorAll('[class*="consent"],[id*="consent"],[class*="cookie"],[id*="cookie"]').forEach(e => {
    if (!e.isConnected) return;
    const s = getComputedStyle(e);
    if (s.position === 'fixed' || String(e.className).includes('modal')) { e.remove(); n++; }
  });
  document.documentElement.style.overflow = ''; document.body.style.overflow = '';
  return n;
}"""


def _przycisk(strona, napisy):
    for napis in napisy:
        try:
            p = strona.get_by_role("button", name=re.compile(napis, re.I)).first
            if p.is_visible():
                return p
        except Exception:
            continue
    return None


def _zamknij_okno_ciasteczek(strona, czekaj_ms: int = 8000) -> None:
    """Okno zgody pojawia się z opóźnieniem i zasłania przyciski – czekamy na nie.

    Kolejność: odmowa zgody → usunięcie okna ze strony (bez wyrażania zgody) → zgoda (ostatnia deska ratunku).
    """
    for _ in range(max(1, czekaj_ms // 500)):
        odmowa = _przycisk(strona, ODMOWA)
        if odmowa:
            try:
                odmowa.click(timeout=3000)
                strona.wait_for_timeout(800)
                return
            except Exception:
                pass
        if _przycisk(strona, ZGODA):
            try:
                strona.evaluate(USUN_OKNO_ZGODY)
                strona.wait_for_timeout(500)
            except Exception:
                pass
            zgoda = _przycisk(strona, ZGODA)
            if zgoda:
                try:
                    zgoda.click(timeout=3000)
                    strona.wait_for_timeout(800)
                except Exception:
                    pass
            return
        strona.wait_for_timeout(500)


def _przegladarka(okna, U, dzis: dt.date, test: bool, log) -> Wynik:
    from playwright.sync_api import sync_playwright

    wynik = Wynik("rainbow")
    with sync_playwright() as p:
        przegladarka = p.chromium.launch()
        strona = przegladarka.new_page(locale="pl-PL", viewport={"width": 1400, "height": 2400})
        strona.goto(U.RAINBOW_URL, wait_until="domcontentloaded", timeout=60000)
        _zamknij_okno_ciasteczek(strona)
        strona.wait_for_timeout(3000)
        wyloty = lista_cen(podziel(strona.inner_text("body"))[0], dzis)
        dni = [d for d in sorted(wyloty) if any(o.dobry_wylot(d, dzis) for o in okna)]
        if test:
            dni = dni[:2]
        log(f"Rainbow: {len(wyloty)} dni wylotu na stronie, w Twoich zakresach: {len(dni)}")
        for d in dni:
            wynik.zapytania += 1
            wzor = re.compile(rf"\b0?{d.day}\s+{SKROTY_MIESIECY[d.month]}\b")
            try:
                strona.get_by_text(wzor).first.click(timeout=10000)
                strona.wait_for_timeout(2500)
            except Exception as e:
                log(f"  {d}: nie udało się kliknąć ({type(e).__name__})")
                continue
            tekst = strona.inner_text("body")
            loty = karty(tekst, U.NAZWY_LOTNISK) or [(lotnisko_wylotu(tekst, d, U.NAZWY_LOTNISK) or "?", wyloty[d])]
            wynik.udane += 1
            for i, (kod, cena) in enumerate(loty):
                if kod != "?" and kod not in U.LOTNISKA_WYLOTU:
                    log(f"  {d}: {kod}, {cena} zł – lotnisko spoza kryteriów")
                    continue
                if i > 0:   # powroty pokazują się dla zaznaczonego lotu – zaznacz kolejną kartę
                    try:
                        strona.get_by_text(re.compile(rf"\({kod}\)")).first.click(timeout=10000)
                        strona.wait_for_timeout(2000)
                        tekst = strona.inner_text("body")
                    except Exception as e:
                        log(f"  {d}: {kod} – nie udało się zaznaczyć ({type(e).__name__})")
                        continue
                powroty = lista_cen(podziel(tekst)[1], dzis)
                log(f"  {d}: {kod}, {cena} zł, powrotów: {len(powroty)}")
                wynik.odcinki.append(Odcinek("rainbow", True, "tam", kod, d, cena, OPIS, True, U.RAINBOW_URL, cel=U.CEL, linie=["Rainbow (czarter LOT)"]))
                for r, c in powroty.items():
                    wynik.odcinki.append(Odcinek("rainbow", True, "powrot", kod, r, c, OPIS, True, U.RAINBOW_URL, cel=U.CEL, linie=["Rainbow (czarter LOT)"]))
        przegladarka.close()
    if wynik.udane == 0:
        wynik.status = "błąd"
        wynik.uwaga = "nie odczytano żadnego dnia"
    elif any(o.lotnisko == "?" for o in wynik.odcinki):
        wynik.status = "częściowo"
        wynik.uwaga = "nie rozpoznano lotniska dla części lotów"
    return wynik


def _awaryjnie(okna, U, dzis: dt.date, log) -> Wynik:
    import primp

    wynik = Wynik("rainbow", zapytania=1, status="częściowo",
                  uwaga="tryb awaryjny: tylko ceny wylotów, bez lotniska i powrotów")
    strona = primp.Client(impersonate="chrome_145", impersonate_os="macos", timeout=40).get(U.RAINBOW_URL).text
    wyloty = lista_cen(podziel(tekst_z_html(strona))[0], dzis)
    for d, c in wyloty.items():
        if any(o.dobry_wylot(d, dzis) for o in okna):
            wynik.odcinki.append(Odcinek("rainbow", True, "tam", "?", d, c, OPIS, True, U.RAINBOW_URL, cel=U.CEL, linie=["Rainbow (czarter LOT)"]))
    if wyloty:
        wynik.udane = 1
    else:
        wynik.status, wynik.uwaga = "błąd", "nie odczytano cen (zmiana strony?)"
    return wynik


def pobierz(okna, U, dzis: dt.date, test: bool = False, log=print) -> Wynik:
    try:
        wynik = _przegladarka(okna, U, dzis, test, log)
        if wynik.status != "błąd":
            return wynik
        log(f"Rainbow: przeglądarka – {wynik.uwaga}; przechodzę w tryb awaryjny")
    except Exception as e:
        log(f"Rainbow: przeglądarka – błąd {type(e).__name__}: {e}; przechodzę w tryb awaryjny")
    try:
        return _awaryjnie(okna, U, dzis, log)
    except Exception as e:
        return Wynik("rainbow", status="błąd", uwaga=f"{type(e).__name__}: {e}")


def zrzut(U, katalog: Path) -> None:
    """Zapisuje tekst, HTML i zrzut ekranu strony – do diagnozy przy zmianie wyglądu strony."""
    from playwright.sync_api import sync_playwright

    katalog.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        s = b.new_page(locale="pl-PL", viewport={"width": 1400, "height": 2400})
        s.goto(U.RAINBOW_URL, wait_until="domcontentloaded", timeout=60000)
        _zamknij_okno_ciasteczek(s)
        s.wait_for_timeout(3000)
        (katalog / "rainbow.txt").write_text(s.inner_text("body"), encoding="utf-8")
        (katalog / "rainbow.html").write_text(s.content(), encoding="utf-8")
        s.screenshot(path=str(katalog / "rainbow.png"), full_page=True)
        b.close()
