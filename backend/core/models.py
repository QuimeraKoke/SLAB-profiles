import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Club(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Department(models.Model):
    """Departments are defined once per club (Medical, Physical, Nutritional, ...).

    Categories opt in to the departments they actually run, so the U-8 roster
    doesn't see exam templates designed for the First Team's sports-science staff.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)

    class Meta:
        unique_together = [("club", "name"), ("club", "slug")]
        ordering = ("name",)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.club.name} – {self.name}"


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=80)
    departments = models.ManyToManyField(
        Department,
        related_name="categories",
        blank=True,
        help_text="Departments active for this category. Must belong to the same club.",
    )

    class Meta:
        unique_together = ("club", "name")
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return f"{self.club.name} – {self.name}"


class Position(models.Model):
    """Soccer positions are defined per club so each team can use its own taxonomy."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="positions")
    name = models.CharField(max_length=80, help_text="e.g. 'Volante Interior'")
    abbreviation = models.CharField(max_length=8, help_text="e.g. 'MC'")
    role = models.CharField(
        max_length=40,
        blank=True,
        help_text="Optional grouping shown above the name, e.g. 'Mediocampista'.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("club", "abbreviation"), ("club", "name")]
        ordering = ("sort_order", "abbreviation")

    def __str__(self) -> str:
        return f"{self.abbreviation} – {self.name}"


class StaffMembership(models.Model):
    """Scopes a Django user to one club and a subset of its categories/departments.

    A user without a StaffMembership (typically the platform admin) sees
    everything via the API. A user with a membership is filtered to their club,
    and within that club to the chosen categories and departments — unless the
    `all_categories` / `all_departments` flag is set, in which case the
    explicit M2M list is ignored.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_membership",
    )
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="memberships")

    all_categories = models.BooleanField(
        default=False,
        help_text="If checked, the user has access to every category in this club, "
        "including ones added later. The categories list below is ignored.",
    )
    categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name="staff_memberships",
        help_text="Specific categories the user has access to. Ignored if 'All categories' is checked.",
    )

    all_departments = models.BooleanField(
        default=False,
        help_text="If checked, the user has access to every department in this club, "
        "including ones added later. The departments list below is ignored.",
    )
    departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name="staff_memberships",
        help_text="Specific departments the user has access to. Ignored if 'All departments' is checked.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user} @ {self.club}"


class Player(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="players")
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        related_name="players",
        null=True,
        blank=True,
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(
        max_length=80,
        blank=True,
        help_text="Free-form, e.g. 'Chile'. We can promote this to an FK later.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"
