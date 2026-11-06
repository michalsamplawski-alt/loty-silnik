"""Silnik aplikacji „Loty” – sprawdza ceny dla wyjazdów ustawionych w panelu.

    python narzedzie.py                 tryb aplikacji: wyjazdy i wyniki w Dropboxie (sekrety DROPBOX_*),
                                        raport mailem, jeśli ustawiono SMTP_*
    python narzedzie.py --przygotuj     założenie folderu aplikacji w Dropboxie
    python narzedzie.py --lokalnie      jeden wyjazd z ustawienia.py, raport na ekran
    python narzedzie.py --test-zrodel   krótki test każdego źródła (kilka zapytań)
    python narzedzie.py --zrzut         zapis stron Rainbow/Itaka do dane/zrzuty (diagnoza)
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from zrodla import google, itaka, rainbow
from zrodla.wspolne import Okno, Podroz, Wynik, wczytaj_okna, zl

KATALOG = Path(__file__).resolve().parent
MODULY = {"google": google, "rainbow": rainbow, "itaka": itaka}
NAZWY_ZRODEL = {"google": "Loty rejsowe", "rainbow": "Czarter Rainbow", "itaka": "Czarter Itaka"}

DOMYSLNE = dict(
    OKNA=[], MIN_NOCY_NA_MIEJSCU=7, MAKS_NOCY_NA_MIEJSCU=None, PRZYLOT_NASTEPNEGO_DNIA=True,
    DNI_WYLOTU=["pn", "wt", "śr", "czw", "pt", "sob", "nd"],
    LOTNISKA_WYLOTU=["WAW"], POWROT_NA_INNE_LOTNISKO=False, CEL="", CEL_NAZWA="", CELE_DODATKOWE=[],
    LICZBA_OSOB=1, BAGAZ_REJESTROWANY=0, KLASA="economy",
    MAKS_PRZESIADEK=1, MIN_PRZESIADKA_GODZ=None, MAKS_PRZESIADKA_GODZ=4, MAKS_CZAS_PODROZY_GODZ=17,
    GODZINY_WYLOTU=[None, None], WYKLUCZONE_PRZESIADKI=[], OZNACZ_PRZESIADKI={},
    PREFEROWANE_LINIE=[], WYKLUCZONE_LINIE=[],
    BUDZET_MAKS=None, CENA_DOCELOWA=None, DOPLATA_ZA_BEZPOSREDNI=None,
    PREFEROWANE_LOTNISKO=None, DOPLATA_ZA_PREFEROWANE_LOTNISKO=None,
    ZRODLA={"google": True, "rainbow": False, "itaka": False}, SPRAWDZAJ_W_JEDNA_STRONE=True,
    WYSYLAJ="zawsze", ILE_W_RAPORCIE=5, ODBIORCY=[],
    RAINBOW_URL="", ITAKA_URL="", ITAKA_LOTNISKO="WAW",
    PRZERWA_SEK=(1.5, 4.0),
    NAZWY_LOTNISK={"Warszawa": "WAW", "Katowice": "KTW", "Poznań": "POZ", "Kraków": "KRK", "Gdańsk": "GDN",
                   "Wrocław": "WRO", "Rzeszów": "RZE", "Łódź": "LCJ", "Lublin": "LUB", "Bydgoszcz": "BZG",
                   "Szczecin": "SZZ", "Modlin": "WMI"},
)

KATEGORIE = [
    ("najtaniej", "Najtaniej ogółem", lambda p: True),
    ("lot_bez_przesiadek", "Rejsowy bez przesiadek", lambda p: p.rodzaj == "rejsowy" and p.bezposredni),
    ("czarter", "Czarter w obie strony", lambda p: p.rodzaj == "czarter"),
    ("mieszany", "Czarter tam, rejsowy z powrotem", lambda p: p.rodzaj == "mieszany"),
    ("z_przesiadka", "Z przesiadką", lambda p: not p.bezposredni),
]


def ustawienia(dane: dict | None = None) -> SimpleNamespace:
    """Kryteria z panelu (albo z ustawienia.py) uzupełnione wartościami domyślnymi."""
    k = dict(DOMYSLNE)
    for klucz, wartosc in (dane or {}).items():
        k[klucz] = wartosc
    k["ZRODLA"] = {**DOMYSLNE["ZRODLA"], **(k.get("ZRODLA") or {})}
    if not k.get("RAINBOW_URL"):
        k["ZRODLA"]["rainbow"] = False
    if not k.get("ITAKA_URL"):
        k["ZRODLA"]["itaka"] = False
    k["PRZERWA_SEK"] = tuple(k["PRZERWA_SEK"])
    for pole in ("CELE_DODATKOWE", "PREFEROWANE_LINIE", "WYKLUCZONE_LINIE", "ODBIORCY", "WYKLUCZONE_PRZESIADKI"):
        k[pole] = list(k.get(pole) or [])
    k["OZNACZ_PRZESIADKI"] = dict(k.get("OZNACZ_PRZESIADKI") or {})
    return SimpleNamespace(**k)


# ---------- analiza ----------

def podroze_w_oknie(K, okno: Okno, wyniki: dict[str, Wynik], dzis: dt.date) -> list[Podroz]:
    """Gotowe podróże ze źródeł + połączenia osobnych biletów, zgodne z kryteriami."""
    lista = [p for w in wyniki.values() for p in w.podroze if okno.dobra_para(p.wylot, p.powrot)]
    tam = [o for w in wyniki.values() for o in w.odcinki
           if o.kierunek == "tam" and o.lotnisko != "?" and okno.dobry_wylot(o.data, dzis)]
    powrot = [o for w in wyniki.values() for o in w.odcinki
              if o.kierunek == "powrot" and o.lotnisko != "?" and okno.dobry_powrot(o.data, dzis)]
    for a in tam:
        for b in powrot:
            if not okno.dobra_para(a.data, b.data):
                continue
            if a.lotnisko != b.lotnisko and not K.POWROT_NA_INNE_LOTNISKO:
                continue
            # Powrót czarterem tylko wtedy, gdy wylot był tym samym czarterem z tego samego lotniska.
            if b.czarter and not (a.czarter and a.zrodlo == b.zrodlo and a.lotnisko == b.lotnisko):
                continue
            if a.czarter and b.czarter:
                rodzaj = "czarter"
            elif not a.czarter and not b.czarter:
                rodzaj = "rejsowy"
            else:
                rodzaj = "mieszany"
            zrodlo = a.zrodlo if a.zrodlo == b.zrodlo else f"{a.zrodlo}+{b.zrodlo}"
            opis = a.opis if a.opis == b.opis else f"tam: {a.opis}; powrót: {b.opis}"
            lista.append(Podroz(zrodlo, rodzaj, a.lotnisko, b.lotnisko, a.data, b.data, a.cena + b.cena,
                                opis, a.bezposredni and b.bezposredni, [a.link, b.link], dwa_bilety=True,
                                cel=a.cel if a.cel == b.cel else f"{a.cel}/{b.cel}",
                                linie=list(dict.fromkeys(a.linie + b.linie)), przes_tam=a.przesiadki,
                                przes_pow=b.przesiadki, czas_tam=a.czas_min, czas_pow=b.czas_min))
    return sorted(lista, key=lambda p: (p.cena, p.wylot, p.powrot))


def prawie(okno: Okno, wyniki: dict[str, Wynik]) -> list[Podroz]:
    """Czartery w zakresie, którym brakuje jednej nocy do wymaganego minimum."""
    return sorted((p for w in wyniki.values() for p in w.podroze
                   if p.rodzaj == "czarter" and okno.od <= p.wylot and p.powrot <= okno.do
                   and okno.noce(p.wylot, p.powrot) == okno.min_nocy - 1), key=lambda p: p.cena)


def najlepsze_w_kategoriach(lista: list[Podroz]) -> dict[str, Podroz]:
    wynik = {}
    for klucz, _, warunek in KATEGORIE:
        pasujace = [p for p in lista if warunek(p)]
        if pasujace:
            wynik[klucz] = pasujace[0]
    return wynik


def polecam(K, lista: list[Podroz]) -> tuple[Podroz, str] | None:
    """Rekomendacja według gotowości do dopłaty (tylko gdy kryteria ją określają)."""
    if not lista or (K.DOPLATA_ZA_BEZPOSREDNI is None and not K.PREFEROWANE_LOTNISKO):
        return None
    wybor, powod = lista[0], "najtańsza opcja"
    if K.DOPLATA_ZA_BEZPOSREDNI is not None and not wybor.bezposredni:
        bez = next((p for p in lista if p.bezposredni), None)
        if bez and bez.cena - wybor.cena <= K.DOPLATA_ZA_BEZPOSREDNI:
            powod = f"bez przesiadek, tylko {zl(bez.cena - wybor.cena)} drożej od najtańszej"
            wybor = bez
    if K.PREFEROWANE_LOTNISKO and wybor.lotnisko_wylotu != K.PREFEROWANE_LOTNISKO:
        alt = next((p for p in lista if p.lotnisko_wylotu == K.PREFEROWANE_LOTNISKO
                    and (p.bezposredni or not wybor.bezposredni)), None)
        if alt and alt.cena - wybor.cena <= (K.DOPLATA_ZA_PREFEROWANE_LOTNISKO or 0):
            roznica = alt.cena - wybor.cena
            powod = (f"wylot z {K.PREFEROWANE_LOTNISKO}"
                     + (f", {zl(roznica)} drożej" if roznica > 0 else ", bez dopłaty")
                     + (", bez przesiadek" if alt.bezposredni else ""))
            wybor = alt
    return wybor, powod


def trend(historia: list[dict], okno: str, kategoria: str, dzis: dt.date) -> dict:
    wiersze = [(dt.date.fromisoformat(w["data"]), int(w["cena"])) for w in historia
               if w["okno"] == okno and w["kategoria"] == kategoria and w["data"] < dzis.isoformat()]
    if not wiersze:
        return {}
    wiersze.sort()
    tydzien = [c for d, c in wiersze if d <= dzis - dt.timedelta(days=7)]
    return {"poprzednio": wiersze[-1][1], "tydzien": tydzien[-1] if tydzien else None,
            "rekord": min(c for _, c in wiersze)}


def zmiana(teraz: int, wczesniej: int | None) -> str:
    if wczesniej is None:
        return ""
    r = teraz - wczesniej
    return "bez zmian" if r == 0 else (f"▼{zl(-r)}" if r < 0 else f"▲{zl(r)}")


def aktualizuj_zdrowie(stan: dict, wyniki: dict[str, Wynik], dzis: dt.date) -> dict:
    stan = json.loads(json.dumps(stan or {}))
    for nazwa, w in wyniki.items():
        s = stan.setdefault(nazwa, {"ostatni_sukces": None, "problemy_z_rzedu": 0})
        if w.status == "ok":
            s["ostatni_sukces"], s["problemy_z_rzedu"] = dzis.isoformat(), 0
        else:
            s["problemy_z_rzedu"] = s.get("problemy_z_rzedu", 0) + 1
        s["status"], s["uwaga"] = w.status, w.uwaga
    return stan


# ---------- wynik dla aplikacji i mail ----------

def jako_dane(p: Podroz, okno: Okno, K=None) -> dict:
    porty = [x[0] for x in (p.przes_tam or []) + (p.przes_pow or [])]
    oznacz = (K.OZNACZ_PRZESIADKI if K else {}) or {}
    return {"oznaczone": list(dict.fromkeys(oznacz[x] for x in porty if x in oznacz)),"zrodlo": p.zrodlo, "rodzaj": p.rodzaj, "trasa": p.trasa, "wylot": p.wylot.isoformat(),
            "powrot": p.powrot.isoformat(), "lotnisko_wylotu": p.lotnisko_wylotu,
            "lotnisko_powrotu": p.lotnisko_powrotu, "cel": p.cel, "cena": p.cena, "opis": p.opis,
            "bezposredni": p.bezposredni, "linki": [l for l in p.linki if l], "dwa_bilety": p.dwa_bilety,
            "noce": okno.noce(p.wylot, p.powrot), "linie": p.linie, "przes_tam": p.przes_tam,
            "przes_pow": p.przes_pow, "czas_tam": p.czas_tam, "czas_pow": p.czas_pow}


LIMIT_POLACZEN = 600


def do_przegladania(lista: list[Podroz], okno: Okno, K=None) -> list[dict]:
    """Wszystkie połączenia okna do filtrowania w aplikacji – bez powtórzeń, najtańsze najpierw."""
    widziane, wynik = set(), []
    for p in lista:
        klucz = (p.wylot, p.powrot, p.lotnisko_wylotu, p.lotnisko_powrotu, p.rodzaj, p.bezposredni,
                 tuple(p.linie), p.cel)
        if klucz in widziane:
            continue
        widziane.add(klucz)
        wynik.append(jako_dane(p, okno, K))
        if len(wynik) >= LIMIT_POLACZEN:
            break
    return wynik


def przeanalizuj(K, okna: list[Okno], wyniki: dict[str, Wynik], dzis: dt.date,
                 historia: list[dict], zdrowie: dict) -> dict:
    """Wynik dla panelu: dane do ekranu, wiersze historii, treść maila i decyzja o wysyłce."""
    dane = {"data": dzis.isoformat(), "czas": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "zrodla": {}, "okna": [], "osob": K.LICZBA_OSOB}
    problem = False
    for nazwa, w in wyniki.items():
        z = zdrowie.get(nazwa, {})
        dane["zrodla"][nazwa] = {"nazwa": NAZWY_ZRODEL[nazwa], "status": w.status, "uwaga": w.uwaga,
                                 "problemy_z_rzedu": z.get("problemy_z_rzedu", 0)}
        if w.status != "ok" and z.get("problemy_z_rzedu", 0) >= 2:
            problem = True
    wiersze_historii, spadek, okazja = [], False, False
    for okno in okna:
        wszystkie = podroze_w_oknie(K, okno, wyniki, dzis)
        lista = [p for p in wszystkie if K.BUDZET_MAKS is None or p.cena <= K.BUDZET_MAKS]
        kat = najlepsze_w_kategoriach(lista)
        o = {"nazwa": okno.nazwa, "krotko": okno.krotko, "od": okno.od.isoformat(), "do": okno.do.isoformat(),
             "min_nocy": okno.min_nocy, "liczba": len(lista), "kategorie": [], "top": [], "prawie": [],
             "awaryjne": [], "polecam": None, "poza_budzetem": None}
        if wszystkie and not lista:
            o["poza_budzetem"] = jako_dane(wszystkie[0], okno, K)
        for klucz, etykieta, _ in KATEGORIE:
            p = kat.get(klucz)
            if not p:
                continue
            t = trend(historia, okno.nazwa, klucz, dzis)
            o["kategorie"].append({"klucz": klucz, "etykieta": etykieta, **jako_dane(p, okno, K), "trend": t})
            wiersze_historii.append({"data": dzis.isoformat(), "okno": okno.nazwa, "kategoria": klucz,
                                     "cena": p.cena})
            if klucz == "najtaniej":
                if not t or p.cena < t["poprzednio"]:
                    spadek = True
                if K.CENA_DOCELOWA and p.cena <= K.CENA_DOCELOWA:
                    okazja = True
        o["top"] = [jako_dane(p, okno, K) for p in lista[:K.ILE_W_RAPORCIE]]
        o["polaczenia"] = do_przegladania(lista, okno, K)
        o["prawie"] = [jako_dane(p, okno, K) for p in prawie(okno, wyniki)[:2]]
        o["awaryjne"] = [{"data": x.data.isoformat(), "cena": x.cena} for x in sorted(
            (x for w in wyniki.values() for x in w.odcinki
             if x.lotnisko == "?" and x.kierunek == "tam" and okno.dobry_wylot(x.data, dzis)),
            key=lambda x: x.cena)[:3]]
        rek = polecam(K, lista)
        if rek:
            o["polecam"] = {**jako_dane(rek[0], okno, K), "powod": rek[1]}
        dane["okna"].append(o)
    temat, tresc_html, tekst = mail(K, dane, problem, okazja)
    wyslac = problem or K.WYSYLAJ == "zawsze" or (K.WYSYLAJ == "spadek" and spadek) \
        or (K.WYSYLAJ == "okazja" and okazja)
    dane["temat"] = temat
    return {"najnowsze": dane, "historia_dzis": wiersze_historii,
            "mail": {"temat": temat, "html": tresc_html, "tekst": tekst, "wyslij": wyslac, "do": K.ODBIORCY}}


def _linia(p: dict, osob: int) -> str:
    suma = f" (razem {zl(p['cena'] * osob)})" if osob > 1 else ""
    linki = p.get("linki") or []
    link = ""
    if linki:
        link = f' · <a href="{html.escape(linki[0])}">otwórz</a>'
        if len(linki) > 1 and linki[1] != linki[0]:
            link = f' · <a href="{html.escape(linki[0])}">tam</a> / <a href="{html.escape(linki[1])}">powrót</a>'
    return f"<b>{zl(p['cena'])}</b>{suma} – {html.escape(p['trasa'])} · {html.escape(p['opis'])}{link}"


def mail(K, dane: dict, problem: bool, okazja: bool) -> tuple[str, str, str]:
    osob = dane["osob"]
    dzien_ = dt.date.fromisoformat(dane["data"])
    czesci = [f"<h3>Loty – {html.escape(K.CEL_NAZWA or K.CEL)} – {dzien_:%d.%m.%Y}</h3>",
              "<p>Ceny za osobę, w obie strony.</p>"]
    zr = []
    for z in dane["zrodla"].values():
        znak = {"ok": "✔", "częściowo": "◐", "błąd": "✘"}.get(z["status"], "?")
        t = f"{z['nazwa']} {znak}"
        if z["status"] != "ok":
            t += f" ({html.escape(z['uwaga'])}" + (
                f"; {z['problemy_z_rzedu']} dni z rzędu" if z["problemy_z_rzedu"] >= 2 else "") + ")"
        zr.append(t)
    czesci.append("<p><b>Źródła:</b> " + " · ".join(zr) + "</p>")
    temat = []
    for o in dane["okna"]:
        czesci.append(f"<h4>{html.escape(o['nazwa'])}</h4>")
        if o["polecam"]:
            czesci.append(f"<p><b>Polecam:</b> {_linia(o['polecam'], osob)}<br><i>{html.escape(o['polecam']['powod'])}</i></p>")
        for k in o["kategorie"]:
            t = k["trend"]
            dod = []
            if t:
                dod.append(f"od poprzedniego {zmiana(k['cena'], t['poprzednio'])}")
                if t.get("tydzien") is not None:
                    dod.append(f"w tydzień {zmiana(k['cena'], t['tydzien'])}")
                dod.append("NAJNIŻSZA DOTĄD" if k["cena"] < t["rekord"] else f"najniżej dotąd {zl(t['rekord'])}")
            czesci.append(f"<p><b>{k['etykieta']}:</b> {_linia(k, osob)}"
                          + (f"<br><i>{' · '.join(dod)}</i>" if dod else "") + "</p>")
        if not o["kategorie"]:
            czesci.append("<p>Brak połączeń spełniających kryteria"
                          + (f" – najtańsza opcja kosztuje {zl(o['poza_budzetem']['cena'])}, powyżej limitu."
                             if o["poza_budzetem"] else ".") + "</p>")
            temat.append(f"{o['krotko']}: brak")
            continue
        naj = o["kategorie"][0]
        temat.append(f"{o['krotko']} od {zl(naj['cena'])}"
                     + (f" {zmiana(naj['cena'], naj['trend']['poprzednio'])}" if naj["trend"] else ""))
    tytul = ("UWAGA: źródło nie działa – " if problem else "") + ("OKAZJA! " if okazja else "") \
        + f"Loty {K.CEL} {dzien_:%d.%m}: " + " | ".join(temat)
    tresc = "".join(czesci)
    tekst = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<(br|/p|/h3|/h4)>", "\n", tresc)))
    return tytul, tresc, tekst


# ---------- zbieranie i panel ----------

def zbierz(K, okna, dzis, test=False) -> dict[str, Wynik]:
    wyniki = {}
    for nazwa, modul in MODULY.items():
        if not K.ZRODLA.get(nazwa):
            continue
        try:
            wyniki[nazwa] = modul.pobierz(okna, K, dzis, test=test)
        except Exception as e:
            wyniki[nazwa] = Wynik(nazwa, status="błąd", uwaga=f"{type(e).__name__}: {e}")
        w = wyniki[nazwa]
        print(f"→ {NAZWY_ZRODEL[nazwa]}: {w.status}; podróży {len(w.podroze)}, odcinków {len(w.odcinki)}"
              + (f"; {w.uwaga}" if w.uwaga else ""))
    return wyniki


def wyslij_mail(mail: dict) -> bool:
    """Raport mailem (opcjonalnie): SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    host = os.environ.get("SMTP_HOST")
    if not host or not mail.get("wyslij") or not mail.get("temat"):
        return False
    port = int(os.environ.get("SMTP_PORT") or 465)
    uzytkownik, haslo = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    adresaci = list(mail.get("do") or []) or [a.strip() for a in (os.environ.get("MAIL_TO") or uzytkownik).split(",")]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = mail["temat"], uzytkownik, ", ".join(adresaci)
    msg.attach(MIMEText(mail.get("tekst", ""), "plain", "utf-8"))
    msg.attach(MIMEText(mail.get("html", ""), "html", "utf-8"))
    serwer = smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)
    with serwer:
        if port != 465:
            serwer.starttls()
        serwer.login(uzytkownik, haslo)
        serwer.sendmail(uzytkownik, adresaci, msg.as_string())
    return True


def tryb_aplikacji(dzis: dt.date) -> None:
    import magazyn
    db = magazyn.Dropbox()
    magazyn.przygotuj(db)
    zlecone = magazyn.zlecenia(db)
    lista = magazyn.wyjazdy(db)
    print(f"Aktywnych wyjazdów: {len(lista)}" + (f", zleceń „Sprawdź teraz”: {len(zlecone)}" if zlecone else ""))
    nieudane = 0
    for w in lista:
        print(f"\n=== {w.get('nazwa')} ===")
        try:
            K = ustawienia(w.get("ustawienia"))
            okna = wczytaj_okna(K, dzis)
            if not okna:
                magazyn.zapisz_wyniki(db, w["id"], {"najnowsze": {
                    "data": dzis.isoformat(), "koniec": True, "zrodla": {}, "okna": [],
                    "temat": "Wszystkie zakresy dat już minęły"}, "historia_dzis": [], "zdrowie": w.get("zdrowie") or {}})
                print("Zakresy dat minęły – pomijam.")
                continue
            wyniki = zbierz(K, okna, dzis)
            zdrowie = aktualizuj_zdrowie(w.get("zdrowie") or {}, wyniki, dzis)
            wynik = przeanalizuj(K, okna, wyniki, dzis, w.get("historia") or [], zdrowie)
            wynik["zdrowie"] = zdrowie
            magazyn.zapisz_wyniki(db, w["id"], wynik)
            try:
                wyslano = wyslij_mail(wynik["mail"])
            except Exception as e:
                wyslano = False
                print(f"Mail nie wyszedł: {type(e).__name__}: {e}")
            print("Zapisano w Dropboxie.", "Mail wysłany." if wyslano else "Bez maila.")
            if wyniki and all(x.status == "błąd" for x in wyniki.values()):
                nieudane += 1
        except Exception as e:
            nieudane += 1
            print(f"BŁĄD wyjazdu {w.get('nazwa')}: {type(e).__name__}: {e}")
    for z in zlecone:
        db.usun(z)
    magazyn.zapisz_stan(db, przebieg_koniec=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    if lista and nieudane == len(lista):
        sys.exit(1)


def main() -> None:
    dzis = dt.date.today()
    if "--przygotuj" in sys.argv:
        import magazyn
        magazyn.przygotuj(magazyn.Dropbox())
        print("Folder aplikacji w Dropboxie gotowy.")
        return
    lokalnie = any(a in sys.argv for a in ("--lokalnie", "--test-zrodel", "--zrzut")) or not (
        os.environ.get("DROPBOX_REFRESH_TOKEN") or os.environ.get("DROPBOX_TOKEN"))
    if not lokalnie:
        tryb_aplikacji(dzis)
        return
    import ustawienia as U
    K = ustawienia({k: getattr(U, k) for k in dir(U) if k.isupper()})
    if "--zrzut" in sys.argv:
        rainbow.zrzut(K, KATALOG / "dane" / "zrzuty")
        itaka.zrzut(K, KATALOG / "dane" / "zrzuty")
        return
    okna = wczytaj_okna(K, dzis)
    if not okna:
        print("Wszystkie zakresy dat już minęły.")
        return
    test = "--test-zrodel" in sys.argv
    wyniki = zbierz(K, okna, dzis, test)
    if test:
        for nazwa, w in wyniki.items():
            for p in w.podroze[:2]:
                print(f"   {nazwa}: {p.trasa} {zl(p.cena)} {p.opis}")
            for o in w.odcinki[:3]:
                print(f"   {nazwa}: {o.kierunek} {o.lotnisko} {o.data} {zl(o.cena)} {o.opis}")
        zle = [n for n, w in wyniki.items() if w.status == "błąd"]
        print("\nTEST:", "WSZYSTKIE ŹRÓDŁA DZIAŁAJĄ" if not zle else f"NIE DZIAŁA: {', '.join(zle)}")
        sys.exit(1 if zle else 0)
    wynik = przeanalizuj(K, okna, wyniki, dzis, [], aktualizuj_zdrowie({}, wyniki, dzis))
    print(wynik["mail"]["temat"] + "\n\n" + wynik["mail"]["tekst"])


if __name__ == "__main__":
    main()
