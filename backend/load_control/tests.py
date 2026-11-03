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
