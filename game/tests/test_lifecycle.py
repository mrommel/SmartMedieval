import json
from copy import deepcopy
from unittest.mock import patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..engine import default_map, normalize_map
from ..models import GameInstance, Scenario, SingleGame


@override_settings(ENEMY_AI_API_KEY="test-only-key")
class EditorToBattleLifecycleTests(TestCase):
    def setUp(self):
        self.editor = Client()
        self.editor.force_login(get_user_model().objects.create_superuser(
            "editor", "editor@example.test", "password"
        ))
        self.player = Client()

    def save_game(self, battlefield, *, change_id=None):
        url = (reverse("admin:game_singlegame_change", args=[change_id]) if change_id
               else reverse("admin:game_singlegame_add"))
        response = self.editor.post(url, {
            "name": "Scout mission", "slug": "scout-mission", "description": "A foggy assault.",
            "introduction": "Find the gate.", "sort_order": 0, "is_available": "on",
            "map_definition": json.dumps(battlefield), "_save": "Save",
        })
        self.assertEqual(response.status_code, 302, response.content.decode()[:500])
        return SingleGame.objects.get(slug="scout-mission")

    def action(self, revision, action):
        return self.player.post(reverse("game-action"),
                                data=json.dumps({"revision": revision, "action": action}),
                                content_type="application/json")

    def test_every_seeded_scenario_launches_plays_and_resumes(self):
        scenarios = (
            ("siege-of-greywatch", "greywatch-assault", False),
            ("capture-the-king", "greywatch-throne-room", False),
            ("through-the-hamlet", "greywatch-hamlet", False),
            ("scout-greywatch", "greywatch-reconnaissance", True),
            ("night-watch-greywatch", "greywatch-night-watch", True),
            ("shieldwall-greywatch", "greywatch-shieldwall", True),
        )
        catalog = {entry["slug"]: entry for entry in self.player.get(reverse("scenarios-api")).json()}
        for scenario_slug, game_slug, fogged in scenarios:
            with self.subTest(scenario=scenario_slug):
                scenario = Scenario.objects.get(slug=scenario_slug)
                game = SingleGame.objects.get(slug=game_slug)
                self.assertIn(game.pk, [entry["id"] for entry in catalog[scenario_slug]["games"]])
                response = self.player.post(reverse("start-game", args=["scenarios", scenario.pk]),
                                            data="{}", content_type="application/json")
                self.assertEqual(response.status_code, 201)
                started = response.json()
                self.assertEqual(started["game_id"], game.pk)
                self.assertEqual(started["map"].get("fog_of_war", False), fogged)
                self.assertEqual(started["revision"], 0)
                self.assertEqual(started["state"]["turn"], 1)
                if fogged:
                    for field in ("enemyStartPositions", "items", "horses"):
                        self.assertNotIn(field, started["map"])

                # This first step is open in all six authored encounters.
                moved_response = self.action(0, {"type": "move", "units": [0], "x": 3, "y": 6})
                self.assertEqual(moved_response.status_code, 200, moved_response.content)
                moved = moved_response.json()
                self.assertEqual((moved["state"]["units"][0]["x"], moved["state"]["units"][0]["y"]),
                                 (3, 6))
                self.assertEqual(moved["revision"], 1)

                ended_response = self.action(1, {"type": "end_turn", "offline": True})
                self.assertEqual(ended_response.status_code, 200, ended_response.content)
                ended = ended_response.json()
                self.assertEqual(ended["revision"], 2)
                self.assertEqual(ended["state"]["turn"], 2)
                self.assertEqual(ended["id"], started["id"])
                if fogged:
                    self.assertNotIn("enemyStartPositions", ended["map"])
                    self.assertNotIn("witnessed", json.dumps(ended))

                reloaded = Client()
                reloaded.cookies.update(self.player.cookies)
                self.player = reloaded
                self.assertEqual(self.player.get(reverse("current-game")).json(),
                                 {key: value for key, value in ended.items() if key != "combat_events"})
                instance = GameInstance.objects.get(pk=started["id"])
                self.assertEqual(instance.revision, 2)
                self.assertEqual(instance.state["turn"], 2)
                self.assertEqual(instance.map_definition, normalize_map(game.map_definition))

    def test_authored_scenario_survives_edits_ai_failures_and_resume_until_restart(self):
        original = default_map()
        original.update(fog_of_war=True,
                        startPositions=[{"x": 2, "y": 6, "weapon": "sword", "armor": "leather"}],
                        enemyStartPositions=[{"x": 16, "y": 8, "weapon": "sword"}],
                        items=[{"x": 3, "y": 6, "type": "healing_potion"}])
        game = self.save_game(original)
        response = self.editor.post(reverse("admin:game_scenario_add"), {
            "name": "Scout campaign", "slug": "scout-campaign", "description": "Explore.",
            "introduction": "", "sort_order": 0, "is_available": "on",
            "games": [game.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        scenario = Scenario.objects.get(slug="scout-campaign")
        catalog = self.player.get(reverse("scenarios-api")).json()
        self.assertIn(game.pk, [entry["id"] for entry in next(
            entry for entry in catalog if entry["id"] == scenario.pk)["games"]])
        launch_url = reverse("start-game", args=["scenarios", scenario.pk])
        started_response = self.player.post(launch_url, data="{}", content_type="application/json")
        self.assertEqual(started_response.status_code, 201)
        started = started_response.json()
        self.assertEqual(started["game_id"], game.pk)
        self.assertEqual(started["kind"], "scenarios")
        self.assertNotIn("enemyStartPositions", started["map"])
        self.assertEqual([unit["id"] for unit in started["state"]["units"]], [0])
        self.assertEqual(started["state"]["units"][0]["armor"], "leather")
        self.assertEqual(len(started["state"]["items"]), 1)

        moved_response = self.action(started["revision"], {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertEqual(moved_response.status_code, 200)
        moved = moved_response.json()
        self.assertEqual(moved["state"]["units"][0]["x"], 3)

        revised = deepcopy(original)
        revised["startPositions"][0].update(x=2, y=5, armor="mail")
        revised["items"] = []
        revised["objects"] = [{"x": 3, "y": 6, "type": "rock"}]
        self.save_game(revised, change_id=game.pk)
        instance = GameInstance.objects.get(pk=started["id"])
        self.assertEqual(instance.map_definition, normalize_map(original))

        # A browser reload must recover the same session-owned, fog-safe snapshot.
        reloaded = Client()
        reloaded.cookies = self.player.cookies.copy()
        self.player = reloaded
        current = self.player.get(reverse("current-game")).json()
        self.assertEqual(current, {key: value for key, value in moved.items() if key != "combat_events"})
        self.assertEqual(current["state"]["units"][0]["armor"], "leather")
        self.assertNotIn("objects", current["map"])

        with patch("game.enemy_ai.urlopen") as ai:
            ai.side_effect = URLError("private network detail")
            failed = self.action(moved["revision"], {"type": "end_turn"})
            self.assertEqual(failed.status_code, 503)
            self.assertNotIn("private network detail", failed.content.decode())
            self.assertEqual(self.player.get(reverse("current-game")).json(), current)
            instance.refresh_from_db()
            self.assertEqual(instance.revision, moved["revision"])
            self.assertEqual(instance.state["units"][0]["x"], 3)

            ai.side_effect = None
            ai.return_value.__enter__.return_value.read.return_value = json.dumps({
                "choices": [{"message": {"content": json.dumps({"orders": []})}}],
            }).encode()
            retried = self.action(moved["revision"], {"type": "end_turn"})
            self.assertEqual(retried.status_code, 200)
            retried = retried.json()
            self.assertEqual(retried["revision"], moved["revision"] + 1)
            ai_battlefield = json.loads(json.loads(ai.call_args.args[0].data)["messages"][1]["content"].split("\n")[0])
            self.assertTrue(ai_battlefield["map"]["fog_of_war"])
            self.assertEqual(ai_battlefield["map"]["objects"], [])
            self.assertEqual([unit["side"] for unit in ai_battlefield["units"]], ["defenders"])

            ai.side_effect = URLError("private network detail")
            self.assertEqual(self.action(retried["revision"], {"type": "end_turn"}).status_code, 503)
            offline = self.action(retried["revision"], {"type": "end_turn", "offline": True})
            self.assertEqual(offline.status_code, 200)
            offline = offline.json()
            self.assertEqual(offline["revision"], retried["revision"] + 1)
            self.assertEqual(self.player.get(reverse("current-game")).json(),
                             {key: value for key, value in offline.items() if key != "combat_events"})
            self.assertNotIn("enemyStartPositions", offline["map"])
            self.assertEqual(self.action(retried["revision"], {"type": "end_turn", "offline": True}).status_code, 409)

        restarted_response = self.player.post(launch_url, data="{}", content_type="application/json")
        self.assertEqual(restarted_response.status_code, 201)
        restarted = restarted_response.json()
        self.assertNotEqual(restarted["id"], started["id"])
        self.assertEqual(restarted["revision"], 0)
        self.assertEqual(restarted["state"]["units"][0]["armor"], "mail")
        self.assertEqual(restarted["state"]["units"][0]["x"], 2)
        self.assertEqual(restarted["state"]["units"][0]["y"], 5)
        self.assertEqual(restarted["state"]["items"], [])
        self.assertEqual(restarted["map"]["objects"], revised["objects"])
        self.assertNotIn("enemyStartPositions", restarted["map"])
        self.assertEqual(self.player.get(reverse("current-game")).json(), restarted)
        self.assertEqual(self.action(0, {"type": "move", "units": [0], "x": 3, "y": 6}).status_code, 400)
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).map_definition, normalize_map(original))

    def test_editing_fog_only_affects_new_matches_not_active_snapshots(self):
        battlefield = default_map()
        battlefield.update(fog_of_war=False,
                           startPositions=[{"x": 2, "y": 6, "weapon": "sword"}],
                           enemyStartPositions=[{"x": 16, "y": 8, "weapon": "sword"}])
        game = self.save_game(battlefield)
        response = self.editor.post(reverse("admin:game_scenario_add"), {
            "name": "Scout campaign", "slug": "scout-campaign", "description": "Explore.",
            "introduction": "", "sort_order": 0, "is_available": "on",
            "games": [game.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        scenario = Scenario.objects.get(slug="scout-campaign")
        launch_url = reverse("start-game", args=["scenarios", scenario.pk])
        started = self.player.post(launch_url, data="{}", content_type="application/json").json()
        self.assertFalse(started["map"]["fog_of_war"])
        self.assertIn("enemyStartPositions", started["map"])
        self.assertEqual(len(started["state"]["units"]), 2)

        moved_response = self.action(started["revision"], {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertEqual(moved_response.status_code, 200)
        moved = moved_response.json()
        revised = deepcopy(battlefield)
        revised["fog_of_war"] = True
        self.save_game(revised, change_id=game.pk)

        reloaded = Client()
        reloaded.cookies = self.player.cookies.copy()
        self.player = reloaded
        resumed = self.player.get(reverse("current-game")).json()
        self.assertEqual(resumed, {key: value for key, value in moved.items() if key != "combat_events"})
        self.assertFalse(resumed["map"]["fog_of_war"])
        self.assertIn("enemyStartPositions", resumed["map"])
        self.assertEqual(len(resumed["state"]["units"]), 2)
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).map_definition,
                         normalize_map(battlefield))

        restarted_response = self.player.post(launch_url, data="{}", content_type="application/json")
        self.assertEqual(restarted_response.status_code, 201)
        restarted = restarted_response.json()
        self.assertNotEqual(restarted["id"], started["id"])
        self.assertTrue(restarted["map"]["fog_of_war"])
        self.assertNotIn("enemyStartPositions", restarted["map"])
        self.assertEqual([unit["id"] for unit in restarted["state"]["units"]], [0])
        self.assertEqual(self.player.get(reverse("current-game")).json(), restarted)

    def test_fogged_match_hides_unseen_wall_changes_on_launch_and_resume(self):
        battlefield = default_map()
        battlefield.update(fog_of_war=True,
                           startPositions=[{"x": 2, "y": 6, "weapon": "sword"}],
                           enemyStartPositions=[{"x": 16, "y": 8, "weapon": "sword"}])
        game = self.save_game(battlefield)
        started = self.player.post(reverse("start-game", args=["single-games", game.pk]),
                                   data="{}", content_type="application/json").json()
        instance = GameInstance.objects.get(pk=started["id"])
        # Older match states can lack these keys; a new turn may later add unseen damage.
        instance.state.pop("wall_damage")
        instance.state.pop("breaches")
        instance.save(update_fields=["state"])
        resumed = self.player.get(reverse("current-game")).json()
        self.assertEqual(resumed["state"]["wall_damage"], [])
        self.assertEqual(resumed["state"]["breaches"], [])

        damage = {"x": 11, "y": 7, "damage": 1}
        breach = {"x": 11, "y": 8}
        instance.state["wall_damage"] = [damage]
        instance.state["breaches"] = [breach]
        instance.save(update_fields=["state"])
        hidden = self.player.get(reverse("current-game")).json()
        self.assertEqual(hidden["state"]["wall_damage"], [])
        self.assertEqual(hidden["state"]["breaches"], [])
        self.assertEqual(hidden["state"]["units"], started["state"]["units"])
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).state["breaches"], [breach])

        moved = self.action(hidden["revision"], {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["state"]["wall_damage"], [])
        self.assertEqual(moved.json()["state"]["breaches"], [])
        instance.refresh_from_db()
        instance.state["units"][0].update(x=8, y=7)
        instance.save(update_fields=["state"])
        observed = self.player.get(reverse("current-game")).json()
        self.assertEqual(observed["state"]["wall_damage"], [damage])
        self.assertEqual(observed["state"]["breaches"], [breach])
        self.assertEqual(self.player.get(reverse("current-game")).json(), observed)

        instance.state["units"][0].update(x=2, y=6)
        instance.save(update_fields=["state"])
        out_of_sight = self.player.get(reverse("current-game")).json()
        self.assertEqual(out_of_sight["state"]["wall_damage"], [])
        self.assertEqual(out_of_sight["state"]["breaches"], [])

    def test_legacy_fogged_match_survives_unlisting_and_failed_ai_retries(self):
        battlefield = default_map()
        battlefield.update(fog_of_war=True,
                           startPositions=[{"x": 2, "y": 6, "weapon": "sword"}],
                           enemyStartPositions=[{"x": 16, "y": 8, "weapon": "sword"}])
        game = self.save_game(battlefield)
        response = self.editor.post(reverse("admin:game_scenario_add"), {
            "name": "Scout campaign", "slug": "scout-campaign", "description": "Explore.",
            "introduction": "", "sort_order": 0, "is_available": "on",
            "games": [game.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        scenario = Scenario.objects.get(slug="scout-campaign")
        launch_url = reverse("start-game", args=["scenarios", scenario.pk])
        started = self.player.post(launch_url, data="{}", content_type="application/json").json()
        instance = GameInstance.objects.get(pk=started["id"])

        # Simulate an older saved match with a fog map and no newer state fields.
        legacy_map = deepcopy(instance.map_definition)
        for roster in ("startPositions", "enemyStartPositions"):
            for position in legacy_map[roster]:
                position["type"] = "vanguard"
                del position["weapon"]
        instance.map_definition = legacy_map
        legacy_state = instance.state
        for field in ("items", "next_item_id", "horses", "catapults", "withdrawn", "smoke", "fire",
                      "burned", "wall_damage", "breaches", "extinguished_watchfires", "explored"):
            legacy_state.pop(field, None)
        for unit in legacy_state["units"]:
            unit["type"] = "vanguard"
            for field in ("weapon", "tools", "armor", "armor_equipped", "mount_id",
                          "move_capacity", "reaction_reserved", "move_reserved", "crouched",
                          "shield_raised", "torch_lit", "wound_turns"):
                unit.pop(field, None)
        instance.state = legacy_state
        instance.save(update_fields=["map_definition", "state"])

        game.is_available = False
        game.save(update_fields=["is_available"])
        scenario.is_available = False
        scenario.save(update_fields=["is_available"])
        self.assertNotIn(scenario.pk, [entry["id"] for entry in self.player.get(reverse("scenarios-api")).json()])
        self.assertNotIn(game.pk, [entry["id"] for entry in self.player.get(reverse("single-games-api")).json()])
        self.assertEqual(self.player.post(launch_url, data="{}", content_type="application/json").status_code, 404)

        reloaded = Client()
        reloaded.cookies = self.player.cookies.copy()
        self.player = reloaded
        resumed = self.player.get(reverse("current-game")).json()
        self.assertEqual(resumed["id"], started["id"])
        self.assertEqual(resumed["revision"], 0)
        self.assertNotIn("enemyStartPositions", resumed["map"])
        self.assertEqual([unit["id"] for unit in resumed["state"]["units"]], [0])
        self.assertEqual(resumed["state"]["items"], [])
        self.assertEqual(resumed["state"]["units"][0]["weapon"], "sword")

        moved_response = self.action(0, {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertEqual(moved_response.status_code, 200)
        moved = moved_response.json()
        self.assertEqual(moved["state"]["units"][0]["x"], 3)
        self.assertEqual(moved["revision"], 1)
        self.assertEqual(self.player.get(reverse("current-game")).json(),
                         {key: value for key, value in moved.items() if key != "combat_events"})
        instance.refresh_from_db()
        before_ai = deepcopy(instance.state)

        invalid_response = json.dumps({"choices": [{"message": {"content": "not JSON"}}]}).encode()
        with patch("game.enemy_ai.urlopen") as ai:
            ai.return_value.__enter__.return_value.read.return_value = invalid_response
            failed = self.action(1, {"type": "end_turn"})
            self.assertEqual(failed.status_code, 502)
            self.assertEqual(ai.call_count, 2)
            self.assertEqual(self.player.get(reverse("current-game")).json(),
                             {key: value for key, value in moved.items() if key != "combat_events"})
            instance.refresh_from_db()
            self.assertEqual(instance.revision, 1)
            self.assertEqual(instance.state, before_ai)

        offline = self.action(1, {"type": "end_turn", "offline": True})
        self.assertEqual(offline.status_code, 200)
        advanced = offline.json()
        self.assertEqual(advanced["revision"], 2)
        self.assertEqual(advanced["state"]["turn"], 2)
        self.assertNotIn("enemyStartPositions", advanced["map"])
        self.assertEqual([unit["id"] for unit in advanced["state"]["units"]], [0])
        self.assertEqual(self.player.get(reverse("current-game")).json(),
                         {key: value for key, value in advanced.items() if key != "combat_events"})
        self.assertEqual(self.action(1, {"type": "end_turn", "offline": True}).status_code, 409)
        instance.refresh_from_db()
        self.assertEqual(instance.map_definition, legacy_map)
        self.assertEqual(instance.state["units"][0]["weapon"], "sword")
