"""The period a downloadable report covers, and the one it is compared with.

Every Word report takes a period now (the screen's selector, or the profile's
download dialog). Without one it defaults to the last 30 days — never "all
time": a report about everything is a report about nothing in particular, and
it grew to dozens of pages. The previous period has the SAME length and ends
where this one starts, so "▲ 8 % vs el período anterior" compares like with
like.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

DISPLAY_TZ = ZoneInfo("America/Santiago")
DIAS_POR_DEFECTO = 30


@dataclass(frozen=True)
class Periodo:
    desde: datetime
    hasta: datetime

    @classmethod
    def de(cls, desde: datetime | None, hasta: datetime | None,
           dias: int = DIAS_POR_DEFECTO) -> "Periodo":
        """From the parsed query params (`_parse_date_window`). A missing end
        is now; a missing start is `dias` before the end."""
        fin = hasta or timezone.now()
        if timezone.is_naive(fin):
            fin = timezone.make_aware(fin)
        inicio = desde or (fin - timedelta(days=dias))
        if timezone.is_naive(inicio):
            inicio = timezone.make_aware(inicio)
        if inicio > fin:
            inicio, fin = fin, inicio
        return cls(inicio, fin)

    @property
    def dias(self) -> int:
        return max(1, round((self.hasta - self.desde).total_seconds() / 86400))

    def anterior(self) -> "Periodo":
        largo = self.hasta - self.desde
        fin = self.desde - timedelta(microseconds=1)
        return Periodo(fin - largo, fin)

    def etiqueta(self) -> str:
        a = timezone.localtime(self.desde, DISPLAY_TZ).strftime("%d/%m/%Y")
        b = timezone.localtime(self.hasta, DISPLAY_TZ).strftime("%d/%m/%Y")
        return f"{a} – {b} ({self.dias} días)"

    def clave(self) -> dict:
        """For report signatures and the agent's payload."""
        return {"desde": self.desde.date().isoformat(), "hasta": self.hasta.date().isoformat(),
                "dias": self.dias}


FORMATOS = ("ejecutivo", "completo")


def formato(raw: str | None) -> str:
    return raw if raw in FORMATOS else "ejecutivo"
