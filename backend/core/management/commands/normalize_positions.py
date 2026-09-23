"""Normaliza el catálogo de posiciones: `Position.role` pasa a ser la LÍNEA.

    docker compose exec backend python manage.py normalize_positions
    # ... leer el reporte, después agregar --commit

Por qué
-------
El catálogo de la U. de Chile son dos vocabularios superpuestos: uno genérico
(`Arquero`, `Mediocampista`, `Delantero`, `Defensor`) que usa sobre todo Primer
Equipo, y uno granular (`Defensa central`, `Lateral derecho`, `Volante
interior`, …) que usa el formativo. Comparar un juvenil contra "el promedio de
su posición en Primer Equipo" por nombre exacto dejaba a **154 de 354**
jugadores sin referencia —todos los laterales, entre ellos— y donde sí
coincidía el promedio salía de 1 a 3 jugadores, que no es un promedio.

`Position.role` ya existía para esto: su docstring dice "Optional grouping shown
above the name, e.g. 'Mediocampista'". Pero se estaba usando como marca de
GRANULARIDAD (`General` / `Específica` / vacío), que no agrupa nada. Este
comando lo devuelve a su propósito.

⚠️ Esto NO mueve a ningún jugador de posición
---------------------------------------------
No se borra ninguna fila y no se repunta ningún FK. Sólo se escriben `role` y
`sort_order` de las `Position`. Tres razones para que sea así de conservador:

1. **Ninguna posición está muerta.** Las cinco que no tienen jugadores sí
   sostienen fichas de partido a través de `EventParticipant.position_played`:
   `VD` 80, `LVD` 76, `VI` 53, `LVI` 19. Borrarlas destruiría la posición de
   228 participaciones.
2. **Los genéricos no son un error a corregir.** Que un jugador figure como
   `Mediocampista` y no como `Volante interior` significa que el club no
   especificó el sub-rol, no que esté mal cargado. Meterlo a la fuerza en uno
   específico sería inventar un dato.
3. Un FK que no se toca es un FK que no se puede romper. 414 jugadores, 211
   posiciones secundarias y 3.193 participaciones quedan exactamente igual.

El mapa sale del dato del club, no de mi criterio
-------------------------------------------------
`secondary_position` ya venía usándose como la línea: 211 jugadores la tienen y
SÓLO toma valores del catálogo genérico. El cruce contra la posición primaria
corrobora el mapa de abajo — de 211 filas, 209 caen donde el mapa dice y 2 no
(un `Delantero` sobre `Mediocampista` y otro sobre `Defensa central`, que el
comando reporta para que el club los revise).

Con las cuatro líneas, el 100% de los jugadores activos queda con referencia y
la muestra de Primer Equipo es Defensa 10 · Mediocampo 10 · Ataque 8 ·
Arquero 2. La de arqueros es chica y hay que mostrarla con su `n` al lado.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Club, Player, Position
# El mapa vive en `core.positions` y no acá: lo comparten este comando, el
# importador del plantel formativo y la comparación entre divisiones. Tener una
# copia por consumidor es exactamente el problema que este comando arregla.
from core.positions import CANON


class Command(BaseCommand):
    help = "Escribe la línea (role) y el orden canónico en el catálogo de posiciones."

    def add_arguments(self, parser):
        parser.add_argument("--club", default=None,
                            help="Nombre exacto. Omitido: todos los clubes.")
        parser.add_argument("--commit", action="store_true",
                            help="Escribe. Sin esto: simulación.")

    def handle(self, *args, **opts):
        clubes = Club.objects.all()
        if opts["club"]:
            clubes = clubes.filter(name=opts["club"])
            if not clubes.exists():
                raise CommandError(f"No existe el club '{opts['club']}'.")

        cambios: list[tuple[str, str, str, str]] = []
        sin_mapa: list[str] = []
        with transaction.atomic():
            for club in clubes:
                for pos in Position.objects.filter(club=club).order_by("abbreviation"):
                    canon = CANON.get(pos.abbreviation)
                    if canon is None:
                        sin_mapa.append(f"{club.name} · {pos.abbreviation} — {pos.name}")
                        continue
                    linea, orden = canon
                    antes = pos.role or "—"
                    if pos.role == linea and pos.sort_order == orden:
                        continue
                    cambios.append((club.name, pos.abbreviation, antes, linea))
                    pos.role, pos.sort_order = linea, orden
                    pos.save(update_fields=["role", "sort_order"])
            if not opts["commit"]:
                transaction.set_rollback(True)

        self._reportar(cambios, sin_mapa, clubes, opts)

    # ── reporte ──────────────────────────────────────────────────────────
    def _reportar(self, cambios, sin_mapa, clubes, opts):
        cab = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(f"\n{cab} · {len(cambios)} posición(es) actualizada(s)\n")
        for club, abbr, antes, linea in cambios:
            self.stdout.write(f"  {club} · {abbr:<4} role: {antes:<12} → {linea}")

        if sin_mapa:
            self.stdout.write(self.style.WARNING(
                f"\n  ⚠️ Sin entrada en CANON: {len(sin_mapa)} — quedaron intactas"))
            for s in sin_mapa:
                self.stdout.write(f"      · {s}")
            self.stdout.write(
                "      Agregalas a CANON antes de confiar en la comparación "
                "por línea: una posición sin línea no tiene contra qué medirse.")

        # Contraste contra la evidencia del club: `secondary_position` venía
        # usándose como la línea, así que tiene que coincidir con el mapa.
        self._contrastar_con_secundaria(clubes)

    def _contrastar_con_secundaria(self, clubes):
        discrepan: list[str] = []
        total = 0
        for p in (Player.objects
                  .filter(category__club__in=clubes,
                          secondary_position__isnull=False,
                          position__isnull=False)
                  .select_related("position", "secondary_position")):
            linea_pri = CANON.get(p.position.abbreviation, (None, 0))[0]
            linea_sec = CANON.get(p.secondary_position.abbreviation, (None, 0))[0]
            if linea_pri is None or linea_sec is None:
                continue
            total += 1
            if linea_pri != linea_sec:
                discrepan.append(
                    f"{p.first_name} {p.last_name}: "
                    f"{p.position.name} ({linea_pri}) vs "
                    f"secundaria {p.secondary_position.name} ({linea_sec})")

        if not total:
            return
        ok = total - len(discrepan)
        self.stdout.write(
            f"\n  Contraste con `secondary_position` (la línea que ya cargó el "
            f"club): {ok} de {total} coinciden con el mapa.")
        if discrepan:
            self.stdout.write(self.style.WARNING(
                f"  ⚠️ {len(discrepan)} no coinciden — para que las revise el club:"))
            for d in discrepan:
                self.stdout.write(f"      · {d}")
