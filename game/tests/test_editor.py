import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from ..engine import default_map, normalize_map
from ..models import Scenario, SingleGame


class GameEditorTests(TestCase):
    def test_rejects_invalid_map_in_editor(self):
        game = SingleGame(name="Bad map", slug="bad-map", description="Invalid.")
        for change in (
            lambda data: data["gate"].update(x=2),
            lambda data: data["objective"].update(x=11, y=3),
            lambda data: data["startPositions"][0].update(type="dragon"),
            lambda data: data["enemyStartPositions"][0].update(x=14, y=7),
            lambda data: data["enemyStartPositions"][0].update(x=2, y=6),
            lambda data: data.update(enemyStartPositions=[]),
            lambda data: data.update(cols=True),
        ):
            game.map_definition = default_map()
            change(game.map_definition)
            with self.assertRaises(ValidationError):
                game.full_clean()

    def test_staff_can_create_game_and_link_scenario_in_admin(self):
        user = get_user_model().objects.create_superuser("editor", "editor@example.test", "password")
        self.client.force_login(user)
        custom = default_map()
        custom["startPositions"] = [{"x": 2, "y": 6, "type": "vanguard"}]
        custom["objects"] = [{"x": 5, "y": 6, "type": "tree"},
                             {"x": 6, "y": 6, "type": "rock"},
                             {"x": 8, "y": 8, "type": "well"},
                             {"x": 9, "y": 8, "type": "fence"}]
        custom["strongpoints"] = [{"left": 6, "right": 9, "top": 1, "bottom": 4,
                                   "gate": {"x": 7, "y": 4}}]
        custom["houses"] = [{"left": 6, "right": 7, "top": 9, "bottom": 10}]
        custom["lanes"] = [{"x": 7, "y": 7}]
        custom["items"] = [{"x": 2, "y": 6, "type": "weapon", "name": "longbow"},
                           {"x": 3, "y": 7, "type": "armor", "name": "leather"}]
        response = self.client.post(reverse("admin:game_singlegame_add"), {
            "name": "New match", "slug": "new-match", "description": "New battlefield.",
            "introduction": "Advance.", "sort_order": 2, "is_available": "on",
            "map_definition": json.dumps(custom), "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        game = SingleGame.objects.get(slug="new-match")
        self.assertEqual(game.map_definition, normalize_map(custom))
        response = self.client.post(reverse("admin:game_scenario_add"), {
            "name": "New campaign", "slug": "new-campaign", "description": "Campaign.",
            "introduction": "", "sort_order": 2, "is_available": "on",
            "games": [game.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(Scenario.objects.get(slug="new-campaign").games.all()), [game])

    def test_admin_rejects_invalid_battlefield(self):
        user = get_user_model().objects.create_superuser("editor", "editor@example.test", "password")
        self.client.force_login(user)
        invalid = default_map()
        invalid["gate"] = {"x": 1, "y": 1}
        response = self.client.post(reverse("admin:game_singlegame_add"), {
            "name": "Bad match", "slug": "bad-match", "description": "Unplayable.",
            "sort_order": 0, "is_available": "on",
            "map_definition": json.dumps(invalid), "_save": "Save",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The gate must lie on the keep wall.")
        self.assertFalse(SingleGame.objects.filter(slug="bad-match").exists())
