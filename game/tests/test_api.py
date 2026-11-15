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

    def test_seeded_hamlet_house_entry_persists_and_ai_receives_doors(self):
        self.game = SingleGame.objects.get(slug="greywatch-hamlet")
        started = self.start().json()
        self.assertEqual(started["map"]["houses"][0]["door"], {"x": 7, "y": 4})
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"][0].update(x=7, y=5)
        instance.save(update_fields=["state"])
        door = self.action(0, {"type": "move", "units": [0], "x": 7, "y": 4})
        self.assertEqual(door.status_code, 200)
        inside = self.action(1, {"type": "move", "units": [0], "x": 7, "y": 3})
        self.assertEqual(inside.status_code, 200)
        self.assertEqual((inside.json()["state"]["units"][0]["y"],
                          inside.json()["state"]["units"][0]["move_points"]), (3, 2))
        self.assertEqual(self.client.get(reverse("current-game")).json()["state"], inside.json()["state"])
        self.assertEqual(self.action(1, {"type": "end_turn"}).status_code, 409)
        self.assertEqual(self.action(2, {"type": "end_turn"}).status_code, 200)
        ai_input = json.loads(json.loads(self.ai.call_args.args[0].data)["messages"][1]["content"].split("\n")[0])
        self.assertEqual(ai_input["map"]["houses"][0]["door"], {"x": 7, "y": 4})

    def test_seeded_throne_room_capture_survives_reload_and_is_session_owned(self):
        throne = SingleGame.objects.get(slug="greywatch-throne-room")
        self.assertIn(throne.pk, [game["id"] for game in self.client.get(reverse("single-games-api")).json()])
        started = self.client.post(reverse("start-game", args=["single-games", throne.pk])).json()
        self.assertEqual(started["map"]["mission"], "capture_king")
        king = next(unit for unit in started["state"]["units"] if unit["type"] == "king")
        self.assertEqual((king["x"], king["y"]), (14, 7))
        self.assertEqual(started["state"]["capture_status"], "KING GUARDED")
        self.assertEqual(Client().get(reverse("current-game")).status_code, 404)
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"] = [unit for unit in instance.state["units"]
                                   if unit["side"] != "defenders" or unit["type"] == "king"]
        instance.state["units"][0].update(x=14, y=8)
        instance.save(update_fields=["state"])
        result = self.action(0, {"type": "capture", "unit_id": 0})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["revision"], 1)
        self.assertEqual(result.json()["state"]["capture_status"], "KING CAPTURED")
        self.assertTrue(result.json()["state"]["captured"])
        self.assertEqual(result.json()["state"]["history"][-1]["type"], "capture")
        self.assertEqual(self.client.get(reverse("current-game")).json()["state"], result.json()["state"])
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).state["history"][-1]["type"], "capture")
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 409)
        self.assertEqual(self.action(1, {"type": "end_turn"}).status_code, 400)
        self.ai.assert_not_called()

    def test_seeded_assault_catapult_actions_persist_and_ai_uses_breaches(self):
        game = SingleGame.objects.get(slug="greywatch-assault")
        self.assertEqual(game.map_definition["catapults"], [{"x": 3, "y": 7}])
        self.assertEqual(game.map_definition["enemyStartPositions"], MAP["enemyStartPositions"])
        self.game = game
        started = self.start().json()
        self.assertEqual(started["map"]["enemyStartPositions"], MAP["enemyStartPositions"])
        self.assertEqual(started["state"]["catapults"][0]["ammo"], 3)
        aim = {"type": "aim_catapult", "unit_id": 1, "catapult_id": 0, "x": 11, "y": 7}
        self.assertEqual(self.action(0, {**aim, "x": True}).status_code, 400)
        aimed = self.action(0, aim)
        self.assertEqual(aimed.status_code, 200)
        self.assertEqual(aimed.json()["state"]["catapults"][0]["aim"], {"x": 11, "y": 7})
        self.assertEqual(self.action(0, aim).status_code, 409)
        self.assertEqual(self.action(1, {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0}).status_code, 400)
        self.assertEqual(self.action(1, {"type": "end_turn"}).status_code, 200)
        shot = self.action(2, {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0})
        self.assertEqual(shot.status_code, 200)
        self.assertEqual(shot.json()["combat_events"][0]["weapon"], "catapult")
        self.assertEqual(shot.json()["state"]["wall_damage"], [{"x": 11, "y": 7, "damage": 1}])
        self.assertEqual(self.client.get(reverse("current-game")).json()["state"], shot.json()["state"])
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).state["catapults"][0]["ammo"], 2)

        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["breaches"] = [{"x": 11, "y": 7}]
        instance.save(update_fields=["state"])
        instance.state["units"][6].update(x=10, y=7)
        instance.save(update_fields=["state"])
        self.set_ai_orders([{"unit_id": 6, "x": 12, "y": 7}])
        ended = self.action(3, {"type": "end_turn"})
        self.assertEqual(ended.status_code, 200)
        self.assertEqual((ended.json()["state"]["units"][6]["x"],
                          ended.json()["state"]["units"][6]["y"]), (12, 7))
        self.assertEqual(ended.json()["state"]["breaches"], [{"x": 11, "y": 7}])
        self.assertIn("breaches", json.loads(json.loads(self.ai.call_args.args[0].data)["messages"][1]["content"].split("\n")[0])["map"])

    def test_king_killed_is_defeat_and_ai_cannot_order_king(self):
        throne = SingleGame.objects.get(slug="greywatch-throne-room")
        started = self.client.post(reverse("start-game", args=["single-games", throne.pk])).json()
        instance = GameInstance.objects.get(pk=started["id"])
        king = next(unit for unit in instance.state["units"] if unit["type"] == "king")
        instance.state["units"][0].update(x=14, y=8)
        king["health"] = 1
        instance.save(update_fields=["state"])
        self.assertEqual(self.action(0, {"type": "capture", "unit_id": 0}).status_code, 400)
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 200)
        request = self.ai.call_args.args[0]
        ai_input = json.loads(json.loads(request.data)["messages"][1]["content"].split("\n")[0])
        self.assertEqual(ai_input["map"]["mission"], "capture_king")
        self.assertIn("king", [unit["type"] for unit in ai_input["units"]])
        self.set_ai_orders([{"unit_id": king["id"], "x": 14, "y": 8}])
        self.assertEqual(self.action(1, {"type": "end_turn"}).status_code, 502)
        self.set_ai_orders([])
        defeated = self.action(1, {"type": "attack", "unit_id": 0, "target_id": king["id"]})
        self.assertEqual(defeated.status_code, 200)
        self.assertTrue(defeated.json()["state"]["defeated"])
        self.assertFalse(defeated.json()["state"]["captured"])
        self.assertEqual(defeated.json()["state"]["capture_status"], "DEFEATED")
        self.assertEqual(self.action(2, {"type": "end_turn"}).status_code, 400)

    def test_start_load_move_and_resume_server_owned_game(self):
        started = self.start()
        self.assertEqual(started.status_code, 201)
        data = started.json()
        self.assertEqual(data["map"], MAP)
        self.assertEqual(data["entry"]["name"], self.game.name)
        self.assertEqual(data["state"]["units"][0]["move_points"], 4)
        self.assertEqual(data["state"]["units"][0]["health"], 3)
        self.assertEqual(data["state"]["units"][0]["fight_points"], 1)
        self.assertEqual(data["state"]["units"][0]["morale"], 3)
        self.assertEqual(data["state"]["units"][0]["rank"], "recruit")
        self.assertEqual(data["state"]["history"], [])
        self.assertEqual(len([unit for unit in data["state"]["units"] if unit["side"] == "defenders"]), 3)
        self.assertEqual(GameInstance.objects.count(), 1)

        moved = self.action(0, {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["state"]["units"][0]["x"], 3)
        self.assertEqual(moved.json()["revision"], 1)
        self.assertEqual(moved.json()["combat_events"], [])
        self.assertEqual(self.client.get(reverse("current-game")).json(),
                         {key: value for key, value in moved.json().items() if key != "combat_events"})
        self.assertEqual(GameInstance.objects.get(pk=data["id"]).state["units"][0]["x"], 3)

        next_turn = self.action(1, {"type": "end_turn"})
        self.assertEqual(next_turn.json()["state"]["turn"], 2)
        self.assertEqual(next_turn.json()["state"]["units"][0]["move_points"], 4)
        request = self.ai.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11435/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL")
        battlefield = json.loads(json.loads(request.data)["messages"][1]["content"].split("\n")[0])
        self.assertEqual(battlefield["map"]["objective"], {"x": 14, "y": 7})
        self.assertEqual([unit["id"] for unit in battlefield["units"] if unit["side"] == "defenders"], [6, 7, 8])
        self.assertEqual((battlefield["units"][0]["morale"], battlefield["units"][0]["rank"]),
                         (3, "recruit"))
        self.assertNotIn("test-only-key", json.dumps(next_turn.json()))
        self.assertNotIn("test-only-key", request.data.decode())

    def test_elevated_map_is_snapshotted_and_shared_with_defender_ai(self):
        battlefield = default_map()
        battlefield["startPositions"] = [{"x": 2, "y": 5, "type": "vanguard"}]
        battlefield["elevation"] = [{"x": 3, "y": 5, "height": 1, "access": "ramp"}]
        self.game.map_definition = battlefield
        self.game.full_clean()
        self.game.save()
        started = self.start().json()
        self.assertEqual(started["map"]["elevation"], battlefield["elevation"])
        moved = self.action(0, {"type": "move", "units": [0], "x": 3, "y": 5}).json()
        self.assertEqual((moved["state"]["units"][0]["z"],
                          moved["state"]["units"][0]["move_points"]), (1, 3))
        battlefield["elevation"] = []
        self.game.map_definition = battlefield
        self.game.save()
        self.assertEqual(self.client.get(reverse("current-game")).json()["map"]["elevation"],
                         [{"x": 3, "y": 5, "height": 1, "access": "ramp"}])
        ended = self.action(1, {"type": "end_turn"})
        self.assertEqual(ended.status_code, 200)
        request = self.ai.call_args.args[0]
        ai_map = json.loads(json.loads(request.data)["messages"][1]["content"].split("\n")[0])["map"]
        self.assertEqual(ai_map["elevation"], started["map"]["elevation"])

    def test_map_objects_remain_in_active_match_after_editor_changes(self):
        battlefield = default_map()
        battlefield["objects"] = [{"x": 3, "y": 6, "type": "tree"},
                                  {"x": 5, "y": 6, "type": "rock"}]
        self.game.map_definition = battlefield
        self.game.full_clean()
        self.game.save()
        started = self.start().json()
        self.assertEqual(started["map"]["objects"], battlefield["objects"])
        battlefield["objects"] = []
        self.game.map_definition = battlefield
        self.game.save()
        self.assertEqual(self.action(0, {"type": "move", "units": [0], "x": 3, "y": 6}).status_code, 400)
        self.assertEqual(self.client.get(reverse("current-game")).json()["map"]["objects"],
                         started["map"]["objects"])
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 200)
        request = self.ai.call_args.args[0]
        ai_map = json.loads(json.loads(request.data)["messages"][1]["content"].split("\n")[0])["map"]
        self.assertEqual(ai_map["objects"], started["map"]["objects"])
        self.assertEqual(self.start().json()["map"]["objects"], [])

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
        self.assertEqual(attacked.json()["combat_events"], [])
        self.assertNotIn("combat_events", self.client.get(reverse("current-game")).json())

    def test_combat_history_survives_reload_and_resets_on_restart(self):
        started = self.start().json()
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"][2].update(x=2, y=6)
        instance.state["units"][6].update(x=6, y=6, health=1)
        instance.save(update_fields=["state"])
        attacked = self.action(0, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        self.assertEqual(attacked.status_code, 200)
        event = attacked.json()["state"]["history"][0]
        self.assertEqual((event["turn"], event["actor_id"], event["target_id"], event["killed"]),
                         (1, 2, 6, True))
        self.assertEqual(event["morale_changes"], [{"unit_id": 2, "change": 1}])
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).state["history"], [event])
        self.assertEqual(self.client.get(reverse("current-game")).json()["state"]["history"], [event])
        self.assertNotIn("combat_events", GameInstance.objects.get(pk=started["id"]).state)
        self.assertEqual(self.action(0, {"type": "end_turn"}).status_code, 409)
        self.assertEqual(self.start().json()["state"]["history"], [])

    def test_promotion_requires_morale_and_persists_veteran_allowances(self):
        started = self.start().json()
        self.assertEqual(self.action(0, {"type": "promote", "unit_id": 0}).status_code, 400)
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"][0]["morale"] = 5
        instance.save(update_fields=["state"])
        result = self.action(0, {"type": "promote", "unit_id": 0})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["revision"], 1)
        self.assertEqual(result.json()["state"]["units"][0]["rank"], "veteran")
        self.assertEqual(result.json()["state"]["units"][0]["morale"], 3)
        self.assertEqual(result.json()["combat_events"], [])
        self.assertEqual(self.action(0, {"type": "promote", "unit_id": 0}).status_code, 409)
        self.assertEqual(self.action(1, {"type": "promote", "unit_id": 0}).status_code, 400)
        ended = self.action(1, {"type": "end_turn"})
        self.assertEqual(ended.status_code, 200)
        self.assertEqual((ended.json()["state"]["units"][0]["move_points"],
                          ended.json()["state"]["units"][0]["fight_points"]), (5, 2))
        self.assertNotIn("combat_events", self.client.get(reverse("current-game")).json())

    def test_ranged_attack_persists_damage_and_reload_state(self):
        started = self.start().json()
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"][2].update(x=2, y=6)
        instance.state["units"][6].update(x=6, y=6)
        instance.save(update_fields=["state"])

        attacked = self.action(0, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        self.assertEqual(attacked.status_code, 200)
        units = {unit["id"]: unit for unit in attacked.json()["state"]["units"]}
        self.assertEqual(units[2]["reload_turns"], 2)
        self.assertEqual(units[6]["health"], 2)
        self.assertEqual(attacked.json()["combat_events"], [{
            "type": "projectile", "weapon": "longbow",
            "from": {"x": 2, "y": 6}, "to": {"x": 6, "y": 6},
        }])
        self.assertNotIn("combat_events", self.client.get(reverse("current-game")).json())
        self.assertNotIn("combat_events", GameInstance.objects.get(pk=started["id"]).state)

    def test_cover_blocks_one_shot_across_saved_actions(self):
        battlefield = default_map()
        battlefield["objects"] = [{"x": 5, "y": 4, "type": "rock"}]
        self.game.map_definition = battlefield
        self.game.full_clean()
        self.game.save()
        started = self.start().json()
        instance = GameInstance.objects.get(pk=started["id"])
        instance.state["units"][2].update(x=3, y=5)
        instance.state["units"][6].update(x=6, y=5)
        instance.save(update_fields=["state"])

        action = lambda unit_id: {"type": "ranged_attack", "unit_id": unit_id, "target_id": 6}
        blocked = self.action(0, action(2))
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.json()["state"]["units"][6]["health"], 3)
        self.assertEqual(blocked.json()["state"]["history"][0]["cover"], "rock")
        self.assertEqual(blocked.json()["state"]["units"][6]["cover_turn"], 1)
        self.assertEqual(len(blocked.json()["combat_events"]), 1)
        self.assertEqual(self.client.get(reverse("current-game")).json()["state"]["history"],
                         blocked.json()["state"]["history"])

        second = self.action(1, action(3))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["state"]["units"][6]["health"], 2)
        self.assertEqual(second.json()["state"]["history"][1]["damage"], 1)
        self.assertNotIn("cover", second.json()["state"]["history"][1])

    def test_defender_turn_reports_multiple_shots_even_when_a_target_dies(self):
        started = self.start().json()
        instance = GameInstance.objects.get(pk=started["id"])
        units = instance.state["units"]
        units[0].update(x=4, y=6, health=1)
        units[1].update(x=5, y=7)
        units[6].update(x=6, y=6, type="longbow")
        units[7].update(x=7, y=7, type="crossbow")
        instance.save(update_fields=["state"])

        result = self.action(0, {"type": "end_turn"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["combat_events"], [
            {"type": "projectile", "weapon": "longbow",
             "from": {"x": 6, "y": 6}, "to": {"x": 4, "y": 6}},
            {"type": "projectile", "weapon": "crossbow",
             "from": {"x": 7, "y": 7}, "to": {"x": 5, "y": 7}},
        ])
        self.assertNotIn(0, [unit["id"] for unit in result.json()["state"]["units"]])
        self.assertNotIn("combat_events", self.client.get(reverse("current-game")).json())

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
        self.assertEqual(self.client.get(reverse("current-game")).json(),
                         {key: value for key, value in turn.json().items() if key != "combat_events"})
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).revision, 1)

        self.ai.side_effect = URLError("private-network-detail")
        unavailable = self.action(1, {"type": "end_turn"})
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(self.client.get(reverse("current-game")).json(),
                         {key: value for key, value in turn.json().items() if key != "combat_events"})
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
