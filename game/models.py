import uuid

from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError

from .engine import InvalidMap, default_map, normalize_map, validate_map


class GameCatalogEntry(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField()
    introduction = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_available = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Scenario(GameCatalogEntry):
    """A scenario entry shown in the play menu."""

    games = models.ManyToManyField("SingleGame", blank=True, related_name="scenarios")


class SingleGame(GameCatalogEntry):
    """A standalone match that can be started without a scenario."""

    map_definition = models.JSONField(default=default_map, help_text="Battlefield geometry and starting units (JSON).")

    def clean(self):
        super().clean()
        try:
            validate_map(self.map_definition)
        except InvalidMap as error:
            raise ValidationError({"map_definition": str(error)}) from error
        self.map_definition = normalize_map(self.map_definition)


class GameInstance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario = models.ForeignKey(Scenario, on_delete=models.PROTECT, null=True, blank=True)
    single_game = models.ForeignKey(SingleGame, on_delete=models.PROTECT, null=True, blank=True)
    source_game = models.ForeignKey(
        SingleGame, on_delete=models.PROTECT, null=True, blank=True, related_name="instances"
    )
    state = models.JSONField()
    map_definition = models.JSONField(default=default_map)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(scenario__isnull=False, single_game__isnull=True)
                           | Q(scenario__isnull=True, single_game__isnull=False)),
                name="game_instance_one_catalog_entry",
            ),
        ]
