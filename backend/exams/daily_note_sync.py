"""Daily meeting notes → the department's "Notas diarias" exam.

The morning meeting (`/daily`) writes `core.DailyNote`s; each department also
has a "Notas diarias" exam (`seed_daily_notes`). Two stores for the same kind
of thing meant a physio's note from the Daily never appeared in the Médico
tab, the player's timeline, or the notes history — and a note typed in the
tab never reached the meeting.

The link is ONE-WAY and the Daily is the source: every "Pauta del día" note
tagged with an área is mirrored as one `ExamResult` of that área's "Notas
diarias" — fecha = meeting day, asunto = "Daily · Pauta del día", nota = the
text — and follows the note when it is edited, re-tagged or deleted. The
mirror is found by `result_data["daily_note_id"]`, never by content.

Not mirrored, on purpose:

* **General notes** (no área): there is no department to file them under.
  They are 158 of the first 228 pautas, so they stay a Daily-only thing.
* **Plan de trabajo**: medium-term guidance, not a daily note.

An edit made to the mirror from the department tab is overwritten the next
time the Daily note changes — the Daily owns it.
"""
from __future__ import annotations

from datetime import datetime, time

from django.utils import timezone

ORIGEN = "daily"
ASUNTO = "Daily · Pauta del día"


def _template_for(note):
    from exams.models import ExamTemplate

    if note.kind != note.KIND_PAUTA or note.department_id is None:
        return None
    slug = f"notas_diarias_{note.department.slug.replace('-', '_')}"
    return ExamTemplate.objects.filter(
        department_id=note.department_id, slug=slug, is_active_version=True,
    ).first()


def _mirror(note):
    from exams.models import ExamResult

    return ExamResult.objects.filter(result_data__daily_note_id=str(note.pk)).first()


def _autor(note) -> str:
    u = note.created_by
    if u is None:
        return ""
    return (u.get_full_name() or u.username).strip()


def sync(note) -> str:
    """Create, update or remove the mirror of one note. Returns what it did."""
    from exams.models import ExamResult

    template = _template_for(note)
    existente = _mirror(note)

    if template is None:
        if existente is not None:
            existente.delete()
            return "borrada"
        return "sin_espejo"

    datos = {
        "fecha": note.date.isoformat(),
        "asunto": ASUNTO,
        "nota": note.text,
        "origen": ORIGEN,
        "daily_note_id": str(note.pk),
        "autor": _autor(note),
    }
    cuando = timezone.make_aware(datetime.combine(note.date, time(12, 0)))

    # Re-tagged to another área: the mirror moves to that área's template.
    if existente is not None and existente.template_id != template.pk:
        existente.delete()
        existente = None

    if existente is None:
        ExamResult.objects.create(player_id=note.player_id, template=template,
                                  recorded_at=cuando, result_data=datos, inputs_snapshot={})
        return "creada"
    if existente.result_data == datos and existente.recorded_at == cuando:
        return "igual"
    existente.result_data = datos
    existente.recorded_at = cuando
    existente.save(update_fields=["result_data", "recorded_at"])
    return "actualizada"


def delete_for(note) -> None:
    from exams.models import ExamResult

    ExamResult.objects.filter(result_data__daily_note_id=str(note.pk)).delete()
