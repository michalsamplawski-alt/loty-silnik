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
    try:
        stan = json.loads(db.pobierz(magazyn.sciezka("stan.json")) or "{}")
    except ValueError:
        stan = {}
    teraz = dt.datetime.now(dt.timezone.utc)
    zdarzenie = os.environ.get("GITHUB_EVENT_NAME", "")
    uruchom, powod = decyzja(zdarzenie, teraz, stan, bool(magazyn.zlecenia(db)) if zdarzenie != "workflow_dispatch" else False)
    print("Pełne sprawdzanie:", uruchom, f"({powod})" if powod else "")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as f:
        f.write(f"uruchom={uruchom}\npowod={powod}\n")
