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
    slug = models.SlugField(
        max_length=80, blank=True, default="",
        help_text=(
            "Identificador estable usado en fórmulas para referenciar resultados "
            "de esta plantilla, ej. `[pentacompartimental.peso]`. Se autogenera "
            "del nombre si se deja en blanco. No puede ser 'player'."
        ),
    )
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
    # ---- Versioning ----
    # `family_id` groups all versions of a template together; the slug-uniqueness
    # rule + the registrar's "which template to write to?" lookup both rely on
    # exactly one version per family being marked `is_active_version=True`.
    # Reads (dashboards, history) fan out across the whole family by joining on
    # this field — see `aggregation._fetch_results` and `team_aggregation`.
    family_id = models.UUIDField(
        default=uuid.uuid4, editable=False,
        help_text="Shared by every version of the same template. Set by `fork_new_version`.",
    )
    version = models.PositiveIntegerField(default=1)
    is_active_version = models.BooleanField(
        default=True,
        help_text=(
            "Exactly one version per family is active. New ExamResults are written "
            "against the active version (resolved by slug); inactive versions stay "
            "for history but are hidden from the registrar's template picker."
        ),
    )
    is_locked = models.BooleanField(
        default=False,
        help_text="Once results exist, the template is locked. New changes spawn a new version.",
    )
    link_to_match = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, the data-entry form shows an 'Asociar partido' selector. "
            "The picked match becomes the authoritative timestamp (overrides "
            "recorded_at) and is FK-stored on every result. Applies to single, "
            "bulk-ingest, and team-table forms."
        ),
    )
    is_episodic = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, results on this template form linked Episodes. "
            "Each result either opens a new Episode or progresses an existing "
            "open one (via episode_id). The Episode auto-derives stage / "
            "status / title from the latest linked result, and the player's "
            "Player.status is recomputed from their open episodes."
        ),
    )
    show_injuries = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, the data-entry form for this template displays a "
            "panel listing the player's open injuries, with a button to add a "
            "new one without leaving the form. Useful for daily-notes / "
            "session-tracking templates where the doctor needs context on "
            "current injuries while filling unrelated data."
        ),
    )
    episode_config = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Episodic-template config. Required when is_episodic=True. "
            'Shape: {"stage_field": "stage", '
            '"open_stages": ["injured", "recovery", "reintegration"], '
            '"closed_stage": "closed", '
            '"title_template": "{type} — {body_part}"}. '
            "open_stages is ordered WORST → BEST."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            GinIndex(fields=["config_schema"]),
            models.Index(fields=["slug"]),
            # Lets the registrar resolve "active template for slug X" with a
            # single seek instead of scanning the family.
            models.Index(
                fields=["slug", "is_active_version"],
                name="exam_tpl_slug_active_idx",
            ),
        ]
        constraints = [
            # (family_id, version) must be unique — protects against accidental
            # double-fork from concurrent admin edits.
            models.UniqueConstraint(
                fields=["family_id", "version"],
                name="exam_tpl_family_version_unique",
            ),
            # Exactly one active version per family.
            models.UniqueConstraint(
                fields=["family_id"],
                condition=models.Q(is_active_version=True),
                name="exam_tpl_one_active_per_family",
            ),
        ]

    RESERVED_SLUGS = frozenset({"player"})

    def clean(self):
        """Validate input_config has the right shape and references known modes."""
        from django.core.exceptions import ValidationError
        from django.utils.text import slugify

        # Auto-derive slug from name if blank.
        if not self.slug and self.name:
            self.slug = slugify(self.name).replace("-", "_")[:80]
        if self.slug:
            if self.slug in self.RESERVED_SLUGS:
                raise ValidationError({"slug": f"'{self.slug}' is reserved and cannot be used."})
            # Must match identifier rules so it parses inside formula brackets.
            import re
            if not re.fullmatch(r"[a-z][a-z0-9_]*", self.slug):
                raise ValidationError(
                    {"slug": "Must be lowercase letters, digits and underscores; "
                             "must start with a letter."}
                )
            # Club-wide uniqueness — but only against OTHER active versions.
            # Old versions in the same family keep their slug; the constraint
            # only kicks in for distinct families competing for the same slug.
            # Also restrict the check to active-vs-active so a brand-new
            # template doesn't conflict with retired versions of an unrelated
            # template (rare but possible after a chain of forks).
            if self.department_id and self.is_active_version:
                conflict = (
                    ExamTemplate.objects
                    .filter(
                        slug=self.slug,
                        department__club=self.department.club,
                        is_active_version=True,
                    )
                    .exclude(pk=self.pk)
                    .exclude(family_id=self.family_id)  # same family ≠ conflict
                    .first()
                )
                if conflict:
                    raise ValidationError(
                        {"slug": f"Slug '{self.slug}' is already used by template "
                                 f"'{conflict.name}' in this club."}
                    )

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
        if self.MODE_TEAM_TABLE in modes:
            self._validate_team_table(cfg.get("team_table"))

        # Episodic templates require a usable episode_config.
        if self.is_episodic:
            self._validate_episode_config()

    def _validate_episode_config(self):
        from django.core.exceptions import ValidationError

        cfg = self.episode_config or {}
        if not isinstance(cfg, dict):
            raise ValidationError({"episode_config": "Must be an object."})
        stage_field = cfg.get("stage_field")
        if not isinstance(stage_field, str) or not stage_field.strip():
            raise ValidationError(
                {"episode_config": "'stage_field' is required (the field key carrying the stage)."}
            )
        open_stages = cfg.get("open_stages")
        if (not isinstance(open_stages, list) or not open_stages
                or any(not isinstance(s, str) for s in open_stages)):
            raise ValidationError(
                {"episode_config": "'open_stages' must be a non-empty list of strings (worst→best)."}
            )
        closed_stage = cfg.get("closed_stage")
        if not isinstance(closed_stage, str) or not closed_stage.strip():
            raise ValidationError(
                {"episode_config": "'closed_stage' is required."}
            )
        if closed_stage in open_stages:
            raise ValidationError(
                {"episode_config": "'closed_stage' must NOT be in 'open_stages'."}
            )

        # If the schema is already populated, validate stage_field references
        # exist and that the stage values declared overlap with the field's
        # categorical options.
        schema_fields = (self.config_schema or {}).get("fields") or []
        if schema_fields:
            target = next(
                (f for f in schema_fields
                 if isinstance(f, dict) and f.get("key") == stage_field),
                None,
            )
            if target is None:
                valid = sorted(
                    f.get("key") for f in schema_fields
                    if isinstance(f, dict) and f.get("key")
                )
                raise ValidationError({
                    "episode_config": (
                        f"stage_field '{stage_field}' not found in template fields. "
                        f"Available: {', '.join(valid)}"
                    )
                })
            if target.get("type") not in {"categorical", "text"}:
                raise ValidationError({
                    "episode_config": (
                        f"stage_field '{stage_field}' must be categorical or text "
                        f"(got '{target.get('type')}')."
                    )
                })

    def _validate_team_table(self, cfg):
        """Light shape validation for the team_table config block.

        team_table = {
            "shared_fields": ["fecha"],   # asked once at the top of the form
            "row_fields":   ["valor"],    # one column per — defaults to all
                                          # non-shared, non-calculated keys
            "include_inactive": false
        }
        """
        from django.core.exceptions import ValidationError

        if cfg is None:
            return  # All fields default to row_fields automatically.
        if not isinstance(cfg, dict):
            raise ValidationError({"input_config": "'team_table' must be an object."})

        all_keys = {
            f.get("key")
            for f in (self.config_schema or {}).get("fields", [])
            if isinstance(f, dict) and f.get("key")
        }
        calculated_keys = {
            f.get("key")
            for f in (self.config_schema or {}).get("fields", [])
            if isinstance(f, dict) and f.get("type") == "calculated" and f.get("key")
        }

        shared = cfg.get("shared_fields") or []
        rows = cfg.get("row_fields") or []
        if not isinstance(shared, list) or not isinstance(rows, list):
            raise ValidationError(
                {"input_config": "'team_table.shared_fields' and 'row_fields' must be lists."}
            )

        unknown_shared = [k for k in shared if k not in all_keys]
        unknown_rows = [k for k in rows if k not in all_keys]
        if unknown_shared:
            raise ValidationError(
                {"input_config": f"team_table.shared_fields references unknown key(s): {', '.join(unknown_shared)}."}
            )
        if unknown_rows:
            raise ValidationError(
                {"input_config": f"team_table.row_fields references unknown key(s): {', '.join(unknown_rows)}."}
            )

        bad_calc_shared = [k for k in shared if k in calculated_keys]
        if bad_calc_shared:
            raise ValidationError(
                {"input_config": f"team_table.shared_fields cannot include calculated field(s): {', '.join(bad_calc_shared)}."}
            )

        overlap = set(shared) & set(rows)
        if overlap:
            raise ValidationError(
                {"input_config": f"Field(s) cannot be in both shared_fields and row_fields: {', '.join(sorted(overlap))}."}
            )

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

    def save(self, *args, **kwargs):
        # Keep input_config.allow_event_link mirrored from the model field so
        # frontend reads stay backwards-compatible. Model field is canonical.
        cfg = dict(self.input_config or {})
        if cfg.get("allow_event_link") != bool(self.link_to_match):
            cfg["allow_event_link"] = bool(self.link_to_match)
            self.input_config = cfg
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "input_config" not in update_fields:
                kwargs["update_fields"] = list(update_fields) + ["input_config"]
        # Auto-derive slug from name when missing (e.g. programmatic creation
        # via seed commands that bypass full_clean).
        if not self.slug and self.name:
            from django.utils.text import slugify
            self.slug = slugify(self.name).replace("-", "_")[:80] or "template"
        # Every brand-new template starts a fresh family. The field default
        # already gives us a UUID; we only need to ensure programmatic
        # creations that explicitly pass `family_id=None` (no callers do
        # today but be defensive) get a fresh one.
        if self.family_id is None:
            self.family_id = uuid.uuid4()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} v{self.version} ({self.department})"

    # ---- Versioning -------------------------------------------------------
    def fork_new_version(self) -> "ExamTemplate":
        """Clone this template into v+1 and make the clone the active version.

        Copies the runtime schema (`config_schema`, `input_config`,
        `episode_config`), the structured `TemplateField` rows, the
        `applicable_categories` M2M, and reassigns every WidgetDataSource +
        TeamReportWidgetDataSource pointing at this version to the new one.
        The old version stays in the DB, no longer active — historical
        `ExamResult` rows continue to point at it.

        The clone starts UNLOCKED so the admin can edit its schema; it
        re-locks itself on the first ExamResult save (same auto-lock signal
        that gates the original).

        Returns the new ExamTemplate instance.
        """
        from django.db import transaction

        with transaction.atomic():
            # Step 1: create the v+1 row. Take family_id from self so both
            # versions share it.
            new_version = ExamTemplate.objects.create(
                name=self.name,
                slug=self.slug,
                department=self.department,
                config_schema=dict(self.config_schema or {}),
                input_config=dict(self.input_config or {}),
                family_id=self.family_id,
                version=self.version + 1,
                is_active_version=False,  # flip later, after old is deactivated
                is_locked=False,
                link_to_match=self.link_to_match,
                is_episodic=self.is_episodic,
                show_injuries=self.show_injuries,
                episode_config=dict(self.episode_config or {}),
            )

            # Step 2: copy TemplateField rows. Bulk-create for speed; we
            # already have the schema in JSON form so `rebuild_template_fields`
            # would be redundant.
            field_rows = list(self.template_fields.all().order_by("sort_order", "key"))
            TemplateField.objects.bulk_create([
                TemplateField(
                    template=new_version,
                    sort_order=row.sort_order,
                    key=row.key,
                    label=row.label,
                    type=row.type,
                    unit=row.unit,
                    group=row.group,
                    options=list(row.options or []),
                    option_labels=dict(row.option_labels or {}),
                    option_regions=dict(row.option_regions or {}),
                    formula=row.formula,
                    chart_type=row.chart_type,
                    required=row.required,
                    multiline=row.multiline,
                    rows=row.rows,
                    placeholder=row.placeholder,
                    direction_of_good=row.direction_of_good,
                    reference_ranges=list(row.reference_ranges or []),
                    writes_to_player_field=row.writes_to_player_field,
                )
                for row in field_rows
            ])

            # Step 3: copy the applicable_categories M2M.
            new_version.applicable_categories.set(self.applicable_categories.all())

            # Step 4: hand off data sources from old → new so dashboards keep
            # working. WidgetDataSource is for per-player layouts;
            # TeamReportWidgetDataSource is the team-report mirror. Lazy
            # imports — the dashboards app is a downstream consumer of
            # ExamTemplate and we want to avoid a cycle at module load.
            from dashboards.models import (  # noqa: WPS433
                TeamReportWidgetDataSource, WidgetDataSource,
            )
            WidgetDataSource.objects.filter(template=self).update(template=new_version)
            TeamReportWidgetDataSource.objects.filter(template=self).update(
                template=new_version,
            )

            # Step 5: flip the active flags atomically — old → inactive,
            # new → active. Order matters because of the partial-unique
            # constraint on (family_id) where is_active_version=True.
            ExamTemplate.objects.filter(pk=self.pk).update(is_active_version=False)
            ExamTemplate.objects.filter(pk=new_version.pk).update(is_active_version=True)
            new_version.refresh_from_db()

        return new_version

    @classmethod
    def active_for_slug(
        cls, *, slug: str, department_id=None, club_id=None,
    ):
        """Resolve the active version for `slug` scoped by department or club.

        Used by the registrar and seed commands so writes always target the
        current version even when forks have happened in between.
        """
        qs = cls.objects.filter(slug=slug, is_active_version=True)
        if department_id is not None:
            qs = qs.filter(department_id=department_id)
        if club_id is not None:
            qs = qs.filter(department__club_id=club_id)
        return qs.first()

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
                    option_labels=raw.get("option_labels") or {},
                    option_regions=raw.get("option_regions") or {},
                    formula=raw.get("formula", "") or "",
                    chart_type=raw.get("chart_type", "") or "",
                    required=bool(raw.get("required")),
                    multiline=bool(raw.get("multiline")),
                    rows=raw.get("rows"),
                    placeholder=raw.get("placeholder", "") or "",
                    direction_of_good=raw.get("direction_of_good", "") or TemplateField.DIRECTION_NEUTRAL,
                    reference_ranges=raw.get("reference_ranges") or [],
                    writes_to_player_field=raw.get("writes_to_player_field", "") or "",
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
    TYPE_FILE = "file"
    TYPE_CHOICES = [
        (TYPE_NUMBER, "Número"),
        (TYPE_TEXT, "Texto"),
        (TYPE_CATEGORICAL, "Categórico (lista)"),
        (TYPE_CALCULATED, "Calculado (fórmula)"),
        (TYPE_BOOLEAN, "Sí/No"),
        (TYPE_DATE, "Fecha"),
        (TYPE_FILE, "Archivo (uno o varios)"),
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
    option_labels = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Solo para tipo categórico. Diccionario opcional que asocia cada "
            "valor de `options` con la etiqueta visible en el formulario "
            "(ej. {\"injured\": \"Lesionado\"}). Si está vacío o falta una "
            "clave, se muestra el valor tal cual."
        ),
    )
    option_regions = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Solo para tipo categórico. Diccionario opcional que asocia cada "
            "valor de `options` con una región del cuerpo (head, neck, "
            "chest, abdomen, pelvis, left_shoulder, right_shoulder, left_arm, "
            "right_arm, left_forearm, right_forearm, left_hand, right_hand, "
            "left_thigh, right_thigh, left_knee, right_knee, left_calf, "
            "right_calf, left_foot, right_foot). Lo usa el widget "
            "`body_map_heatmap` para colorear regiones según cuántos "
            "resultados las mencionan."
        ),
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

    # Direction-of-good for numeric / calculated fields. Tells the frontend
    # which way deltas should be colored green vs red on widgets like
    # `team_roster_matrix`. `up` = higher is better (e.g. CMJ); `down` =
    # lower is better (e.g. CK, resting HR); `neutral` (default) keeps the
    # current blue/orange neutral palette — used when the metric has no
    # obvious clinical direction (e.g. body composition that depends on
    # role, position-specific norms, etc.).
    DIRECTION_NEUTRAL = "neutral"
    DIRECTION_UP = "up"
    DIRECTION_DOWN = "down"
    DIRECTION_CHOICES = [
        (DIRECTION_NEUTRAL, "Neutro (sin opinión)"),
        (DIRECTION_UP, "Más es mejor (verde si sube)"),
        (DIRECTION_DOWN, "Menos es mejor (verde si baja)"),
    ]
    direction_of_good = models.CharField(
        max_length=10, choices=DIRECTION_CHOICES,
        blank=True, default=DIRECTION_NEUTRAL,
        help_text=(
            "Para campos numéricos/calculados. Define cómo colorear los "
            "deltas de variación en widgets como Roster Matrix: 'up' pinta "
            "verde un alza y rojo una baja; 'down' invierte; 'neutral' "
            "mantiene el paleta azul/naranja sin juicio."
        ),
    )

    # Reference bands for numeric/calculated fields. Each band is
    # {"label": str, "min": float?, "max": float?, "color": str?}.
    # At least one of `min` / `max` must be set per band; bands must be
    # ordered and disjoint (validated in `clean()`). Drives:
    #   - Compact + dynamic hint under the form input.
    #   - Cell border coloring on `team_roster_matrix` + `comparison_table`.
    # When empty, no hint is shown and widgets keep their default coloring.
    reference_ranges = models.JSONField(
        default=list, blank=True,
        help_text=(
            "Bandas de referencia clínica para campos numéricos. Lista de "
            "objetos: {\"label\": \"Normal\", \"min\": 30, \"max\": 200, "
            "\"color\": \"#16a34a\"}. min y max son opcionales por banda "
            "(banda abierta a un lado), pero al menos uno debe estar. Las "
            "bandas deben ser disjuntas y ordenadas de menor a mayor. "
            "Ejemplo CK: [{\"label\":\"Bajo\",\"max\":30},"
            "{\"label\":\"Normal\",\"min\":30,\"max\":200},"
            "{\"label\":\"Elevado\",\"min\":200,\"max\":400},"
            "{\"label\":\"Severo\",\"min\":400}]"
        ),
    )

    # Player profile write-back. When set, saving an ExamResult that holds a
    # non-null value for this field will update the named Player attribute
    # (provided this result is the most recent for the (player, template)).
    PLAYER_FIELD_NONE = ""
    PLAYER_FIELD_WEIGHT = "current_weight_kg"
    PLAYER_FIELD_HEIGHT = "current_height_cm"
    PLAYER_FIELD_SEX = "sex"
    PLAYER_FIELD_CHOICES = [
        (PLAYER_FIELD_NONE, "—"),
        (PLAYER_FIELD_WEIGHT, "Player.current_weight_kg"),
        (PLAYER_FIELD_HEIGHT, "Player.current_height_cm"),
        (PLAYER_FIELD_SEX, "Player.sex"),
    ]
    writes_to_player_field = models.CharField(
        max_length=32, choices=PLAYER_FIELD_CHOICES, blank=True, default="",
        help_text=(
            "Cuando se guarda un resultado, se copia el valor de este campo "
            "al atributo del jugador (sólo si es el resultado más reciente "
            "para esta plantilla)."
        ),
    )

    class Meta:
        ordering = ("sort_order", "key")
        unique_together = [("template", "key")]

    def clean(self):
        from django.core.exceptions import ValidationError
        import re

        # Field keys must be safe identifiers (and dot-free) to play nicely
        # with the formula engine's namespace resolver.
        if self.key:
            if "." in self.key:
                raise ValidationError(
                    {"key": "Field keys cannot contain '.' (reserved for namespace syntax in formulas)."}
                )
            if self.key in {"player"}:
                raise ValidationError(
                    {"key": "'player' is a reserved name and cannot be used as a field key."}
                )
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", self.key):
                raise ValidationError(
                    {"key": "Field keys must be valid identifiers (letters, digits, underscores; must start with a letter or underscore)."}
                )

        if self.type == self.TYPE_CATEGORICAL:
            if not isinstance(self.options, list) or not self.options:
                raise ValidationError(
                    {"options": "Los campos categóricos requieren al menos una opción."}
                )
        if self.type == self.TYPE_CALCULATED and not (self.formula or "").strip():
            raise ValidationError({"formula": "Los campos calculados requieren una fórmula."})
        if self.multiline and self.type != self.TYPE_TEXT:
            raise ValidationError({"multiline": "Multi-línea solo aplica a campos de texto."})

        # Reference bands: numeric/calculated only, shape + ordering rules.
        if self.reference_ranges:
            if self.type not in {self.TYPE_NUMBER, self.TYPE_CALCULATED}:
                raise ValidationError({
                    "reference_ranges": (
                        "Las bandas de referencia solo aplican a campos "
                        "numéricos o calculados."
                    ),
                })
            self._validate_reference_ranges()

    def _validate_reference_ranges(self):
        """Check `reference_ranges` shape + ordering + disjointness.

        Each band needs a label and at least one bound. We allow at most
        one band open on each end (one with no `min`, one with no `max`)
        and require the closed-bound bands in between to chain without
        overlap or gap (the next band's min ≥ previous band's max).
        """
        from django.core.exceptions import ValidationError

        bands = self.reference_ranges
        if not isinstance(bands, list):
            raise ValidationError({"reference_ranges": "Debe ser una lista de bandas."})

        normalized = []
        for i, band in enumerate(bands):
            if not isinstance(band, dict):
                raise ValidationError({
                    "reference_ranges": f"Banda #{i + 1}: debe ser un objeto.",
                })
            label = (band.get("label") or "").strip()
            if not label:
                raise ValidationError({
                    "reference_ranges": f"Banda #{i + 1}: 'label' es obligatorio.",
                })
            lo = band.get("min")
            hi = band.get("max")
            if lo is None and hi is None:
                raise ValidationError({
                    "reference_ranges": (
                        f"Banda '{label}': definí al menos uno de 'min' o 'max'."
                    ),
                })
            try:
                lo_f = float(lo) if lo is not None else None
                hi_f = float(hi) if hi is not None else None
            except (TypeError, ValueError):
                raise ValidationError({
                    "reference_ranges": (
                        f"Banda '{label}': 'min' y 'max' deben ser numéricos."
                    ),
                })
            if lo_f is not None and hi_f is not None and lo_f >= hi_f:
                raise ValidationError({
                    "reference_ranges": (
                        f"Banda '{label}': 'min' ({lo_f}) debe ser menor que 'max' ({hi_f})."
                    ),
                })
            normalized.append((label, lo_f, hi_f))

        # Ordering + disjointness. Sort by effective lower bound (None
        # treated as -infinity), then walk pairs.
        ordered = sorted(
            normalized,
            key=lambda b: float("-inf") if b[1] is None else b[1],
        )
        for prev, curr in zip(ordered, ordered[1:]):
            prev_max = prev[2]
            curr_min = curr[1]
            if prev_max is None or curr_min is None:
                raise ValidationError({
                    "reference_ranges": (
                        f"Bandas '{prev[0]}' y '{curr[0]}': solo una banda puede "
                        "quedar abierta en cada extremo (la más baja sin 'min', "
                        "la más alta sin 'max'). El resto debe tener ambos límites."
                    ),
                })
            if curr_min < prev_max:
                raise ValidationError({
                    "reference_ranges": (
                        f"Bandas '{prev[0]}' y '{curr[0]}' se solapan "
                        f"(prev.max={prev_max} > curr.min={curr_min})."
                    ),
                })

    def to_schema_dict(self) -> dict:
        """Serialize this row back into the JSON shape stored in config_schema['fields']."""
        out: dict = {"key": self.key, "label": self.label, "type": self.type}
        if self.unit:
            out["unit"] = self.unit
        if self.group:
            out["group"] = self.group
        if self.type == self.TYPE_CATEGORICAL and self.options:
            out["options"] = list(self.options)
            if self.option_labels:
                out["option_labels"] = dict(self.option_labels)
            if self.option_regions:
                out["option_regions"] = dict(self.option_regions)
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
        if self.direction_of_good and self.direction_of_good != self.DIRECTION_NEUTRAL:
            out["direction_of_good"] = self.direction_of_good
        if self.reference_ranges:
            out["reference_ranges"] = list(self.reference_ranges)
        if self.writes_to_player_field:
            out["writes_to_player_field"] = self.writes_to_player_field
        return out

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"


class ExamResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="exam_results")
    template = models.ForeignKey(ExamTemplate, on_delete=models.PROTECT, related_name="results")
    recorded_at = models.DateTimeField()
    result_data = models.JSONField(default=dict)
    # Audit-of-record: every external value (`player.X`, `<slug>.Y`) read by
    # this result's calculated fields, captured at the moment of evaluation.
    # Empty dict when no namespace references were used. Older rows backfilled
    # to {} via migration. See exams.calculations.compute_result_data().
    inputs_snapshot = models.JSONField(default=dict, blank=True)
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="exam_results",
        help_text="Optional link to a calendar event (e.g. the match this GPS export came from).",
    )
    episode = models.ForeignKey(
        "exams.Episode",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="results",
        help_text=(
            "Set when the result is part of an episodic template's lifecycle. "
            "PROTECT prevents accidental episode deletion while results exist."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            GinIndex(fields=["result_data"]),
            models.Index(fields=["player", "recorded_at"]),
            models.Index(fields=["event"]),
            models.Index(fields=["episode"]),
        ]
        ordering = ("-recorded_at",)

    def clean(self) -> None:
        """Enforce `template.link_to_match` — if the template requires a
        match link, every result MUST point at an Event. Caught at
        `full_clean()` (admin save, API serializers) and at signal-time
        in `events/services` writers. We don't add a DB-level constraint
        because legacy data exists without events; the validator is the
        single point of truth and the backfill command brings old rows
        into compliance over time.
        """
        from django.core.exceptions import ValidationError

        super().clean()
        if (
            self.template_id
            and getattr(self.template, "link_to_match", False)
            and self.event_id is None
        ):
            raise ValidationError({
                "event": (
                    f"La plantilla '{self.template.name}' requiere vincular "
                    "el resultado a un Evento (partido). Selecciona el "
                    "partido al que pertenece esta carga."
                ),
            })

    def __str__(self) -> str:
        return f"{self.template.name} – {self.player} @ {self.recorded_at:%Y-%m-%d}"


class Episode(models.Model):
    """A clinical episode tying a sequence of ExamResults together.

    Used by templates with `is_episodic=True` (e.g. injuries, surgeries,
    concussion protocols). Each ExamResult on the template links to an
    Episode; the Episode auto-derives `stage`, `status`, `title`, and
    `ended_at` from the latest linked result via post-save signal.

    Player.status is recomputed from open episodes (worst stage wins).
    """

    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Abierto"),
        (STATUS_CLOSED, "Cerrado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    player = models.ForeignKey(
        "core.Player", on_delete=models.CASCADE, related_name="episodes",
    )
    template = models.ForeignKey(
        ExamTemplate, on_delete=models.PROTECT, related_name="episodes",
    )
    status = models.CharField(
        max_length=8, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    )
    stage = models.CharField(
        max_length=40, blank=True,
        help_text="Free-form per template; populated by signal from latest result's stage_field.",
    )
    title = models.CharField(
        max_length=200, blank=True,
        help_text="Human-readable summary (auto-derived from latest result via title_template).",
    )
    started_at = models.DateTimeField(
        help_text="When the first linked result was recorded.",
    )
    ended_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when the episode transitions to 'closed' (= recorded_at of the closing result).",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_episodes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["player", "status"]),
            models.Index(fields=["template", "status"]),
        ]

    def __str__(self) -> str:
        scope = self.title or self.stage or "(sin título)"
        return f"[{self.get_status_display()}] {self.player} · {scope}"
