from copy import deepcopy
from importlib import import_module

from django.apps import apps
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from ..engine import default_map, initial_state
from ..models import GameInstance, Scenario, SingleGame


class GameCatalogApiTests(TestCase):
    def test_assault_upgrade_preserves_custom_maps_and_active_matches(self):
        upgrade = import_module("game.migrations.0006_tune_greywatch_assault")
        game = SingleGame.objects.get(slug="greywatch-assault")
        old_map = deepcopy(upgrade.PREVIOUS_ASSAULT)
        game.map_definition = old_map
        game.save(update_fields=["map_definition"])
        match = GameInstance.objects.create(
            single_game=game, source_game=game,
            map_definition=deepcopy(old_map), state=initial_state(old_map),
        )

        upgrade.tune_seeded_assault(apps, None)
        game.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(game.map_definition, default_map())
        self.assertEqual(match.map_definition, old_map)
        self.assertEqual(len(match.state["units"]), 8)
        upgrade.tune_seeded_assault(apps, None)
        game.refresh_from_db()
        self.assertEqual(game.map_definition, default_map())

        custom = deepcopy(old_map)
        custom["enemyStartPositions"][0]["x"] = 13
        game.map_definition = custom
        game.save(update_fields=["map_definition"])
        upgrade.tune_seeded_assault(apps, None)
        game.refresh_from_db()
        self.assertEqual(game.map_definition, custom)

    def test_seeded_scenario_links_seeded_game(self):
        scenario = Scenario.objects.get(slug="siege-of-greywatch")
        self.assertEqual(
            list(scenario.games.values_list("slug", flat=True)),
            ["greywatch-assault"],
        )

    def test_scenarios_api_returns_available_scenarios(self):
        scenario = Scenario.objects.create(
            name="Greywatch Campaign",
            slug="greywatch-campaign",
            description="Take the keep.",
            sort_order=1,
        )
        game = SingleGame.objects.create(
            name="Quick Siege", slug="quick-siege", description="Assault the keep."
        )
        scenario.games.add(game)
        Scenario.objects.create(
            name="Unavailable scenario",
            slug="unavailable-scenario",
            description="Not ready.",
            is_available=False,
        )

        response = self.client.get(reverse("scenarios-api"))

        self.assertEqual(response.status_code, 200)
        scenarios = response.json()
        self.assertIn({
            "id": Scenario.objects.get(slug="greywatch-campaign").pk,
            "name": "Greywatch Campaign",
            "slug": "greywatch-campaign",
            "description": "Take the keep.",
            "introduction": "",
            "games": [{
                "id": game.pk,
                "name": game.name,
                "slug": game.slug,
                "description": game.description,
                "introduction": game.introduction,
            }],
        }, scenarios)
        self.assertNotIn("unavailable-scenario", [item["slug"] for item in scenarios])

    def test_single_games_api_returns_available_games(self):
        game = SingleGame.objects.create(
            name="Quick Siege",
            slug="quick-siege",
            description="A standalone assault.",
            introduction="Cross the courtyard.",
        )

        response = self.client.get(reverse("single-games-api"))

        self.assertEqual(response.status_code, 200)
        self.assertIn({
            "id": game.pk,
            "name": game.name,
            "slug": game.slug,
            "description": game.description,
            "introduction": game.introduction,
        }, response.json())

    def test_catalog_apis_only_allow_get(self):
        response = self.client.post(reverse("scenarios-api"))

        self.assertEqual(response.status_code, 405)

    def test_home_renders_game_start_screen(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Play game")
        self.assertContains(response, "static/game/favicon.ico")
        self.assertContains(response, "static/game/site.webmanifest")
        self.assertContains(response, 'id="pause-game" type="button" aria-pressed="false"')
        self.assertContains(response, '<label for="animation-speed">Animation speed</label>')
        self.assertContains(response, "static/game/game.js")
        self.assertIsNotNone(finders.find("game/renderer.js"))
