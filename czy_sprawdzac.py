"""Szybka decyzja dla harmonogramu: czy uruchomić pełne sprawdzanie (tylko biblioteka standardowa + strefa czasowa).

Tak, gdy:
- uruchomienie ręczne,
- zlecenie „Sprawdź teraz” z aplikacji,
- po 6:00 czasu polskiego, a dzisiejszego porannego sprawdzenia jeszcze nie było.
  GitHub potrafi pominąć zaplanowane uruchomienie (np. o 6:15), więc poranne sprawdzenie robi
  pierwsze uruchomienie, które faktycznie nastąpi po tej godzinie.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

POLSKA = ZoneInfo("Europe/Warsaw")
GODZINA_PORANNA = 6


def decyzja(zdarzenie: str, teraz: dt.datetime, stan: dict | None, zlecenia: bool) -> tuple[str, str]:
    """(uruchom „tak”/„nie”, powód: „reczne” / „poranne” / „zlecenie” / „”)."""
    lokalnie = teraz.astimezone(POLSKA)
    if zdarzenie == "workflow_dispatch":
        return "tak", "reczne"
    if lokalnie.hour >= GODZINA_PORANNA and (stan or {}).get("poranne") != lokalnie.date().isoformat():
        return "tak", "poranne"
    if zlecenia:
        return "tak", "zlecenie"
    return "nie", ""


if __name__ == "__main__":
    import magazyn

    db = magazyn.Dropbox()
    if "--koniec" in sys.argv:
        # po wszystkich równoległych zadaniach: aplikacja przestaje pokazywać „Trwa nowe sprawdzenie”
        magazyn.zapisz_stan(db, przebieg_koniec=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        print("Sprawdzanie zakończone.")
        sys.exit(0)
    try:
        stan = json.loads(db.pobierz(magazyn.sciezka("stan.json")) or "{}")
    except ValueError:
        stan = {}
    teraz = dt.datetime.now(dt.timezone.utc)
    zdarzenie = os.environ.get("GITHUB_EVENT_NAME", "")
    uruchom, powod = decyzja(zdarzenie, teraz, stan, bool(magazyn.zlecenia(db)) if zdarzenie != "workflow_dispatch" else False)
    ids: list[str] = []
    if uruchom == "tak":
        # Plan dla równoległych zadań: lista wyjazdów; zlecenia „Sprawdź teraz” są od razu przyjęte (usunięte),
        # a znacznik porannego sprawdzenia ustawiony – kolejne godzinne uruchomienia go nie powtórzą.
        magazyn.przygotuj(db)
        ids = [w["id"] for w in magazyn.wyjazdy(db) if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", w["id"])]
        for z in magazyn.zlecenia(db):
            db.usun(z)
        zmiany = {"przebieg_start": teraz.isoformat(timespec="seconds")}
        lokalnie = teraz.astimezone(POLSKA)
        if powod in ("poranne", "reczne") and lokalnie.hour >= GODZINA_PORANNA:
            zmiany["poranne"] = lokalnie.date().isoformat()
        if not ids:
            uruchom = "nie"
            zmiany["przebieg_koniec"] = zmiany["przebieg_start"]
        magazyn.zapisz_stan(db, **zmiany)
    print("Pełne sprawdzanie:", uruchom, f"({powod})" if powod else "", f"– wyjazdy: {', '.join(ids)}" if ids else "")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as f:
        f.write(f"uruchom={uruchom}\npowod={powod}\nwyjazdy={json.dumps(ids)}\n")
