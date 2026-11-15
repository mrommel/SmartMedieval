from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from ..models import Scenario, SingleGame


class GameCatalogApiTests(TestCase):
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
