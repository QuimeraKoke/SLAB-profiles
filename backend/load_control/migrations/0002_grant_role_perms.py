"""Give the role groups the Control de carga permissions on deploy.

Same shape `seed_role_groups` produces once `load_control` is in its
OPERATIONAL_MODELS: Editors (and Administrador) plan, readers see. Written as a
migration so a deploy does not depend on someone re-running the seed.
"""
from django.db import migrations

MODELS = ["microcycle", "microcycleday"]
EDITORS = ["Administrador", "Editor", "Editor Formativo"]
READERS = ["Solo Lectura", "Lectura Formativo"]


def grant(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    config = apps.get_app_config("load_control")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perms = Permission.objects.filter(content_type__app_label="load_control",
                                      content_type__model__in=MODELS)
    for name in EDITORS:
        group = Group.objects.filter(name=name).first()
        if group:
            group.permissions.add(*perms)
    view = perms.filter(codename__startswith="view_")
    for name in READERS:
        group = Group.objects.filter(name=name).first()
        if group:
            group.permissions.add(*view)


def revoke(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    perms = Permission.objects.filter(content_type__app_label="load_control",
                                      content_type__model__in=MODELS)
    for group in Group.objects.filter(name__in=EDITORS + READERS):
        group.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("load_control", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
