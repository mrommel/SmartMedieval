from copy import deepcopy
from importlib import import_module

from django.apps import apps
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from ..engine import default_map, initial_state, normalize_map, validate_map
from ..models import GameInstance, Scenario, SingleGame


class GameCatalogApiTests(TestCase):
    def test_equipment_upgrade_keeps_active_match_and_is_repeatable(self):
        upgrade = import_module("game.migrations.0010_unit_equipment")
        game = SingleGame.objects.get(slug="greywatch-assault")
        legacy = deepcopy(game.map_definition)
        for name in ("startPositions", "enemyStartPositions"):
            for point in legacy[name]:
                point["type"] = {"sword": "vanguard", "longbow": "longbow", "crossbow": "crossbow"}[point.pop("weapon")]
        game.map_definition = legacy
        game.save(update_fields=["map_definition"])
        match = GameInstance.objects.create(single_game=game, source_game=game,
                                            map_definition=deepcopy(legacy), state=initial_state(legacy), revision=4)
        match.state["units"][0]["type"] = "vanguard"
        del match.state["units"][0]["weapon"]
        match.state["history"] = [{"turn": 1, "type": "attack", "actor_type": "vanguard",
                                   "target_type": "longbow"}]
        match.save(update_fields=["state"])
        schema_editor = type("Editor", (), {"connection": type("Connection", (), {"alias": "default"})()})()
        upgrade.migrate_equipment(apps, schema_editor)
        game.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(game.map_definition, default_map())
        self.assertEqual(match.map_definition, default_map())
        self.assertEqual((match.state["units"][0]["weapon"], match.state["units"][0]["tools"]), ("sword", []))
        self.assertNotIn("type", match.state["units"][0])
        self.assertEqual(match.state["history"][0]["actor_weapon"], "sword")
        self.assertEqual(match.revision, 4)
        snapshot = deepcopy(match.state)
        upgrade.migrate_equipment(apps, schema_editor)
        match.refresh_from_db()
        self.assertEqual(match.state, snapshot)

    def test_seeded_village_has_reachable_map_and_linked_scenario(self):
        game = SingleGame.objects.get(slug="greywatch-hamlet")
        scenario = Scenario.objects.get(slug="through-the-hamlet")
        self.assertEqual(list(scenario.games.all()), [game])
        self.assertEqual(len(game.map_definition["houses"]), 2)
        self.assertEqual([house["door"] for house in game.map_definition["houses"]],
                         [{"x": 7, "y": 4}, {"x": 7, "y": 10}])
        validate_map(game.map_definition)
        self.assertEqual(len(initial_state(game.map_definition)["units"]), 7)
        self.assertIn(game.name, [entry["name"] for entry in self.client.get(reverse("single-games-api")).json()])

    def test_house_door_upgrade_preserves_custom_maps_and_active_matches(self):
        upgrade = import_module("game.migrations.0008_hamlet_house_doors")
        game = SingleGame.objects.get(slug="greywatch-hamlet")
        previous = deepcopy(upgrade.PREVIOUS_HAMLET)
        upgraded = deepcopy(previous)
        upgraded["houses"][0]["door"] = {"x": 7, "y": 4}
        upgraded["houses"][1]["door"] = {"x": 7, "y": 10}
        game.map_definition = previous
        game.save(update_fields=["map_definition"])
        match = GameInstance.objects.create(
            single_game=game, source_game=game,
            map_definition=deepcopy(previous), state=initial_state(previous),
        )
        upgrade.open_seeded_houses(apps, None)
        game.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(game.map_definition, upgraded)
        self.assertEqual(match.map_definition, previous)
        upgrade.open_seeded_houses(apps, None)
        game.refresh_from_db()
        self.assertEqual(game.map_definition, upgraded)

        custom = deepcopy(previous)
        custom["houses"][0]["left"] = 5
        game.map_definition = custom
        game.save(update_fields=["map_definition"])
        upgrade.open_seeded_houses(apps, None)
        game.refresh_from_db()
        self.assertEqual(game.map_definition, custom)

    def test_potion_upgrade_preserves_custom_maps_and_active_matches(self):
        upgrade = import_module("game.migrations.0009_hamlet_healing_potions")
        game = SingleGame.objects.get(slug="greywatch-hamlet")
        upgraded = deepcopy(game.map_definition)
        previous = deepcopy(upgrade.PREVIOUS_HAMLET)
        game.map_definition = previous
        game.save(update_fields=["map_definition"])
        match = GameInstance.objects.create(
            single_game=game, source_game=game,
            map_definition=deepcopy(previous), state=initial_state(previous),
        )
        upgrade.stock_hamlet(apps, None)
        game.refresh_from_db()
        match.refresh_from_db()
        self.assertEqual(normalize_map(game.map_definition), upgraded)
        self.assertEqual(match.map_definition, previous)
        self.assertEqual(match.state["items"], [])
        upgrade.stock_hamlet(apps, None)
        game.refresh_from_db()
        self.assertEqual(normalize_map(game.map_definition), upgraded)
        custom = deepcopy(previous)
        custom["items"] = [{"x": 5, "y": 7, "type": "healing_potion"}]
        game.map_definition = custom
        game.save(update_fields=["map_definition"])
        upgrade.stock_hamlet(apps, None)
        game.refresh_from_db()
        self.assertEqual(game.map_definition, custom)

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
        self.assertEqual(normalize_map(game.map_definition), default_map())
        self.assertEqual(match.map_definition, old_map)
        self.assertEqual(len(match.state["units"]), 8)
        upgrade.tune_seeded_assault(apps, None)
        game.refresh_from_db()
        self.assertEqual(normalize_map(game.map_definition), default_map())

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
