"""Guards for the load-control foundations (PLAN_CONTROL_CARGA.md §4.0, §8.2–8.3).

Each test names a decision the staff made on 2026-11-03, so a change that
breaks one breaks something the club asked for: the reference is per position
group, only > 75 GPS minutes, only official matches, the last 28 days, frozen
when the microcycle opens; a friendly cuts the microcycle.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.management.commands.backfill_cohorts import BRACKETS
from core.models import Bracket, Category, Club, Department, Player, Position, TeamSeason
from events.models import Event
from exams.models import ExamResult, ExamTemplate
from load_control import defaults
from load_control.labels import label_days, relabel
from load_control.models import LoadControlConfig, Microcycle, MicrocycleDay
from load_control.reference import compute_reference, day_targets
from load_control.services import open_microcycle


def aware(d: date, hour: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()).replace(hour=hour))


ANCHOR = date(2026, 10, 26)  # Monday that opens U20's M41


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(name="Universidad de Chile")
        cls.other_club = Club.objects.create(name="Otro club")
        cls.dept = Department.objects.create(club=cls.club, name="Físico", slug="fisico")
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.create(code=code, name=name, age=age, order=order)
        cls.sub20 = Bracket.objects.get(name="Sub 20")
        cls.sub18 = Bracket.objects.get(name="Sub 18")
        cls.cat = Category.objects.create(club=cls.club, name="SUB-20")
        TeamSeason.objects.create(team=cls.cat, season=2026, bracket=cls.sub20)
        TeamSeason.objects.create(team=cls.cat, season=2025, bracket=cls.sub20)
        cls.pos_dc = Position.objects.create(club=cls.club, name="Defensa central", abbreviation="DC")
        cls.pos_ext = Position.objects.create(club=cls.club, name="Extremo", abbreviation="EX")
        cls.players = [Player.objects.create(category=cls.cat, first_name=f"J{i}",
                                             last_name="Test", position=cls.pos_dc)
                       for i in range(4)]
        cls.tpl = ExamTemplate.objects.create(department=cls.dept, name="GPS partido",
                                              slug="gps_partido", config_schema={"fields": []})
        cls.cfg = defaults.merged()

    def match_row(self, player, day: date, *, dur=90, pos="DEFENSA CENTRAL", hoja="U20",
                  match_type="official", **metrics):
        data = {"tot_dur": dur, "tot_dist": 10000, "hsr": 600, "sprint_dist": 150,
                "acc": 40, "dec": 45, "origen_hoja": hoja, "match_type": match_type}
        if pos is not None:
            data["posicion_hoja"] = pos
        data.update(metrics)
        return ExamResult(template=self.tpl, player=player, recorded_at=aware(day),
                          result_data=data)

    def ref(self, rows, anchor=ANCHOR, cfg=None):
        ExamResult.objects.bulk_create(rows)
        return compute_reference(club=self.club, bracket=self.sub20, anchor=anchor,
                                 cfg=cfg or self.cfg)


class ConfigTests(Base):
    def test_sin_configuracion_usa_los_valores_decididos(self):
        cfg = LoadControlConfig.resolved(self.club, self.sub20)
        self.assertEqual((cfg["band_ok_pct"], cfg["band_mild_pct"], cfg["ref_window_days"],
                          cfg["ref_min_minutes"], cfg["ref_official_only"]), (8, 12, 28, 75, True))
        self.assertEqual(cfg["excluded_groups"], ["POR"])

    def test_el_club_sobrescribe_y_el_equipo_sobrescribe_al_club(self):
        LoadControlConfig.objects.create(club=self.club, settings={"band_ok_pct": 10},
                                         bracket_overrides={"sub_20": {"band_ok_pct": 6}})
        self.assertEqual(LoadControlConfig.resolved(self.club, self.sub18)["band_ok_pct"], 10)
        self.assertEqual(LoadControlConfig.resolved(self.club, self.sub20)["band_ok_pct"], 6)

    def test_una_clave_desconocida_no_se_guarda(self):
        with self.assertRaises(ValidationError):
            LoadControlConfig(club=self.club, settings={"banda": 5}).full_clean()

    def test_la_posicion_de_la_fila_manda_y_el_plantel_es_el_respaldo(self):
        g = defaults.GroupResolver(self.cfg)
        self.assertEqual(g.group({"posicion_hoja": "EXTREMO"}, "Defensa central"), "EXT")
        self.assertEqual(g.group({}, "Defensa central"), "DFC")
        self.assertIsNone(g.group({}, None))

    def test_la_abreviatura_dc_de_slab_no_es_el_grupo_dc(self):
        # SLAB's "DC" is a centre-back; the club's DC group is the centre-forward.
        g = defaults.GroupResolver(self.cfg)
        self.assertEqual(g.group({}, self.pos_dc.name), "DFC")


class LabelTests(Base):
    def test_un_amistoso_intermedio_corta_el_microciclo(self):
        semana = [ANCHOR + timedelta(days=i) for i in range(7)]  # lun 26 → dom 1
        partidos = {semana[2], semana[6]}  # amistoso miércoles, oficial domingo
        labels = label_days(((d, d in partidos) for d in semana),
                            outside_matches=[ANCHOR - timedelta(days=1)])  # dom 25
        self.assertEqual([labels[d][0] for d in semana],
                         ["MD+1", "MD-1", "MD", "MD+1", "MD-2", "MD-1", "MD"])

    def test_el_codigo_del_club_manda_sobre_el_calculo(self):
        # Lunes 19 después del sábado 17 y antes del jueves 22: el club escribe
        # MD-3 (contado al partido que viene); el más cercano diría MD+2.
        lunes, sabado, jueves = date(2026, 10, 19), date(2026, 10, 17), date(2026, 10, 22)
        labels = label_days([(lunes, False), (jueves, True)], [sabado],
                            club_labels={lunes: "MD-3"})
        self.assertEqual(labels[lunes], ("MD-3", "club"))
        self.assertEqual(label_days([(lunes, False), (jueves, True)], [sabado])[lunes],
                         ("MD+2", "calc"))

    def test_la_regla_siguiente_cuenta_al_partido_que_viene(self):
        lunes, sabado, jueves = date(2026, 10, 19), date(2026, 10, 17), date(2026, 10, 22)
        labels = label_days([(lunes, False), (jueves, True)], [sabado], rule="next")
        self.assertEqual(labels[lunes], ("MD-3", "calc"))

    def test_relabel_toma_el_codigo_de_la_planilla(self):
        mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20,
                                       number=42, start_date=ANCHOR,
                                       end_date=ANCHOR + timedelta(days=1))
        for i in range(2):
            MicrocycleDay.objects.create(microcycle=mc, date=ANCHOR + timedelta(days=i))
        sesion = ExamTemplate.objects.create(department=self.dept, name="GPS sesión",
                                             slug="gps_sesion", config_schema={"fields": []})
        ExamResult.objects.bulk_create([ExamResult(
            template=sesion, player=self.players[0], recorded_at=aware(ANCHOR),
            result_data={"origen_hoja": "U20", "origen_codigo": "MD-4"})])
        relabel(mc)
        first = mc.days.get(date=ANCHOR)
        self.assertEqual((first.md_label, first.md_label_source), ("MD-4", "club"))

    def test_relabel_usa_el_partido_oficial_de_la_semana_anterior(self):
        Event.objects.create(club=self.club, department=self.dept, event_type=Event.TYPE_MATCH,
                             title="U. Española", starts_at=aware(ANCHOR - timedelta(days=1), 21),
                             bracket=self.sub20)
        mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20,
                                       number=41, start_date=ANCHOR,
                                       end_date=ANCHOR + timedelta(days=6))
        for i in range(7):
            MicrocycleDay.objects.create(
                microcycle=mc, date=ANCHOR + timedelta(days=i),
                kind=MicrocycleDay.KIND_OFFICIAL if i == 6 else MicrocycleDay.KIND_TRAINING)
        relabel(mc)
        labels = list(mc.days.values_list("md_label", flat=True))
        self.assertEqual(labels[0], "MD+1", "el lunes después del domingo 21:00 hora local")
        self.assertEqual(labels[-1], "MD")


class ReferenceTests(Base):
    def test_promedio_por_posicion_de_los_que_jugaron_mas_de_75(self):
        p = self.players
        r = self.ref([
            self.match_row(p[0], ANCHOR - timedelta(days=3), tot_dist=10000),
            self.match_row(p[1], ANCHOR - timedelta(days=3), tot_dist=9000),
            self.match_row(p[2], ANCHOR - timedelta(days=3), dur=75, tot_dist=1000),  # = 75: no
            self.match_row(p[3], ANCHOR - timedelta(days=3), dur=40, tot_dist=500),
        ])
        dfc = r["groups"]["DFC"]
        self.assertEqual(dfc["tot_dist"]["value"], 9500.0)
        self.assertEqual((dfc["n_players"], dfc["n_matches"], dfc["fallback"]), (2, 1, False))
        self.assertEqual(r["skipped"]["short"], 2)

    def test_los_amistosos_no_entran_en_la_referencia(self):
        r = self.ref([
            self.match_row(self.players[0], ANCHOR - timedelta(days=3), tot_dist=10000),
            self.match_row(self.players[1], ANCHOR - timedelta(days=5), tot_dist=4000,
                           match_type="friendly"),
        ])
        self.assertEqual(r["groups"]["DFC"]["tot_dist"]["value"], 10000.0)
        self.assertEqual(r["skipped"]["friendly"], 1)

    def test_la_ventana_son_los_28_dias_antes_de_abrir(self):
        p = self.players[0]
        r = self.ref([
            self.match_row(p, ANCHOR - timedelta(days=28), tot_dist=8000),   # primer día: entra
            self.match_row(p, ANCHOR - timedelta(days=29), tot_dist=1),      # fuera
            self.match_row(p, ANCHOR, tot_dist=1),                           # el día que abre: fuera
        ])
        self.assertEqual(r["groups"]["DFC"]["tot_dist"]["value"], 8000.0)
        self.assertEqual(r["window"], {"start": "2026-09-28", "end": "2026-10-26"})

    def test_solo_cuentan_los_partidos_del_equipo_y_del_club(self):
        otro = Category.objects.create(club=self.other_club, name="SUB-20 otro")
        ajeno = Player.objects.create(category=otro, first_name="X", last_name="Y")
        d = ANCHOR - timedelta(days=3)
        r = self.ref([
            self.match_row(self.players[0], d, tot_dist=10000),
            self.match_row(self.players[1], d, tot_dist=1, hoja="U18"),        # otro equipo
            self.match_row(self.players[2], d, tot_dist=1, hoja="SPARRING"),   # sparring
            self.match_row(ajeno, d, tot_dist=1),                              # otro club
        ])
        self.assertEqual(r["groups"]["DFC"]["tot_dist"]["value"], 10000.0)

    def test_una_posicion_sin_muestra_usa_el_promedio_del_equipo(self):
        d = ANCHOR - timedelta(days=3)
        r = self.ref([self.match_row(self.players[0], d, tot_dist=10000),
                      self.match_row(self.players[1], d, tot_dist=12000, pos="EXTREMO")])
        lat = r["groups"]["LAT"]
        self.assertEqual((lat["fallback"], lat["tot_dist"]["value"]), (True, 11000.0))
        self.assertNotIn("POR", r["groups"], "los arqueros quedan fuera por defecto")

    def test_un_grupo_bajo_el_minimo_configurado_usa_el_equipo(self):
        d = ANCHOR - timedelta(days=3)
        rows = [self.match_row(self.players[0], d, tot_dist=8000),
                self.match_row(self.players[1], d, tot_dist=12000, pos="EXTREMO"),
                self.match_row(self.players[2], d, tot_dist=12000, pos="EXTREMO")]
        r = self.ref(rows, cfg=defaults.merged({"ref_min_players": 2}))
        dfc = r["groups"]["DFC"]
        self.assertEqual((dfc["fallback"], dfc["own_players"], dfc["tot_dist"]["value"]),
                         (True, 1, 10666.7))
        self.assertFalse(r["groups"]["EXT"]["fallback"])

    def test_por_defecto_basta_un_jugador(self):
        r = self.ref([self.match_row(self.players[0], ANCHOR - timedelta(days=3))])
        self.assertFalse(r["groups"]["DFC"]["fallback"])

    def test_el_arquero_no_cuenta_ni_en_el_equipo(self):
        d = ANCHOR - timedelta(days=3)
        r = self.ref([self.match_row(self.players[0], d, tot_dist=10000),
                      self.match_row(self.players[1], d, tot_dist=5000, pos="GUARDAMETA")])
        self.assertEqual(r["team"]["tot_dist"]["value"], 10000.0)
        self.assertEqual(r["skipped"]["excluded_group"], 1)

    def test_sin_posicion_en_la_fila_usa_la_del_plantel(self):
        r = self.ref([self.match_row(self.players[0], ANCHOR - timedelta(days=3),
                                     pos=None, tot_dist=7000)])
        self.assertEqual(r["groups"]["DFC"]["tot_dist"]["value"], 7000.0)

    def test_una_ventana_de_enero_alcanza_diciembre(self):
        anchor = date(2026, 1, 12)
        r = self.ref([self.match_row(self.players[0], date(2025, 12, 20), tot_dist=9000)],
                     anchor=anchor)
        self.assertEqual(r["groups"]["DFC"]["tot_dist"]["value"], 9000.0)

    def test_los_parametros_vienen_de_la_configuracion(self):
        cfg = defaults.merged({"ref_min_minutes": 30})
        r = self.ref([self.match_row(self.players[0], ANCHOR - timedelta(days=3),
                                     dur=40, tot_dist=500)], cfg=cfg)
        self.assertEqual(r["groups"]["DFC"]["tot_dist"]["value"], 500.0)


class MicrocycleTests(Base):
    def make(self, **kw):
        return Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20,
                                         number=41, start_date=ANCHOR,
                                         end_date=ANCHOR + timedelta(days=6), **kw)

    def test_abrir_congela_la_referencia(self):
        ExamResult.objects.bulk_create([self.match_row(self.players[0], ANCHOR - timedelta(days=3))])
        mc = open_microcycle(self.make())
        self.assertEqual(mc.status, Microcycle.STATUS_OPEN)
        self.assertIsNotNone(mc.frozen_at)
        antes = mc.ref_snapshot["groups"]["DFC"]["tot_dist"]["value"]
        # Un partido jugado después no reescribe la semana.
        ExamResult.objects.bulk_create([self.match_row(self.players[1], ANCHOR + timedelta(days=2),
                                                       tot_dist=1)])
        mc.refresh_from_db()
        self.assertEqual(mc.ref_snapshot["groups"]["DFC"]["tot_dist"]["value"], antes)
        with self.assertRaises(ValidationError):
            open_microcycle(mc)

    def test_objetivo_es_referencia_por_porcentaje(self):
        mc = self.make(ref_snapshot={
            "params": {"metrics": ["tot_dist", "hsr"]},
            "groups": {"DFC": {"tot_dist": {"value": 10000.0}, "hsr": {"value": 600.0}}}})
        entreno = MicrocycleDay(microcycle=mc, date=ANCHOR, targets_pct={"tot_dist": 65})
        partido = MicrocycleDay(microcycle=mc, date=ANCHOR + timedelta(days=6),
                                kind=MicrocycleDay.KIND_OFFICIAL)
        self.assertEqual(day_targets(mc, entreno)["DFC"], {"tot_dist": 6500.0, "hsr": None})
        self.assertEqual(day_targets(mc, partido)["DFC"], {"tot_dist": 10000.0, "hsr": 600.0})

    def test_un_dia_de_partido_no_lleva_porcentaje(self):
        mc = self.make()
        with self.assertRaises(ValidationError):
            MicrocycleDay(microcycle=mc, date=ANCHOR, kind=MicrocycleDay.KIND_FRIENDLY,
                          targets_pct={"tot_dist": 50}).full_clean()

    def test_un_dia_fuera_del_microciclo_no_se_guarda(self):
        mc = self.make()
        with self.assertRaises(ValidationError):
            MicrocycleDay(microcycle=mc, date=ANCHOR + timedelta(days=9)).full_clean()

    def test_un_porcentaje_invalido_no_se_guarda(self):
        mc = self.make()
        for malo in (-5, 250, "60", True):
            with self.assertRaises(ValidationError, msg=repr(malo)):
                MicrocycleDay(microcycle=mc, date=ANCHOR, targets_pct={"hsr": malo}).full_clean()

    def test_un_equipo_no_repite_numero_de_microciclo(self):
        from django.db import IntegrityError, transaction
        self.make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make()


class MatchDayTests(Base):
    """`load_control.matches`: the club's GPS codes beat drifting fixtures."""

    def days(self, start, end):
        from load_control.matches import team_match_days
        return team_match_days(self.club, 2026, self.sub20, start, end)

    def event(self, d, hour=18):  # 18:00 UTC = 15:00 en Santiago, el mismo día
        Event.objects.create(club=self.club, department=self.dept, event_type=Event.TYPE_MATCH,
                             title="U20 vs rival", starts_at=aware(d, hour), bracket=self.sub20)

    def test_el_partido_es_el_dia_del_gps_no_el_del_fixture(self):
        sabado = date(2026, 10, 17)
        ExamResult.objects.bulk_create([self.match_row(self.players[0], sabado)])
        self.event(sabado + timedelta(days=2), hour=4)  # el fixture: lunes 19, 01:00 en Chile
        self.assertEqual(self.days(date(2026, 10, 12), date(2026, 10, 25)), {sabado: "official"})

    def test_sin_gps_el_fixture_cuenta(self):
        futuro = date(2026, 11, 8)
        self.event(futuro, hour=16)
        self.assertEqual(self.days(date(2026, 11, 2), date(2026, 11, 8)), {futuro: "official"})

    def test_el_amistoso_viene_del_codigo_del_club(self):
        d = date(2026, 10, 28)
        ExamResult.objects.bulk_create([self.match_row(self.players[0], d, match_type="friendly",
                                                       origen_codigo="MD AMISTOSO")])
        self.assertEqual(self.days(d, d), {d: "friendly"})


class EvaluationTests(Base):
    """`load_control.evaluation`: plan vs real, as the club asked to read it."""

    MON = date(2025, 10, 27)  # 2025 so "hasta hoy" never cuts the week

    def setUp(self):
        from load_control.evaluation import evaluate
        self.evaluate = evaluate
        self.sesion = ExamTemplate.objects.create(department=self.dept, name="GPS sesión",
                                                  slug="gps_sesion", config_schema={"fields": []})
        self.mc = Microcycle.objects.create(
            club=self.club, season=2025, bracket=self.sub20, number=44, start_date=self.MON,
            end_date=self.MON + timedelta(days=2), frozen_at=timezone.now(),
            status=Microcycle.STATUS_OPEN, ref_snapshot={
                "params": {"metrics": ["tot_dist", "hsr", "sprint_dist", "acc", "dec"]},
                "groups": {g: {"tot_dist": {"value": 10000.0}, "hsr": {"value": 600.0}}
                           for g in ("DFC", "LAT", "MC", "EXT", "DC")}})
        MicrocycleDay.objects.create(microcycle=self.mc, date=self.MON,
                                     targets_pct={"tot_dist": 50})       # hsr sin %
        MicrocycleDay.objects.create(microcycle=self.mc, date=self.MON + timedelta(days=1),
                                     kind=MicrocycleDay.KIND_REST)
        MicrocycleDay.objects.create(microcycle=self.mc, date=self.MON + timedelta(days=2),
                                     kind=MicrocycleDay.KIND_OFFICIAL)

    def row(self, player, d, dist, *, tpl=None, hoja="U20", pos="DEFENSA CENTRAL", dur=60, **extra):
        data = {"origen_hoja": hoja, "posicion_hoja": pos, "tot_dist": dist, "tot_dur": dur, **extra}
        return ExamResult(template=tpl or self.sesion, player=player, recorded_at=aware(d),
                          result_data=data)

    def cells(self, out, i, metric="tot_dist"):
        by = {p["name"]: p for p in out["players"]}
        return by[f"J{i} Test"]["cells"][metric]

    def test_bandas_simetricas_sobre_el_objetivo_del_dia(self):
        p = self.players
        ExamResult.objects.bulk_create([self.row(p[0], self.MON, 5000), self.row(p[1], self.MON, 5500),
                                        self.row(p[2], self.MON, 4000), self.row(p[3], self.MON, 6000)])
        out = self.evaluate(self.mc, day=self.MON)
        self.assertEqual([self.cells(out, i)["band"] for i in range(4)], ["ok", "leve", "grave", "grave"])
        self.assertEqual(self.cells(out, 2)["pct"], -20.0)
        # −20% y +20% pesan igual (simétrica): empate por nombre; la leve, al final.
        self.assertEqual([(a["name"], a["band"]) for a in out["alerts"]],
                         [("J2 Test", "grave"), ("J3 Test", "grave"), ("J1 Test", "leve")])

    def test_una_metrica_sin_porcentaje_es_sin_objetivo(self):
        ExamResult.objects.bulk_create([self.row(self.players[0], self.MON, 5000, hsr=300)])
        c = self.cells(self.evaluate(self.mc, day=self.MON), 0, "hsr")
        self.assertEqual((c["target"], c["real"], c["pct"], c["band"]), (None, 300.0, None, None))

    def test_sin_gps_no_es_cero(self):
        ExamResult.objects.bulk_create([self.row(self.players[0], self.MON, 5000)])
        out = self.evaluate(self.mc, day=self.MON)
        self.assertEqual([p["name"] for p in out["players"]], ["J0 Test"])

    def test_la_fila_duplicada_cuenta_una_vez(self):
        partido = self.tpl  # gps_partido
        d = self.MON + timedelta(days=2)
        ExamResult.objects.bulk_create([self.row(self.players[0], d, 10000, tpl=partido, dur=95),
                                        self.row(self.players[0], d, 10000, dur=95)])
        out = self.evaluate(self.mc, day=d)
        self.assertEqual(self.cells(out, 0)["real"], 10000.0)
        self.assertEqual(out["provenance"]["duplicates_dropped"], 1)

    def test_una_doble_sesion_real_suma(self):
        ExamResult.objects.bulk_create([self.row(self.players[0], self.MON, 3000, dur=40),
                                        self.row(self.players[0], self.MON, 2000, dur=30)])
        self.assertEqual(self.cells(self.evaluate(self.mc, day=self.MON), 0)["real"], 5000.0)

    def test_el_sparring_suma_y_se_puede_dejar_fuera(self):
        p = self.players[1]
        ExamResult.objects.bulk_create([self.row(p, self.MON, 4000),
                                        self.row(p, self.MON, 1500, hoja="SPARRING", es_sparring=True,
                                                 pos="DEFENSA CENTRAL", dur=45)])
        con = self.evaluate(self.mc, day=self.MON)
        sin = self.evaluate(self.mc, day=self.MON, include_sparring=False)
        self.assertEqual((self.cells(con, 1)["real"], self.cells(sin, 1)["real"]), (5500.0, 4000.0))
        self.assertEqual(con["provenance"]["players_with_sparring"], 1)

    def test_el_grupo_es_la_posicion_de_ese_dia(self):
        ExamResult.objects.bulk_create([self.row(self.players[0], self.MON, 5000, pos="EXTREMO")])
        out = self.evaluate(self.mc, day=self.MON)
        self.assertEqual(out["players"][0]["group"], "EXT")

    def test_el_arquero_queda_fuera(self):
        ExamResult.objects.bulk_create([self.row(self.players[0], self.MON, 5000, pos="GUARDAMETA")])
        self.assertEqual(self.evaluate(self.mc, day=self.MON)["players"], [])

    def test_el_acumulado_compara_solo_los_dias_con_dato(self):
        p = self.players[0]
        d = self.MON + timedelta(days=2)
        ExamResult.objects.bulk_create([self.row(p, self.MON, 5000),
                                        self.row(p, d, 9000, tpl=self.tpl, dur=95),
                                        self.row(self.players[1], d, 10000, tpl=self.tpl, dur=95)])
        out = self.evaluate(self.mc)
        c0, c1 = self.cells(out, 0), self.cells(out, 1)
        self.assertEqual((c0["target"], c0["real"]), (15000.0, 14000.0))
        self.assertEqual((c1["target"], c1["real"]), (10000.0, 10000.0), "sólo el partido")
        self.assertEqual([x["days"] for x in out["players"]][:2], [2, 1])
        self.assertEqual(out["players"][0]["days_planned"], 2, "el descanso no se cuenta")
        sin_partido = self.evaluate(self.mc, include_matches=False)
        self.assertEqual(self.cells(sin_partido, 0)["target"], 5000.0)

    def test_el_resumen_promedia_y_cuenta_bandas(self):
        p = self.players
        ExamResult.objects.bulk_create([self.row(p[0], self.MON, 5000), self.row(p[1], self.MON, 6000)])
        s = self.evaluate(self.mc, day=self.MON)["summary"]["tot_dist"]
        self.assertEqual((s["target"], s["real"], s["pct"], s["counts"]),
                         (5000.0, 5500.0, 10.0, {"ok": 1, "leve": 0, "grave": 1}))


class PostponedMatchTests(Base):
    """A postponed match: COMET's Event keeps the scheduled date (12-oct), its
    match sheets and the club's GPS carry the day it was played (22-oct)."""

    def setUp(self):
        self.ficha = ExamTemplate.objects.create(department=self.dept, name="Ficha",
                                                 slug="ficha_partido", config_schema={"fields": []})
        self.event = Event.objects.create(club=self.club, department=self.dept,
                                          event_type=Event.TYPE_MATCH, title="U. de Chile vs Cobreloa",
                                          starts_at=aware(date(2026, 10, 12), 4), bracket=self.sub20)
        ExamResult.objects.bulk_create([ExamResult(template=self.ficha, player=self.players[0],
                                                   event=self.event, recorded_at=aware(date(2026, 10, 22), 15),
                                                   result_data={"minutos": 90})])

    def test_el_partido_postergado_cae_el_dia_que_se_jugo(self):
        from load_control.matches import team_match_days
        days = team_match_days(self.club, 2026, self.sub20, date(2026, 10, 10), date(2026, 10, 25))
        self.assertEqual(days, {date(2026, 10, 22): "official"}, "sin partido fantasma el 12")

    def test_el_dia_que_se_jugo_queda_vinculado_al_partido(self):
        from load_control.matches import match_links
        links = match_links(self.club, 2026, self.sub20, {date(2026, 10, 22): "official"})
        self.assertEqual(links[date(2026, 10, 22)]["event_id"], str(self.event.id))


class WellnessTests(Base):
    """`load_control.wellness`: check-in / out read the way the club asked."""

    MON = date(2026, 10, 26)

    def setUp(self):
        from load_control.wellness import wellness
        self.wellness = wellness
        self.cin = ExamTemplate.objects.create(department=self.dept, name="Check-in",
                                               slug="checkin_formativo", config_schema={"fields": []})
        self.cout = ExamTemplate.objects.create(department=self.dept, name="Check-out",
                                                slug="checkout_formativo", config_schema={"fields": []})
        self.mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20, number=43,
                                            start_date=self.MON, end_date=self.MON + timedelta(days=1))
        for i in range(2):
            MicrocycleDay.objects.create(microcycle=self.mc, date=self.MON + timedelta(days=i))

    def checkin(self, player, when, s=5, f=5, e=5, a=5, d=5, **extra):
        return ExamResult(template=self.cin, player=player, recorded_at=when,
                          result_data={"calidad_sueno": s, "nivel_fatiga": f, "nivel_estres": e,
                                       "estado_animo": a, "dano_muscular": d, **extra})

    def at(self, d, hour_utc):
        return timezone.make_aware(datetime.combine(d, datetime.min.time()).replace(hour=hour_utc))

    def test_el_dia_es_el_de_chile(self):
        # 02:00 UTC del martes = 23:00 del lunes en Santiago.
        ExamResult.objects.bulk_create([self.checkin(self.players[0], self.at(self.MON + timedelta(days=1), 2))])
        series = self.wellness(self.mc)["series"]
        self.assertEqual([r["checkin_n"] for r in series], [1, 0])

    def test_promedios_y_totales_del_grupo(self):
        ExamResult.objects.bulk_create([
            self.checkin(self.players[0], self.at(self.MON, 11), s=4, f=3, e=5, a=5, d=3),   # 20 / 6
            self.checkin(self.players[1], self.at(self.MON, 11), s=2, f=5, e=5, a=5, d=5)])  # 22 / 10
        r = self.wellness(self.mc)["series"][0]
        self.assertEqual((r["calidad_sueno"], r["total_bienestar"], r["total_muscular"]), (3.0, 21.0, 8.0))

    def test_cuenta_la_ultima_respuesta_del_dia(self):
        p = self.players[0]
        ExamResult.objects.bulk_create([self.checkin(p, self.at(self.MON, 11), s=1),
                                        self.checkin(p, self.at(self.MON, 12), s=5)])
        self.assertEqual(self.wellness(self.mc)["series"][0]["calidad_sueno"], 5.0)

    def test_bienestar_bajo_y_dolor_primero(self):
        p = self.players
        ExamResult.objects.bulk_create([
            self.checkin(p[0], self.at(self.MON, 11), s=2, f=2),                       # 2 ítems bajos
            self.checkin(p[1], self.at(self.MON, 11), dolor_muscular="Isquiotibial der"),
            self.checkin(p[2], self.at(self.MON, 11), sintomas="No"),                  # "No" no es dolor
        ])
        out = self.wellness(self.mc, day=self.MON)
        self.assertEqual([f["name"] for f in out["flagged"]], ["J1 Test", "J0 Test"])
        self.assertEqual([x["key"] for x in out["flagged"][1]["lows"]], ["calidad_sueno", "nivel_fatiga"])
        self.assertEqual(out["missing"], [], "J3 no entrenó ni respondió: no es del plantel de la semana")
        self.assertEqual(out["answered"], {"checkin": 3, "checkout": 0})

    def test_check_out_ua_es_minutos_por_rpe(self):
        ExamResult.objects.bulk_create([ExamResult(template=self.cout, player=self.players[0],
                                                   recorded_at=self.at(self.MON, 22),
                                                   result_data={"duracion_min": 60, "rpe": 7,
                                                                "molestia_post": "Gemelo izq"})])
        out = self.wellness(self.mc, day=self.MON)
        self.assertEqual((out["series"][0]["ua"], out["rows"][0]["ua"]), (420.0, 420.0))
        self.assertEqual(out["flagged"][0]["pain_out"], ["Gemelo izq"])

    def test_un_jugador(self):
        ExamResult.objects.bulk_create([self.checkin(self.players[0], self.at(self.MON, 11), s=1),
                                        self.checkin(self.players[1], self.at(self.MON, 11), s=5)])
        r = self.wellness(self.mc, player_id=self.players[0].id)["series"][0]
        self.assertEqual((r["calidad_sueno"], r["players"]), (1.0, 1))
        with self.assertRaises(ValueError):
            self.wellness(self.mc, player_id="00000000-0000-0000-0000-000000000000")

    def test_sin_responder_es_del_plantel_que_entreno(self):
        gps = ExamResult(template=self.tpl, player=self.players[3], recorded_at=aware(self.MON),
                         result_data={"origen_hoja": "U20", "tot_dist": 5000})
        ExamResult.objects.bulk_create([gps, self.checkin(self.players[0], self.at(self.MON, 11))])
        out = self.wellness(self.mc, day=self.MON)
        self.assertEqual((out["players"], [m["name"] for m in out["missing"]]), (2, ["J3 Test"]))
        # El martes J3 no tuvo GPS ni respondió: no estaba, no se lista.
        martes = self.wellness(self.mc, day=self.MON + timedelta(days=1))
        self.assertEqual(martes["missing"], [])

    def test_sin_check_in_y_sin_check_out_del_dia(self):
        gps = ExamResult(template=self.tpl, player=self.players[3], recorded_at=aware(self.MON),
                         result_data={"origen_hoja": "U20", "tot_dist": 5000})
        ExamResult.objects.bulk_create([gps, self.checkin(self.players[0], self.at(self.MON, 11))])
        out = self.wellness(self.mc, day=self.MON)
        # J3 entrenó sin responder nada; J0 hizo el check-in pero no el check-out.
        self.assertEqual([(w["name"], w["trained"]) for w in out["no_checkin"]], [("J3 Test", True)])
        self.assertEqual([(w["name"], w["trained"]) for w in out["no_checkout"]],
                         [("J3 Test", True), ("J0 Test", False)], "primero los que entrenaron")
        # El martes nadie respondió: todo el plantel de la semana debe ambos formularios.
        martes = self.wellness(self.mc, day=self.MON + timedelta(days=1))
        self.assertEqual({w["name"] for w in martes["no_checkin"]}, {"J0 Test", "J3 Test"})

    def test_el_dolor_repetido_en_ambos_formularios_se_muestra_una_vez(self):
        ExamResult.objects.bulk_create([
            self.checkin(self.players[0], self.at(self.MON, 11), dolor_muscular="Rodilla Der."),
            ExamResult(template=self.cout, player=self.players[0], recorded_at=self.at(self.MON, 22),
                       result_data={"molestia_post": "Rodilla Der."})])
        self.assertEqual(self.wellness(self.mc, day=self.MON)["flagged"][0]["pain"], ["Rodilla Der."])

    def test_un_sintoma_no_es_una_molestia(self):
        ExamResult.objects.bulk_create([
            self.checkin(self.players[0], self.at(self.MON, 11), sintomas="Fiebre"),
            self.checkin(self.players[1], self.at(self.MON, 11), dolor_muscular="Tobillo")])
        f = {x["name"]: x for x in self.wellness(self.mc, day=self.MON)["flagged"]}
        self.assertEqual((f["J0 Test"]["pain"], f["J0 Test"]["symptoms"]), ([], ["Fiebre"]))
        self.assertEqual(f["J1 Test"]["pain"], ["Tobillo"])
        self.assertEqual(list(f), ["J1 Test", "J0 Test"], "la molestia va antes que el síntoma")


class AvailabilityTests(Base):
    """`load_control.availability`: who is out, since when, until when."""

    MON = date(2026, 10, 26)

    def setUp(self):
        from exams.models import Episode
        from load_control.availability import availability
        self.availability, self.Episode = availability, Episode
        self.les = ExamTemplate.objects.create(department=self.dept, name="Lesiones", slug="lesiones",
                                               config_schema={"fields": []})
        self.mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20, number=43,
                                            start_date=self.MON, end_date=self.MON + timedelta(days=6))
        for i in range(7):
            MicrocycleDay.objects.create(microcycle=self.mc, date=self.MON + timedelta(days=i))

    def injure(self, player, status, started, expected=None, closed_at=None, title="Isquiotibial"):
        player.status = status
        player.save(update_fields=["status"])
        e = self.Episode.objects.create(player=player, template=self.les, title=title,
                                        started_at=aware(started),
                                        status="closed" if closed_at else "open",
                                        ended_at=aware(closed_at) if closed_at else None)
        # bulk_create: no signals — the lifecycle would re-derive the episode and
        # the player's status from the result, and this test sets them itself.
        ExamResult.objects.bulk_create([ExamResult(
            template=self.les, player=player, episode=e, recorded_at=aware(started),
            result_data={"expected_return_date": expected.isoformat() if expected else None,
                         "body_part": "Muslo"})])
        return e

    def test_no_disponibles_desde_cuando_y_cuanto_falta(self):
        p = self.players
        self.injure(p[0], "injured", date(2026, 10, 1), expected=date(2026, 11, 10))
        self.injure(p[1], "reintegration", date(2026, 10, 20), expected=date(2026, 10, 28))
        out = self.availability(self.mc, day=self.MON)
        self.assertEqual({c["label"]: c["n"] for c in out["counts"]}["Disponible"], 2)
        first, second = out["unavailable"]
        self.assertEqual((first["name"], first["episode"]["days_out"], first["episode"]["days_to_return"]),
                         ("J0 Test", 25, 15))
        self.assertEqual((second["status_label"], second["episode"]["days_to_return"]), ("Return to Train", 2))

    def test_historial_de_la_temporada(self):
        self.injure(self.players[2], "available", date(2026, 9, 1), closed_at=date(2026, 9, 15))
        self.injure(self.players[3], "available", date(2025, 6, 1), closed_at=date(2025, 6, 10))  # otra temporada
        out = self.availability(self.mc, day=self.MON)
        self.assertEqual([(h["name"], h["days_out"]) for h in out["history"]], [("J2 Test", 14)])


class ParticipationTests(Base):
    """`load_control.participation`: minutes (COMET, else GPS) and attendance."""

    MON = date(2026, 10, 26)

    def setUp(self):
        from load_control.participation import _rival, participation
        self.participation, self._rival = participation, _rival
        self.ficha = ExamTemplate.objects.create(department=self.dept, name="Ficha", slug="ficha_partido",
                                                 config_schema={"fields": []})
        self.sesion = ExamTemplate.objects.create(department=self.dept, name="GPS sesión", slug="gps_sesion",
                                                  config_schema={"fields": []})
        self.mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20, number=43,
                                            start_date=self.MON, end_date=self.MON + timedelta(days=6))
        for i in range(7):
            MicrocycleDay.objects.create(microcycle=self.mc, date=self.MON + timedelta(days=i))

    def gps(self, player, d, tpl=None, hoja="U20", **data):
        return ExamResult(template=tpl or self.sesion, player=player, recorded_at=aware(d),
                          result_data={"origen_hoja": hoja, "tot_dist": 4000, **data})

    def test_minutos_de_la_ficha_comet(self):
        sab = self.MON + timedelta(days=5)
        ev = Event.objects.create(club=self.club, department=self.dept, event_type=Event.TYPE_MATCH,
                                  title="UNIVERSIDAD DE CHILE vs COBRELOA", starts_at=aware(sab, 18),
                                  bracket=self.sub20)
        ExamResult.objects.bulk_create([
            ExamResult(template=self.ficha, player=self.players[0], event=ev, recorded_at=aware(sab, 18),
                       result_data={"minutos": 90, "titular": True}),
            ExamResult(template=self.ficha, player=self.players[1], event=ev, recorded_at=aware(sab, 18),
                       result_data={"minutos": 27, "titular": False})])
        out = self.participation(self.mc)
        self.assertEqual(out["matches"][0]["source"], "comet")
        self.assertEqual(out["matches"][0]["opponent"], "COBRELOA")
        by = {r["name"]: r for r in out["rows"]}
        self.assertEqual((by["J0 Test"]["minutes"], by["J0 Test"]["minutes_pct"], by["J0 Test"]["starts"]), (90, 100, 1))
        self.assertEqual(by["J1 Test"]["minutes_pct"], 30)

    def test_sin_ficha_los_minutos_salen_del_gps(self):
        sab = self.MON + timedelta(days=5)
        ExamResult.objects.bulk_create([self.gps(self.players[0], sab, tpl=self.tpl, tot_dur=97,
                                                 opponent="COLO COLO")])
        out = self.participation(self.mc)
        self.assertEqual((out["matches"][0]["source"], out["matches"][0]["opponent"]), ("gps", "COLO COLO"))
        self.assertEqual(out["rows"][0]["minutes"], 90, "tope de 90")

    def test_asistencia_sobre_las_sesiones_del_equipo(self):
        j4 = Player.objects.create(category=self.cat, first_name="J4", last_name="Test")
        j5 = Player.objects.create(category=self.cat, first_name="J5", last_name="Test")
        lun, mar = self.MON, self.MON + timedelta(days=1)
        rows = [self.gps(p, lun) for p in (*self.players, j4, j5)]        # 6 jugadores: sesión
        rows += [self.gps(p, mar) for p in (*self.players, j5)]           # 5 jugadores: sesión
        rows.append(self.gps(self.players[0], self.MON + timedelta(days=2)))  # 1 jugador: no es sesión
        ExamResult.objects.bulk_create(rows)
        out = self.participation(self.mc)
        by = {r["name"]: r for r in out["rows"]}
        self.assertEqual(out["sessions"], 2)
        self.assertEqual((by["J1 Test"]["attendance_pct"], by["J4 Test"]["attendance_pct"]), (100, 50))
        self.assertFalse(any(r["attendance_low"] for r in out["rows"]), "sin umbral del club, sin semáforo")
        with self.settings():
            cfg = LoadControlConfig.objects.create(club=self.club, settings={"attendance_low_pct": 80})
            self.assertTrue({r["name"]: r for r in self.participation(self.mc)["rows"]}["J4 Test"]["attendance_low"])
            cfg.delete()

    def test_el_rival_es_el_otro_lado_del_titulo(self):
        self.assertEqual(self._rival("COLO COLO vs UNIVERSIDAD DE CHILE", "Universidad de Chile"), "COLO COLO")

    def test_entrenamiento_por_cualquier_senal(self):
        j4 = Player.objects.create(category=self.cat, first_name="J4", last_name="Test")
        j5 = Player.objects.create(category=self.cat, first_name="J5", last_name="Test")
        cin = ExamTemplate.objects.create(department=self.dept, name="Check-in", slug="checkin_formativo",
                                          config_schema={"fields": []})
        lun, mar, mie = self.MON, self.MON + timedelta(days=1), self.MON + timedelta(days=2)
        # 5 jugadores con GPS del equipo los tres días (sin J0): tres sesiones.
        rows = [self.gps(p, d) for d in (lun, mar, mie) for p in (*self.players[1:], j4, j5)]
        rows += [self.gps(self.players[0], lun, hoja=None, origen="catapult"),           # GPS de otra fuente
                 ExamResult(template=cin, player=self.players[0], recorded_at=aware(mar, 11),
                            result_data={"calidad_sueno": 5}),                            # sólo formulario
                 self.gps(self.players[0], mie, origen_codigo="MD AMISTOSO")]             # amistoso: no
        ExamResult.objects.bulk_create(rows)
        by = {r["name"]: r for r in self.participation(self.mc)["rows"]}
        j0 = by["J0 Test"]
        self.assertEqual((j0["sessions_attended"], j0["sessions_gps"], j0["sessions_form_only"]), (2, 1, 1))

    def test_un_dia_de_partido_no_es_sesion(self):
        sab = self.MON + timedelta(days=5)
        ExamResult.objects.bulk_create([self.gps(p, sab, origen_codigo="MD OFICIAL") for p in self.players])
        self.assertEqual(self.participation(self.mc)["sessions"], 0)


class FatigueTests(Base):
    """`load_control.fatigue`: match fatigue, basal and accumulated fatigue."""

    def setUp(self):
        from load_control.fatigue import fatigue
        self.fatigue = fatigue
        self.salto = ExamTemplate.objects.create(department=self.dept, name="Salto", slug="control_salto",
                                                 config_schema={"fields": []})
        self.mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20, number=43,
                                            start_date=date(2026, 10, 26), end_date=date(2026, 11, 1))
        for i in range(7):
            MicrocycleDay.objects.create(microcycle=self.mc, date=self.mc.start_date + timedelta(days=i))

    def jump(self, player, d, pre, post, method="rebote / contacto", team="U20"):
        return ExamResult(template=self.salto, player=player, recorded_at=aware(d),
                          result_data={"rsi_pre_best": pre, "rsi_post_best": post, "rsi_metodo": method,
                                       "equipo_hoja": team, "fecha_fuente": "propuesta", "hoja": "M41",
                                       "rival": "COLO COLO"})

    def season(self, player, pres, start=date(2026, 3, 7), method="rebote / contacto"):
        return [self.jump(player, start + timedelta(days=7 * i), v, v, method) for i, v in enumerate(pres)]

    def test_tres_saltos_golpe_y_como_llega_al_proximo(self):
        p = self.players[0]
        ExamResult.objects.bulk_create([
            self.jump(p, date(2026, 10, 31), 1.6, 1.44),                   # golpe −10 %
            self.jump(p, date(2026, 11, 7), 1.56, 1.5),                    # próximo PRE −2,5 % vs PRE
        ])
        out = self.fatigue(self.mc)
        r = out["rows"][0]
        self.assertEqual((out["match"]["date"], out["next_match"]["date"]), ("2026-10-31", "2026-11-07"))
        self.assertEqual((r["pre"], r["post"], r["next_pre"]), (1.6, 1.44, 1.56))
        self.assertEqual((r["golpe_pct"], r["golpe_band"]), (-10.0, "grave"))
        self.assertEqual((r["llega_pct"], r["llega_band"], r["llega_state"]), (-2.5, "leve", "measured"))

    def test_la_curva_trae_sus_ultimos_partidos_hasta_este(self):
        p = self.players[0]
        ExamResult.objects.bulk_create(self.season(p, [1.5] * 6) + [self.jump(p, date(2026, 10, 31), 1.6, 1.44),
                                                                    self.jump(p, date(2026, 11, 7), 1.6, 1.6)])
        recent = self.fatigue(self.mc)["rows"][0]["recent"]
        self.assertEqual(len(recent), 4)
        self.assertEqual((recent[-1]["date"], recent[-1]["golpe_band"]), ("2026-10-31", "grave"))

    def test_sin_proximo_partido_medido_queda_pendiente(self):
        ExamResult.objects.bulk_create([self.jump(self.players[0], date(2026, 10, 31), 1.6, 1.5)])
        r = self.fatigue(self.mc)["rows"][0]
        self.assertEqual((r["next_pre"], r["llega_state"]), (None, "pending"))

    def test_no_salto_el_proximo_es_faltante_no_pendiente(self):
        ExamResult.objects.bulk_create([self.jump(self.players[0], date(2026, 10, 31), 1.6, 1.5),
                                        self.jump(self.players[1], date(2026, 10, 31), 1.6, 1.5),
                                        self.jump(self.players[1], date(2026, 11, 7), 1.6, 1.5)])
        rows = {r["name"]: r for r in self.fatigue(self.mc)["rows"]}
        self.assertEqual(rows["J0 Test"]["llega_state"], "missing")

    def test_el_basal_da_contexto_y_usa_solo_el_mismo_metodo(self):
        p = self.players[0]
        rows = self.season(p, [0.5, 0.5, 0.5], method="RSI mod")           # CMJ: otra escala
        rows += self.season(p, [1.6, 1.8], start=date(2026, 6, 6))
        rows.append(self.jump(p, date(2026, 10, 31), 1.53, 1.5))
        ExamResult.objects.bulk_create(rows)
        r = self.fatigue(self.mc)["rows"][0]
        self.assertEqual((r["basal"], r["basal_n"], r["pre_vs_basal"]), (1.7, 2, -10.0))

    def test_deriva_de_temporada_compara_basal_actual_con_el_de_inicio(self):
        p = self.players[0]
        ExamResult.objects.bulk_create(self.season(p, [2.0] * 5 + [1.8] * 5)
                                       + [self.jump(p, date(2026, 10, 31), 1.8, 1.8)])
        r = self.fatigue(self.mc)["rows"][0]
        self.assertEqual((r["season_drift_pct"], r["season_drift_band"]), (-10.0, "grave"))

    def test_los_partidos_son_los_de_la_planilla_del_equipo(self):
        ExamResult.objects.bulk_create([self.jump(self.players[0], date(2026, 10, 28), 1.5, 1.5, team="U18"),
                                        self.jump(self.players[1], date(2026, 10, 31), 1.5, 1.4)])
        out = self.fatigue(self.mc)
        self.assertEqual(out["match"]["date"], "2026-10-31")
        self.assertEqual([r["name"] for r in out["rows"]], ["J1 Test"])

    def test_primero_el_que_llega_peor_al_proximo(self):
        d, nxt = date(2026, 10, 31), date(2026, 11, 7)
        ExamResult.objects.bulk_create([
            self.jump(self.players[0], d, 1.5, 1.2), self.jump(self.players[0], nxt, 1.55, 1.5),  # golpe duro, recuperado
            self.jump(self.players[1], d, 1.5, 1.45), self.jump(self.players[1], nxt, 1.3, 1.3),  # llega mal
            self.jump(self.players[2], d, 1.5, 1.5),                                               # sin próximo
        ])
        self.assertEqual([r["name"] for r in self.fatigue(self.mc)["rows"]], ["J1 Test", "J2 Test", "J0 Test"])


class SummaryTests(Base):
    """`load_control.summary`: the club's short/over rules and who to review first."""

    def test_compensar_exige_tres_metricas_y_salud_va_primero(self):
        from unittest import mock

        from load_control import summary as sm
        cells = lambda pcts: {k: {"pct": v, "band": None, "target": 1, "real": 1} for k, v in pcts.items()}
        ev = {"metrics": [{"key": k, "label": k.upper(), "short": k.upper()} for k in ("a", "b", "c", "d")],
              "summary": {}, "days": [],
              "players": [
                  {"player_id": "1", "name": "Dos bajo", "days": 5, "days_planned": 5, "cells": cells({"a": -20, "b": -20, "c": 0, "d": 0})},
                  {"player_id": "2", "name": "Tres bajo", "days": 5, "days_planned": 5, "cells": cells({"a": -9, "b": -9, "c": -9, "d": 0})},
                  {"player_id": "3", "name": "Pasado", "days": 5, "days_planned": 5, "cells": cells({"a": 21, "b": 0, "c": 0, "d": 0})},
              ]}
        fa = {"next_match": None, "match": None, "rows": [], "summary": {"counts": {"golpe": {"ok": 0, "leve": 0, "grave": 0}}, "golpe_n": 0}}
        av = {"counts": [], "players": 3, "unavailable": [{"player_id": "3", "name": "Pasado", "status_label": "Lesionado", "episode": None}]}
        mc = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20, number=43,
                                       start_date=date(2026, 10, 26), end_date=date(2026, 11, 1))
        with mock.patch.object(sm, "evaluate", return_value=ev), mock.patch.object(sm, "fatigue", return_value=fa), \
                mock.patch.object(sm, "availability", return_value=av), \
                mock.patch.object(sm, "participation", return_value={"sessions": 0, "matches": []}):
            out = sm.summary(mc)
        self.assertEqual((out["cards"]["load"]["short"], out["cards"]["load"]["over"]), (1, 1))
        self.assertEqual([r["name"] for r in out["review"]], ["Pasado", "Tres bajo"],
                         "el no disponible primero; 'Dos bajo' no llega a 3 métricas")
