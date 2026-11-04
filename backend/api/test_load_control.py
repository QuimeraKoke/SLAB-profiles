"""Control de carga planning API (`api/load_control.py`, `load_control/planning.py`).

The week under test is U20's real M41 shape: Monday 26-oct after Sunday's
official match, a FRIENDLY on Wednesday that cuts the microcycle, the official
match on Sunday 1-nov. M40 is the plan its % are copied from.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from api.auth import issue_token
from core.management.commands.backfill_cohorts import BRACKETS
from core.models import (Bracket, Category, Club, Department, Player, Position,
                         StaffMembership, TeamSeason)
from events.models import Event
from exams.models import ExamResult, ExamTemplate
from load_control.models import Microcycle, MicrocycleDay

User = get_user_model()
MON = date(2026, 10, 26)
WEEK = [MON + timedelta(days=i) for i in range(7)]


def aware(d: date, hour: int = 0) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()).replace(hour=hour))


class LoadControlApiTests(TestCase):
    def setUp(self):
        call_command("seed_role_groups", "--skip-backfill", stdout=open("/dev/null", "w"))
        self.club = Club.objects.create(name="Universidad de Chile")
        self.dept = Department.objects.create(club=self.club, name="Físico", slug="fisico")
        for order, (code, name, age) in enumerate(BRACKETS):
            Bracket.objects.get_or_create(code=code, defaults={"name": name, "age": age,
                                                               "order": order})
        self.sub20 = Bracket.objects.get(name="Sub 20")
        self.cat = Category.objects.create(club=self.club, name="SUB-20")
        TeamSeason.objects.create(team=self.cat, season=2026, bracket=self.sub20)
        self.sin_tramo = Category.objects.create(club=self.club, name="Escuela")
        pos = Position.objects.create(club=self.club, name="Defensa central", abbreviation="DC")
        self.player = Player.objects.create(category=self.cat, first_name="Ana", last_name="Soto",
                                            position=pos)
        self.partido = ExamTemplate.objects.create(department=self.dept, name="GPS partido",
                                                   slug="gps_partido", config_schema={"fields": []})
        self.sesion = ExamTemplate.objects.create(department=self.dept, name="GPS sesión",
                                                  slug="gps_sesion", config_schema={"fields": []})
        for d in (MON - timedelta(days=1), WEEK[6]):  # domingos oficiales, 21:00
            Event.objects.create(club=self.club, department=self.dept, event_type=Event.TYPE_MATCH,
                                 title="U20 vs rival", starts_at=aware(d, 21), bracket=self.sub20)
        # El amistoso del miércoles sólo existe en el GPS, como en la planilla real.
        ExamResult.objects.bulk_create([ExamResult(
            template=self.sesion, player=self.player, recorded_at=aware(WEEK[2]),
            result_data={"origen_hoja": "U20", "origen_codigo": "MD AMISTOSO",
                         "tipo_sesion": "amistoso", "microciclo": 41, "opponent": "COLINA",
                         "tipo_microciclo": "mixta", "tot_dist": 5000})])
        # Referencia: un partido oficial completo una semana antes.
        ExamResult.objects.bulk_create([ExamResult(
            template=self.partido, player=self.player, recorded_at=aware(MON - timedelta(days=8)),
            result_data={"origen_hoja": "U20", "match_type": "official", "tot_dur": 92,
                         "posicion_hoja": "DEFENSA CENTRAL", "tot_dist": 10000, "hsr": 600,
                         "sprint_dist": 150, "acc": 40, "dec": 45})])
        # M40: la semana anterior, con % por etiqueta MD.
        self.m40 = Microcycle.objects.create(club=self.club, season=2026, bracket=self.sub20,
                                             number=40, start_date=MON - timedelta(days=7),
                                             end_date=MON - timedelta(days=1), kind="mixta")
        plan = {"MD+1": 30, "MD-1": 45, "MD-2": 65}
        for i in range(7):
            d = MON - timedelta(days=7 - i)
            label = ["MD+1", "MD-5", "MD-4", "MD-3", "MD-2", "MD-1", "MD"][i]
            MicrocycleDay.objects.create(
                microcycle=self.m40, date=d, md_label=label,
                kind=MicrocycleDay.KIND_OFFICIAL if label == "MD" else MicrocycleDay.KIND_TRAINING,
                targets_pct={"tot_dist": plan[label], "hsr": plan[label] - 20} if label in plan else {})

    def client_for(self, role: str | None, club=None) -> Client:
        if role is None:
            user = User.objects.create_superuser(f"su{User.objects.count()}", "su@x.com", "x")
        else:
            user = User.objects.create_user(username=f"{role}{User.objects.count()}", password="x")
            user.groups.add(Group.objects.get(name=role))
            m = StaffMembership.objects.create(user=user, club=club or self.club,
                                               all_departments=True)
            m.categories.add(self.cat)
        return Client(HTTP_AUTHORIZATION=f"Bearer {issue_token(User.objects.get(pk=user.pk))[0]}")

    def create(self, c=None, **extra):
        body = {"category_id": str(self.cat.id), "season": 2026, "start_date": MON.isoformat(),
                "end_date": WEEK[6].isoformat(), "number": 41, "kind": "mixta",
                "copy_from_id": str(self.m40.id), **extra}
        return (c or self.client_for("Editor Formativo")).post(
            "/api/load-control/microcycles", body, content_type="application/json")

    # ── permisos y alcance ───────────────────────────────────────────────
    def test_lectura_ve_pero_no_planifica(self):
        c = self.client_for("Lectura Formativo")
        r = c.get("/api/load-control/team", {"category_id": str(self.cat.id), "season": 2026})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["label"], "U20")
        self.assertEqual(self.create(c).status_code, 403)

    def test_editor_formativo_planifica(self):
        self.assertEqual(self.create().status_code, 200)

    def test_otro_club_no_ve_el_microciclo(self):
        otro = Club.objects.create(name="Otro")
        c = self.client_for("Editor Formativo", club=otro)
        self.assertEqual(c.get(f"/api/load-control/microcycles/{self.m40.id}").status_code, 404)

    def test_una_categoria_sin_tramo_no_tiene_equipo(self):
        c = self.client_for(None)
        r = c.get("/api/load-control/team", {"category_id": str(self.sin_tramo.id), "season": 2026})
        self.assertEqual(r.status_code, 404)

    # ── sugerencia ──────────────────────────────────────────────────────
    def test_la_sugerencia_viene_de_la_planilla_y_del_calendario(self):
        c = self.client_for(None)
        r = c.get("/api/load-control/microcycles/suggestion",
                  {"category_id": str(self.cat.id), "season": 2026}).json()
        self.assertEqual((r["start_date"], r["number"], r["kind"]), ("2026-10-26", 41, "mixta"))
        self.assertEqual(r["copy_from"]["number"], 40)
        self.assertEqual([d["kind"] for d in r["days"]],
                         ["training", "training", "friendly", "training", "training",
                          "training", "official"])
        self.assertEqual([d["md_label"] for d in r["days"]],
                         ["MD+1", "MD-1", "MD", "MD+1", "MD-2", "MD-1", "MD"])

    # ── crear y copiar ──────────────────────────────────────────────────
    def test_crear_copia_los_porcentajes_por_etiqueta(self):
        r = self.create().json()
        pct = {d["date"]: d["targets_pct"] for d in r["days"]}
        self.assertEqual(pct["2026-10-26"], {"tot_dist": 30, "hsr": 10})   # MD+1 ← MD+1
        self.assertEqual(pct["2026-10-29"], {"tot_dist": 30, "hsr": 10})   # MD+1 tras el amistoso
        self.assertEqual(pct["2026-10-30"], {"tot_dist": 65, "hsr": 45})   # MD-2
        self.assertEqual(pct["2026-10-28"], {}, "el amistoso no lleva %")
        self.assertEqual(r["changed_vs_copy"], {})
        self.assertTrue(r["reference"]["preview"], "en borrador la referencia es una vista previa")
        self.assertEqual(r["targets"]["2026-10-30"]["DFC"]["tot_dist"], 6500.0)
        self.assertEqual(r["targets"]["2026-10-28"]["DFC"]["tot_dist"], 10000.0, "partido = 100%")

    def test_no_se_repite_el_numero(self):
        self.create()
        r = self.create()
        self.assertEqual(r.status_code, 400)
        self.assertIn("semana 41", r.json()["detail"])

    def test_un_tipo_desconocido_se_rechaza(self):
        self.assertEqual(self.create(kind="intensiva").status_code, 400)

    # ── editar ──────────────────────────────────────────────────────────
    def days_body(self, r, **overrides):
        out = []
        for d in r["days"]:
            item = {"date": d["date"], "kind": d["kind"], "targets_pct": d["targets_pct"]}
            item.update(overrides.get(d["date"], {}))
            out.append(item)
        return out

    def put(self, mc_id, body):
        return self.client_for("Editor Formativo").put(
            f"/api/load-control/microcycles/{mc_id}", body, content_type="application/json")

    def test_editar_marca_lo_que_cambio_respecto_de_la_copia(self):
        r = self.create().json()
        body = {"days": self.days_body(r, **{"2026-10-30": {"targets_pct": {"tot_dist": 70, "hsr": 45}}})}
        out = self.put(r["id"], body)
        self.assertEqual(out.status_code, 200)
        self.assertEqual(out.json()["changed_vs_copy"], {"2026-10-30": ["tot_dist"]})

    def test_mover_el_amistoso_reetiqueta_la_semana(self):
        r = self.create().json()
        body = {"days": self.days_body(r, **{
            "2026-10-28": {"kind": "training", "targets_pct": {}},
            "2026-10-29": {"kind": "friendly", "targets_pct": {}}})}
        out = self.put(r["id"], body).json()
        self.assertEqual([d["md_label"] for d in out["days"]],
                         # Martes: a 2 días del domingo anterior y del amistoso
                         # del jueves; en el empate gana el partido que viene.
                         ["MD+1", "MD-2", "MD-1", "MD", "MD+1", "MD-1", "MD"])

    def test_un_dia_que_pasa_a_partido_pierde_sus_porcentajes(self):
        # Un partido vale 100%: si el PF cambia un entrenamiento a partido, los %
        # que traía se descartan en vez de bloquear el guardado.
        r = self.create().json()
        body = {"days": self.days_body(r, **{"2026-10-30": {"kind": "official"}})}
        out = self.put(r["id"], body).json()
        dia = next(d for d in out["days"] if d["date"] == "2026-10-30")
        self.assertEqual((dia["kind"], dia["targets_pct"]), ("official", {}))

    def test_un_porcentaje_fuera_de_rango_se_rechaza(self):
        r = self.create().json()
        body = {"days": self.days_body(r, **{"2026-10-30": {"targets_pct": {"tot_dist": 250}}})}
        resp = self.put(r["id"], body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("2026-10-30", resp.json()["detail"])

    def test_el_plan_trae_todos_los_dias(self):
        r = self.create().json()
        self.assertEqual(self.put(r["id"], {"days": self.days_body(r)[:5]}).status_code, 400)

    def test_una_metrica_desconocida_se_rechaza(self):
        r = self.create().json()
        body = {"days": self.days_body(r, **{"2026-10-30": {"targets_pct": {"rpe": 50}}})}
        self.assertEqual(self.put(r["id"], body).status_code, 400)

    # ── abrir ───────────────────────────────────────────────────────────
    def test_abrir_congela_y_no_se_abre_dos_veces(self):
        r = self.create().json()
        c = self.client_for("Editor Formativo")
        out = c.post(f"/api/load-control/microcycles/{r['id']}/open").json()
        self.assertEqual(out["status"], "open")
        self.assertFalse(out["reference"]["preview"])
        self.assertEqual(out["reference"]["groups"]["DFC"]["tot_dist"]["value"], 10000.0)
        self.assertEqual(c.post(f"/api/load-control/microcycles/{r['id']}/open").status_code, 400)

    def test_un_lector_no_abre(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        self.assertEqual(c.post(f"/api/load-control/microcycles/{r['id']}/open").status_code, 403)

    # ── evaluación (Carga GPS) ──────────────────────────────────────────
    def test_lectura_ve_la_evaluacion_del_dia(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        out = c.get(f"/api/load-control/microcycles/{r['id']}/evaluation", {"day": "2026-10-28"})
        self.assertEqual(out.status_code, 200)
        body = out.json()
        self.assertEqual((body["mode"], body["days"][0]["md_label"]), ("day", "MD"))
        self.assertEqual(body["players"][0]["cells"]["tot_dist"]["real"], 5000.0)

    def test_un_dia_fuera_del_microciclo_es_400(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        out = c.get(f"/api/load-control/microcycles/{r['id']}/evaluation", {"day": "2026-12-01"})
        self.assertEqual(out.status_code, 400)

    # ── partidos vinculados ─────────────────────────────────────────────
    def test_el_partido_oficial_queda_vinculado_y_el_amistoso_muestra_su_rival(self):
        r = self.create().json()
        dias = {d["date"]: d for d in r["days"]}
        domingo = Event.objects.get(starts_at__date=WEEK[6])
        self.assertEqual(dias["2026-11-01"]["event_id"], str(domingo.id))
        self.assertEqual(dias["2026-10-28"]["opponent"], "COLINA")
        self.assertIsNone(dias["2026-10-28"]["event_id"],
                          "el amistoso no toma el partido oficial más cercano")
        self.assertIsNone(dias["2026-10-30"]["event_id"], "un entrenamiento no lleva partido")

    def test_el_gps_manda_sobre_la_fecha_del_fixture(self):
        # El fixture del domingo quedó un día corrido (lunes 2); el GPS del
        # domingo ya lo trae vinculado: ése es el partido.
        corrido = Event.objects.create(club=self.club, department=self.dept,
                                       event_type=Event.TYPE_MATCH, title="Fixture corrido",
                                       starts_at=aware(WEEK[6] + timedelta(days=1), 1),
                                       bracket=self.sub20)
        ExamResult.objects.bulk_create([ExamResult(
            template=self.partido, player=self.player, recorded_at=aware(WEEK[6]), event=corrido,
            result_data={"origen_hoja": "U20", "match_type": "official", "opponent": "COLO COLO",
                         "tot_dur": 90, "tot_dist": 9000})])
        r = self.create().json()
        domingo = next(d for d in r["days"] if d["date"] == "2026-11-01")
        self.assertEqual((domingo["event_id"], domingo["opponent"]), (str(corrido.id), "COLO COLO"))

    def test_un_partido_que_pasa_a_entrenamiento_pierde_el_vinculo(self):
        r = self.create().json()
        body = {"days": self.days_body(r, **{"2026-11-01": {"kind": "training", "targets_pct": {}}})}
        out = self.put(r["id"], body).json()
        domingo = next(d for d in out["days"] if d["date"] == "2026-11-01")
        self.assertIsNone(domingo["event_id"])

    # ── check-in / out ──────────────────────────────────────────────────
    def test_lectura_ve_el_check_in_out(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        out = c.get(f"/api/load-control/microcycles/{r['id']}/wellness", {"day": "2026-10-27"})
        self.assertEqual(out.status_code, 200)
        body = out.json()
        self.assertEqual(len(body["series"]), 7)
        self.assertEqual([i["key"] for i in body["items"]][:2], ["calidad_sueno", "nivel_fatiga"])
        self.assertIn("missing", body)

    # ── kinesia y lesiones ──────────────────────────────────────────────
    def test_lectura_ve_la_disponibilidad(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        out = c.get(f"/api/load-control/microcycles/{r['id']}/availability")
        self.assertEqual(out.status_code, 200)
        self.assertEqual([x["label"] for x in out.json()["counts"]],
                         ["Lesionado", "Recuperación", "Return to Train", "Disponible"])

    # ── minutos y asistencia ────────────────────────────────────────────
    def test_lectura_ve_minutos_y_asistencia(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        for scope in ("microcycle", "season"):
            out = c.get(f"/api/load-control/microcycles/{r['id']}/participation", {"scope": scope})
            self.assertEqual(out.status_code, 200, scope)
        self.assertEqual(c.get(f"/api/load-control/microcycles/{r['id']}/participation",
                               {"scope": "anual"}).status_code, 400)

    # ── fatiga post-partido ─────────────────────────────────────────────
    def test_lectura_ve_la_fatiga_del_partido(self):
        r = self.create().json()
        salto = ExamTemplate.objects.create(department=self.dept, name="Salto", slug="control_salto",
                                            config_schema={"fields": []})
        ExamResult.objects.create(template=salto, player=self.player, recorded_at=aware(date(2026, 10, 31)),
                                  result_data={"rsi_pre_best": 1.5, "rsi_post_best": 1.35, "equipo_hoja": "U20",
                                               "rsi_metodo": "rebote / contacto", "hoja": "M41"})
        c = self.client_for("Lectura Formativo")
        url = f"/api/load-control/microcycles/{r['id']}/fatigue"
        out = c.get(url, {"player_id": str(self.player.id)})
        self.assertEqual(out.status_code, 200)
        body = out.json()
        self.assertEqual((body["match"]["date"], body["rows"][0]["golpe_pct"]), ("2026-10-31", -10.0))
        self.assertEqual(body["trend"]["name"], body["rows"][0]["name"])
        self.assertEqual(c.get(url, {"match_date": "2026-10-28"}).status_code, 400)

    # ── composición corporal ────────────────────────────────────────────
    def test_composicion_ultima_vs_anterior_y_promedio(self):
        penta = ExamTemplate.objects.create(department=self.dept, name="Pentacompartimental",
                                            slug="pentacompartimental", config_schema={"fields": []})
        for d, peso, mmp in ((date(2026, 3, 1), 70.0, 50.0), (date(2026, 6, 1), 71.0, 51.5)):
            ExamResult.objects.create(template=penta, player=self.player, recorded_at=aware(d, 12),
                                      result_data={"peso": peso, "masa_muscular_pct": mmp, "suma_pliegues": 40})
        c = self.client_for("Lectura Formativo")
        out = c.get("/api/load-control/composition", {"category_id": str(self.cat.id), "player_id": str(self.player.id)})
        self.assertEqual(out.status_code, 200)
        body = out.json()
        row = body["rows"][0]
        self.assertEqual((row["last"]["date"], row["prev_date"], row["delta"]["mmp"], row["delta"]["pl"]),
                         ("2026-06-01", "2026-03-01", 1.5, 0.0))
        self.assertEqual((body["mean"]["peso"], len(body["player"]["measurements"])), (71.0, 2))
        self.assertEqual(c.get("/api/load-control/composition", {"category_id": "00000000-0000-0000-0000-000000000000"}).status_code, 404)

    # ── jugador ─────────────────────────────────────────────────────────
    def test_ficha_del_jugador_junta_todas_las_pestanas(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        roster = c.get(f"/api/load-control/microcycles/{r['id']}/players").json()
        self.assertIn(str(self.player.id), [x["player_id"] for x in roster])
        out = c.get(f"/api/load-control/microcycles/{r['id']}/players/{self.player.id}")
        self.assertEqual(out.status_code, 200)
        body = out.json()
        self.assertEqual(set(body), {"player", "load", "wellness", "fatigue", "minutes", "status",
                                     "evaluations", "composition"})
        self.assertEqual(len(body["load"]["days"]), 7)
        self.assertEqual(c.get(f"/api/load-control/microcycles/{r['id']}/players/"
                               "00000000-0000-0000-0000-000000000000").status_code, 400)

    # ── resumen ─────────────────────────────────────────────────────────
    def test_resumen_frase_tarjetas_y_para_revisar(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        out = c.get(f"/api/load-control/microcycles/{r['id']}/summary")
        self.assertEqual(out.status_code, 200)
        body = out.json()
        self.assertTrue(body["sentence"].endswith("."))
        self.assertEqual(set(body["cards"]), {"load", "fatigue", "wellness", "availability", "participation"})
        self.assertIsInstance(body["review"], list)

    # ── navegación por día (Centro de mando) ────────────────────────────
    def test_cualquier_dia_abre_su_semana_aunque_no_este_planificada(self):
        c = self.client_for("Lectura Formativo")
        nav = c.get("/api/load-control/day", {"category_id": str(self.cat.id), "day": "2026-10-28"})
        self.assertEqual(nav.status_code, 200)
        body = nav.json()
        self.assertEqual((body["start_date"], body["end_date"], body["planned"], body["microcycle_id"]),
                         ("2026-10-26", "2026-11-01", False, None))
        key = body["week_key"]
        for path in ("summary", "wellness", "availability", "participation", "fatigue", "players"):
            self.assertEqual(c.get(f"/api/load-control/microcycles/{key}/{path}").status_code, 200, path)
        detail = c.get(f"/api/load-control/microcycles/{key}").json()
        self.assertEqual(len(detail["days"]), 7)
        ev = c.get(f"/api/load-control/microcycles/{key}/evaluation").json()
        self.assertFalse(ev["provenance"]["planned"], "sin plan no hay objetivo")
        self.assertTrue(all(cell["target"] is None for p in ev["players"] for cell in p["cells"].values()))

    def test_un_dia_de_una_semana_planificada_usa_su_plan(self):
        r = self.create().json()
        c = self.client_for("Lectura Formativo")
        body = c.get("/api/load-control/day", {"category_id": str(self.cat.id), "day": r["start_date"]}).json()
        self.assertEqual((body["planned"], body["microcycle_id"]), (True, r["id"]))

    def test_la_semana_va_de_lunes_a_domingo(self):
        self.assertEqual(self.create(start_date="2026-10-27", end_date="2026-11-02").status_code, 400)
        self.assertEqual(self.create(end_date="2026-10-30").status_code, 400)
