import uuid

from django.contrib.postgres.indexes import GinIndex
from django.db import models

from core.models import Category, Department, Player


def default_input_config() -> dict:
    """Default `input_config` for new templates: single-player only, no modifiers."""
    return {
        "input_modes": ["single"],
        "default_input_mode": "single",
        "modifiers": {"prefill_from_last": False},
    }


class ExamTemplate(models.Model):
    """Configuration-driven exam definition.

    config_schema follows the structure described in PROJECT.md, e.g.:
        {"fields": [{"key": "...", "label": "...", "type": "...", "chart_type": "..."}]}

    input_config controls how staff submit data for this template:
        {
          "input_modes": ["single", "team_table", "quick_list", "bulk_ingest"],
          "default_input_mode": "single",
          "modifiers": {"prefill_from_last": false},

          # Only meaningful when "bulk_ingest" is enabled. Tells the parser
          # how to translate a spreadsheet's columns into the template's
          # `result_data` shape.
          "column_mapping": {
            "player_lookup": {
              "column": "Players",            # spreadsheet column to look players up by
              "kind": "alias"                 # "name" | "alias" | "external_id"
              # "source": "catapult"          # required only when kind == "external_id"
            },
            "session_label": {                # optional — column whose value labels the session/match
              "column": "Sessions"
            },
            "segment": {                      # optional — when present, multiple rows per
              "column": "Tasks",              # player are collapsed into one ExamResult and
              "values": {                     # field keys are pattern-substituted per segment
                "Primer Tiempo": "p1",
                "Segundo Tiempo": "p2"
              }
            },
            "field_map": {
              # Per-segment fields: pattern-substituted using `segment.values[row]`.
              "Tot Dist (m)": {"template_key_pattern": "tot_dist_{segment}"},
              # Cross-segment fields: collapsed via `reduce` (max | min | sum | avg | last).
              "Max Vel (km/h)": {"template_key": "max_vel", "reduce": "max"}
            }
          }
        }
    """

    MODE_SINGLE = "single"
    MODE_TEAM_TABLE = "team_table"
    MODE_QUICK_LIST = "quick_list"
    MODE_BULK_INGEST = "bulk_ingest"
    INPUT_MODE_CHOICES = [
        (MODE_SINGLE, "Single player"),
        (MODE_TEAM_TABLE, "Team table"),
        (MODE_QUICK_LIST, "Quick list (categorical roster)"),
        (MODE_BULK_INGEST, "Bulk ingest (paste / file upload)"),
    ]
    INPUT_MODE_VALUES = {value for value, _label in INPUT_MODE_CHOICES}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="exam_templates"
    )
    applicable_categories = models.ManyToManyField(Category, related_name="exam_templates")
    config_schema = models.JSONField(default=dict)
    input_config = models.JSONField(
        default=default_input_config,
        help_text=(
            "Controls how staff submit data for this template. "
            "See model docstring for the schema."
        ),
    )
    version = models.PositiveIntegerField(default=1)
    is_locked = models.BooleanField(
        default=False,
        help_text="Once results exist, the template is locked. New changes spawn a new version.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [GinIndex(fields=["config_schema"])]

    def clean(self):
        """Validate input_config has the right shape and references known modes."""
        from django.core.exceptions import ValidationError

        cfg = self.input_config or {}
        modes = cfg.get("input_modes", [])
        if not isinstance(modes, list) or not modes:
            raise ValidationError({"input_config": "'input_modes' must be a non-empty list."})
        unknown = [m for m in modes if m not in self.INPUT_MODE_VALUES]
        if unknown:
            raise ValidationError(
                {"input_config": f"Unknown input mode(s): {', '.join(unknown)}."}
            )
        default_mode = cfg.get("default_input_mode")
        if default_mode and default_mode not in modes:
            raise ValidationError(
                {"input_config": f"'default_input_mode' ({default_mode}) must be one of input_modes."}
            )
        if self.MODE_BULK_INGEST in modes:
            self._validate_column_mapping(cfg.get("column_mapping"))

    def _validate_column_mapping(self, mapping):
        """Light shape validation for the bulk_ingest column mapping.

        Cross-validation of field keys against `config_schema.fields` happens
        in the ingest endpoint; here we only catch obvious shape errors.
        """
        from django.core.exceptions import ValidationError

        if mapping in (None, {}):
            # Allow incremental config — admin can save the template before
            # they finish wiring the file mapping.
            return
        if not isinstance(mapping, dict):
            raise ValidationError({"input_config": "'column_mapping' must be an object."})

        lookup = mapping.get("player_lookup")
        if not isinstance(lookup, dict) or not lookup.get("column") or not lookup.get("kind"):
            raise ValidationError(
                {"input_config": "'column_mapping.player_lookup' must be an object with 'column' and 'kind'."}
            )
        if lookup["kind"] not in {"name", "alias", "external_id"}:
            raise ValidationError(
                {"input_config": f"'player_lookup.kind' must be one of name|alias|external_id, got {lookup['kind']!r}."}
            )

        segment = mapping.get("segment")
        if segment is not None:
            if not isinstance(segment, dict) or not segment.get("column") or not isinstance(segment.get("values"), dict):
                raise ValidationError(
                    {"input_config": "'column_mapping.segment' must have 'column' and a 'values' object."}
                )

        field_map = mapping.get("field_map")
        if not isinstance(field_map, dict) or not field_map:
            raise ValidationError(
                {"input_config": "'column_mapping.field_map' must be a non-empty object."}
            )
        for col, spec in field_map.items():
            if not isinstance(spec, dict):
                raise ValidationError(
                    {"input_config": f"'field_map[{col!r}]' must be an object."}
                )
            has_pattern = "template_key_pattern" in spec
            has_key = "template_key" in spec
            if has_pattern == has_key:  # exactly one must be set
                raise ValidationError(
                    {"input_config": f"'field_map[{col!r}]' must set exactly one of 'template_key_pattern' or 'template_key'."}
                )
            if has_pattern and segment is None:
                raise ValidationError(
                    {"input_config": f"'field_map[{col!r}]' uses a segmented pattern but no 'segment' is configured."}
                )
            reduce_mode = spec.get("reduce")
            if reduce_mode is not None and reduce_mode not in {"max", "min", "sum", "avg", "last"}:
                raise ValidationError(
                    {"input_config": f"'field_map[{col!r}].reduce' must be one of max|min|sum|avg|last."}
                )

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.department})"

    # ---- Authoring sync helpers ----------------------------------------------
    # The canonical runtime source is `config_schema["fields"]` (a JSON list).
    # When admins edit through the inline they edit `template_fields` rows,
    # which then get dumped back into `config_schema["fields"]`. The inverse
    # direction (JSON → rows) is used to backfill rows after a seed command,
    # or whenever the JSON was edited outside the admin.

    def regenerate_config_schema_from_fields(self):
        """Dump the related TemplateField rows into `config_schema["fields"]`."""
        rows = list(self.template_fields.all().order_by("sort_order", "key"))
        schema = dict(self.config_schema or {})
        schema["fields"] = [row.to_schema_dict() for row in rows]
        self.config_schema = schema
        self.save(update_fields=["config_schema", "updated_at"])

    def rebuild_template_fields(self):
        """Recreate TemplateField rows to match `config_schema["fields"]`.

        Idempotent: replaces all existing rows. Use when JSON was written by
        a seed command or external script and the rows need to be rebuilt.
        """
        from django.db import transaction

        fields = (self.config_schema or {}).get("fields") or []

        with transaction.atomic():
            self.template_fields.all().delete()
            objs = []
            for idx, raw in enumerate(fields):
                if not isinstance(raw, dict):
                    continue
                ftype = raw.get("type") or TemplateField.TYPE_NUMBER
                objs.append(TemplateField(
                    template=self,
                    sort_order=idx,
                    key=raw.get("key", f"field_{idx}"),
                    label=raw.get("label", raw.get("key", f"Campo {idx + 1}")),
                    type=ftype,
                    unit=raw.get("unit", "") or "",
                    group=raw.get("group", "") or "",
                    options=raw.get("options") or [],
                    formula=raw.get("formula", "") or "",
                    chart_type=raw.get("chart_type", "") or "",
                    required=bool(raw.get("required")),
                    multiline=bool(raw.get("multiline")),
                    rows=raw.get("rows"),
                    placeholder=raw.get("placeholder", "") or "",
                ))
            TemplateField.objects.bulk_create(objs)


class TemplateField(models.Model):
    """Structured authoring rows for `ExamTemplate.config_schema['fields']`.

    The JSONB blob on the template stays the canonical runtime source — every
    reader (formula engine, frontend, bulk ingest) keeps reading from it. These
    rows exist so Django Admin can offer real inline forms instead of asking
    non-technical staff to type JSON. Saving rows in admin regenerates the
    parent's config_schema from this related set.

    Going JSON → rows: run `python manage.py sync_template_fields` after a seed
    command, or call `ExamTemplate.rebuild_template_fields()` from a shell.
    """

    TYPE_NUMBER = "number"
    TYPE_TEXT = "text"
    TYPE_CATEGORICAL = "categorical"
    TYPE_CALCULATED = "calculated"
    TYPE_BOOLEAN = "boolean"
    TYPE_DATE = "date"
    TYPE_CHOICES = [
        (TYPE_NUMBER, "Número"),
        (TYPE_TEXT, "Texto"),
        (TYPE_CATEGORICAL, "Categórico (lista)"),
        (TYPE_CALCULATED, "Calculado (fórmula)"),
        (TYPE_BOOLEAN, "Sí/No"),
        (TYPE_DATE, "Fecha"),
    ]

    CHART_TYPE_CHOICES = [
        ("", "Ninguno"),
        ("line", "Línea"),
        ("stat_card", "Tarjeta de estadística"),
        ("body_map", "Mapa corporal"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        "exams.ExamTemplate",
        on_delete=models.CASCADE,
        related_name="template_fields",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Determina el orden en el formulario y el reporte.",
    )

    key = models.CharField(
        max_length=64,
        help_text="Identificador interno (slug). Solo letras, números y guión bajo. "
                  "Una vez que el template tiene resultados, no debería cambiar.",
    )
    label = models.CharField(max_length=140, help_text="Etiqueta visible para el staff.")
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_NUMBER)

    unit = models.CharField(max_length=24, blank=True, help_text="Ej. kg, cm, min, m/min.")
    group = models.CharField(
        max_length=80, blank=True,
        help_text="Sección lógica en el formulario (ej. 'Datos básicos', 'Distancia').",
    )

    options = models.JSONField(
        default=list, blank=True,
        help_text="Solo para tipo categórico. Lista de strings, una opción por elemento.",
    )
    formula = models.TextField(
        blank=True,
        help_text="Solo para tipo calculado. Ej. [peso] / (([talla] / 100) ** 2).",
    )

    chart_type = models.CharField(
        max_length=32, choices=CHART_TYPE_CHOICES, blank=True, default="",
        help_text="Visualización por defecto para este campo en las tarjetas de resumen.",
    )
    required = models.BooleanField(default=False)
    multiline = models.BooleanField(
        default=False,
        help_text="Solo para texto. Renderiza un cuadro de texto multi-línea.",
    )
    rows = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Solo para texto multi-línea. Cantidad de filas visibles.",
    )
    placeholder = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("sort_order", "key")
        unique_together = [("template", "key")]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.type == self.TYPE_CATEGORICAL:
            if not isinstance(self.options, list) or not self.options:
                raise ValidationError(
                    {"options": "Los campos categóricos requieren al menos una opción."}
                )
        if self.type == self.TYPE_CALCULATED and not (self.formula or "").strip():
            raise ValidationError({"formula": "Los campos calculados requieren una fórmula."})
        if self.multiline and self.type != self.TYPE_TEXT:
            raise ValidationError({"multiline": "Multi-línea solo aplica a campos de texto."})

    def to_schema_dict(self) -> dict:
        """Serialize this row back into the JSON shape stored in config_schema['fields']."""
        out: dict = {"key": self.key, "label": self.label, "type": self.type}
        if self.unit:
            out["unit"] = self.unit
        if self.group:
            out["group"] = self.group
        if self.type == self.TYPE_CATEGORICAL and self.options:
            out["options"] = list(self.options)
        if self.type == self.TYPE_CALCULATED and self.formula:
            out["formula"] = self.formula
        if self.chart_type:
            out["chart_type"] = self.chart_type
        if self.required:
            out["required"] = True
        if self.type == self.TYPE_TEXT and self.multiline:
            out["multiline"] = True
            if self.rows:
                out["rows"] = self.rows
        if self.placeholder:
            out["placeholder"] = self.placeholder
        return out

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"


class ExamResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="exam_results")
    template = models.ForeignKey(ExamTemplate, on_delete=models.PROTECT, related_name="results")
    recorded_at = models.DateTimeField()
    result_data = models.JSONField(default=dict)
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="exam_results",
        help_text="Optional link to a calendar event (e.g. the match this GPS export came from).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            GinIndex(fields=["result_data"]),
            models.Index(fields=["player", "recorded_at"]),
            models.Index(fields=["event"]),
        ]
        ordering = ("-recorded_at",)

    def __str__(self) -> str:
        return f"{self.template.name} – {self.player} @ {self.recorded_at:%Y-%m-%d}"
