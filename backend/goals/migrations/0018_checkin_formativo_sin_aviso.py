from django.db import migrations


def apagar_aviso(apps, schema_editor):
    """El check-IN formativo alerta sólo en 1 y 2 («Crítico»), no en 3
    («Aviso») — pedido del club, 2026-10-28.

    Las reglas «Aviso» se DESACTIVAN, no se borran: quedan en Reglas de alerta
    para que el club pueda volver a encenderlas. Sus alertas activas se cierran
    como resueltas, para que no sigan en el Centro de mando ni en los perfiles.
    """
    AlertRule = apps.get_model("goals", "AlertRule")
    Alert = apps.get_model("goals", "Alert")
    reglas = [r for r in AlertRule.objects.filter(template__slug="checkin_formativo", kind="band")
              if "Aviso" in ((r.config or {}).get("trigger_labels") or [])]
    ids = [r.id for r in reglas]
    AlertRule.objects.filter(id__in=ids).update(is_active=False)
    Alert.objects.filter(source_type="threshold", source_id__in=ids,
                         status="active").update(status="resolved")


class Migration(migrations.Migration):

    dependencies = [
        ("goals", "0017_alertrule_config_ranges_help"),
        ("exams", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apagar_aviso, migrations.RunPython.noop),
    ]
