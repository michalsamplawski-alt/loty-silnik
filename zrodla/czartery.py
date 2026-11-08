"""Automatyczny dobór stron z czarterami dla lotnisk docelowych wyjazdu.

Rainbow: lista wszystkich kierunków z mapy strony (sitemap) – dopasowanie po nazwie miasta.
Itaka:   słownik kierunków z kodami lotnisk zapisany w stronie z biletami – dopasowanie po kodzie.
Do tego zawsze dochodzi adres wpisany ręcznie w kryteriach (jeśli jest).
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path

RAINBOW_MAPA = "https://r.pl/sitemap-bilety-czarterowe.xml"
RAINBOW_BAZA = "https://r.pl/bilety-czarterowe/"
ITAKA_LISTA = "https://www.itaka.pl/bilety-lotnicze/"
PRZEGLADARKA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

_MIASTA: dict[str, list[str]] | None = None

# Kierunki Rainbow nazwane inaczej niż miasto w podpowiedziach aplikacji (nazwa w adresie → lotnisko).
RAINBOW_KODY = {
    "puerto-del-rosario": "FUE", "mao": "MAH", "espargos": "SID", "luqa": "MLA", "port-luis": "MRU",
    "male": "MLE", "mopa": "GOX", "goa": "GOI", "antananarywa": "TNR", "colombo": "CMB",
    "ho-chi-minh-sajgon": "SGN", "phu-quoc": "PQC", "wadzda": "OUD", "konstanca": "CND", "patra": "GPA",
    "mitylena": "MJT", "gerona": "GRO", "keflavik": "KEF", "lamezia-di-terme": "SUF", "puerto-plata": "POP",
    "vieux-fort": "UVF", "porlamar": "PMV", "taszkent": "TAS", "varadero": "VRA", "ochryda": "OHD",
    "kutaisi": "KUT", "banjul": "BJL", "zanzibar": "ZNZ", "mombasa": "MBA", "salalah": "SLL", "aqaba": "AQJ",
    "penang": "PEN", "cebu": "CEB", "liberia": "LIR", "puerto-vallarta": "PVR", "cancun": "CUN",
    "cartagena-de-indias": "CTG", "katmandu": "KTM", "palma-de-mallorca": "PMI", "las-palmas": "LPA",
    "teneryfa": "TFS", "volos": "VOL", "reus": "REU", "olbia": "OLB", "alghero": "AHO", "cagliari": "CAG",
    "katania": "CTA", "werona": "VRN", "neapol": "NAP", "rzym": "FCO", "londyn": "LHR", "ateny": "ATH",
    "saloniki": "SKG", "nowy-jork": "JFK", "miami": "MIA", "seattle": "SEA", "mexico-city": "MEX",
    "rio-de-janeiro": "GIG", "eindhoven": "EIN", "bazylea": "BSL", "oslo": "OSL", "praga": "PRG",
    "zagrzeb": "ZAG", "split": "SPU", "dubrownik": "DBV", "podgorica": "TGD", "skopje": "SKP",
    "abu-dhabi": "AUH", "dubaj": "DXB", "rijad": "RUH", "new-delhi": "DEL", "istambul": "IST",
}


def miasta() -> dict[str, list[str]]:
    """{kod lotniska: [miasto, nazwa lotniska, inne nazwy…]} – te same dane, co podpowiedzi w aplikacji."""
    global _MIASTA
    if _MIASTA is None:
        _MIASTA = json.loads((Path(__file__).with_name("miasta_lotnisk.json")).read_text(encoding="utf-8"))
    return _MIASTA


def slug(tekst: str) -> str:
    t = unicodedata.normalize("NFKD", tekst.replace("ł", "l").replace("Ł", "L"))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def cele(U) -> list[str]:
    """Wszystkie lotniska docelowe wyjazdu (główne + dodatkowe), bez powtórzeń."""
    return list(dict.fromkeys(k for k in [U.CEL, *(U.CELE_DODATKOWE or [])] if k))


def auto(U) -> bool:
    return bool(getattr(U, "CZARTERY_AUTO", True))


def _pobierz(url: str) -> str:
    zad = urllib.request.Request(url, headers={"User-Agent": PRZEGLADARKA, "Accept-Language": "pl-PL,pl"})
    with urllib.request.urlopen(zad, timeout=40) as odp:
        return odp.read().decode("utf-8", "replace")


def rainbow_kierunki(mapa_xml: str) -> list[str]:
    """[„tajlandia/phuket”, …] – tylko strony konkretnych miast (kraj/miasto)."""
    wynik = []
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", mapa_xml):
        if loc.startswith(RAINBOW_BAZA):
            reszta = loc[len(RAINBOW_BAZA):].strip("/")
            if re.fullmatch(r"[a-z0-9-]+/[a-z0-9-]+", reszta) and not reszta.startswith("polska/"):
                wynik.append(reszta)
    return wynik


def rainbow_dopasuj(kierunki: list[str], kody: list[str]) -> list[tuple[str, str]]:
    """[(adres, kod lotniska), …] – kierunki Rainbow pasujące nazwą miasta do lotnisk wyjazdu.

    Dopasowanie jest hojne (np. „palma” → „palma-de-mallorca”); lotnisko docelowe z kart lotów
    i tak jest potem sprawdzane, więc nadmiarowa strona kosztuje tylko chwilę czasu.
    """
    wynik: list[tuple[str, str]] = []
    for kod in kody:
        nazwy = miasta().get(kod, [])
        dokladne = {slug(n) for n in nazwy} - {""}
        glowne = slug(nazwy[0]) if nazwy else ""
        for k in kierunki:
            miasto = k.split("/", 1)[1]
            if RAINBOW_KODY.get(miasto) == kod or miasto in dokladne or (glowne and (
                    miasto.startswith(glowne + "-") or glowne.startswith(miasto + "-"))):
                adres = RAINBOW_BAZA + k
                if adres not in [a for a, _ in wynik]:
                    wynik.append((adres, kod))
    return wynik


def rainbow_adresy(U, log=print) -> list[tuple[str, str]]:
    adresy: list[tuple[str, str]] = []
    if auto(U):
        try:
            adresy = rainbow_dopasuj(rainbow_kierunki(_pobierz(RAINBOW_MAPA)), cele(U))
        except Exception as e:
            log(f"Rainbow: nie udało się pobrać listy kierunków ({type(e).__name__}) – tylko adres z kryteriów")
    reczny = (getattr(U, "RAINBOW_URL", "") or "").strip()
    if reczny and reczny.rstrip("/") not in [a.rstrip("/") for a, _ in adresy]:
        adresy.append((reczny, U.CEL))
    return adresy


def itaka_kierunki(html: str) -> dict[str, str]:
    """{kod lotniska: nazwa w adresie} ze słownika kierunków zapisanego w stronie Itaki."""
    t = html.replace('\\"', '"')
    wynik: dict[str, str] = {}
    for nazwa, kod in re.findall(r'"([a-z0-9-]+)":\{[^{}]*?"iataCode":"([A-Z]{3})"', t):
        wynik.setdefault(kod, nazwa)
    return wynik


def itaka_adresy(html_listy: str | None, U, log=print) -> list[tuple[str, str]]:
    adresy: list[tuple[str, str]] = []
    if auto(U) and html_listy:
        mapa = itaka_kierunki(html_listy)
        adresy = [(f"{ITAKA_LISTA}{mapa[k]}/", k) for k in cele(U) if k in mapa]
    reczny = (getattr(U, "ITAKA_URL", "") or "").strip()
    if reczny and reczny.rstrip("/") not in [a.rstrip("/") for a, _ in adresy]:
        adresy.append((reczny, U.CEL))
    return adresy
