"""Vincular cada plantilla a las categorías donde el club YA cargó datos.

    # ensayo
    docker compose exec backend python manage.py link_templates_with_data \\
        --club "Universidad de Chile"

    # aplicar
    docker compose exec backend python manage.py link_templates_with_data \\
        --club "Universidad de Chile" --commit

El mismo desfase apareció tres veces en una semana — `ficha_partido` con 2920
fichas invisibles, `pentacompartimental` con 1465, y un puñado de exámenes
médicos sueltos — así que conviene un comando y no un one-off más.

El síntoma es siempre el mismo y es silencioso: alguien carga el examen para una
categoría, el dato queda bien atribuido al jugador, y no aparece en ningún
dashboard porque `applicable_categories` nunca se amplió. Nada falla; la
pantalla simplemente está vacía.

La regla que aplica: **si hay resultados de esa plantilla para jugadores de esa
categoría, la categoría usa la plantilla.** Los datos son la evidencia; la M2M
es la que quedó atrás.

⚠️ Salta las plantillas que declaran un bloque `wellness`
--------------------------------------------------------
`api/wellness.py` elige el formulario de check-in de una categoría entre las
plantillas que le aplican Y declaran `wellness`. Vincular `checkin_formativo` a
Primer Equipo por tener datos de un ascendido haría que ESE pase a ser su
check-in declarado, y el plantel entero quedaría midiéndose contra un formulario
que no llena. Para el historial del jugador que cambió de categoría está el
fallback de lectura en `dashboards/chart_spec.py`, que no toca la M2M.

Tampoco toca `applicable_categories` a la baja: sólo agrega.

⚠️ Distinguir "la categoría usa el examen" de "un ascendido trae historial"
--------------------------------------------------------------------------
Las dos cosas se ven igual en la base — hay filas de esa plantilla para
jugadores de esa categoría — y necesitan soluciones opuestas. `pentacompartimental`
en SUB-20 son 311 mediciones que el club sigue tomando: hay que vincular.
`carreras` en Primer Equipo son 52 filas del historial juvenil de jugadores
promovidos: vincular ahí le ofrecería al plantel una batería de tests que no
corre, y el historial ya se resuelve por el fallback de lectura de
`dashboards/chart_spec.py`.

La señal que las separa es la FECHA: si la última fila de esa categoría es vieja
mientras la plantilla se sigue usando en otras, es historial y no práctica. El
comando la imprime en cada línea; **la decisión es del operador**, por eso
`--slug` existe y el ensayo es el modo por defecto.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Max

from core.models import Club
from exams.models import ExamResult, ExamTemplate


class Command(BaseCommand):
    help = ("Amplía applicable_categories a las categorías que ya tienen "
            "resultados de esa plantilla.")

    def add_arguments(self, parser):
        parser.add_argument("--club", required=True)
        parser.add_argument("--slug", action="append", dest="slugs",
                            help="Limitar a una plantilla (repetible).")
        parser.add_argument("--min-resultados", type=int, default=1,
                            help="Ignorar categorías con menos de N filas.")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        club = Club.objects.filter(name=opts["club"]).first()
        if club is None:
            raise CommandError(f"No existe el club '{opts['club']}'.")

        plantillas = ExamTemplate.objects.filter(department__club=club)
        if opts["slugs"]:
            plantillas = plantillas.filter(slug__in=opts["slugs"])

        if not opts["commit"]:
            self.stdout.write(self.style.WARNING("ENSAYO — no escribe nada.\n"))

        total_cats = total_filas = 0
        saltadas = []
        with transaction.atomic():
            for t in plantillas.order_by("slug"):
                if (t.config_schema or {}).get("wellness"):
                    saltadas.append(t.slug)
                    continue
                aplica = set(t.applicable_categories.values_list("id", flat=True))
                faltan = [
                    (r["player__category_id"], r["player__category__name"],
                     r["n"], r["ultima"])
                    for r in (ExamResult.objects
                              .filter(template=t, player__category__club=club)
                              .values("player__category_id",
                                      "player__category__name")
                              .annotate(n=Count("id"), ultima=Max("recorded_at")))
                    if r["player__category_id"] not in aplica
                    and r["n"] >= opts["min_resultados"]
                ]
                if not faltan:
                    continue
                faltan.sort(key=lambda x: -x[2])
                filas = sum(x[2] for x in faltan)
                # La última fila que la plantilla tiene en las categorías que SÍ
                # la aplican: el punto de comparación para leer las fechas.
                viva = (ExamResult.objects
                        .filter(template=t,
                                player__category_id__in=aplica)
                        .aggregate(m=Max("recorded_at"))["m"])
                total_cats += len(faltan)
                total_filas += filas
                self.stdout.write(self.style.SUCCESS(
                    f"  {t.slug:24} +{len(faltan)} categorías · {filas} filas"))
                for _, nombre, n, ultima in faltan:
                    marca = ""
                    if viva and ultima and (viva - ultima).days > 90:
                        marca = "   ⚠ parece historial, no práctica"
                    fecha = ultima.date().isoformat() if ultima else "—"
                    self.stdout.write(
                        f"      · {nombre:22} {n:5}  última {fecha}{marca}")
                t.applicable_categories.add(*[x[0] for x in faltan])
            if not opts["commit"]:
                transaction.set_rollback(True)

        self.stdout.write("")
        if saltadas:
            # No es un error: es la política. Que se vea, para que nadie la
            # confunda con un olvido.
            self.stdout.write(self.style.NOTICE(
                f"  Saltadas por declarar bloque `wellness`: {', '.join(saltadas)}"))
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"  {total_cats} vínculo(s) · {total_filas} filas que pasan a ser "
            f"visibles"))
        if not opts["commit"]:
            self.stdout.write(self.style.WARNING(
                "\n  ENSAYO — volvé a correr con --commit."))
