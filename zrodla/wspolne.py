"""Wspólne struktury danych i pomocnicze funkcje."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

DNI = ["pn", "wt", "śr", "czw", "pt", "sob", "nd"]
MIESIACE = {"sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
            "lip": 7, "sie": 8, "wrz": 9, "paź": 10, "lis": 11, "gru": 12}
SKROTY_MIESIECY = {v: k for k, v in MIESIACE.items()}


def zl(kwota: int) -> str:
    return f"{kwota:,.0f}".replace(",", " ") + " zł"


def dzien(d: dt.date) -> str:
    return f"{d:%d.%m} ({DNI[d.weekday()]})"


def godz(minuty: int) -> str:
    return f"{minuty // 60} h {minuty % 60:02d} min"


def rok_dla_miesiaca(mies: int, dzis: dt.date) -> int:
    """Strony biur podróży podają daty bez roku – bierzemy najbliższy przyszły."""
    return dzis.year if mies >= dzis.month else dzis.year + 1


@dataclass
class Okno:
    nazwa: str
    krotko: str
    od: dt.date
    do: dt.date
    min_nocy: int
    przylot_nast: bool = True              # przylot dzień po wylocie (lot daleki)
    maks_nocy: int | None = None
    dni: frozenset = frozenset(range(7))   # dozwolone dni tygodnia wylotu (0 = poniedziałek)

    def noce(self, wylot: dt.date, powrot: dt.date) -> int:
        return (powrot - wylot).days - (1 if self.przylot_nast else 0)

    def _odstep(self) -> dt.timedelta:
        return dt.timedelta(days=self.min_nocy + (1 if self.przylot_nast else 0))

    def dobra_para(self, wylot: dt.date, powrot: dt.date) -> bool:
        n = self.noce(wylot, powrot)
        return (self.od <= wylot and powrot <= self.do and wylot.weekday() in self.dni
                and n >= self.min_nocy and (self.maks_nocy is None or n <= self.maks_nocy))

    def dobry_wylot(self, d: dt.date, dzis: dt.date) -> bool:
        return d > dzis and self.od <= d and d.weekday() in self.dni and d + self._odstep() <= self.do

    def dobry_powrot(self, d: dt.date, dzis: dt.date) -> bool:
        najwczesniej = max(self.od, dzis + dt.timedelta(days=1)) + self._odstep()
        return najwczesniej <= d <= self.do

    def wyloty(self, dzis: dt.date) -> list[dt.date]:
        return [self.od + dt.timedelta(days=i) for i in range((self.do - self.od).days + 1)
                if self.dobry_wylot(self.od + dt.timedelta(days=i), dzis)]

    def powroty(self, dzis: dt.date) -> list[dt.date]:
        return [self.od + dt.timedelta(days=i) for i in range((self.do - self.od).days + 1)
                if self.dobry_powrot(self.od + dt.timedelta(days=i), dzis)]

    def pary(self, dzis: dt.date) -> list[tuple[dt.date, dt.date]]:
        return [(w, r) for w in self.wyloty(dzis) for r in self.powroty(dzis) if self.dobra_para(w, r)]


def wczytaj_okna(U, dzis: dt.date) -> list[Okno]:
    dni = frozenset(DNI.index(d) for d in (getattr(U, "DNI_WYLOTU", None) or DNI) if d in DNI)
    okna = [Okno(o["nazwa"], o.get("krotko") or (o["nazwa"].split() or ["Zakres"])[0],
                 dt.date.fromisoformat(o["od"]), dt.date.fromisoformat(o["do"]), int(U.MIN_NOCY_NA_MIEJSCU),
                 bool(getattr(U, "PRZYLOT_NASTEPNEGO_DNIA", True)),
                 getattr(U, "MAKS_NOCY_NA_MIEJSCU", None), dni) for o in U.OKNA]
    return [o for o in okna if o.pary(dzis)]


@dataclass
class Odcinek:
    """Lot w jedną stronę (bilet sprzedawany osobno)."""
    zrodlo: str            # google / rainbow / itaka
    czarter: bool
    kierunek: str          # "tam" albo "powrot"
    lotnisko: str          # polskie lotnisko (WAW, KTW…); "?" gdy nieznane
    data: dt.date
    cena: int              # za osobę
    opis: str
    bezposredni: bool
    link: str = ""
    cel: str = ""
    linie: list[str] = field(default_factory=list)
    przesiadki: list = field(default_factory=list)   # [[port, minuty], …]
    czas_min: int | None = None                       # cała podróż w jedną stronę
    rozklad: list | None = None   # [[skąd, „HH:MM”, dokąd, „HH:MM”, dni po wylocie], …]; None = nieznany


@dataclass
class Podroz:
    """Gotowa podróż tam i z powrotem."""
    zrodlo: str
    rodzaj: str            # "rejsowy" / "czarter" / "mieszany"
    lotnisko_wylotu: str
    lotnisko_powrotu: str
    wylot: dt.date
    powrot: dt.date
    cena: int              # za osobę, w obie strony
    opis: str
    bezposredni: bool
    linki: list[str] = field(default_factory=list)
    dwa_bilety: bool = False
    cel: str = ""
    linie: list[str] = field(default_factory=list)
    przes_tam: list | None = field(default_factory=list)   # None = nieznane
    przes_pow: list | None = field(default_factory=list)
    czas_tam: int | None = None
    czas_pow: int | None = None
    rozklad_tam: list | None = None   # godziny odcinków (jak Odcinek.rozklad); None = nieznane
    rozklad_pow: list | None = None

    @property
    def trasa(self) -> str:
        lot = self.lotnisko_wylotu if self.lotnisko_wylotu == self.lotnisko_powrotu \
            else f"{self.lotnisko_wylotu}/{self.lotnisko_powrotu}"
        if self.cel:
            lot += f"–{self.cel}"
        return f"{lot} {dzien(self.wylot)} → {dzien(self.powrot)}"


@dataclass
class Wynik:
    zrodlo: str
    podroze: list[Podroz] = field(default_factory=list)
    odcinki: list[Odcinek] = field(default_factory=list)
    zapytania: int = 0
    udane: int = 0
    status: str = "ok"     # ok / częściowo / błąd
    uwaga: str = ""
