"""Szybka decyzja dla harmonogramu: czy uruchomić pełne sprawdzanie (tylko biblioteka standardowa).

Tak: ręczne uruchomienie, poranne sprawdzanie albo zlecenie „Sprawdź teraz” z aplikacji.
"""
import os

import magazyn

ZDARZENIE = os.environ.get("GITHUB_EVENT_NAME", "")
HARMONOGRAM = os.environ.get("HARMONOGRAM", "")
PORANNY = os.environ.get("PORANNY", "15 5 * * *")

if ZDARZENIE == "workflow_dispatch" or HARMONOGRAM == PORANNY:
    decyzja = "tak"
else:
    decyzja = "tak" if magazyn.zlecenia(magazyn.Dropbox()) else "nie"
print("Pełne sprawdzanie:", decyzja)
with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as f:
    f.write(f"uruchom={decyzja}\n")
