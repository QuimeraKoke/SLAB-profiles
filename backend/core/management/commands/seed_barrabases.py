"""Club de demostración "Los Barrabases": clon de features, datos propios.

    docker compose exec backend python manage.py seed_barrabases
    # ... leer el reporte, después agregar --commit

Dos mitades, y la separación es deliberada.

**La configuración se CLONA** del club de origen: departamentos, catálogo de
posiciones, plantillas de examen, bandas por categoría y layouts. Clonar en vez
de re-sembrar garantiza que la demo tenga exactamente las mismas features que
el club real — si mañana alguien agrega un campo a una plantilla, la demo lo
hereda sin que nadie tenga que acordarse de actualizar un segundo seed.

**Los datos se GENERAN** remuestreando la distribución real del club de origen,
de forma determinista (`core.demo_distribution`). Ni inventados ni copiados:
copiar sería filtrar los números de jugadores reales a una demo, e inventar con
`random()` produce planteles donde los percentiles no significan nada y el
radar sale dentado. Ver el docstring de ese módulo para el porqué de cada
propiedad.

La correspondencia entre categorías va por BRACKET de la temporada, no por
nombre: el Sub 15 de la demo toma la distribución de la categoría del club de
origen que compite en Sub 15 esa temporada. Un Sub 15 y un Sub 20 no comparten
escala en ninguna métrica física, así que tomar "la primera que haya" sería
regalarle a un chico de 14 los números de uno de 19.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.demo_distribution import (
    Distribucion, cuantil_de_jugador, cuantil_para, indice_estable,
)

# Nombres inventados. Listas fijas y combinación determinista: el jugador
# número 7 del Sub 14 se llama siempre igual, así una captura de pantalla de
# la demo sigue siendo válida la semana que viene.
NOMBRES = [
    "Matías", "Benjamín", "Vicente", "Agustín", "Joaquín", "Cristóbal",
    "Tomás", "Lucas", "Martín", "Diego", "Gabriel", "Ignacio", "Maximiliano",
    "Bastián", "Sebastián", "Nicolás", "Felipe", "Emilio", "Alonso", "Renato",
    "Damián", "Facundo", "Gaspar", "Amaro", "Bruno", "Dante", "Elías",
    "Franco", "Gonzalo", "Isidro", "Julián", "León",
]
APELLIDOS = [
    "Barraza", "Cifuentes", "Peñaloza", "Riquelme", "Zamorano", "Salgado",
    "Maturana", "Villablanca", "Ormeño", "Carrasco", "Bustamante", "Leiva",
    "Pizarro", "Aravena", "Cortés", "Sandoval", "Quiroz", "Verdugo",
    "Manríquez", "Iturra", "Cáceres", "Palacios", "Rebolledo", "Tapia",
    "Ulloa", "Vergara", "Yáñez", "Zúñiga", "Alarcón", "Bravo", "Cornejo",
    "Donoso",
]

# Cuántos jugadores por categoría. Un plantel de 24 es realista y alcanza para
# que un percentil intra-categoría signifique algo (el mínimo del sistema es 3,
# pero con 24 la escala se lee de verdad).
POR_CATEGORIA = 24

# Casos clínicos deliberados. Sin esto, todas las superficies de
# disponibilidad, la Daily y el panel de alertas salen verdes y la demo no
# muestra la mitad de la plataforma.
# Rivales inventados. Lista fija: el Sub 15 juega siempre contra los mismos,
# en el mismo orden, corrida tras corrida.
RIVALES = [
    "Deportes Quilicura", "Andes FC", "Cóndores de Renca", "Unión Maipo",
    "Atlético Peñalolén", "Santiago Norte", "Lo Prado United",
    "Racing de Cerrillos", "Estrella de La Pintana", "Cerro Blanco",
]

# Días entre partidos. Uno cada dos semanas es la cadencia real del formativo.
CADA_PARTIDO = 14

# (categoría, progresión de etapas, tipo, zona, gravedad). Las etapas son el
# VOCABULARIO DEL CLUB (`aguda` → `intermedia` → `reintegro`), que es lo que el
# `stage_status_map` de la plantilla sabe traducir a estado del jugador.
CASOS = [
    ("Sub 20", ["aguda"], "Lesion muscular (desgarro/rotura)", "Muslo posterior", "Moderada"),
    ("Sub 16", ["aguda"], "Esguince/Lesion ligamentosa", "Tobillo", "Leve"),
    ("Sub 18", ["aguda", "intermedia"], "Lesion muscular (desgarro/rotura)", "Aductores", "Moderada"),
    ("Primer Equipo", ["aguda", "intermedia"], "Lesion tendinosa/Tendinopatia", "Rodilla", "Moderada"),
    ("Sub 15", ["aguda", "intermedia", "reintegro"], "Lesion muscular (desgarro/rotura)", "Gemelo", "Leve"),
    ("Primer Equipo", ["aguda"], "Lesion meniscal/cartilago", "Rodilla", "Grave"),
]


class Command(BaseCommand):
    help = 'Crea el club demo "Los Barrabases" clonando la configuración del club de origen.'

    def add_arguments(self, parser):
        parser.add_argument("--club", default="Los Barrabases")
        parser.add_argument("--source", default="Universidad de Chile",
                            help="Club del que se clona la configuración y se "
                                 "toma la distribución de los datos.")
        parser.add_argument("--season", type=int, default=date.today().year)
        parser.add_argument("--months", type=int, default=6,
                            help="Meses de historia a generar.")
        parser.add_argument("--players", type=int, default=POR_CATEGORIA)
        parser.add_argument("--email", default="demo@barrabases.cl")
        parser.add_argument("--password", default="SLAB092026")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--reset", action="store_true",
                            help="Borra el club demo antes de regenerarlo. "
                                 "Sin esto una re-corrida DUPLICA los "
                                 "resultados: los jugadores y las reglas son "
                                 "get_or_create pero los ExamResult no.")

    def handle(self, *args, **opts):
        from core.models import Club

        origen = Club.objects.filter(name=opts["source"]).first()
        if origen is None:
            raise CommandError(f"No existe el club de origen '{opts['source']}'.")

        self.rep: dict[str, int] = {}
        self.avisos: list[str] = []

        with transaction.atomic():
            if opts["reset"]:
                self._reset(opts["club"])
            club = self._club(opts["club"])
            deptos = self._departamentos(club, origen)
            self._posiciones(club, origen)
            cats, equivalencias = self._categorias(club, origen, opts["season"])
            self._jugadores(club, cats, opts["season"], opts["players"])
            plantillas = self._plantillas(club, origen, deptos)
            self._bandas(cats, equivalencias, plantillas)
            con_datos = self._datos(cats, equivalencias, plantillas, opts["months"])
            self._aplicabilidad(plantillas, con_datos)
            self._partidos(club, cats, equivalencias, plantillas,
                           opts["months"], deptos)
            self._layouts(club, origen, cats, equivalencias, plantillas, deptos)
            self._reporte_partido(origen, cats, equivalencias, plantillas)
            self._casos(cats)
            self._alertas(cats)
            self._usuario(club, opts["email"], opts["password"])
            if not opts["commit"]:
                transaction.set_rollback(True)

        self._imprimir(opts)

    # ── 0 · reset ────────────────────────────────────────────────────────
    def _reset(self, nombre: str) -> None:
        """Borra el club demo entero, en orden de dependencias.

        `Club.delete()` sola falla: `Department.club` y `Category.club` son
        PROTECT. Y borrar a medias es peor que no borrar — una re-corrida sobre
        un estado sucio duplicó 60.696 resultados, porque jugadores y reglas
        usan `get_or_create` pero los `ExamResult` se crean siempre.
        """
        from core.models import Category, Club, Department, Position

        from core.models import Player
        from goals.models import AlertRule

        club = Club.objects.filter(name=nombre).first()
        if club is None:
            self.rep["reset"] = 0
            return
        # El orden es obligado: `Player.category` y `Category.club` son ambos
        # PROTECT, así que hay que ir de la hoja a la raíz. Los jugadores
        # arrastran sus resultados, episodios y alertas en cascada.
        from dashboards.models import DepartmentLayout, TeamReportLayout
        from events.models import Event
        from goals.models import Alert
        from exams.models import ExamTemplate

        from exams.models import Episode, ExamResult

        Alert.objects.filter(player__category__club=club).delete()
        Event.objects.filter(club=club).delete()
        # `Episode.player` y `ExamResult.episode` son PROTECT los dos, así que
        # los episodios hay que desarmarlos de adentro hacia afuera antes de
        # tocar a los jugadores.
        episodios = Episode.objects.filter(player__category__club=club)
        ExamResult.objects.filter(episode__in=episodios).delete()
        episodios.delete()
        borrados, _ = Player.objects.filter(category__club=club).delete()
        AlertRule.objects.filter(category__club=club).delete()
        # Los layouts apuntan a las plantillas; las plantillas al departamento.
        # Todo el camino es PROTECT, así que se baja nivel por nivel.
        DepartmentLayout.objects.filter(category__club=club).delete()
        TeamReportLayout.objects.filter(category__club=club).delete()
        ExamTemplate.objects.filter(department__club=club).delete()
        Category.objects.filter(club=club).delete()
        Department.objects.filter(club=club).delete()
        Position.objects.filter(club=club).delete()
        club.delete()
        self.rep["reset"] = borrados

    # ── 1 · club y departamentos ─────────────────────────────────────────
    def _club(self, nombre: str):
        from core.models import Club
        club, creado = Club.objects.get_or_create(name=nombre)
        self.rep["club"] = 1 if creado else 0
        return club

    def _departamentos(self, club, origen) -> dict[str, object]:
        from core.models import Department
        out = {}
        for d in Department.objects.filter(club=origen).order_by("name"):
            nuevo, _ = Department.objects.get_or_create(
                club=club, slug=d.slug, defaults={"name": d.name})
            out[d.slug] = nuevo
        self.rep["departamentos"] = len(out)
        return out

    # ── 2 · posiciones ───────────────────────────────────────────────────
    def _posiciones(self, club, origen) -> None:
        from core.models import Position
        n = 0
        for p in Position.objects.filter(club=origen):
            _, creado = Position.objects.get_or_create(
                club=club, abbreviation=p.abbreviation,
                defaults={"name": p.name, "role": p.role,
                          "sort_order": p.sort_order})
            n += bool(creado)
        self.rep["posiciones"] = Position.objects.filter(club=club).count()

    # ── 3 · categorías ───────────────────────────────────────────────────
    def _categorias(self, club, origen, season):
        """Primer Equipo + Sub 12…Sub 20, y con qué categoría del origen se
        corresponde cada una.

        La correspondencia es por BRACKET de la temporada. Si el origen no
        tiene una categoría compitiendo en ese bracket, la demo igual crea la
        suya pero se queda sin distribución — y eso se reporta en vez de
        rellenarse con la de otra edad.
        """
        from core.models import Bracket, Category, Department, TeamSeason

        # bracket → categoría del origen que compite ahí esta temporada.
        por_bracket: dict[str, object] = {}
        for c in Category.objects.filter(club=origen).prefetch_related(
                "team_seasons__bracket"):
            if c.is_senior:
                por_bracket.setdefault("Primera", c)
                continue
            ts = next((t for t in c.team_seasons.all()
                       if t.season == season and t.bracket_id), None)
            if ts:
                por_bracket.setdefault(ts.bracket.name, c)
            elif c.cohort_year:
                b = Bracket.for_age(season - c.cohort_year, Bracket.ladder())
                if b and not b.is_senior:
                    por_bracket.setdefault(b.name, c)

        deptos = list(Department.objects.filter(club=club))
        cats: dict[str, object] = {}
        equivalencias: dict[str, object] = {}

        # Primer Equipo.
        pe, _ = Category.objects.get_or_create(
            club=club, name="Primer Equipo", defaults={"is_senior": True})
        pe.departments.set(deptos)
        cats["Primer Equipo"] = pe
        if (src := por_bracket.get("Primera")):
            equivalencias["Primer Equipo"] = src

        # Formativo: la escalera ANFP no tiene Sub 17 ni Sub 19, así que se
        # camina `Bracket.order` en vez de restar años.
        for b in Bracket.ladder():
            if b.is_senior or b.age is None or not (12 <= b.age <= 20):
                continue
            cohorte = season - b.age
            cat, _ = Category.objects.get_or_create(
                club=club, name=b.name,
                defaults={"cohort_year": cohorte, "is_senior": False})
            if cat.cohort_year != cohorte:
                cat.cohort_year = cohorte
                cat.save(update_fields=["cohort_year"])
            cat.departments.set(deptos)
            TeamSeason.objects.get_or_create(
                team=cat, season=season, defaults={"bracket": b, "derived": False})
            cats[b.name] = cat
            if (src := por_bracket.get(b.name)):
                equivalencias[b.name] = src
            else:
                self.avisos.append(
                    f"{b.name}: el origen no tiene categoría en ese bracket — "
                    f"queda creada pero sin datos.")

        self.rep["categorias"] = len(cats)
        return cats, equivalencias

    # ── 4 · jugadores ────────────────────────────────────────────────────
    def _jugadores(self, club, cats, season, cuantos) -> None:
        from core.models import Player, Position

        posiciones = list(Position.objects.filter(club=club).order_by("sort_order"))
        if not posiciones:
            raise CommandError("El club quedó sin posiciones; revisá el origen.")
        # Una plantilla de puestos realista: un arquero cada ~11, el resto
        # repartido por línea. Determinista, no sorteada.
        creados = 0
        for nombre_cat, cat in cats.items():
            for i in range(cuantos):
                clave = f"{nombre_cat}|{i}"
                nombre = NOMBRES[indice_estable(clave + "|n", len(NOMBRES))]
                ap1 = APELLIDOS[indice_estable(clave + "|a", len(APELLIDOS))]
                ap2 = APELLIDOS[indice_estable(clave + "|b", len(APELLIDOS))]
                pos = posiciones[indice_estable(clave + "|p", len(posiciones))]
                # Fecha de nacimiento dentro del año de la cohorte, repartida
                # por el calendario para que las edades no sean todas iguales.
                anio = cat.cohort_year or (season - 24)
                dia = 1 + (indice_estable(clave + "|d", 360))
                nacimiento = date(anio, 1, 1) + timedelta(days=dia - 1)
                _, creado = Player.objects.get_or_create(
                    category=cat, first_name=nombre, last_name=ap1,
                    second_last_name=ap2,
                    defaults={"position": pos, "date_of_birth": nacimiento,
                              "is_active": True, "nationality": "Chile",
                              "sex": "M"},
                )
                creados += bool(creado)
        self.rep["jugadores"] = Player.objects.filter(
            category__club=club).count()

    # ── 5 · plantillas ───────────────────────────────────────────────────
    def _plantillas(self, club, origen, deptos) -> dict:
        """Clona cada plantilla activa del origen. Devuelve origen → nueva."""
        from exams.models import ExamTemplate

        out = {}
        fuentes = (ExamTemplate.objects
                   .filter(department__club=origen, is_active_version=True)
                   .select_related("department").order_by("slug"))
        for t in fuentes:
            depto = deptos.get(t.department.slug)
            if depto is None:
                continue
            nueva = ExamTemplate.objects.filter(
                department=depto, slug=t.slug).first()
            if nueva is None:
                nueva = ExamTemplate.objects.create(
                    department=depto, slug=t.slug, name=t.name,
                    config_schema=t.config_schema, input_config=t.input_config,
                    episode_config=t.episode_config, is_episodic=t.is_episodic,
                    show_injuries=t.show_injuries, link_to_match=t.link_to_match,
                    version=1, is_locked=False, is_active_version=True,
                )
                # Familia propia: la demo no comparte historial de versiones
                # con el club real, y colgarla de su `family_id` haría que una
                # consulta por familia mezclara los dos clubes.
                nueva.family_id = nueva.id
                nueva.save(update_fields=["family_id"])
            out[t.id] = nueva
        self.rep["plantillas"] = len(out)
        return out

    # ── 6 · bandas por categoría ─────────────────────────────────────────
    def _bandas(self, cats, equivalencias, plantillas) -> None:
        """Clona las reglas BAND de la categoría equivalente.

        Las bandas son por categoría a propósito —41,89 cm de CMJ no
        significan lo mismo en Sub 20 que en Sub 13— así que se copian desde la
        categoría del origen que corresponde a la misma edad, no desde una
        sola tabla compartida.
        """
        from goals.models import AlertRule, AlertRuleKind

        n = 0
        for nombre, cat in cats.items():
            src = equivalencias.get(nombre)
            if src is None:
                continue
            for r in AlertRule.objects.filter(
                    category=src, kind=AlertRuleKind.BAND, is_active=True):
                nueva = plantillas.get(r.template_id)
                if nueva is None:
                    continue
                _, creada = AlertRule.objects.get_or_create(
                    category=cat, template=nueva, field_key=r.field_key,
                    kind=AlertRuleKind.BAND,
                    defaults={"severity": r.severity, "config": r.config,
                              "is_active": True},
                )
                n += bool(creada)
        self.rep["reglas_banda"] = n

    # ── 7 · datos ────────────────────────────────────────────────────────
    def _datos(self, cats, equivalencias, plantillas, meses) -> None:
        """El corazón: remuestrea la distribución real, sin azar.

        Se muestrean sólo los campos de ENTRADA; los calculados los deriva el
        motor de fórmulas. Muestrear un calculado por separado lo dejaría
        peleado con sus propias entradas —un "mejor de tres intentos" que no es
        ninguno de los tres— y eso se detecta a simple vista en la ficha.
        """
        from core.models import Player
        from exams.calculations import compute_result_data
        from exams.models import ExamResult

        # Ancladas a medianoche: dos corridas del mismo día dan exactamente
        # las mismas marcas de tiempo. Que la ventana avance con el calendario
        # es deliberado — una demo cuyos datos terminan hace seis meses se ve
        # abandonada.
        ahora = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        desde = ahora - timedelta(days=30 * meses)
        creados = 0
        sin_muestra = 0
        con_datos: dict[object, set] = {}

        for nombre, cat in cats.items():
            src = equivalencias.get(nombre)
            if src is None:
                continue
            jugadores = list(Player.objects.filter(category=cat)
                             .order_by("last_name", "first_name"))
            for src_tpl_id, tpl in plantillas.items():
                # Las plantillas de partido las llena la fase de partidos: su
                # dato existe sólo los días que se jugó y sólo para quien jugó.
                # Generarlas con una cadencia fija las dejaría sin evento y las
                # superficies de día de partido no las verían.
                if tpl.link_to_match:
                    continue
                campos = _campos_de_entrada(tpl)
                if not campos:
                    continue
                dist = _distribuciones(src_tpl_id, src, list(campos))
                if not dist:
                    sin_muestra += 1
                    continue
                cadencia = _cadencia(tpl.slug)
                fechas = _fechas(desde, ahora, cadencia)
                if tpl.slug == ANTRO_SLUG:
                    # Crecimiento needs measurements ≥ 6 months apart, and a
                    # year to trust a velocity: two years, quarterly.
                    fechas = _fechas(ahora - timedelta(days=730), ahora, 91)
                if not fechas:
                    continue
                nuevos = []
                for idx, jugador in enumerate(jugadores):
                    base = cuantil_de_jugador(idx, len(jugadores))
                    # ⚠️ La semilla NO puede ser el UUID del jugador: se genera
                    # nuevo en cada `--reset`, así que los valores cambiaban en
                    # cada corrida y el determinismo que este módulo promete era
                    # falso. La identidad estable del jugador en la demo es su
                    # categoría más su lugar en el plantel ordenado.
                    pid = f"{nombre}|{idx}"
                    for paso, cuando in enumerate(fechas):
                        crudo = {}
                        for clave, d in dist.items():
                            q = cuantil_para(base, pid, clave, paso=paso,
                                             pasos=len(fechas))
                            # Menos es mejor → el jugador hábil va al cuantil
                            # BAJO de la muestra real.
                            if campos.get(clave) == "down":
                                q = 1.0 - q
                            v = d.muestrear(q)
                            if v is not None:
                                crudo[clave] = v
                        if not crudo:
                            continue
                        if tpl.slug == ANTRO_SLUG and "talla" in dist:
                            crudo |= _antropometria(jugador, pid, cuando, ahora, dist["talla"])
                        datos, snapshot = compute_result_data(
                            tpl, crudo, player=jugador)
                        nuevos.append(ExamResult(
                            player=jugador, template=tpl, recorded_at=cuando,
                            result_data=datos, inputs_snapshot=snapshot))
                if nuevos:
                    con_datos.setdefault(tpl.id, set()).add(cat.id)
                    # `bulk_create` no dispara señales: nada de cascada de
                    # alertas ni recomputo por fila mientras se siembra.
                    ExamResult.objects.bulk_create(nuevos, batch_size=500)
                    creados += len(nuevos)
        self.rep["resultados"] = creados
        return con_datos
        if sin_muestra:
            self.avisos.append(
                f"{sin_muestra} (plantilla × categoría) sin muestra en el "
                f"origen — esas quedaron vacías en vez de inventarse.")

    # ── 7b · aplicabilidad ───────────────────────────────────────────────
    def _aplicabilidad(self, plantillas, con_datos) -> None:
        """Cada plantilla queda aplicable SÓLO donde hay datos.

        Hacerlas aplicables a todo llenaba el menú de cada categoría con
        exámenes que a esa edad no se toman: un Sub 12 con la sección de
        análisis de sangre del plantel profesional, vacía. En una demo una
        sección vacía es peor que una sección ausente — parece que algo se
        rompió.
        """
        from core.models import Category

        n = 0
        for tpl in plantillas.values():
            ids = con_datos.get(tpl.id) or set()
            tpl.applicable_categories.set(Category.objects.filter(id__in=ids))
            n += bool(ids)
        self.rep["plantillas_con_datos"] = n

    # ── 7c · partidos ────────────────────────────────────────────────────
    def _partidos(self, club, cats, equivalencias, plantillas, meses, deptos) -> None:
        """Calendario con partidos jugados y por jugar.

        Los pasados llevan convocatoria y datos —GPS de partido y rendimiento—
        VINCULADOS al evento. Ese vínculo es el punto: un resultado de partido
        sin `event` no lo ve ninguna superficie de día de partido, y la ficha
        queda huérfana aunque el número exista.

        Los futuros van vacíos a propósito. Un partido que todavía no se jugó
        con minutos y distancia cargados sería una demo que miente sobre lo que
        el sistema sabe.
        """
        from core.models import Player
        from events.models import Event, EventParticipant
        from exams.calculations import compute_result_data
        from exams.models import ExamResult

        ahora = timezone.now().replace(hour=16, minute=0, second=0, microsecond=0)
        primero = ahora - timedelta(days=30 * meses)
        # Ocho semanas hacia adelante: suficiente para que el calendario tenga
        # próximos partidos sin inventar una temporada entera.
        ultimo = ahora + timedelta(days=56)

        # `Event.department` es obligatorio. En el club real 671 de 674
        # partidos cuelgan de Táctico; se sigue esa convención.
        depto_partidos = deptos.get("tactico") or next(iter(deptos.values()))
        por_partido = [t for t in plantillas.values() if t.link_to_match]
        jugados = futuros = participaciones = resultados = 0

        # Who plays where. A player's identity for the data generator stays
        # his HOME category and place in it, wherever he plays.
        plantel = {n: list(Player.objects.filter(category=c).order_by("last_name", "first_name"))
                   for n, c in cats.items()}
        identidad = {p.id: (n, idx, len(lst))
                     for n, lst in plantel.items() for idx, p in enumerate(lst)}
        self.promovidos = _promociones(list(cats), plantel)
        arriba = {p.id for lista in self.promovidos.values() for p in lista}
        from core.models import Bracket

        # `is_senior` is a property (`age is None`), not a column.
        primera = next((b for b in Bracket.ladder() if b.is_senior), None)

        for nombre, cat in cats.items():
            src = equivalencias.get(nombre)
            # The ones playing up all season are not in their own team's
            # sheets; the ones coming from below are.
            jugadores = ([p for p in plantel[nombre] if p.id not in arriba]
                         + self.promovidos.get(nombre, []))
            if not jugadores:
                continue
            dists = {}
            if src is not None:
                for tpl in por_partido:
                    src_id = next((k for k, v in plantillas.items() if v == tpl), None)
                    campos = _campos_de_entrada(tpl)
                    if src_id and campos:
                        d = _distribuciones(src_id, src, list(campos))
                        if d:
                            dists[tpl.id] = (tpl, campos, d)

            ts = cat.team_seasons.select_related("bracket").order_by("-season").first()
            # Primer Equipo has no TeamSeason; its matches are Primera's —
            # without a bracket Desarrollo cannot see a youth playing there.
            bracket = ts.bracket if ts else (primera if cat.is_senior else None)
            cuando = primero
            i = 0
            while cuando <= ultimo:
                rival = RIVALES[indice_estable(f"{nombre}|{i}", len(RIVALES))]
                de_local = indice_estable(f"{nombre}|{i}|sede", 2) == 0
                titulo = (f"Los Barrabases vs {rival}" if de_local
                          else f"{rival} vs Los Barrabases")
                pasado = cuando < ahora
                # Marcador determinista, sólo para los ya jugados.
                gf = indice_estable(f"{nombre}|{i}|gf", 4)
                gc = indice_estable(f"{nombre}|{i}|gc", 4)
                meta = {
                    "opponent": rival,
                    "is_home": de_local,
                    "competition_label": f"Campeonato {nombre} · {cuando.year}",
                }
                if pasado:
                    meta |= {
                        "score": {"local": gf if de_local else gc,
                                  "visita": gc if de_local else gf},
                        "is_won": gf > gc,
                    }
                evento, creado = Event.objects.get_or_create(
                    club=club, category=cat, event_type="match",
                    starts_at=cuando,
                    defaults={"title": titulo, "scope": "category",
                              "department": depto_partidos,
                              # The team's bracket: GPS partido reads a
                              # category's matches through it (team_scope).
                              "bracket": bracket,
                              "ends_at": cuando + timedelta(minutes=110),
                              "metadata": meta},
                )
                if not creado:
                    cuando += timedelta(days=CADA_PARTIDO)
                    i += 1
                    continue

                if not pasado:
                    futuros += 1
                    cuando += timedelta(days=CADA_PARTIDO)
                    i += 1
                    continue
                jugados += 1

                # Convocatoria: 11 titulares, 7 suplentes, el resto no citado.
                # Determinista, y rota con el número de partido para que no sea
                # siempre el mismo once.
                orden = sorted(
                    jugadores,
                    key=lambda j: indice_estable(f"{nombre}|{i}|{j.last_name}{j.first_name}", 1000))
                nuevos_part, nuevos_res = [], []
                for pos, j in enumerate(orden):
                    if pos < 11:
                        rol, minutos, asistencia = "titular", 60 + (pos % 4) * 10, "attended"
                    elif pos < 18:
                        rol, minutos, asistencia = "suplente_ingresa", 10 + (pos % 3) * 10, "attended"
                    else:
                        rol, minutos, asistencia = "no_citado", 0, "scheduled"
                    goles = 1 if (pos < 11 and indice_estable(f"{nombre}|{i}|{pos}|gol", 12) == 0) else 0
                    amarillas = 1 if indice_estable(f"{nombre}|{i}|{pos}|ama", 14) == 0 else 0
                    nuevos_part.append(EventParticipant(
                        event=evento, player=j, match_role=rol,
                        attendance=asistencia, minutes_played=minutos,
                        position_played=j.position,
                        goals=goles, yellow_cards=amarillas, red_cards=0,
                    ))
                    if minutos == 0:
                        continue
                    # Sólo quien jugó tiene datos de partido.
                    casa, idx_casa, n_casa = identidad[j.id]
                    base = cuantil_de_jugador(idx_casa, n_casa)
                    pid = f"{casa}|{idx_casa}"
                    for tpl, campos, dist in dists.values():
                        crudo = {}
                        for clave, d in dist.items():
                            q = cuantil_para(base, pid, clave, paso=i, pasos=30)
                            if campos.get(clave) == "down":
                                q = 1.0 - q
                            v = d.muestrear(q)
                            if v is not None:
                                crudo[clave] = v
                        if not crudo:
                            continue
                        if tpl.slug == "rendimiento_de_partido":
                            # The match sheet already says who started, for how
                            # long, who scored and who was booked: drawing them
                            # again gave a player 0 minutes next to 9 km of GPS.
                            crudo |= {"minutes_played": float(minutos),
                                      "started_eleven": pos < 11,
                                      "goals": float(goles),
                                      "yellow_cards": float(amarillas),
                                      "red_card": False}
                        if tpl.slug == "gps_partido":
                            crudo = _a_sus_minutos(crudo, minutos)
                            crudo |= _datos_de_partido(rival, de_local, gf, gc, cuando)
                        datos, snap = compute_result_data(tpl, crudo, player=j)
                        nuevos_res.append(ExamResult(
                            player=j, template=tpl, recorded_at=cuando,
                            result_data=datos, inputs_snapshot=snap,
                            event=evento))
                EventParticipant.objects.bulk_create(nuevos_part, batch_size=500)
                ExamResult.objects.bulk_create(nuevos_res, batch_size=500)
                participaciones += len(nuevos_part)
                resultados += len(nuevos_res)
                cuando += timedelta(days=CADA_PARTIDO)
                i += 1

        self._microciclo(cats)
        self._convocados(cats, primero)
        self.rep["partidos_jugados"] = jugados
        self.rep["partidos_futuros"] = futuros
        self.rep["convocatorias"] = participaciones
        self.rep["resultados_de_partido"] = resultados

    # ── 7e · convocados ──────────────────────────────────────────────────
    def _convocados(self, cats, desde) -> None:
        """Los que juegan arriba quedan convocados a esa categoría, como en el
        club real (`PlayerCallUp`): aparecen en su plantel con el badge, y
        Desarrollo los cuenta como jugando sobre su edad."""
        from core.models import PlayerCallUp

        n = 0
        for destino, jugadores in self.promovidos.items():
            cat = cats[destino]
            for j in jugadores:
                PlayerCallUp.objects.get_or_create(
                    player=j, category=cat,
                    defaults={"status": (PlayerCallUp.STATUS_PROMOTION if cat.is_senior
                                         else PlayerCallUp.STATUS_CALL_UP),
                              "active": True, "since": desde.date(),
                              "note": f"Juega la temporada en {destino}"})
                n += 1
        self.rep["convocados_arriba"] = n

    # ── 7d · día de microciclo de las sesiones ───────────────────────────
    def _microciclo(self, cats) -> None:
        """MD-n / MD+n de cada sesión de GPS, del calendario de la demo.

        En el club real el día lo escribe el club (su CÓDIGO); acá el
        calendario lo inventa la propia demo, así que derivarlo de él es
        exacto. Sin esto los gráficos y filtros por día de microciclo de la
        demo salen vacíos.
        """
        from exams.microcycle import apply_md_labels
        from exams.models import ExamResult

        sesiones = list(ExamResult.objects
                        .filter(player__category__in=cats.values(), template__slug="gps_sesion")
                        .select_related("player"))
        for r in sesiones:
            r.result_data.setdefault("tipo_sesion", "entrenamiento")
        apply_md_labels(sesiones)
        for r in sesiones:
            md = r.result_data.get("md_label")
            r.result_data["sesion"] = (f"Sesión {timezone.localtime(r.recorded_at):%Y-%m-%d}"
                                       + (f" · {md}" if md else ""))
        ExamResult.objects.bulk_update(sesiones, ["result_data"], batch_size=500)
        self.rep["sesiones_con_md"] = sum(1 for r in sesiones if r.result_data.get("md_label"))

    # ── 8 · layouts ──────────────────────────────────────────────────────
    def _layouts(self, club, origen, cats, equivalencias, plantillas, deptos) -> None:
        """Clona los layouts de jugador y de equipo de la categoría equivalente."""
        from dashboards.models import (
            DepartmentLayout, LayoutSection, TeamReportLayout,
            TeamReportSection, TeamReportWidget, TeamReportWidgetDataSource,
            Widget, WidgetDataSource,
        )

        jugador = equipo = 0
        for nombre, cat in cats.items():
            src = equivalencias.get(nombre)
            if src is None:
                continue

            for lay in DepartmentLayout.objects.filter(category=src):
                depto = deptos.get(lay.department.slug)
                if depto is None or DepartmentLayout.objects.filter(
                        department=depto, category=cat).exists():
                    continue
                nuevo = DepartmentLayout.objects.create(
                    department=depto, category=cat)
                for sec in lay.sections.all():
                    ns = LayoutSection.objects.create(
                        layout=nuevo, title=sec.title,
                        is_collapsible=sec.is_collapsible,
                        default_collapsed=sec.default_collapsed,
                        sort_order=sec.sort_order)
                    for w in sec.widgets.all():
                        nw = Widget.objects.create(
                            section=ns, chart_type=w.chart_type, title=w.title,
                            description=w.description, column_span=w.column_span,
                            sort_order=w.sort_order,
                            display_config=w.display_config,
                            chart_height=w.chart_height)
                        for ds in w.data_sources.all():
                            tpl = plantillas.get(ds.template_id)
                            if tpl is None:
                                continue
                            WidgetDataSource.objects.create(
                                widget=nw, template=tpl,
                                field_keys=ds.field_keys,
                                aggregation=ds.aggregation,
                                aggregation_param=ds.aggregation_param,
                                label=ds.label, color=ds.color,
                                sort_order=ds.sort_order,
                                date_shift_days=ds.date_shift_days)
                jugador += 1

            # EVERY team layout of the department, not the first: a department
            # can have several (Físico → General / Evaluaciones / GPS partido,
            # Médico → General / Lesiones), and cloning one per department
            # dropped the rest. Keyed by slug, so a re-run adds what is new.
            for lay in (TeamReportLayout.objects.filter(category=src, scope="period")
                        .order_by("department__name", "sort_order")):
                depto = deptos.get(lay.department.slug) if lay.department else None
                if depto is None or TeamReportLayout.objects.filter(
                        department=depto, category=cat, scope="period",
                        slug=lay.slug).exists():
                    continue
                nuevo = TeamReportLayout.objects.create(
                    department=depto, category=cat, name=lay.name, slug=lay.slug,
                    sort_order=lay.sort_order, default_period_days=lay.default_period_days,
                    is_active=lay.is_active, scope=lay.scope,
                    match_selector_config=lay.match_selector_config)
                for sec in lay.sections.all():
                    ns = TeamReportSection.objects.create(
                        layout=nuevo, title=sec.title, sort_order=sec.sort_order,
                        is_collapsible=sec.is_collapsible,
                        default_collapsed=sec.default_collapsed)
                    for w in sec.widgets.all():
                        nw = TeamReportWidget.objects.create(
                            section=ns, chart_type=w.chart_type, title=w.title,
                            description=w.description, column_span=w.column_span,
                            sort_order=w.sort_order,
                            display_config=w.display_config,
                            chart_height=w.chart_height)
                        for ds in w.data_sources.all():
                            tpl = plantillas.get(ds.template_id)
                            if tpl is None:
                                continue
                            TeamReportWidgetDataSource.objects.create(
                                widget=nw, template=tpl,
                                field_keys=ds.field_keys,
                                aggregation=ds.aggregation,
                                aggregation_param=ds.aggregation_param,
                                label=ds.label, color=ds.color,
                                sort_order=ds.sort_order)
                equipo += 1

        self.rep["layouts_jugador"] = jugador
        self.rep["layouts_equipo"] = equipo

    # ── 8b · reporte de partido ──────────────────────────────────────────
    def _reporte_partido(self, origen, cats, equivalencias, plantillas) -> None:
        """El reporte combinado que se abre desde Partidos, en CADA categoría.

        Es un layout aparte (`scope="match"`, sin departamento) y `_layouts`
        clona sólo los de período: sin esto cada partido de la demo decía
        "Sin reporte para este partido" aunque tuviera GPS y rendimiento
        vinculados. El club de origen tiene reporte de partido sólo en Primer
        Equipo, así que una categoría sin el suyo toma ese — quedándose sólo
        con los widgets cuyos datos esa categoría tiene: un widget vacío en una
        demo parece una falla, no una ausencia.
        """
        from dashboards.models import (
            TeamReportLayout, TeamReportSection, TeamReportWidget,
            TeamReportWidgetDataSource,
        )
        from exams.models import ExamResult

        respaldo = (TeamReportLayout.objects.filter(category__club=origen, scope="match")
                    .order_by("-category__is_senior").first())
        n = widgets = 0
        for nombre, cat in cats.items():
            if TeamReportLayout.objects.filter(category=cat, scope="match").exists():
                continue
            src = equivalencias.get(nombre)
            lay = (TeamReportLayout.objects.filter(category=src, scope="match").first()
                   if src else None) or respaldo
            if lay is None:
                continue
            con_datos = set(ExamResult.objects.filter(player__category=cat)
                            .values_list("template_id", flat=True).distinct())
            nuevo = TeamReportLayout.objects.create(
                department=None, category=cat, name=lay.name, slug=lay.slug,
                is_active=lay.is_active, scope="match",
                match_selector_config=lay.match_selector_config)
            for sec in lay.sections.all():
                fuentes_ok = []
                for w in sec.widgets.all():
                    ds = [(d, plantillas.get(d.template_id)) for d in w.data_sources.all()]
                    if ds and all(t is not None and t.id in con_datos for _, t in ds):
                        fuentes_ok.append((w, ds))
                if not fuentes_ok:
                    continue
                ns = TeamReportSection.objects.create(
                    layout=nuevo, title=sec.title, sort_order=sec.sort_order,
                    is_collapsible=sec.is_collapsible,
                    default_collapsed=sec.default_collapsed)
                for w, ds in fuentes_ok:
                    nw = TeamReportWidget.objects.create(
                        section=ns, chart_type=w.chart_type, title=w.title,
                        description=w.description, column_span=w.column_span,
                        sort_order=w.sort_order, display_config=w.display_config,
                        chart_height=w.chart_height)
                    for d, t in ds:
                        TeamReportWidgetDataSource.objects.create(
                            widget=nw, template=t, field_keys=d.field_keys,
                            aggregation=d.aggregation,
                            aggregation_param=d.aggregation_param,
                            label=d.label, color=d.color, sort_order=d.sort_order)
                    widgets += 1
            n += 1
        self.rep["reportes_partido"] = n
        self.rep["reportes_partido_widgets"] = widgets

    # ── 9 · casos clínicos ───────────────────────────────────────────────
    def _casos(self, cats) -> None:
        """Lesiones de verdad: un Episode con su progresión de partes.

        NO se toca `Player.status` a mano. La señal de `episode_lifecycle`
        lo deriva de la etapa del episodio a través del `stage_status_map` de
        la plantilla — escribirlo a mano fue mi primer intento y quedó con
        valores en español (`lesionado`) que el modelo no define: seis
        jugadores con un estado que ningún filtro matchea, y las superficies
        de disponibilidad sin verlos.

        Además, sin Episode la ficha de lesión, la bitácora y el bloque de
        lesionados de la Daily quedan vacíos aunque el jugador figure fuera.
        """
        from core.models import Player
        from exams.calculations import compute_result_data
        from exams.models import Episode, ExamResult, ExamTemplate

        ahora = timezone.now()
        n = 0
        for i, (nombre_cat, etapas, tipo, zona, gravedad) in enumerate(CASOS):
            cat = cats.get(nombre_cat)
            if cat is None:
                continue
            les = ExamTemplate.objects.filter(
                slug="lesiones", department__club=cat.club).first()
            if les is None:
                self.avisos.append("Sin plantilla de lesiones: no hay casos.")
                return
            jugadores = list(Player.objects.filter(category=cat)
                             .order_by("last_name", "first_name"))
            if not jugadores:
                continue
            j = jugadores[indice_estable(f"caso|{i}|{nombre_cat}", len(jugadores))]

            inicio = ahora - timedelta(days=9 * len(etapas) + 4)
            episodio = Episode.objects.create(
                player=j, template=les, status=Episode.STATUS_OPEN,
                stage=etapas[0], started_at=inicio)
            for k, etapa in enumerate(etapas):
                crudo = {
                    "diagnosed_at": inicio.date().isoformat(),
                    "type": tipo, "body_part": zona, "lado": "Derecho",
                    "severity": gravedad, "stage": etapa,
                    "expected_return_date": (inicio + timedelta(days=35)).date().isoformat(),
                    "exposicion": "Entrenamiento",
                }
                datos, snap = compute_result_data(les, crudo, player=j)
                # `create` y no `bulk_create` A PROPÓSITO: esto SÍ tiene que
                # disparar la señal que sincroniza episodio y estado.
                ExamResult.objects.create(
                    player=j, template=les, episode=episodio,
                    recorded_at=inicio + timedelta(days=k * 9),
                    result_data=datos, inputs_snapshot=snap)
            n += 1
        self.rep["casos_clinicos"] = n

    # ── 9b · alertas ─────────────────────────────────────────────────────
    def _alertas(self, cats) -> None:
        """Evalúa las reglas sobre la última lectura de cada jugador.

        `bulk_create` no dispara señales —a propósito, o sembrar 46.000 filas
        encadenaría una evaluación por cada una— así que sin este paso el club
        demo queda con 65 reglas de banda configuradas y CERO alertas: la
        campana vacía, el panel vacío y el widget de alertas del equipo vacío.
        Es el mismo recomputo explícito que ya hace el ingest de GPS.

        Sólo la ÚLTIMA lectura por (jugador, plantilla): una alerta es sobre el
        estado actual, y evaluar la historia entera generaría miles de avisos
        sobre lecturas que ya quedaron atrás.
        """
        from core.models import Player
        from exams.models import ExamResult
        from goals.evaluator import evaluate_threshold_rules_for_result

        n = 0
        for cat in cats.values():
            ultimos = (ExamResult.objects
                       .filter(player__category=cat)
                       .order_by("player_id", "template_id", "-recorded_at")
                       .distinct("player_id", "template_id"))
            for r in ultimos.select_related("template", "player"):
                try:
                    n += len(evaluate_threshold_rules_for_result(r) or [])
                except Exception:  # noqa: BLE001 — una regla rota no corta el seed
                    self.avisos.append(
                        f"Falló la evaluación de {r.template.slug} para "
                        f"{r.player.last_name}.")
        self.rep["alertas"] = n

    # ── 10 · usuario de demo ─────────────────────────────────────────────
    def _usuario(self, club, email: str, password: str) -> None:
        """Login con alcance a este club.

        Con `StaffMembership` pero sin grupo de rol el usuario tiene CERO
        permisos: entra y no ve nada, porque el frontend esconde las acciones y
        los endpoints exigen `exams.add_examresult`. Por eso se le da Editor —
        la membresía lo mantiene acotado a este club igual.
        """
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from core.models import StaffMembership

        User = get_user_model()
        # El username sale del correo ENTERO, no del local part: ya existe un
        # usuario `demo` (el del workspace de La Roja) y colisionaba.
        local, _, dominio = email.partition("@")
        username = f"{local}_{dominio.split('.')[0]}".replace(".", "_")
        usuario = (User.objects.filter(email=email).first()
                   or User.objects.filter(username=username).first()
                   or User(username=username))
        usuario.email = email
        usuario.first_name = "Demo"
        usuario.last_name = "Barrabases"
        usuario.is_active = True
        # Explícito, no por omisión: un usuario de demo con `is_superuser`
        # saltea TODO el scoping —ve los otros clubes y pasa por el bypass de
        # `_has_perm`— y la demo dejaría de mostrar los permisos funcionando.
        # Apareció en True una vez sin que el código lo pusiera; fijarlo acá
        # cierra la puerta sea cual sea la causa.
        usuario.is_superuser = False
        usuario.is_staff = False
        usuario.set_password(password)
        usuario.save()

        m, _ = StaffMembership.objects.get_or_create(
            user=usuario, defaults={"club": club})
        m.club = club
        m.all_categories = True
        m.all_departments = True
        m.save()

        editor = Group.objects.filter(name="Editor").first()
        if editor is not None:
            usuario.groups.add(editor)
            self.rep["usuario_demo"] = 1
        else:
            self.avisos.append(
                "No existe el grupo Editor: el usuario demo entra sin "
                "permisos. Corré `seed_role_groups`.")

        # Desarrollo y Crecimiento: un permiso aparte que Editor no trae. Va al
        # USUARIO, no al grupo — darlo a Editor se lo daría a los Editores de
        # los clubes reales.
        from django.contrib.auth.models import Permission

        perm = Permission.objects.filter(content_type__app_label="core",
                                         codename="view_development").first()
        if perm is not None:
            usuario.user_permissions.add(perm)
            self.rep["permiso_desarrollo"] = 1
        else:
            self.avisos.append("No existe core.view_development: sin Desarrollo ni Crecimiento.")

    # ── reporte ──────────────────────────────────────────────────────────
    def _imprimir(self, opts) -> None:
        cab = "APLICADO" if opts["commit"] else "SIMULACIÓN (sin --commit no escribe)"
        self.stdout.write(f"\n{cab} · club '{opts['club']}'\n")
        for k, v in self.rep.items():
            self.stdout.write(f"  {k:<18} {v}")
        for a in self.avisos:
            self.stdout.write(self.style.WARNING(f"  ⚠️ {a}"))


# ── helpers ──────────────────────────────────────────────────────────────

_NUMERICOS = {"number"}


def _campos_de_entrada(template) -> dict[str, str]:
    """Campos numéricos que se CARGAN (no los calculados) → su dirección.

    La dirección es indispensable y no un adorno: el cuantil 0,9 de la muestra
    real es un salto ALTO en CMJ (bueno) pero un tiempo LENTO en T10 (malo).
    Sin invertirla, el jugador de mayor habilidad sale corriendo lento y
    saltando alto a la vez — medido, daba correlación −0,56 entre sprint y
    salto, y el radar y el comparador contaban un disparate coherente consigo
    mismo.
    """
    campos = [f for f in (template.config_schema or {}).get("fields", [])
              if isinstance(f, dict) and f.get("key")]

    # ⚠️ Los campos de ENTRADA casi nunca declaran dirección: `t10_1` es
    # `neutral` y sólo el calculado `t10_best` dice `down`. Muestreando sólo
    # entradas, un lookup directo no encuentra nada y la inversión no ocurre
    # — medido, dejaba correlación −0,59 entre sprint y salto.
    #
    # Se hereda del hermano calculado por prefijo: `t10_1` toma la de
    # `t10_best`. Es una heurística sobre la convención de nombres del club,
    # no una regla del modelo; un campo que no la siga queda `neutral`, que es
    # el comportamiento anterior y no empeora nada.
    por_prefijo: dict[str, str] = {}
    for f in campos:
        d = f.get("direction_of_good")
        if d and d != "neutral":
            por_prefijo.setdefault(f["key"].rsplit("_", 1)[0], d)

    out = {}
    for f in campos:
        if f.get("type") not in _NUMERICOS:
            continue
        propia = f.get("direction_of_good")
        if propia and propia != "neutral":
            out[f["key"]] = propia
        else:
            out[f["key"]] = por_prefijo.get(f["key"].rsplit("_", 1)[0], "neutral")
    return out


def _distribuciones(src_template_id, src_category, campos) -> dict[str, Distribucion]:
    """La muestra real del origen para (categoría, plantilla), por campo."""
    from exams.models import ExamResult

    filas = (ExamResult.objects
             .filter(template_id=src_template_id, player__category=src_category)
             .values_list("result_data", flat=True))
    acumulado: dict[str, list[float]] = {c: [] for c in campos}
    for datos in filas:
        for c in campos:
            v = (datos or {}).get(c)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                acumulado[c].append(float(v))
    return {c: Distribucion(vs) for c, vs in acumulado.items() if len(vs) >= 5}


PARTIDO_COMPLETO = 96   # minutes, added time included

# Metrics that accumulate with time on the pitch; the rest (m/min, top speed)
# are rates or peaks and do not.
_VOLUMEN = ("tot_dist", "hsr", "sprint_dist", "sprints", "acc", "dec", "acc_dec",
            "player_load", "dist_acc", "dist_dec", "hmld", "hiaa",
            "zone_75_85", "zone_85_95", "zone_95_100")
_CONTEOS = ("sprints", "acc", "dec", "acc_dec", "hiaa")


def _a_sus_minutos(crudo: dict, minutos: int) -> dict:
    """A match reading consistent with the minutes the player was on.

    Each metric is drawn on its own from the real distribution, so a sampled
    duration of 8 min could sit next to a full match's 8.500 m — visible at a
    glance in the match table. The duration becomes the minutes played (plus
    the added time a full match carries); the distance is the drawn PACE
    (m/min) times those minutes; the other volume metrics scale against a
    full match. Never against the drawn duration: it is independent of them,
    and a short one multiplied a distance by ten.
    """
    if not minutos:
        return crudo
    real = minutos + (6 if minutos >= 60 else 0)
    factor = real / PARTIDO_COMPLETO
    out = dict(crudo, tot_dur=float(real))
    for k in _VOLUMEN:
        if isinstance(out.get(k), (int, float)):
            out[k] = round(out[k] * factor, 0 if k in _CONTEOS else 1)
    if isinstance(crudo.get("mpm"), (int, float)):
        out["tot_dist"] = round(crudo["mpm"] * real, 1)
    return out


def _datos_de_partido(rival: str, de_local: bool, gf: int, gc: int, cuando) -> dict:
    """Lo que la planilla del club dice de un partido (rival, localía, calidad
    del rival, resultado — `formativo_gps_ingest.CAMPOS_PARTIDO`), para la
    demo: el resultado sale del marcador del propio evento, la posición del
    rival es fija por rival."""
    from core.demo_distribution import indice_estable

    puesto = 1 + indice_estable(f"{rival}|tabla", 16)
    return {
        "sesion": f"Partido {cuando:%Y-%m-%d} · MD OFICIAL · {rival.upper()}",
        "opponent": rival, "match_type": "official",
        "venue": "home" if de_local else "away",
        "result": "won" if gf > gc else "lost" if gf < gc else "drawn",
        "opponent_quality": str(puesto), "opponent_rank": puesto,
        "md_label": "MD", "md_label_source": "club",
    }


ANTRO_SLUG = "pentacompartimental"


def _q(clave: str) -> float:
    """A stable quantile in (0.03, 0.97) for one (player, trait)."""
    from core.demo_distribution import indice_estable

    return 0.03 + 0.94 * indice_estable(clave, 10_000) / 10_000


def _velocidad(edad: float, aphv: float) -> float:
    """cm/año a esa edad: ~5,5 en la niñez, ~9,5 en el pico (APHV), ~0 tres
    años después. Una curva de libro, no la de nadie en particular."""
    from math import exp

    fondo = 5.5 if edad <= aphv else 5.5 * exp(-(edad - aphv) / 1.0)
    return fondo + 4.0 * exp(-0.5 * ((edad - aphv) / 0.85) ** 2)


def _antropometria(jugador, pid: str, cuando, ahora, dist_talla) -> dict:
    """Talla, talla sentado y peso de UNA curva de crecimiento por jugador.

    Muestrearlas por separado en cada medición daba tallas que bajaban
    (144,2 → 143,2 → 146,5 → 143,2 cm) y 13 kg de diferencia en un mes, y
    Crecimiento calculaba velocidades de nada. Acá cada jugador tiene su edad
    de pico (temprano, normal o tardío), su talla de HOY sacada de la
    distribución real de su categoría, y la curva hacia atrás; la talla
    sentado y el peso siguen a la talla.
    """
    from statistics import NormalDist

    nac = jugador.date_of_birth
    if nac is None:
        return {}
    edad = lambda t: (t.date() - nac).days / 365.25
    aphv = NormalDist(13.8, 0.9).inv_cdf(_q(pid + "|aphv"))
    hoy = dist_talla.muestrear(_q(pid + "|talla"))
    if hoy is None:
        return {}
    # Talla en `cuando` = la de hoy menos lo que creció entre medio.
    a, b = edad(cuando), edad(ahora)
    paso, crecio, x = 0.02, 0.0, a
    while x < b:
        crecio += _velocidad(x + paso / 2, aphv) * min(paso, b - x)
        x += paso
    talla = hoy - crecio
    ratio = NormalDist(0.522, 0.011).inv_cdf(_q(pid + "|sentado")) - 0.004 * (min(a, 18) - 13)
    imc = NormalDist(19.6, 1.6).inv_cdf(_q(pid + "|imc")) + 0.45 * (min(a, 19) - 14)
    return {"talla": round(talla, 1), "talla_sentado": round(talla * ratio, 1),
            "peso": round(imc * (talla / 100) ** 2, 1)}


def _promociones(categorias: list[str], plantel: dict) -> dict[str, list]:
    """destino → los que juegan ahí la temporada entera, desde abajo.

    Los dos mejores de cada juvenil juegan un escalón arriba; en Sub 14 y
    Sub 16 el mejor salta DOS (lo que Desarrollo destaca); los dos mejores de
    Sub 20 están en proyección al Primer Equipo. "Mejor" = el cuantil de
    habilidad más alto del plantel, el mismo que usa el generador.
    """
    juveniles = [c for c in categorias if c != "Primer Equipo"]
    out: dict[str, list] = {}
    for k, nombre in enumerate(juveniles):
        lst = plantel.get(nombre) or []
        if len(lst) < 3:
            continue
        mejores = lst[-3:][::-1]        # idx más alto = cuantil más alto
        arriba1 = juveniles[k + 1] if k + 1 < len(juveniles) else (
            "Primer Equipo" if "Primer Equipo" in categorias else None)
        if arriba1 is None:
            continue
        if nombre in ("Sub 14", "Sub 16") and k + 2 < len(juveniles):
            out.setdefault(juveniles[k + 2], []).append(mejores[0])
            out.setdefault(arriba1, []).extend(mejores[1:3])
        else:
            out.setdefault(arriba1, []).extend(mejores[0:2])
    return out


def _cadencia(slug: str) -> int:
    """Días entre lecturas, según qué tan seguido se toma ese examen."""
    if slug.startswith("gps_") or slug.startswith("checkin") or slug.startswith("checkout"):
        return 3          # varias por semana
    if slug in {"hoja_diaria_medico", "molestias"}:
        return 7
    return 30             # tests físicos, antropometría: mensual


def _fechas(desde, hasta, cada_dias: int) -> list:
    out, cursor = [], desde
    while cursor <= hasta:
        out.append(cursor)
        cursor += timedelta(days=cada_dias)
    return out
