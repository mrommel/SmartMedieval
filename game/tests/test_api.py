import json
from unittest.mock import patch
from urllib.error import URLError

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..engine import MAP, default_map
from ..models import GameInstance, Scenario, SingleGame


@override_settings(ENEMY_AI_API_KEY="test-only-key")
class GameInstanceApiTests(TestCase):
    def setUp(self):
        patcher = patch("game.enemy_ai.urlopen")
        self.ai = patcher.start()
        self.addCleanup(patcher.stop)
        self.set_ai_orders([])
        self.game = SingleGame.objects.create(
            name="Quick Siege", slug="quick-siege", description="A standalone assault."
        )

    def set_ai_orders(self, orders):
        self.ai.return_value.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"orders": orders})}}],
        }).encode()

    def start(self):
        return self.client.post(reverse("start-game", args=["single-games", self.game.pk]))

    def action(self, revision, action):
        return self.client.post(
            reverse("game-action"),
            data=json.dumps({"revision": revision, "action": action}),
            content_type="application/json",
        )

    def test_start_load_move_and_resume_server_owned_game(self):
        started = self.start()
        self.assertEqual(started.status_code, 201)
        data = started.json()
        self.assertEqual(data["map"], MAP)
        self.assertEqual(data["entry"]["name"], self.game.name)
        self.assertEqual(data["state"]["units"][0]["move_points"], 4)
        self.assertEqual(data["state"]["units"][0]["health"], 3)
        self.assertEqual(data["state"]["units"][0]["fight_points"], 1)
        self.assertEqual(len([unit for unit in data["state"]["units"] if unit["side"] == "defenders"]), 2)
        self.assertEqual(GameInstance.objects.count(), 1)

        moved = self.action(0, {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["state"]["units"][0]["x"], 3)
        self.assertEqual(moved.json()["revision"], 1)
        self.assertEqual(self.client.get(reverse("current-game")).json(), moved.json())
        self.assertEqual(GameInstance.objects.get(pk=data["id"]).state["units"][0]["x"], 3)

        next_turn = self.action(1, {"type": "end_turn"})
        self.assertEqual(next_turn.json()["state"]["turn"], 2)
        self.assertEqual(next_turn.json()["state"]["units"][0]["move_points"], 4)
        request = self.ai.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11435/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL")
        battlefield = json.loads(json.loads(request.data)["messages"][1]["content"].split("\n")[0])
        self.assertEqual(battlefield["map"]["objective"], {"x": 14, "y": 7})
        self.assertEqual([unit["id"] for unit in battlefield["units"] if unit["side"] == "defenders"], [6, 7])
        self.assertNotIn("test-only-key", json.dumps(next_turn.json()))
        self.assertNotIn("test-only-key", request.data.decode())

    def test_attack_action_persists_damage_and_spent_fight_point(self):
        started = self.start().json()
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"][0].update(x=12, y=4)
        instance.save(update_fields=["state"])

        attacked = self.action(0, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual(attacked.status_code, 200)
        state = attacked.json()["state"]
        self.assertEqual(state["units"][0]["fight_points"], 0)
        self.assertEqual(state["units"][6]["health"], 2)
        self.assertEqual(attacked.json()["revision"], 1)
        self.assertEqual(self.client.get(reverse("current-game")).json(), attacked.json())

    def test_rejects_stale_invalid_and_unauthorized_actions(self):
        self.assertEqual(self.client.get(reverse("current-game")).status_code, 404)
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 404)
        started = self.start().json()
        outsider = Client()
        self.assertEqual(outsider.get(reverse("current-game")).status_code, 404)
        self.assertEqual(outsider.post(reverse("game-action")).status_code, 404)
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 200)
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 409)
        self.assertEqual(self.action(1, {"type": "move", "units": [99], "x": 3, "y": 6}).status_code, 400)
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).revision, 1)

    def test_start_only_accepts_available_entries_and_post(self):
        self.game.is_available = False
        self.game.save()
        self.assertEqual(self.start().status_code, 404)
        self.assertEqual(self.client.get(reverse("start-game", args=["single-games", self.game.pk])).status_code, 405)

    def test_scenario_start_and_restart_replace_active_match(self):
        scenario = Scenario.objects.create(
            name="Greywatch Campaign", slug="greywatch-campaign", description="Take the keep."
        )
        scenario.games.add(self.game)
        first = self.client.post(
            reverse("start-game", args=["scenarios", scenario.pk]),
            data="{}", content_type="application/json",
        ).json()
        self.assertEqual(first["kind"], "scenarios")
        self.assertEqual(first["game_id"], self.game.pk)
        self.assertEqual(first["state"]["capture_status"], "UNCLAIMED")
        second = self.start().json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.client.get(reverse("current-game")).json()["id"], second["id"])

    def test_csrf_required_for_start_and_actions(self):
        browser = Client(enforce_csrf_checks=True)
        start_url = reverse("start-game", args=["single-games", self.game.pk])
        self.assertEqual(browser.post(start_url).status_code, 403)
        browser.get(reverse("home"))
        token = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post(start_url, HTTP_X_CSRFTOKEN=token).status_code, 201)
        self.assertEqual(browser.post(reverse("game-action")).status_code, 403)

    def test_scenario_selects_only_linked_available_game(self):
        scenario = Scenario.objects.create(name="Campaign", slug="campaign", description="Two battles.")
        second = SingleGame.objects.create(
            name="Second battle", slug="second-battle", description="Different map."
        )
        custom = default_map()
        custom["startPositions"] = [{"x": 6, "y": 6, "type": "crossbow"}]
        second.map_definition = custom
        second.save()
        scenario.games.add(self.game, second)
        url = reverse("start-game", args=["scenarios", scenario.pk])
        self.assertEqual(self.client.post(url, data="{}", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, data=json.dumps({"single_game_id": 999}),
                                          content_type="application/json").status_code, 400)
        unlinked = SingleGame.objects.create(
            name="Unlinked", slug="unlinked", description="Not in campaign."
        )
        self.assertEqual(self.client.post(url, data=json.dumps({"single_game_id": unlinked.pk}),
                                          content_type="application/json").status_code, 400)
        started = self.client.post(url, data=json.dumps({"single_game_id": second.pk}),
                                   content_type="application/json")
        self.assertEqual(started.status_code, 201)
        self.assertEqual(started.json()["game_id"], second.pk)
        self.assertEqual(started.json()["map"], custom)
        self.assertEqual(len([unit for unit in started.json()["state"]["units"] if unit["side"] == "attackers"]), 1)
        second.is_available = False
        second.save()
        self.assertEqual(self.client.post(url, data=json.dumps({"single_game_id": second.pk}),
                                          content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get(reverse("current-game")).json()["map"], custom)

    def test_active_match_keeps_its_map_after_definition_changes(self):
        custom = default_map()
        custom["objective"] = {"x": 4, "y": 5}
        custom["startPositions"] = [{"x": 2, "y": 5, "type": "vanguard"}]
        self.game.map_definition = custom
        self.game.full_clean()
        self.game.save()
        started = self.start().json()
        self.assertEqual(started["map"], custom)
        self.game.map_definition = default_map()
        self.game.save()
        moved = self.action(0, {"type": "move", "units": [0], "x": 4, "y": 5})
        self.assertEqual(moved.status_code, 200)
        captured = self.action(1, {"type": "end_turn"})
        self.assertEqual(captured.json()["state"]["capture_status"], "CAPTURING")
        self.assertEqual(captured.json()["map"], custom)
        self.assertEqual(self.start().json()["map"], MAP)

    def test_enemy_ai_moves_only_defenders_and_failed_turns_are_not_saved(self):
        started = self.start().json()
        self.set_ai_orders([{"unit_id": 6, "x": 12, "y": 6}])
        turn = self.action(0, {"type": "end_turn"})
        self.assertEqual(turn.status_code, 200)
        self.assertEqual((turn.json()["state"]["units"][6]["x"], turn.json()["state"]["units"][6]["y"]), (12, 6))
        self.assertEqual(turn.json()["revision"], 1)

        self.set_ai_orders([{"unit_id": 0, "x": 12, "y": 6}])
        rejected = self.action(1, {"type": "end_turn"})
        self.assertEqual(rejected.status_code, 502)
        self.assertEqual(self.client.get(reverse("current-game")).json(), turn.json())
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).revision, 1)

        self.ai.side_effect = URLError("private-network-detail")
        unavailable = self.action(1, {"type": "end_turn"})
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(self.client.get(reverse("current-game")).json(), turn.json())
        self.assertNotIn("private-network-detail", json.dumps(unavailable.json()))

    def test_existing_map_without_defender_roster_still_starts_a_match(self):
        legacy_map = default_map()
        del legacy_map["enemyStartPositions"]
        self.game.map_definition = legacy_map
        self.game.full_clean()
        self.game.save()
        started = self.start().json()
        self.assertEqual(started["map"], legacy_map)
        self.assertEqual(len([unit for unit in started["state"]["units"] if unit["side"] == "defenders"]), 1)

    def test_malformed_ai_response_does_not_advance_the_turn(self):
        started = self.start().json()
        self.ai.return_value.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": None}}],
        }).encode()
        response = self.action(0, {"type": "end_turn"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get(reverse("current-game")).json(), started)

    def test_invalid_model_goal_is_retried_before_ending_turn(self):
        self.start()
        def response(orders):
            return json.dumps({
                "choices": [{"message": {"content": json.dumps({"orders": orders})}}],
            }).encode()

        self.ai.return_value.__enter__.return_value.read.side_effect = [
            response([{"unit_id": 6, "x": "west", "y": 7}]),
            response([{"unit_id": 6, "x": 13, "y": 7}]),
        ]
        result = self.action(0, {"type": "end_turn"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual((result.json()["state"]["units"][6]["x"],
                          result.json()["state"]["units"][6]["y"]), (13, 7))
        self.assertEqual(self.ai.call_count, 2)
        retry = json.loads(self.ai.call_args.args[0].data)["messages"][1]["content"]
        self.assertIn("previous answer was rejected", retry)

    def test_ai_goal_on_objective_is_resolved_to_a_legal_move(self):
        started = self.start().json()
        self.set_ai_orders([{"unit_id": 6, "x": 14, "y": 7}])
        result = self.action(0, {"type": "end_turn"})
        self.assertEqual(result.status_code, 200)
        self.assertNotEqual(
            (result.json()["state"]["units"][6]["x"], result.json()["state"]["units"][6]["y"]),
            (14, 7),
        )
        self.assertNotEqual(result.json()["state"]["units"][6], started["state"]["units"][6])
        self.assertEqual(self.ai.call_count, 1)

    @override_settings(ENEMY_AI_API_KEY=None)
    def test_missing_key_blocks_end_turn_without_changing_match(self):
        started = self.start().json()
        response = self.action(0, {"type": "end_turn"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("SPLASH_API_KEY", response.json()["error"])
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).revision, 0)
        self.ai.assert_not_called()
