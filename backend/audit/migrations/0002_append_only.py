"""The audit logs are append-only at the database level.

A trigger rejects UPDATE and DELETE on both tables, whoever runs them (the
app, the Django admin, a psql session with the app's user). TRUNCATE is not a
row operation and stays possible for the test runner; it is not used by the
app. Lifting this requires dropping the trigger by hand, on purpose.
"""
from django.db import migrations

TABLES = ["audit_changeevent", "audit_accessevent"]

FORWARD = """
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'El registro de auditoría no se puede modificar ni borrar (%).', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
""" + "".join(f"""
CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t}
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();
""" for t in TABLES)

REVERSE = "".join(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};\n" for t in TABLES) + \
    "DROP FUNCTION IF EXISTS audit_append_only();\n"


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
