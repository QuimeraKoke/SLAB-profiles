"""Seeds the demo club's load data and prints what the explainer animation
draws, straight from the module's own calculation (no hand-made numbers):
the matches of the reference window with each player's minutes and position
group, and the resulting reference per group.

    docker compose exec -T backend python manage.py shell < tutoriales/programar-carga/exportar_datos.py
"""
import json
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from core.models import Category
from exams.models import ExamResult
from load_control.defaults import GroupResolver, merged
from load_control.planning import team_for
from load_control.reference import compute_reference, team_match_rows

call_command("seed_demo_carga", commit=True)

category = Category.objects.get(club__name="Selección Chilena", name="Selección Nacional")
team = team_for(category)
today = timezone.localdate()
anchor = today - timedelta(days=today.weekday())
cfg = merged()
ref = compute_reference(club=team.club, bracket=team.bracket, anchor=anchor, cfg=cfg)
resolver = GroupResolver(cfg)

partidos = {}
for rec, data, pos in (ExamResult.objects
                       .filter(team_match_rows(team.club, team.bracket, anchor - timedelta(days=28), anchor))
                       .values_list("recorded_at", "result_data", "player__position__name")
                       .order_by("recorded_at")):
    day = timezone.localtime(rec).date().isoformat()
    p = partidos.setdefault(day, {"fecha": day, "rival": data.get("opponent"), "jugadores": []})
    p["jugadores"].append({"grupo": resolver.group(data, pos), "min": data.get("tot_dur"),
                           "dt": data.get("tot_dist")})

print("@@DATOS@@" + json.dumps({
    "inicio": ref["window"]["start"], "fin": ref["window"]["end"],
    "min_minutos": cfg["ref_min_minutes"],
    "partidos": list(partidos.values()),
    "referencia": {g: {"dt": v["tot_dist"]["value"], "jugadores": v["n_players"]}
                   for g, v in ref["groups"].items()},
}))
