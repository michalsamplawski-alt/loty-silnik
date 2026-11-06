"""Dropbox jako miejsce wymiany danych z aplikacją „Loty” w Claude.

Układ folderu aplikacji (Dropbox → Aplikacje → Loty):
    stan.json                              znacznik gotowości + czas ostatniego sprawdzenia
    wyjazdy/<id>/kryteria-<czas>.json      kryteria zapisane w aplikacji (najnowszy plik obowiązuje)
    wyniki/<id>/najnowsze.json             ostatnie wyniki do ekranu
    wyniki/<id>/historia.json              najniższe ceny z kolejnych dni
    wyniki/<id>/zdrowie.json               stan źródeł (ile dni z rzędu nie działają)
    zlecenia/<czas>.json                   przycisk „Sprawdź teraz”

Tylko biblioteka standardowa – używa go też szybki skrypt czy_sprawdzac.py.
Sekrety: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN (albo DROPBOX_TOKEN do testów).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("DROPBOX_API_URL", "https://api.dropboxapi.com")
TRESC = os.environ.get("DROPBOX_CONTENT_URL", "https://content.dropboxapi.com")
FOLDER = os.environ.get("DROPBOX_FOLDER", "").rstrip("/")   # "" = folder aplikacji
ZACHOWAJ_WERSJI = 3


def sciezka(*czesci: str) -> str:
    return FOLDER + "/" + "/".join(czesci)


class BladDropboxa(RuntimeError):
    def __init__(self, kod: int, tresc: str):
        super().__init__(f"Dropbox {kod}: {tresc[:300]}")
        self.kod, self.tresc = kod, tresc

    @property
    def nie_ma(self) -> bool:
        return self.kod == 409 and "not_found" in self.tresc


class Dropbox:
    def __init__(self) -> None:
        self._token: str | None = None

    def token(self) -> str:
        if self._token:
            return self._token
        if os.environ.get("DROPBOX_TOKEN"):
            self._token = os.environ["DROPBOX_TOKEN"]
            return self._token
        dane = urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": os.environ["DROPBOX_REFRESH_TOKEN"],
            "client_id": os.environ["DROPBOX_APP_KEY"], "client_secret": os.environ["DROPBOX_APP_SECRET"],
        }).encode()
        with urllib.request.urlopen(urllib.request.Request(API + "/oauth2/token", data=dane), timeout=30) as odp:
            self._token = json.load(odp)["access_token"]
        return self._token

    def _wyslij(self, url: str, *, json_cialo=None, arg=None, dane: bytes | None = None, pobieranie=False) -> bytes:
        naglowki = {"Authorization": "Bearer " + self.token()}
        if arg is not None:
            naglowki["Dropbox-API-Arg"] = json.dumps(arg)          # ASCII – wymóg Dropboxa
        if json_cialo is not None:
            naglowki["Content-Type"] = "application/json"
            dane = json.dumps(json_cialo).encode()
        elif pobieranie:
            naglowki["Content-Type"] = "text/plain; charset=dropbox-cors-hack"
            dane = b""
        else:
            naglowki["Content-Type"] = "application/octet-stream"
        ostatni: Exception | None = None
        for proba in range(4):
            try:
                req = urllib.request.Request(url, data=dane if dane is not None else b"", method="POST", headers=naglowki)
                with urllib.request.urlopen(req, timeout=90) as odp:
                    return odp.read()
            except urllib.error.HTTPError as e:
                tresc = e.read().decode("utf-8", "replace")
                if e.code in (429, 500, 502, 503, 504):
                    ostatni = BladDropboxa(e.code, tresc)
                    time.sleep(float(e.headers.get("Retry-After") or 3 * (proba + 1)))
                    continue
                raise BladDropboxa(e.code, tresc) from None
            except urllib.error.URLError as e:
                ostatni = e
                time.sleep(3 * (proba + 1))
        raise RuntimeError(f"Dropbox niedostępny: {ostatni}")

    def lista(self, sciezka_: str, rekursywnie: bool = True) -> list[dict]:
        try:
            odp = json.loads(self._wyslij(API + "/2/files/list_folder",
                                          json_cialo={"path": sciezka_, "recursive": rekursywnie}))
        except BladDropboxa as e:
            if e.nie_ma:
                return []
            raise
        wpisy = odp["entries"]
        while odp.get("has_more"):
            odp = json.loads(self._wyslij(API + "/2/files/list_folder/continue", json_cialo={"cursor": odp["cursor"]}))
            wpisy += odp["entries"]
        return wpisy

    def pobierz(self, sciezka_: str) -> str | None:
        try:
            return self._wyslij(TRESC + "/2/files/download", arg={"path": sciezka_}, pobieranie=True).decode("utf-8")
        except BladDropboxa as e:
            if e.nie_ma:
                return None
            raise

    def zapisz(self, sciezka_: str, tekst: str) -> None:
        self._wyslij(TRESC + "/2/files/upload", arg={"path": sciezka_, "mode": "overwrite", "mute": True},
                     dane=tekst.encode("utf-8"))

    def usun(self, sciezka_: str) -> None:
        try:
            self._wyslij(API + "/2/files/delete_v2", json_cialo={"path": sciezka_})
        except BladDropboxa as e:
            if not e.nie_ma:
                raise

    def utworz_folder(self, sciezka_: str) -> None:
        try:
            self._wyslij(API + "/2/files/create_folder_v2", json_cialo={"path": sciezka_})
        except BladDropboxa as e:
            if e.kod != 409:
                raise


def _json(tekst: str | None, domyslne):
    if not tekst:
        return domyslne
    try:
        return json.loads(tekst)
    except ValueError:
        return domyslne


def _sciezka_wpisu(wpis: dict) -> str:
    """Ścieżka do operacji na pliku (z zachowaniem wielkości liter)."""
    return wpis.get("path_display") or wpis["path_lower"]


def _wzgledna(wpis: dict) -> str:
    """Ścieżka wpisu względem folderu aplikacji, małymi literami."""
    pelna = wpis["path_lower"]
    baza = FOLDER.lower()
    return pelna[len(baza):].lstrip("/") if baza and pelna.startswith(baza) else pelna.lstrip("/")


def przygotuj(db: Dropbox) -> None:
    """Zakłada strukturę folderu i znacznik gotowości, który sprawdza aplikacja w Claude."""
    for f in ("wyjazdy", "wyniki", "zlecenia"):
        db.utworz_folder(sciezka(f))
    if db.pobierz(sciezka("stan.json")) is None:
        db.zapisz(sciezka("stan.json"), json.dumps({"gotowe": True, "utworzono": _teraz()}, ensure_ascii=False))


def _teraz() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def wyjazdy(db: Dropbox) -> list[dict]:
    """Aktywne wyjazdy z najnowszych kryteriów; przy okazji sprząta stare wersje i usunięte wyjazdy."""
    pliki: dict[str, list[dict]] = {}
    for w in db.lista(sciezka("wyjazdy")):
        if w.get(".tag") != "file" or not w["name"].startswith("kryteria-"):
            continue
        czesci = _wzgledna(w).split("/")
        if len(czesci) == 3 and czesci[0] == "wyjazdy":
            pliki.setdefault(czesci[1], []).append(w)
    wynik = []
    for id_, lista in pliki.items():
        lista.sort(key=lambda w: w["name"])
        kryteria = _json(db.pobierz(_sciezka_wpisu(lista[-1])), None)
        for stary in lista[:-ZACHOWAJ_WERSJI]:
            db.usun(_sciezka_wpisu(stary))
        if not kryteria:
            continue
        if kryteria.get("usuniety"):
            db.usun(sciezka("wyjazdy", id_))
            db.usun(sciezka("wyniki", id_))
            continue
        if not kryteria.get("aktywny", True):
            continue
        wynik.append({
            "id": id_, "nazwa": kryteria.get("nazwa", id_), "ustawienia": kryteria.get("ustawienia") or {},
            "historia": _json(db.pobierz(sciezka("wyniki", id_, "historia.json")), []),
            "zdrowie": _json(db.pobierz(sciezka("wyniki", id_, "zdrowie.json")), {}),
        })
    return wynik


def zapisz_wyniki(db: Dropbox, id_: str, wynik: dict) -> None:
    db.utworz_folder(sciezka("wyniki", id_))
    db.zapisz(sciezka("wyniki", id_, "najnowsze.json"), json.dumps(wynik.get("najnowsze") or {}, ensure_ascii=False))
    db.zapisz(sciezka("wyniki", id_, "zdrowie.json"), json.dumps(wynik.get("zdrowie") or {}, ensure_ascii=False))
    dzis = wynik.get("historia_dzis") or []
    daty = {w["data"] for w in dzis}
    historia = [w for w in _json(db.pobierz(sciezka("wyniki", id_, "historia.json")), []) if w.get("data") not in daty]
    historia = sorted(historia + dzis, key=lambda w: w["data"])[-5000:]
    db.zapisz(sciezka("wyniki", id_, "historia.json"), json.dumps(historia, ensure_ascii=False))


def zapisz_stan(db: Dropbox, **zmiany) -> None:
    stan = _json(db.pobierz(sciezka("stan.json")), {"gotowe": True})
    stan.update(zmiany)
    db.zapisz(sciezka("stan.json"), json.dumps(stan, ensure_ascii=False))


def zlecenia(db: Dropbox) -> list[str]:
    return [_sciezka_wpisu(w) for w in db.lista(sciezka("zlecenia"), rekursywnie=False) if w.get(".tag") == "file"]
