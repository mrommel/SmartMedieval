from django.test import TestCase

from ..engine import (
    HISTORY_LIMIT, MAP, InvalidAction, InvalidMap, apply_action, can_step, capture_status, default_map, defender_destinations, find_path,
    carried_weight, has_line_of_sight, initial_state, is_walkable, move_allowance, normalize_map,
    record_attack, resolve_defender_goals, validate_map, visible_tiles,
)


class WithdrawalTests(TestCase):
    def setUp(self):
        self.battlefield = default_map()
        self.battlefield.update(
            exit={"x": 2, "y": 6},
            startPositions=[{"x": 2, "y": 6, "weapon": "sword", "armor": "leather", "tools": ["rope"]},
                            {"x": 3, "y": 6, "weapon": "longbow"}],
            enemyStartPositions=[{"x": 4, "y": 6, "weapon": "sword"}],
            items=[{"x": 2, "y": 6, "type": "healing_potion"}],
            horses=[{"x": 2, "y": 6}],
        )

    def withdraw(self, state, unit_id=0):
        return apply_action(state, {"type": "withdraw", "unit_id": unit_id}, self.battlefield)

    def test_exit_validation_and_legacy_maps(self):
        validate_map(self.battlefield)
        for exit_tile in ({"x": True, "y": 6}, {"x": 100, "y": 6},
                          {"x": 2}, self.battlefield["objective"], {"x": 2, "y": 6, "z": 0}):
            with self.subTest(exit=exit_tile), self.assertRaises(InvalidMap):
                validate_map({**self.battlefield, "exit": exit_tile})
        with self.assertRaises(InvalidMap):
            validate_map({**self.battlefield, "exit": {"x": 2, "y": 6},
                          "elevation": [{"x": 2, "y": 6, "height": 1, "access": "ramp"}]})
        with self.assertRaises(InvalidMap):
            validate_map({**self.battlefield, "exit": {"x": 0, "y": 0},
                          "objects": [{"x": 1, "y": 0, "type": "rock"},
                                      {"x": 0, "y": 1, "type": "rock"}]})
        legacy = default_map()
        with self.assertRaises(InvalidAction):
            apply_action(initial_state(legacy), {"type": "withdraw", "unit_id": 0}, legacy)

    def test_withdraw_preserves_inventory_horse_and_original_state(self):
        state = initial_state(self.battlefield)
        state["items"][0]["carrier_id"] = 0
        state["units"][0]["mount_id"] = 0
        state["horses"][0]["rider_id"] = 0
        result = self.withdraw(state)
        self.assertEqual(len(state["units"]), 3)
        self.assertEqual([unit["id"] for unit in result["units"]], [1, 2])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["horses"], [])
        survivor = result["withdrawn"][0]
        self.assertEqual((survivor["id"], survivor["fight_points"], survivor["armor"], survivor["tools"]),
                         (0, 0, "leather", ["rope"]))
        self.assertEqual(survivor["items"][0]["type"], "healing_potion")
        self.assertEqual(survivor["horse"]["id"], 0)
        self.assertFalse(result["captured"])
        with self.assertRaises(InvalidAction):
            self.withdraw(result)

    def test_last_soldier_withdraws_and_battle_locks(self):
        state = initial_state(self.battlefield)
        state["units"].remove(state["units"][1])
        result = self.withdraw(state)
        self.assertTrue(result["captured"])
        self.assertFalse(result["defeated"])
        self.assertEqual(capture_status(result, self.battlefield), "WITHDRAWN")
        with self.assertRaises(InvalidAction):
            apply_action(result, {"type": "end_turn"}, self.battlefield)

    def test_partial_withdrawal_then_last_soldier_falls_is_retreat(self):
        state = self.withdraw(initial_state(self.battlefield))
        state["units"][0]["health"] = 1
        result = apply_action(state, {"type": "end_turn"}, self.battlefield, enemy_orders=[])
        self.assertTrue(result["captured"])
        self.assertFalse(result["defeated"])
        self.assertEqual(capture_status(result, self.battlefield), "WITHDRAWN")

    def test_invalid_orders_do_not_change_state(self):
        state = initial_state(self.battlefield)
        for action in ({"type": "withdraw", "unit_id": True}, {"type": "withdraw", "unit_id": 2},
                       {"type": "withdraw", "unit_id": 1},
                       {"type": "withdraw", "unit_id": 0, "extra": 1}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, self.battlefield)
        state["units"][0]["fight_points"] = 0
        with self.assertRaises(InvalidAction):
            self.withdraw(state)
        self.assertEqual(state["withdrawn"], [])


class CrouchTests(TestCase):
    def setUp(self):
        self.battlefield = default_map()
        self.battlefield["startPositions"] = [{"x": 2, "y": 6, "weapon": "sword", "armor": "leather"}]
        self.battlefield["enemyStartPositions"] = [{"x": 6, "y": 6, "weapon": "longbow"}]

    def crouch(self, state):
        return apply_action(state, {"type": "crouch", "unit_id": 0}, self.battlefield)

    def test_cost_lockout_and_expiry(self):
        state = initial_state(self.battlefield)
        del state["units"][0]["crouched"]  # Legacy matches are standing.
        crouched = self.crouch(state)
        self.assertFalse(state["units"][0].get("crouched", False))
        self.assertEqual((crouched["units"][0]["fight_points"], crouched["units"][0]["move_points"]), (0, 0))
        self.assertTrue(crouched["units"][0]["crouched"])
        for action in ({"type": "move", "units": [0], "x": 3, "y": 6},
                       {"type": "reserve_movement", "unit_id": 0, "reserved": True},
                       {"type": "crouch", "unit_id": 0}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(crouched, action, self.battlefield)
        next_turn = apply_action(crouched, {"type": "end_turn"}, self.battlefield, enemy_orders=[])
        self.assertFalse(next_turn["units"][0]["crouched"])
        self.assertGreater(next_turn["units"][0]["move_points"], 0)

    def test_defender_shot_is_blocked_then_stance_expires(self):
        state = self.crouch(initial_state(self.battlefield))
        next_turn = apply_action(state, {"type": "end_turn"}, self.battlefield, enemy_orders=[])
        self.assertEqual(next_turn["units"][0]["health"], 3)
        self.assertEqual(next_turn["history"][-1]["stance_blocked"], 1)
        self.assertFalse(next_turn["units"][0]["crouched"])

    def test_dropping_weight_does_not_restore_crouched_movement(self):
        state = initial_state(self.battlefield)
        state["units"][0].update(rank="veteran", fight_points=2, fight_capacity=2)
        state = self.crouch(state)
        state = apply_action(state, {"type": "drop_armor", "unit_id": 0}, self.battlefield)
        self.assertEqual(state["units"][0]["move_points"], 0)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6}, self.battlefield)

    def test_validation(self):
        state = initial_state(self.battlefield)
        for action in ({"type": "crouch", "unit_id": True}, {"type": "crouch", "unit_id": 1},
                       {"type": "crouch", "unit_id": 0, "extra": 1}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, self.battlefield)
        state["units"][0]["fight_points"] = 0
        with self.assertRaises(InvalidAction):
            self.crouch(state)
        state = initial_state(self.battlefield)
        state = apply_action(state, {"type": "reserve_movement", "unit_id": 0, "reserved": True}, self.battlefield)
        with self.assertRaises(InvalidAction):
            self.crouch(state)

    def test_ranged_defense_stacks_with_armor_but_not_melee_or_catapult(self):
        state = self.crouch(initial_state(self.battlefield))
        record_attack(state, state["units"][1], state["units"][0], True, self.battlefield, damage=3)
        self.assertEqual(state["units"][0]["health"], 2)
        self.assertEqual(state["history"][-1]["stance_blocked"], 1)
        self.assertEqual(state["history"][-1]["armor_blocked"], 1)
        record_attack(state, state["units"][1], state["units"][0], False, self.battlefield)
        self.assertEqual(state["units"][0]["health"], 1)
        self.assertNotIn("stance_blocked", state["history"][-1])
        record_attack(state, state["units"][1], state["units"][0], True, self.battlefield,
                      damage=1, weapon="catapult")
        self.assertNotIn("stance_blocked", state["history"][-1])


class ReactionTests(TestCase):
    def battlefield(self, weapon="sword", defender_x=5, fog=False):
        battlefield = default_map()
        battlefield["startPositions"] = [{"x": 2, "y": 6, "weapon": weapon}]
        battlefield["enemyStartPositions"] = [{"x": defender_x, "y": 6, "weapon": "sword"}]
        if fog:
            battlefield["fog_of_war"] = True
        return battlefield

    def reserve(self, state, battlefield, reserved=True):
        return apply_action(state, {"type": "reserve_reaction", "unit_id": 0, "reserved": reserved}, battlefield)

    def reserve_movement(self, state, battlefield, reserved=True):
        return apply_action(state, {"type": "reserve_movement", "unit_id": 0, "reserved": reserved}, battlefield)

    def test_movement_reservation_validation_cancel_and_legacy_state(self):
        battlefield = self.battlefield()
        original = initial_state(battlefield)
        del original["units"][0]["move_reserved"]
        for action in ({"type": "reserve_movement", "unit_id": 0, "reserved": 1},
                       {"type": "reserve_movement", "unit_id": True, "reserved": True},
                       {"type": "reserve_movement", "unit_id": 1, "reserved": True},
                       {"type": "reserve_movement", "unit_id": 0, "reserved": True, "extra": 1}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(original, action, battlefield)
        armed = self.reserve_movement(original, battlefield)
        self.assertEqual((armed["units"][0]["move_points"], armed["units"][0]["move_reserved"]), (0, 4))
        self.assertEqual(original["units"][0]["move_points"], 4)
        with self.assertRaises(InvalidAction):
            self.reserve_movement(armed, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(armed, {"type": "move", "units": [0], "x": 1, "y": 6}, battlefield)
        cancelled = self.reserve_movement(armed, battlefield, False)
        self.assertEqual((cancelled["units"][0]["move_points"], cancelled["units"][0]["move_reserved"]), (4, 0))
        with self.assertRaises(InvalidAction):
            self.reserve_movement(cancelled, battlefield, False)
        spent = initial_state(battlefield)
        spent["units"][0]["move_points"] = 0
        with self.assertRaises(InvalidAction):
            self.reserve_movement(spent, battlefield)

    def test_movement_reaction_evasion_precedes_enemy_attack_and_expires(self):
        battlefield = self.battlefield()
        armed = self.reserve_movement(initial_state(battlefield), battlefield)
        result = apply_action(armed, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 1, "x": 3, "y": 6}])
        self.assertEqual((result["units"][0]["x"], result["units"][0]["y"]), (1, 6))
        self.assertEqual(result["units"][0]["health"], 3)
        self.assertEqual(result["history"], [])
        self.assertEqual(result["units"][0]["move_reserved"], 0)
        self.assertEqual(result["units"][0]["move_points"], 4)
        idle = apply_action(armed, {"type": "end_turn"}, battlefield, enemy_orders=[])
        self.assertEqual((idle["units"][0]["x"], idle["units"][0]["move_reserved"]), (2, 0))

    def test_movement_reaction_respects_terrain_cost(self):
        battlefield = self.battlefield()
        battlefield["terrain"] = [{"x": 1, "y": 6, "type": "grass"},
                                  {"x": 2, "y": 5, "type": "mud"},
                                  {"x": 2, "y": 7, "type": "swamp"}]
        state = initial_state(battlefield)
        state["units"][0]["move_points"] = 2
        armed = self.reserve_movement(state, battlefield)
        result = apply_action(armed, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 1, "x": 3, "y": 6}])
        self.assertEqual((result["units"][0]["x"], result["units"][0]["y"]), (1, 6))
        state["units"][0]["move_points"] = 1
        armed = self.reserve_movement(state, battlefield)
        result = apply_action(armed, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 1, "x": 3, "y": 6}])
        self.assertEqual((result["units"][0]["x"], result["units"][0]["y"]), (2, 6))

    def test_movement_reaction_does_not_enter_occupied_or_blocked_exits(self):
        battlefield = self.battlefield()
        battlefield["objects"] = [{"x": 1, "y": 6, "type": "rock"},
                                  {"x": 2, "y": 5, "type": "tree"}]
        battlefield["startPositions"].append({"x": 2, "y": 7, "weapon": "sword"})
        state = self.reserve_movement(initial_state(battlefield), battlefield)
        result = apply_action(state, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 2, "x": 3, "y": 6}])
        self.assertEqual((result["units"][0]["x"], result["units"][0]["y"]), (2, 6))
        self.assertEqual(result["units"][0]["health"], 2)
        self.assertEqual(result["units"][0]["move_reserved"], 0)

    def test_reservation_reconciles_equipment_weight_changes(self):
        battlefield = self.battlefield("crossbow")
        state = self.reserve_movement(initial_state(battlefield), battlefield)
        self.assertEqual(state["units"][0]["move_reserved"], 3)
        state = apply_action(state, {"type": "drop_weapon", "unit_id": 0}, battlefield)
        self.assertEqual((state["units"][0]["move_capacity"], state["units"][0]["move_points"],
                          state["units"][0]["move_reserved"]), (4, 1, 3))
        state = self.reserve_movement(state, battlefield, False)
        self.assertEqual((state["units"][0]["move_points"], state["units"][0]["move_reserved"]), (4, 0))
        battlefield = self.battlefield("sword")
        battlefield["items"] = [{"x": 2, "y": 6, "type": "armor", "name": "mail"}]
        state = self.reserve_movement(initial_state(battlefield), battlefield)
        state = apply_action(state, {"type": "pickup_equipment", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual((state["units"][0]["move_capacity"], state["units"][0]["move_reserved"]), (3, 3))
        state = self.reserve_movement(state, battlefield, False)
        self.assertEqual(state["units"][0]["move_points"], 3)

    def test_mounted_movement_reaction_moves_horse_and_combines_with_attack(self):
        battlefield = self.battlefield()
        battlefield["horses"] = [{"x": 2, "y": 6}]
        state = initial_state(battlefield)
        state["units"][0].update(rank="veteran", fight_points=2, fight_capacity=2)
        state = apply_action(state, {"type": "mount", "unit_id": 0, "horse_id": 0}, battlefield)
        state = self.reserve_movement(self.reserve(state, battlefield), battlefield)
        result = apply_action(state, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 1, "x": 3, "y": 6}])
        self.assertEqual((result["units"][0]["x"], result["horses"][0]["x"]), (1, 1))
        self.assertTrue(result["history"][-1]["reaction"])

    def test_reservation_cost_cancellation_and_validation(self):
        battlefield = self.battlefield()
        original = initial_state(battlefield)
        for action in ({"type": "reserve_reaction", "unit_id": 0, "reserved": 1},
                       {"type": "reserve_reaction", "unit_id": True, "reserved": True},
                       {"type": "reserve_reaction", "unit_id": 1, "reserved": True},
                       {"type": "reserve_reaction", "unit_id": 0, "reserved": True, "extra": 1}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(original, action, battlefield)
        armed = self.reserve(original, battlefield)
        self.assertEqual((armed["units"][0]["fight_points"], armed["units"][0]["reaction_reserved"]), (0, True))
        self.assertEqual(original["units"][0]["fight_points"], 1)
        with self.assertRaises(InvalidAction):
            self.reserve(armed, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(armed, {"type": "attack", "unit_id": 0, "target_id": 1}, battlefield)
        cancelled = self.reserve(armed, battlefield, False)
        self.assertEqual((cancelled["units"][0]["fight_points"], cancelled["units"][0]["reaction_reserved"]), (1, False))
        with self.assertRaises(InvalidAction):
            self.reserve(cancelled, battlefield, False)
        spent = initial_state(battlefield)
        spent["units"][0]["fight_points"] = 0
        with self.assertRaises(InvalidAction):
            self.reserve(spent, battlefield)
        unarmed = initial_state(battlefield)
        unarmed["units"][0]["weapon"] = None
        with self.assertRaises(InvalidAction):
            self.reserve(unarmed, battlefield)
        reloading_map = self.battlefield("crossbow")
        reloading = initial_state(reloading_map)
        reloading["units"][0]["reload_turns"] = 1
        with self.assertRaises(InvalidAction):
            self.reserve(reloading, reloading_map)

    def test_melee_reacts_on_entry_before_defender_can_attack(self):
        battlefield = self.battlefield()
        state = self.reserve(initial_state(battlefield), battlefield)
        state["units"][1]["health"] = 1
        result = apply_action(state, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 1, "x": 3, "y": 6}])
        self.assertEqual(len(result["units"]), 1)
        self.assertEqual(result["units"][0]["health"], 3)
        self.assertTrue(result["history"][-1]["reaction"])
        self.assertEqual(result["history"][-1]["target_id"], 1)
        self.assertFalse(result["units"][0]["reaction_reserved"])
        self.assertEqual(result["units"][0]["fight_points"], 1)

    def test_ranged_reaction_fires_at_first_in_range_step_and_reloads(self):
        battlefield = self.battlefield("longbow", 9, fog=True)
        state = self.reserve(initial_state(battlefield), battlefield)
        events = []
        result = apply_action(state, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 1, "x": 6, "y": 6}], combat_events=events)
        self.assertEqual((events[0]["to"]["x"], events[0]["to"]["y"]), (7, 6))
        self.assertEqual(result["units"][1]["x"], 6)
        self.assertEqual(result["units"][1]["health"], 2)
        self.assertEqual(result["units"][0]["reload_turns"], 1)
        self.assertTrue(result["history"][-1]["reaction"])

    def test_out_of_range_or_unseen_reservations_expire(self):
        battlefield = self.battlefield("crossbow", 9, fog=True)
        state = self.reserve(initial_state(battlefield), battlefield)
        result = apply_action(state, {"type": "end_turn"}, battlefield, enemy_orders=[])
        self.assertFalse(result["units"][0]["reaction_reserved"])
        self.assertEqual(result["units"][0]["fight_points"], 1)
        self.assertEqual(result["history"], [])
        blocked = self.battlefield("longbow", 9, fog=True)
        blocked["objects"] = [{"x": 5, "y": 6, "type": "tree"}]
        state = self.reserve(initial_state(blocked), blocked)
        result = apply_action(state, {"type": "end_turn"}, blocked,
                              enemy_orders=[{"unit_id": 1, "x": 7, "y": 6}])
        self.assertFalse(any(event.get("reaction") for event in result["history"]))


class FogOfWarTests(TestCase):
    def fog_map(self):
        battlefield = default_map()
        battlefield["fog_of_war"] = True
        battlefield["startPositions"] = [{"x": 2, "y": 6, "weapon": "crossbow"}]
        battlefield["enemyStartPositions"] = [{"x": 9, "y": 6, "weapon": "sword"}]
        return battlefield

    def test_map_requires_boolean_and_old_games_do_not_gain_fog(self):
        battlefield = self.fog_map()
        validate_map(battlefield)
        for value in (0, 1, None, "true", []):
            battlefield["fog_of_war"] = value
            with self.subTest(value=value), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        self.assertNotIn("explored", initial_state())

    def test_sight_and_discovery_follow_moves_and_defenders_disappear_without_erasing_terrain(self):
        battlefield = self.fog_map()
        state = initial_state(battlefield)
        self.assertIn((8, 6), visible_tiles(state, battlefield))
        self.assertNotIn((9, 6), visible_tiles(state, battlefield))
        with self.assertRaisesMessage(InvalidAction, "visible defender"):
            apply_action(state, {"type": "ranged_attack", "unit_id": 0, "target_id": 1}, battlefield)
        state = apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6}, battlefield)
        self.assertIn((9, 6), visible_tiles(state, battlefield))
        self.assertIn({"x": 9, "y": 6}, state["explored"])
        state = apply_action(state, {"type": "end_turn"}, battlefield,
                             enemy_orders=[{"unit_id": 1, "x": 10, "y": 6}])
        self.assertNotIn((10, 6), visible_tiles(state, battlefield))
        self.assertIn({"x": 9, "y": 6}, state["explored"])

    def test_breached_walls_and_doorways_reveal_opponents(self):
        battlefield = self.fog_map()
        state = initial_state(battlefield)
        state["units"][0].update(x=10, y=5)
        state["units"][1].update(x=12, y=5)
        self.assertNotIn((12, 5), visible_tiles(state, battlefield))
        state["breaches"] = [{"x": 11, "y": 5}]
        self.assertIn((12, 5), visible_tiles(state, battlefield))

        battlefield["houses"] = [{"left": 4, "right": 5, "top": 2, "bottom": 3,
                                  "door": {"x": 4, "y": 3}}]
        state["units"][0].update(x=3, y=3)
        state["units"][1].update(x=4, y=3)
        self.assertIn((4, 3), visible_tiles(state, battlefield))
        self.assertNotIn((4, 2), visible_tiles(state, battlefield))


class NightBattleTests(TestCase):
    def night_map(self):
        battlefield = default_map()
        battlefield.update(fog_of_war=True, night=True,
                           startPositions=[{"x": 2, "y": 6, "weapon": "crossbow"}],
                           enemyStartPositions=[{"x": 7, "y": 6, "weapon": "sword"}])
        return battlefield

    def ambush_map(self):
        battlefield = self.night_map()
        battlefield["startPositions"].append({"x": 4, "y": 6, "weapon": "sword", "tools": ["torch"]})
        return battlefield

    def test_unseen_shooter_gets_bonus_but_torch_and_daylight_remove_surprise(self):
        battlefield = self.ambush_map()
        state = initial_state(battlefield)
        self.assertIn((7, 6), visible_tiles(state, battlefield))
        self.assertNotIn((2, 6), visible_tiles(state, battlefield, "defenders"))
        action = {"type": "ranged_attack", "unit_id": 0, "target_id": 2}
        result = apply_action(state, action, battlefield)
        self.assertEqual(result["history"][-1]["damage"], 2)
        self.assertTrue(result["history"][-1]["ambush"])
        self.assertEqual(result["units"][2]["health"], 1)
        self.assertEqual(state["units"][2]["health"], 3)

        battlefield["startPositions"][0]["tools"] = ["torch"]
        spotted = apply_action(initial_state(battlefield), action, battlefield)
        self.assertEqual(spotted["history"][-1]["damage"], 1)
        self.assertNotIn("ambush", spotted["history"][-1])
        battlefield["night"] = False
        daylight = apply_action(initial_state(battlefield), action, battlefield)
        self.assertNotIn("ambush", daylight["history"][-1])
        battlefield["fog_of_war"] = False
        battlefield.pop("night")
        legacy = apply_action(initial_state(battlefield), action, battlefield)
        self.assertNotIn("ambush", legacy["history"][-1])

    def test_extinguishing_torch_restores_ambush_when_ally_spots_target(self):
        battlefield = self.ambush_map()
        battlefield["startPositions"][0]["tools"] = ["torch"]
        state = initial_state(battlefield)
        self.assertIn((2, 6), visible_tiles(state, battlefield, "defenders"))
        dark = apply_action(state, {"type": "toggle_torch", "unit_id": 0, "lit": False}, battlefield)
        self.assertNotIn((2, 6), visible_tiles(dark, battlefield, "defenders"))
        self.assertIn((7, 6), visible_tiles(dark, battlefield))
        dark = apply_action(dark, {"type": "end_turn"}, battlefield, enemy_orders=[])
        attacked = apply_action(dark, {"type": "ranged_attack", "unit_id": 0, "target_id": 2}, battlefield)
        self.assertTrue(attacked["history"][-1]["ambush"])
        self.assertEqual(attacked["history"][-1]["damage"], 2)

    def test_ambush_still_respects_cover_armor_and_indirect_fire(self):
        battlefield = self.ambush_map()
        battlefield["objects"] = [{"x": 6, "y": 5, "type": "fence"}]
        state = initial_state(battlefield)
        blocked = apply_action(state, {"type": "ranged_attack", "unit_id": 0, "target_id": 2}, battlefield)
        self.assertEqual(blocked["history"][-1]["damage"], 0)
        self.assertEqual(blocked["history"][-1]["cover"], "fence")
        self.assertTrue(blocked["history"][-1]["ambush"])
        state["units"][2].update(armor="mail", armor_equipped=True, cover_turn=state["turn"])
        armored = apply_action(state, {"type": "ranged_attack", "unit_id": 0, "target_id": 2}, battlefield)
        self.assertEqual(armored["history"][-1]["armor_blocked"], 2)
        self.assertEqual(armored["history"][-1]["damage"], 0)
        record_attack(state, state["units"][0], state["units"][2], False, battlefield,
                      damage=2, weapon="catapult")
        self.assertNotIn("ambush", state["history"][-1])

    def test_reaction_ambush_and_defender_attacks_need_sight(self):
        battlefield = self.ambush_map()
        battlefield["startPositions"][0]["weapon"] = "longbow"
        battlefield["enemyStartPositions"][0]["x"] = 9
        state = apply_action(initial_state(battlefield),
                             {"type": "reserve_reaction", "unit_id": 0, "reserved": True}, battlefield)
        result = apply_action(state, {"type": "end_turn"}, battlefield,
                              enemy_orders=[{"unit_id": 2, "x": 7, "y": 6}])
        self.assertTrue(result["history"][0]["reaction"])
        self.assertTrue(result["history"][0]["ambush"])
        self.assertEqual(result["history"][0]["damage"], 2)

        battlefield = self.night_map()
        battlefield["enemyStartPositions"][0]["weapon"] = "crossbow"
        hidden = apply_action(initial_state(battlefield), {"type": "end_turn"}, battlefield)
        self.assertEqual(hidden["history"], [])
        battlefield["enemyStartPositions"].append(
            {"x": 5, "y": 6, "weapon": "sword", "tools": ["torch"]})
        spotted = apply_action(initial_state(battlefield), {"type": "end_turn"}, battlefield)
        self.assertEqual(spotted["history"][0]["actor_id"], 1)
        self.assertTrue(spotted["history"][0]["ambush"])
        self.assertEqual(spotted["history"][0]["damage"], 2)

    def test_night_and_watchfires_require_valid_map_fields(self):
        battlefield = self.night_map()
        validate_map(battlefield)
        for change in ({"night": 1}, {"fog_of_war": False}, {"watchfires": "invalid"},
                       {"watchfires": [{"x": 2, "y": 6}, {"x": 2, "y": 6}]},
                       {"watchfires": [{"x": True, "y": 6}]},
                       {"watchfires": [{"x": 11, "y": 5}]},
                       {"watchfires": [{"x": 1, "y": 6, "type": "fire"}]}):
            with self.subTest(change=change), self.assertRaises(InvalidMap):
                validate_map({**battlefield, **change})
        with self.assertRaises(InvalidMap):
            validate_map({**default_map(), "watchfires": []})

    def test_torches_extend_sight_but_expose_bearers_and_can_be_dropped(self):
        battlefield = self.night_map()
        state = initial_state(battlefield)
        self.assertNotIn((7, 6), visible_tiles(state, battlefield))
        self.assertNotIn((2, 6), visible_tiles(state, battlefield, "defenders"))
        with self.assertRaisesMessage(InvalidAction, "visible defender"):
            apply_action(state, {"type": "ranged_attack", "unit_id": 0, "target_id": 1}, battlefield)
        battlefield["startPositions"][0]["tools"] = ["torch"]
        state = initial_state(battlefield)
        self.assertIn((7, 6), visible_tiles(state, battlefield))
        self.assertIn((2, 6), visible_tiles(state, battlefield, "defenders"))
        dropped = apply_action(state, {"type": "drop_tool", "unit_id": 0, "tool_index": 0}, battlefield)
        self.assertNotIn((7, 6), visible_tiles(dropped, battlefield))
        self.assertNotIn((2, 6), visible_tiles(dropped, battlefield, "defenders"))
        self.assertIn({"x": 7, "y": 6}, dropped["explored"])

    def test_torch_toggle_changes_sight_without_dropping_or_changing_load(self):
        battlefield = self.night_map()
        battlefield["startPositions"][0]["tools"] = ["torch"]
        state = initial_state(battlefield)
        del state["units"][0]["torch_lit"]  # Old saved matches start with lit torches.
        dark = apply_action(state, {"type": "toggle_torch", "unit_id": 0, "lit": False}, battlefield)
        self.assertNotIn("torch_lit", state["units"][0])
        self.assertFalse(dark["units"][0]["torch_lit"])
        self.assertEqual(dark["units"][0]["tools"], ["torch"])
        self.assertEqual(dark["units"][0]["move_points"], state["units"][0]["move_points"])
        self.assertEqual(dark["units"][0]["fight_points"], 0)
        self.assertEqual(dark["history"][-1]["lit"], False)
        self.assertNotIn((7, 6), visible_tiles(dark, battlefield))
        self.assertNotIn((2, 6), visible_tiles(dark, battlefield, "defenders"))
        self.assertIn({"x": 7, "y": 6}, dark["explored"])
        with self.assertRaises(InvalidAction):
            apply_action(dark, {"type": "toggle_torch", "unit_id": 0, "lit": True}, battlefield)
        next_turn = apply_action(dark, {"type": "end_turn"}, battlefield, enemy_orders=[])
        self.assertFalse(next_turn["units"][0]["torch_lit"])
        lit = apply_action(next_turn, {"type": "toggle_torch", "unit_id": 0, "lit": True}, battlefield)
        self.assertIn((7, 6), visible_tiles(lit, battlefield))
        self.assertIn((2, 6), visible_tiles(lit, battlefield, "defenders"))

    def test_torch_toggle_rejects_invalid_orders_and_pickup_relites_torch(self):
        battlefield = self.night_map()
        battlefield["startPositions"][0]["tools"] = ["torch"]
        state = initial_state(battlefield)
        base = {"type": "toggle_torch", "unit_id": 0, "lit": False}
        for action in ({**base, "unit_id": True}, {**base, "unit_id": 1},
                       {**base, "lit": 0}, {**base, "lit": True},
                       {**base, "extra": 1}, {"type": "toggle_torch", "unit_id": 0}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)
        battlefield["night"] = False
        with self.assertRaises(InvalidAction):
            apply_action(state, base, battlefield)
        battlefield["night"] = True
        state["units"][0]["tools"] = []
        with self.assertRaises(InvalidAction):
            apply_action(state, base, battlefield)
        state["units"][0]["tools"] = ["torch"]
        dark = apply_action(state, base, battlefield)
        next_turn = apply_action(dark, {"type": "end_turn"}, battlefield, enemy_orders=[])
        dropped = apply_action(next_turn, {"type": "drop_tool", "unit_id": 0, "tool_index": 0}, battlefield)
        self.assertTrue(dropped["units"][0]["torch_lit"])
        next_turn = apply_action(dropped, {"type": "end_turn"}, battlefield, enemy_orders=[])
        recovered = apply_action(next_turn, {"type": "pickup_tool", "unit_id": 0,
                                             "item_id": dropped["items"][-1]["id"]}, battlefield)
        self.assertTrue(recovered["units"][0]["torch_lit"])
        self.assertIn((7, 6), visible_tiles(recovered, battlefield))

    def test_watchfires_light_tiles_for_both_sides_without_seeing_through_walls(self):
        battlefield = self.night_map()
        battlefield["watchfires"] = [{"x": 6, "y": 6}]
        state = initial_state(battlefield)
        self.assertIn((7, 6), visible_tiles(state, battlefield))
        self.assertNotIn((2, 6), visible_tiles(state, battlefield, "defenders"))
        battlefield["watchfires"] = [{"x": 3, "y": 6}]
        self.assertIn((2, 6), visible_tiles(state, battlefield, "defenders"))
        battlefield["watchfires"] = [{"x": 10, "y": 5}]
        state["units"][0].update(x=10, y=5)
        state["units"][1].update(x=12, y=5)
        self.assertNotIn((12, 5), visible_tiles(state, battlefield))
        state["breaches"] = [{"x": 11, "y": 5}]
        self.assertIn((12, 5), visible_tiles(state, battlefield))

    def test_watchfire_control_changes_both_sides_sight_and_survives_turns(self):
        battlefield = self.night_map()
        battlefield["startPositions"][0]["x"] = 3
        battlefield["watchfires"] = [{"x": 4, "y": 6}]
        state = initial_state(battlefield)
        self.assertIn((7, 6), visible_tiles(state, battlefield))
        self.assertIn((3, 6), visible_tiles(state, battlefield, "defenders"))
        # Saved matches made before dynamic fires were added still start with all fires lit.
        del state["extinguished_watchfires"]
        action = {"type": "extinguish_watchfire", "unit_id": 0, "x": 4, "y": 6}
        out = apply_action(state, action, battlefield)
        self.assertNotIn("extinguished_watchfires", state)
        self.assertEqual(out["extinguished_watchfires"], [{"x": 4, "y": 6}])
        self.assertEqual(out["units"][0]["fight_points"], 0)
        self.assertEqual(out["history"][-1]["type"], "extinguish_watchfire")
        self.assertNotIn((7, 6), visible_tiles(out, battlefield))
        self.assertNotIn((3, 6), visible_tiles(out, battlefield, "defenders"))
        self.assertIn({"x": 7, "y": 6}, out["explored"])
        next_turn = apply_action(out, {"type": "end_turn"}, battlefield)
        self.assertEqual(next_turn["extinguished_watchfires"], out["extinguished_watchfires"])
        lit = apply_action(next_turn, {"type": "light_watchfire", "unit_id": 0, "x": 4, "y": 6}, battlefield)
        self.assertEqual(lit["extinguished_watchfires"], [])
        self.assertIn((7, 6), visible_tiles(lit, battlefield))
        self.assertIn((3, 6), visible_tiles(lit, battlefield, "defenders"))

    def test_watchfire_control_rejects_forged_and_unaffordable_orders(self):
        battlefield = self.night_map()
        battlefield["startPositions"][0]["x"] = 3
        battlefield["watchfires"] = [{"x": 4, "y": 6}]
        state = initial_state(battlefield)
        base = {"type": "extinguish_watchfire", "unit_id": 0, "x": 4, "y": 6}
        for action in ({**base, "unit_id": True}, {**base, "x": 4.0},
                       {**base, "unit_id": 1}, {**base, "x": 9},
                       {**base, "x": 5}, {**base, "extra": 1},
                       {**base, "type": "light_watchfire"}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)
        state["units"][0]["x"] = 2
        with self.assertRaises(InvalidAction):
            apply_action(state, base, battlefield)
        state["units"][0]["x"] = 3
        state["units"][0]["fight_points"] = 0
        with self.assertRaises(InvalidAction):
            apply_action(state, base, battlefield)
        battlefield["night"] = False
        with self.assertRaises(InvalidAction):
            apply_action(initial_state(battlefield), base, battlefield)


class HorsebackRidingTests(TestCase):
    def horse_map(self):
        battlefield = default_map()
        battlefield["horses"] = [{"x": 2, "y": 6}]
        return battlefield

    def mount(self, state, battlefield):
        return apply_action(state, {"type": "mount", "unit_id": 0, "horse_id": 0}, battlefield)

    def test_map_validates_horse_positions_and_old_maps_need_no_horses(self):
        battlefield = self.horse_map()
        validate_map(battlefield)
        self.assertEqual(initial_state(battlefield)["horses"][0]["health"], 2)
        self.assertEqual(initial_state()["horses"], [])
        for horses in ("invalid", [{"x": 2, "y": 6}] * 2,
                       [{"x": 2, "y": 6}] * 17, [{"x": True, "y": 6}],
                       [{"x": 99, "y": 6}], [{"x": 11, "y": 7}],
                       [{"x": 14, "y": 7}], [{"x": 2, "y": 6, "health": 99}]):
            battlefield["horses"] = horses
            with self.subTest(horses=horses), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        for extra in ({"objects": [{"x": 2, "y": 6, "type": "tree"}]},
                      {"elevation": [{"x": 2, "y": 6, "height": 1, "access": "ramp"}]},
                      {"terrain": [{"x": 2, "y": 6, "type": "swamp"}]}):
            battlefield = self.horse_map()
            battlefield.update(extra)
            with self.subTest(extra=extra), self.assertRaises(InvalidMap):
                validate_map(battlefield)

    def test_mount_dismount_spend_fight_points_and_preserve_spent_movement(self):
        battlefield = self.horse_map()
        battlefield["startPositions"][0]["armor"] = "mail"
        state = initial_state(battlefield)
        state["units"][0]["move_points"] = 1  # 2 of 3 foot MP spent.
        original = initial_state(battlefield)
        for action in ({"type": "mount", "unit_id": True, "horse_id": 0},
                       {"type": "mount", "unit_id": 6, "horse_id": 0},
                       {"type": "mount", "unit_id": 0, "horse_id": False},
                       {"type": "mount", "unit_id": 1, "horse_id": 0},
                       {"type": "dismount", "unit_id": 0}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)
        ridden = self.mount(state, battlefield)
        self.assertEqual((ridden["units"][0]["mount_id"], ridden["horses"][0]["rider_id"]), (0, 0))
        self.assertEqual((ridden["units"][0]["move_capacity"], ridden["units"][0]["move_points"]), (6, 4))
        self.assertEqual(ridden["units"][0]["fight_points"], 0)
        self.assertEqual(state["horses"][0]["rider_id"], None)
        self.assertEqual(original["units"][0]["move_capacity"], 3)
        with self.assertRaises(InvalidAction):
            self.mount(ridden, battlefield)
        ridden["units"][0]["fight_points"] = 1
        walked = apply_action(ridden, {"type": "dismount", "unit_id": 0}, battlefield)
        self.assertEqual((walked["units"][0]["move_capacity"], walked["units"][0]["move_points"]), (3, 1))
        self.assertIsNone(walked["horses"][0]["rider_id"])

    def test_mounted_routes_use_horse_costs_and_cannot_enter_swamps_houses_or_ladders(self):
        battlefield = self.horse_map()
        battlefield["terrain"] = [{"x": 3, "y": 6, "type": "mud"},
                                  {"x": 4, "y": 6, "type": "swamp"}]
        state = self.mount(initial_state(battlefield), battlefield)
        self.assertEqual(state["units"][0]["move_points"], 6)
        moved = apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6}, battlefield)
        self.assertEqual((moved["units"][0]["x"], moved["units"][0]["move_points"]), (3, 2))
        self.assertEqual((moved["horses"][0]["x"], moved["horses"][0]["y"]), (3, 6))
        self.assertNotEqual(find_path((2, 6), (4, 6), battlefield, mounted=True), [(3, 6), (4, 6)])
        self.assertFalse(can_step((3, 6), (4, 6), battlefield, mounted=True))
        self.assertEqual(find_path((2, 6), (4, 6), battlefield)[:2], [(3, 6), (4, 6)])
        house = self.horse_map()
        house["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4,
                            "door": {"x": 4, "y": 4}}]
        self.assertIsNone(find_path((4, 5), (4, 4), house, mounted=True))
        self.assertIsNotNone(find_path((4, 5), (4, 4), house))
        house["elevation"] = [{"x": 3, "y": 6, "height": 1, "access": "ladder"}]
        self.assertFalse(can_step((2, 6), (3, 6), house, mounted=True))
        house["elevation"][0]["access"] = "ramp"
        self.assertTrue(can_step((2, 6), (3, 6), house, mounted=True))

    def test_inventory_changes_do_not_slow_a_mounted_soldier(self):
        battlefield = self.horse_map()
        battlefield["startPositions"][0]["armor"] = "leather"
        battlefield["items"] = [{"x": 2, "y": 6, "type": "healing_potion"}]
        state = self.mount(initial_state(battlefield), battlefield)
        state["units"][0]["fight_points"] = 1
        state["units"][0]["move_points"] = 3
        picked = apply_action(state, {"type": "pickup_item", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual((picked["units"][0]["move_capacity"], picked["units"][0]["move_points"]), (6, 3))
        picked["units"][0]["fight_points"] = 1
        dropped = apply_action(picked, {"type": "drop_item", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual((dropped["units"][0]["move_capacity"], dropped["units"][0]["move_points"]), (6, 3))
        self.assertEqual(move_allowance(dropped["units"][0], dropped["items"]), 6)

    def test_mounted_melee_hits_harder_and_horse_absorbs_hits_until_fallen(self):
        battlefield = self.horse_map()
        state = self.mount(initial_state(battlefield), battlefield)
        state["units"][0].update(x=12, y=4, fight_points=1, armor="mail", armor_equipped=True)
        state["horses"][0].update(x=12, y=4)
        attacked = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        self.assertEqual(attacked["units"][6]["health"], 1)
        self.assertEqual(attacked["history"][-1]["damage"], 2)
        attacked["units"][6]["fight_points"] = 2
        record_attack(attacked, attacked["units"][6], attacked["units"][0], False, battlefield)
        self.assertEqual((attacked["horses"][0]["health"], attacked["units"][0]["health"]), (1, 3))
        self.assertNotIn("armor_blocked", attacked["history"][-1])
        record_attack(attacked, attacked["units"][6], attacked["units"][0], False, battlefield)
        self.assertEqual(attacked["horses"], [])
        self.assertIsNone(attacked["units"][0]["mount_id"])
        self.assertTrue(attacked["history"][-1]["horse_killed"])
        self.assertEqual(attacked["units"][0]["health"], 3)
        record_attack(attacked, attacked["units"][6], attacked["units"][0], False, battlefield)
        self.assertEqual(attacked["units"][0]["health"], 3)  # Mail protects the dismounted rider.

    def test_mounted_soldier_cannot_crew_catapult_or_attack_across_swamp(self):
        battlefield = self.horse_map()
        battlefield["catapults"].append({"x": 2, "y": 6})
        state = self.mount(initial_state(battlefield), battlefield)
        state["units"][0]["fight_points"] = 1
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "aim_catapult", "unit_id": 0, "catapult_id": 1,
                                 "x": 5, "y": 6}, battlefield)
        battlefield["terrain"] = [{"x": 3, "y": 6, "type": "swamp"}]
        state["units"][6].update(x=3, y=6)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)

    def test_old_matches_and_rider_casualties_leave_horses_available(self):
        battlefield = self.horse_map()
        state = self.mount(initial_state(battlefield), battlefield)
        state["units"][0]["health"] = 1
        state["units"][6]["x"], state["units"][6]["y"] = 2, 5
        from ..engine import record_casualty
        record_casualty(state, state["units"][6], state["units"][0])
        self.assertIsNone(state["horses"][0]["rider_id"])
        legacy = initial_state()
        del legacy["horses"]
        for unit in legacy["units"]:
            del unit["mount_id"]
        self.assertEqual(apply_action(legacy, {"type": "end_turn"})["horses"], [])


class UnitEquipmentTests(TestCase):
    def test_equipment_is_explicit_and_no_unit_has_a_type(self):
        battlefield = default_map()
        battlefield["startPositions"][0]["tools"] = ["rope", "spade"]
        validate_map(battlefield)
        state = initial_state(battlefield)
        self.assertEqual(state["units"][0]["weapon"], "sword")
        self.assertEqual(state["units"][0]["tools"], ["rope", "spade"])
        self.assertTrue(all("type" not in unit for unit in state["units"]))
        self.assertTrue(all("type" not in point for point in normalize_map(battlefield)["startPositions"]))
        state = apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6}, battlefield)
        self.assertEqual(state["units"][0]["tools"], ["rope", "spade"])

    def test_rejects_bad_weapon_tools_and_king_marker(self):
        for changes in ({"weapon": "axe"}, {"weapon": None}, {"weapon": "king"},
                        {"is_king": True}, {"tools": "rope"}, {"tools": ["rope"] * 3},
                        {"tools": [7]}, {"type": "vanguard"}):
            battlefield = default_map()
            battlefield["startPositions"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(InvalidMap):
                validate_map(battlefield)

    def test_legacy_state_and_map_keep_equipment_and_king_rules(self):
        battlefield = default_map()
        battlefield["startPositions"][0] = {"x": 2, "y": 6, "type": "vanguard"}
        battlefield["enemyStartPositions"][0] = {"x": 12, "y": 5, "type": "longbow"}
        validate_map(battlefield)
        state = initial_state(battlefield)
        for unit in state["units"]:
            unit["type"] = {"sword": "vanguard", "longbow": "longbow", "crossbow": "crossbow"}[unit["weapon"]]
            del unit["weapon"]
            del unit["tools"]
        self.assertEqual(apply_action(state, {"type": "end_turn"}, battlefield)["units"][0]["weapon"], "sword")
        self.assertTrue(all("type" not in unit for unit in apply_action(state, {"type": "end_turn"}, battlefield)["units"]))
        throne = default_map()
        throne["mission"] = "capture_king"
        throne["enemyStartPositions"] = [{"x": 14, "y": 7, "type": "king"},
                                         {"x": 13, "y": 7, "type": "vanguard"}]
        self.assertTrue(initial_state(throne)["units"][6]["is_king"])
        self.assertEqual(normalize_map(throne)["enemyStartPositions"][0],
                         {"x": 14, "y": 7, "weapon": None, "is_king": True})


class ArmorTests(TestCase):
    def test_map_validates_armor_and_old_units_remain_unarmored(self):
        battlefield = default_map()
        battlefield["startPositions"][0]["armor"] = "leather"
        battlefield["enemyStartPositions"][0]["armor"] = "mail"
        validate_map(battlefield)
        state = initial_state(battlefield)
        self.assertEqual((state["units"][0]["armor"], state["units"][6]["armor"]), ("leather", "mail"))
        self.assertTrue(state["units"][0]["armor_equipped"])
        self.assertIsNone(state["units"][1]["armor"])
        for bad in ("plate", "", 1, False, [], {}):
            battlefield["startPositions"][0]["armor"] = bad
            with self.subTest(armor=bad), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        del state["units"][0]["armor"]
        del state["units"][0]["armor_equipped"]
        self.assertIsNone(apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6}, battlefield)["units"][0]["armor"])

    def test_melee_absorbs_only_two_mail_damage_per_turn_and_refreshes(self):
        battlefield = default_map()
        battlefield["enemyStartPositions"][0]["armor"] = "mail"
        state = initial_state(battlefield)
        state["units"][0].update(x=12, y=4)
        state["units"][1].update(x=12, y=6, rank="veteran", fight_points=2)
        for attacker_id, remaining in ((0, 3), (1, 3), (1, 2)):
            state = apply_action(state, {"type": "attack", "unit_id": attacker_id, "target_id": 6}, battlefield)
            self.assertEqual(state["units"][6]["health"], remaining)
        self.assertEqual([event.get("armor_blocked", 0) for event in state["history"]], [1, 1, 0])
        self.assertEqual(state["history"][-1]["damage"], 1)
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(state["turn"], 2)
        state = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        self.assertEqual(state["units"][6]["health"], 2)
        self.assertEqual(state["history"][-1]["armor_blocked"], 1)

    def test_cover_then_armor_absorbs_ranged_hits_without_consuming_cover(self):
        battlefield = default_map()
        battlefield["objects"] = [{"x": 5, "y": 4, "type": "tree"}]
        battlefield["enemyStartPositions"][0]["armor"] = "leather"
        state = initial_state(battlefield)
        state["units"][2].update(x=3, y=5)
        state["units"][3].update(x=2, y=5)
        state["units"][6].update(x=6, y=5)
        state = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)
        self.assertEqual(state["history"][-1]["cover"], "tree")
        self.assertNotIn("armor_blocked", state["history"][-1])
        self.assertNotIn("armor_absorbed", state["units"][6])
        state = apply_action(state, {"type": "ranged_attack", "unit_id": 3, "target_id": 6}, battlefield)
        self.assertEqual(state["history"][-1]["armor_blocked"], 1)
        self.assertEqual(state["units"][6]["health"], 3)
        state["units"][4].update(x=4, y=5)
        state = apply_action(state, {"type": "ranged_attack", "unit_id": 4, "target_id": 6}, battlefield)
        self.assertEqual(state["units"][6]["health"], 2)

    def test_catapult_damage_and_defender_attacks_use_the_same_armor(self):
        battlefield = default_map()
        battlefield["startPositions"][0]["armor"] = "leather"
        battlefield["enemyStartPositions"][0]["armor"] = "mail"
        state = initial_state(battlefield)
        state = apply_action(state, {"type": "aim_catapult", "unit_id": 1,
                                     "catapult_id": 0, "x": 12, "y": 5}, battlefield)
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        state = apply_action(state, {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0}, battlefield)
        self.assertEqual(state["units"][6]["health"], 3)
        self.assertEqual(state["history"][-1]["armor_blocked"], 2)
        self.assertEqual(state["history"][-1]["weapon"], "catapult")
        state["units"] = [state["units"][0], state["units"][6]]
        state["units"][0].update(x=12, y=6)
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(state["units"][0]["health"], 3)
        self.assertEqual(state["history"][-1]["armor_blocked"], 1)

    def test_equipping_costs_a_fight_point_and_cannot_restore_spent_protection(self):
        battlefield = default_map()
        battlefield["startPositions"][0]["armor"] = "mail"
        state = initial_state(battlefield)
        state["units"][0].update(rank="veteran", fight_points=2)
        record_attack(state, state["units"][6], state["units"][0], False, battlefield)
        original_health = state["units"][0]["health"]
        for equipped in (False, True):
            state = apply_action(state, {"type": "equip_armor", "unit_id": 0, "equipped": equipped}, battlefield)
            self.assertEqual(state["history"][-1]["type"], "equip_armor")
            self.assertEqual(state["history"][-1]["equipped"], equipped)
        self.assertEqual(state["units"][0]["fight_points"], 0)
        self.assertEqual(state["units"][0]["armor_absorbed"], 1)
        record_attack(state, state["units"][6], state["units"][0], True, battlefield)
        self.assertEqual(state["units"][0]["health"], original_health)
        record_attack(state, state["units"][6], state["units"][0], True, battlefield)
        self.assertEqual(state["units"][0]["health"], original_health - 1)
        for action in ({"type": "equip_armor", "unit_id": 0, "equipped": False},
                       {"type": "equip_armor", "unit_id": 6, "equipped": False},
                       {"type": "equip_armor", "unit_id": 1, "equipped": True},
                       {"type": "equip_armor", "unit_id": 0, "equipped": 1},
                       {"type": "equip_armor", "unit_id": 0, "equipped": True, "armor": "mail"}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)


class CarriedWeightTests(TestCase):
    def test_equipment_weight_sets_initial_allowances_even_when_armor_is_removed(self):
        battlefield = default_map()
        battlefield["startPositions"][0].update(armor="mail", tools=["rope"])
        battlefield["enemyStartPositions"][0]["armor"] = "mail"
        state = initial_state(battlefield)
        self.assertEqual((carried_weight(state["units"][0]), state["units"][0]["move_points"]), (5, 3))
        self.assertEqual((carried_weight(state["units"][6]), state["units"][6]["move_points"]), (4, 3))
        self.assertEqual((carried_weight(state["units"][4]), state["units"][4]["move_points"]), (3, 3))
        state = apply_action(state, {"type": "equip_armor", "unit_id": 0, "equipped": False}, battlefield)
        self.assertEqual((carried_weight(state["units"][0]), state["units"][0]["move_points"]), (5, 3))
        self.assertEqual(move_allowance({**state["units"][0], "morale": 0}), 2)
        self.assertEqual(move_allowance({**state["units"][0], "morale": 0, "weapon": "crossbow",
                                         "tools": ["rope", "spade"]}), 1)

    def test_pickup_drop_and_use_adjust_remaining_points_without_resetting_spent_movement(self):
        battlefield = default_map()
        battlefield["items"] = [{"x": 2, "y": 6, "type": "healing_potion"}] * 2
        state = initial_state(battlefield)
        state["units"][0]["fight_points"] = 3
        state["units"][0]["move_points"] = 2  # Two MP already spent this turn.
        pickup = lambda item_id: {"type": "pickup_item", "unit_id": 0, "item_id": item_id}
        state = apply_action(state, pickup(0), battlefield)
        self.assertEqual((state["units"][0]["move_capacity"], state["units"][0]["move_points"]), (4, 2))
        state = apply_action(state, pickup(1), battlefield)
        self.assertEqual((carried_weight(state["units"][0], state["items"]),
                          state["units"][0]["move_capacity"], state["units"][0]["move_points"]), (3, 3, 1))
        self.assertEqual(move_allowance(state["units"][0], state["items"]), 3)
        state["units"][0]["health"] = 1
        state = apply_action(state, {"type": "use_item", "unit_id": 0, "item_id": 1, "target_id": 0}, battlefield)
        self.assertEqual((state["units"][0]["move_capacity"], state["units"][0]["move_points"]), (4, 2))
        state["units"][0]["fight_points"] = 1
        state = apply_action(state, {"type": "drop_item", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual((state["units"][0]["move_capacity"], state["units"][0]["move_points"]), (4, 2))

        legacy = initial_state(battlefield)
        legacy["units"][0].update(move_points=1)
        del legacy["units"][0]["move_capacity"]
        legacy = apply_action(legacy, pickup(0), battlefield)
        self.assertNotIn("move_capacity", legacy["units"][0])
        self.assertEqual(legacy["units"][0]["move_points"], 1)

    def test_overweight_potion_is_rejected_without_changing_state(self):
        battlefield = default_map()
        battlefield["startPositions"][4].update(armor="mail", tools=["rope", "spade"])
        battlefield["items"] = [{"x": 4, "y": 8, "type": "healing_potion"}]
        state = initial_state(battlefield)
        self.assertEqual((carried_weight(state["units"][4]), state["units"][4]["move_capacity"]), (8, 2))
        with self.assertRaisesMessage(InvalidAction, "eight weight"):
            apply_action(state, {"type": "pickup_item", "unit_id": 4, "item_id": 0}, battlefield)
        self.assertIsNone(state["items"][0]["carrier_id"])

    def test_load_limits_orders_and_defender_destinations(self):
        battlefield = default_map()
        battlefield["startPositions"][0]["armor"] = "mail"
        battlefield["enemyStartPositions"][0]["armor"] = "mail"
        state = initial_state(battlefield)
        self.assertEqual(state["units"][0]["move_points"], 3)
        moved = apply_action(state, {"type": "move", "units": [0], "x": 2, "y": 2}, battlefield)
        self.assertEqual((moved["units"][0]["x"], moved["units"][0]["y"],
                          moved["units"][0]["move_points"]), (2, 3, 0))
        destinations = defender_destinations(state["units"][6], battlefield)
        self.assertNotIn((8, 5), destinations)  # Four tiles from the armored guard.


class ToolRecoveryTests(TestCase):
    def test_rope_allows_one_level_climbs_only_while_carried_on_foot(self):
        battlefield = default_map()
        battlefield["elevation"] = [{"x": 3, "y": 6, "height": 1},
                                    {"x": 4, "y": 6, "height": 3}]
        battlefield["items"] = [{"x": 2, "y": 6, "type": "tool", "name": "rope"}]
        state = initial_state(battlefield)
        self.assertIsNone(find_path((2, 6), (3, 6), battlefield))
        self.assertFalse(can_step((2, 6), (3, 6), battlefield))
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6}, battlefield)
        picked = apply_action(state, {"type": "pickup_tool", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual(find_path((2, 6), (3, 6), battlefield, rope=True), [(3, 6)])
        self.assertFalse(can_step((3, 6), (4, 6), battlefield, rope=True))
        self.assertFalse(can_step((2, 6), (3, 6), battlefield, mounted=True, rope=True))
        moved = apply_action(picked, {"type": "move", "units": [0], "x": 3, "y": 6}, battlefield)
        self.assertEqual((moved["units"][0]["x"], moved["units"][0]["z"]), (3, 1))
        self.assertTrue(can_step((3, 6), (2, 6), battlefield, rope=True))
        descended = apply_action(moved, {"type": "move", "units": [0], "x": 2, "y": 6}, battlefield)
        self.assertEqual((descended["units"][0]["x"], descended["units"][0]["z"]), (2, 0))
        moved["units"][0]["fight_points"] = 1
        dropped = apply_action(moved,
                               {"type": "drop_tool", "unit_id": 0, "tool_index": 0}, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(dropped, {"type": "move", "units": [0], "x": 2, "y": 6}, battlefield)

    def test_rope_can_make_an_authored_elevated_objective_reachable(self):
        battlefield = default_map()
        battlefield["elevation"] = [{"x": 14, "y": 7, "height": 1}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        for side in ("startPositions", "enemyStartPositions"):
            for position in battlefield[side]:
                position["tools"] = ["rope"]
        validate_map(battlefield)
        self.assertIn((14, 7), find_path((2, 6), (14, 7), battlefield, rope=True))

    def test_defender_with_rope_can_route_to_unaccessed_ledge(self):
        battlefield = default_map()
        battlefield["elevation"] = [{"x": 13, "y": 5, "height": 1}]
        state = initial_state(battlefield)
        guard = state["units"][6]
        self.assertNotIn((13, 5), defender_destinations(guard, battlefield))
        guard["tools"] = ["rope"]
        self.assertIn((13, 5), defender_destinations(guard, battlefield))

    def test_authored_tool_validation_and_isolated_pickup_drop(self):
        battlefield = default_map()
        for name in ("", "x" * 41, 5, None):
            battlefield["items"] = [{"x": 2, "y": 6, "type": "tool", "name": name}]
            with self.subTest(name=name), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield["items"] = [{"x": 2, "y": 6, "type": "tool", "name": "rope"}]
        validate_map(battlefield)
        state = initial_state(battlefield)
        unit = state["units"][0]
        unit.update(armor="leather", armor_equipped=True, move_capacity=4, move_points=2)
        picked = apply_action(state, {"type": "pickup_tool", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual(picked["units"][0]["tools"], ["rope"])
        self.assertEqual((picked["units"][0]["move_capacity"], picked["units"][0]["move_points"]), (3, 1))
        self.assertEqual(picked["units"][0]["fight_points"], 0)
        self.assertEqual(picked["items"], [])
        self.assertEqual((unit["tools"], state["items"][0]["name"]), ([], "rope"))
        self.assertEqual(picked["history"][-1]["tool"], "rope")
        picked["units"][0]["fight_points"] = 1
        dropped = apply_action(picked, {"type": "drop_tool", "unit_id": 0, "tool_index": 0}, battlefield)
        self.assertEqual(dropped["items"][-1], {"id": 1, "type": "tool", "name": "rope",
                                                "x": 2, "y": 6, "carrier_id": None})
        self.assertEqual(dropped["units"][0]["tools"], [])
        self.assertEqual((dropped["units"][0]["move_capacity"], dropped["units"][0]["move_points"]), (4, 2))
        self.assertEqual(picked["units"][0]["tools"], ["rope"])

    def test_tool_limits_wrong_item_and_forged_actions(self):
        battlefield = default_map()
        battlefield["items"] = [{"x": 2, "y": 6, "type": "tool", "name": "spade"},
                                {"x": 3, "y": 7, "type": "healing_potion"}]
        state = initial_state(battlefield)
        unit = state["units"][0]
        unit["tools"] = ["rope", "rope"]
        unit["fight_points"] = 3
        for action in ({"type": "pickup_tool", "unit_id": 0, "item_id": 0},
                       {"type": "pickup_tool", "unit_id": 0, "item_id": 1},
                       {"type": "pickup_equipment", "unit_id": 0, "item_id": 0},
                       {"type": "pickup_item", "unit_id": 0, "item_id": 0},
                       {"type": "pickup_tool", "unit_id": 6, "item_id": 0},
                       {"type": "drop_tool", "unit_id": 6, "tool_index": 0},
                       {"type": "drop_tool", "unit_id": 0, "tool_index": True},
                       {"type": "drop_tool", "unit_id": 0, "tool_index": 2},
                       {"type": "drop_tool", "unit_id": 0, "tool_index": -1},
                       {"type": "drop_tool", "unit_id": 0, "tool_index": 0, "extra": 1}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)
        dropped = apply_action(state, {"type": "drop_tool", "unit_id": 0, "tool_index": 1}, battlefield)
        self.assertEqual(dropped["units"][0]["tools"], ["rope"])
        dropped["units"][0]["fight_points"] = 1
        picked = apply_action(dropped, {"type": "pickup_tool", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual(picked["units"][0]["tools"], ["rope", "spade"])
        unit.update(weapon="crossbow", armor="mail", tools=["rope"], fight_points=1)
        state["items"][1].update(carrier_id=0, x=None, y=None)
        with self.assertRaisesMessage(InvalidAction, "eight weight"):
            apply_action(state, {"type": "pickup_tool", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual(state["items"][0]["name"], "spade")

    def test_casualty_drops_tools_with_stable_legacy_ids(self):
        battlefield = default_map()
        battlefield["enemyStartPositions"][0]["tools"] = ["rope", "spade"]
        state = initial_state(battlefield)
        state.pop("next_item_id")
        state["history"] = [{"type": "use_item", "item_id": 9, "turn": 1}]
        state["units"] = [state["units"][0], state["units"][6]]
        state["units"][0].update(x=12, y=4)
        state["units"][1]["health"] = 1
        fallen = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        self.assertEqual([(item["id"], item["type"], item.get("name")) for item in fallen["items"]],
                         [(10, "tool", "rope"), (11, "tool", "spade"), (12, "weapon", "sword")])
        self.assertEqual(fallen["next_item_id"], 13)
        self.assertEqual(state["units"][1]["tools"], ["rope", "spade"])


class EquipmentRecoveryTests(TestCase):
    def test_authored_ground_equipment_can_be_recovered_with_existing_rules(self):
        battlefield = default_map()
        battlefield["items"] = [
            {"x": 2, "y": 6, "type": "weapon", "name": "longbow"},
            {"x": 3, "y": 7, "type": "armor", "name": "mail"},
            {"x": 4, "y": 6, "type": "healing_potion"},
        ]
        validate_map(battlefield)
        state = initial_state(battlefield)
        self.assertEqual(state["items"], [
            {"id": 0, "type": "weapon", "name": "longbow", "x": 2, "y": 6, "carrier_id": None},
            {"id": 1, "type": "armor", "name": "mail", "x": 3, "y": 7, "carrier_id": None},
            {"id": 2, "type": "healing_potion", "x": 4, "y": 6, "carrier_id": None},
        ])
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "pickup_equipment", "unit_id": 0, "item_id": 0}, battlefield)
        unarmed = apply_action(state, {"type": "drop_weapon", "unit_id": 0}, battlefield)
        unarmed = apply_action(unarmed, {"type": "end_turn"}, battlefield)
        equipped = apply_action(unarmed, {"type": "pickup_equipment", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual(equipped["units"][0]["weapon"], "longbow")
        self.assertEqual(equipped["units"][0]["fight_points"], 0)
        self.assertEqual(equipped["next_item_id"], 4)
        armored = apply_action(state, {"type": "pickup_equipment", "unit_id": 1, "item_id": 1}, battlefield)
        self.assertEqual(armored["units"][1]["armor"], "mail")
        self.assertTrue(armored["units"][1]["armor_equipped"])
        self.assertEqual(armored["units"][1]["fight_points"], 0)

    def test_authored_equipment_requires_valid_kind_name_and_distinct_open_ground(self):
        for item in (
            {"x": 2, "y": 6, "type": "weapon"},
            {"x": 2, "y": 6, "type": "weapon", "name": "axe"},
            {"x": 2, "y": 6, "type": "armor", "name": []},
            {"x": 2, "y": 6, "type": "armor", "name": "plate"},
            {"x": 2, "y": 6, "type": "healing_potion", "name": "mail"},
            {"x": 2, "y": 6, "type": "weapon", "name": "sword", "id": 3},
            {"x": 11, "y": 7, "type": "armor", "name": "mail"},
            {"x": 2, "y": True, "type": "weapon", "name": "sword"},
        ):
            battlefield = default_map()
            battlefield["items"] = [item]
            with self.subTest(item=item), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield = default_map()
        battlefield["items"] = [{"x": 2, "y": 6, "type": "weapon", "name": "sword"},
                                {"x": 2, "y": 6, "type": "armor", "name": "mail"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)

    def test_casualties_drop_weapon_armor_and_potions_with_stable_ids(self):
        battlefield = default_map()
        battlefield["enemyStartPositions"][0]["armor"] = "mail"
        battlefield["items"] = [{"x": 12, "y": 5, "type": "healing_potion"}]
        state = initial_state(battlefield)
        state["units"] = [state["units"][0], state["units"][6]]
        state["units"][0].update(x=12, y=4)
        state["units"][1].update(health=1, armor_equipped=False)
        state["items"][0].update(x=None, y=None, carrier_id=6)
        fallen = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        self.assertEqual([item["id"] for item in fallen["items"]], [0, 1, 2])
        self.assertEqual([(item["type"], item.get("name"), item["x"], item["y"])
                          for item in fallen["items"]], [
            ("healing_potion", None, 12, 5), ("weapon", "sword", 12, 5), ("armor", "mail", 12, 5)])
        self.assertEqual(fallen["next_item_id"], 3)
        self.assertIsNone(state["items"][0]["x"])
        self.assertEqual(len(state["units"]), 2)

        fallen = apply_action(fallen, {"type": "end_turn"}, battlefield)
        fallen = apply_action(fallen, {"type": "drop_weapon", "unit_id": 0}, battlefield)
        self.assertIsNone(fallen["units"][0]["weapon"])
        self.assertEqual(fallen["items"][-1]["id"], 3)
        fallen = apply_action(fallen, {"type": "move", "units": [0], "x": 12, "y": 5}, battlefield)
        fallen = apply_action(fallen, {"type": "end_turn"}, battlefield)
        recovered = apply_action(fallen, {"type": "pickup_equipment", "unit_id": 0, "item_id": 1}, battlefield)
        self.assertEqual(recovered["units"][0]["weapon"], "sword")
        self.assertEqual(recovered["units"][0]["fight_points"], 0)
        self.assertEqual(recovered["history"][-1]["equipment"], "sword")
        self.assertNotIn(1, [item["id"] for item in recovered["items"]])
        self.assertEqual(recovered["next_item_id"], 4)
        self.assertEqual(recovered["items"][0]["type"], "healing_potion")

    def test_unarmed_soldier_cannot_melee_even_with_forged_order(self):
        battlefield = default_map()
        state = initial_state(battlefield)
        state["units"][0].update(x=12, y=4)
        dropped = apply_action(state, {"type": "drop_weapon", "unit_id": 0}, battlefield)
        dropped["units"][0]["fight_points"] = 1
        with self.assertRaisesMessage(InvalidAction, "needs a sword"):
            apply_action(dropped, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)

    def test_armor_recovery_preserves_used_protection_and_movement_spent(self):
        battlefield = default_map()
        state = initial_state(battlefield)
        unit = state["units"][0]
        unit.update(armor="leather", armor_equipped=True, armor_turn=1, armor_absorbed=1,
                    move_points=2, fight_points=3)
        from ..engine import drop_equipment, armor_remaining
        drop_equipment(state, unit, "armor", "mail")
        dropped = apply_action(state, {"type": "drop_armor", "unit_id": 0}, battlefield)
        self.assertEqual((dropped["units"][0]["move_capacity"], dropped["units"][0]["move_points"]), (4, 2))
        self.assertFalse(dropped["units"][0]["armor_equipped"])
        recovered = apply_action(dropped, {"type": "pickup_equipment", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual((recovered["units"][0]["armor"], recovered["units"][0]["move_capacity"],
                          recovered["units"][0]["move_points"]), ("mail", 3, 1))
        self.assertEqual(armor_remaining(recovered["units"][0], 1), 1)
        self.assertEqual(recovered["units"][0]["fight_points"], 1)

    def test_weight_slot_point_limits_and_potion_actions_reject_gear_ids(self):
        battlefield = default_map()
        battlefield["items"] = [{"x": 2, "y": 6, "type": "healing_potion"}]
        state = initial_state(battlefield)
        unit = state["units"][0]
        unit.update(weapon="crossbow", tools=["rope", "spade"], fight_points=3,
                    move_capacity=2, move_points=2)
        state["items"][0].update(carrier_id=0, x=None, y=None)
        from ..engine import drop_equipment
        drop_equipment(state, unit, "armor", "mail")
        original = initial_state(battlefield)
        for action in ({"type": "pickup_equipment", "unit_id": 0, "item_id": 0},
                       {"type": "pickup_equipment", "unit_id": 6, "item_id": 1},
                       {"type": "pickup_equipment", "unit_id": 0, "item_id": True},
                       {"type": "drop_weapon", "unit_id": 6},
                       {"type": "drop_armor", "unit_id": 0},
                       {"type": "pickup_item", "unit_id": 0, "item_id": 1},
                       {"type": "use_item", "unit_id": 0, "item_id": 1, "target_id": 0}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)
        self.assertEqual(state["items"][1]["name"], "mail")
        self.assertIsNone(original["units"][0]["armor"])
        with self.assertRaisesMessage(InvalidAction, "eight weight"):
            apply_action(state, {"type": "pickup_equipment", "unit_id": 0, "item_id": 1}, battlefield)
        lighter = apply_action(state, {"type": "drop_item", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual(lighter["units"][0]["move_capacity"], 3)
        recovered = apply_action(lighter, {"type": "pickup_equipment", "unit_id": 0, "item_id": 1}, battlefield)
        self.assertEqual(carried_weight(recovered["units"][0], recovered["items"]), 8)
        self.assertEqual(recovered["units"][0]["move_capacity"], 2)
        with self.assertRaises(InvalidAction):
            apply_action(recovered, {"type": "pickup_equipment", "unit_id": 0, "item_id": 1}, battlefield)

    def test_old_state_without_inventory_counter_can_drop_gear_after_consumption(self):
        state = initial_state()
        state.pop("next_item_id")
        state["history"] = [{"turn": 1, "type": "use_item", "item_id": 9,
                             "actor_id": 0, "actor_side": "attackers", "actor_weapon": "sword"}]
        dropped = apply_action(state, {"type": "drop_weapon", "unit_id": 0})
        self.assertEqual(dropped["items"][0]["id"], 10)
        self.assertEqual(dropped["next_item_id"], 11)


class FieldMedicineTests(TestCase):
    def potion_map(self):
        battlefield = default_map()
        battlefield["items"] = [{"x": 2, "y": 6, "type": "healing_potion"}]
        return battlefield

    def test_map_places_potions_only_on_distinct_open_ground(self):
        battlefield = self.potion_map()
        validate_map(battlefield)
        self.assertEqual(initial_state(battlefield)["items"][0], {
            "id": 0, "type": "healing_potion", "x": 2, "y": 6, "carrier_id": None,
        })
        for items in ("invalid", [{"x": 2, "y": 6, "type": "healing_potion"}] * 2,
                      [{"x": 2, "y": 6, "type": "healing_potion"}] * 33,
                      [{"x": True, "y": 6, "type": "healing_potion"}],
                      [{"x": 99, "y": 6, "type": "healing_potion"}],
                      [{"x": 11, "y": 7, "type": "healing_potion"}],
                      [{"x": 2, "y": 6, "type": "sword"}],
                      [{"x": 2, "y": 6, "type": "healing_potion", "amount": 99}]):
            changed = default_map()
            changed["items"] = items
            with self.subTest(items=items), self.assertRaises(InvalidMap):
                validate_map(changed)
        battlefield["elevation"] = [{"x": 2, "y": 6, "height": 1, "access": "ramp"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        battlefield = self.potion_map()
        battlefield["objects"] = [{"x": 2, "y": 6, "type": "tree"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        house = default_map()
        house["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4,
                             "door": {"x": 4, "y": 4}}]
        house["items"] = [{"x": 5, "y": 4, "type": "healing_potion"}]
        validate_map(house)

    def test_pick_up_drop_and_heal_self_or_adjacent_ally(self):
        battlefield = self.potion_map()
        state = initial_state(battlefield)
        original = initial_state(battlefield)
        pickup = {"type": "pickup_item", "unit_id": 0, "item_id": 0}
        carried = apply_action(state, pickup, battlefield)
        self.assertEqual(state, original)
        self.assertEqual(carried["items"][0]["carrier_id"], 0)
        self.assertIsNone(carried["items"][0]["x"])
        self.assertEqual(carried["units"][0]["fight_points"], 0)
        with self.assertRaises(InvalidAction):
            apply_action(carried, pickup, battlefield)
        carried = apply_action(carried, {"type": "end_turn"}, battlefield)
        carried["units"][0]["health"] = 1
        heal = {"type": "use_item", "unit_id": 0, "item_id": 0, "target_id": 0}
        healed = apply_action(carried, heal, battlefield)
        self.assertEqual(healed["units"][0]["health"], 3)
        self.assertEqual(healed["history"][-1]["healed"], 2)
        self.assertEqual(healed["items"], [])
        self.assertEqual(carried["units"][0]["health"], 1)
        with self.assertRaises(InvalidAction):
            apply_action(healed, heal, battlefield)

        state = initial_state(battlefield)
        state["units"][1].update(x=3, y=6, health=2)
        carried = apply_action(state, pickup, battlefield)
        carried = apply_action(carried, {"type": "end_turn"}, battlefield)
        ally = apply_action(carried, {**heal, "target_id": 1}, battlefield)
        self.assertEqual(ally["units"][1]["health"], 3)
        self.assertEqual(ally["history"][-1]["healed"], 1)

        carried = apply_action(state, pickup, battlefield)
        carried = apply_action(carried, {"type": "end_turn"}, battlefield)
        dropped = apply_action(carried, {"type": "drop_item", "unit_id": 0, "item_id": 0}, battlefield)
        self.assertEqual((dropped["items"][0]["x"], dropped["items"][0]["y"],
                          dropped["items"][0]["carrier_id"]), (2, 6, None))
        self.assertEqual(dropped["units"][0]["fight_points"], 0)

    def test_invalid_orders_cannot_mutate_items_or_bypass_capacity_and_healing_rules(self):
        battlefield = self.potion_map()
        battlefield["items"].extend([{"x": 2, "y": 6, "type": "healing_potion"}] * 2)
        state = initial_state(battlefield)  # Deliberately stacked for runtime inventory tests.
        state["units"][0]["fight_points"] = 3
        for item_id in (0, 1):
            state = apply_action(state, {"type": "pickup_item", "unit_id": 0, "item_id": item_id}, battlefield)
        original = initial_state(battlefield)
        for action in ({"type": "pickup_item", "unit_id": 0, "item_id": 2},
                       {"type": "drop_item", "unit_id": 1, "item_id": 0},
                       {"type": "use_item", "unit_id": 0, "item_id": 0, "target_id": 0},
                       {"type": "use_item", "unit_id": 0, "item_id": 0, "target_id": 6},
                       {"type": "use_item", "unit_id": 0, "item_id": 0, "target_id": 1},
                       {"type": "use_item", "unit_id": 0, "item_id": 0, "target_id": True},
                       {"type": "drop_item", "unit_id": True, "item_id": 0},
                       {"type": "pickup_item", "unit_id": 6, "item_id": 2},
                       {"type": "drop_item", "unit_id": 0, "item_id": 0, "extra": 1}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action, battlefield)
        self.assertEqual(state["items"][0]["carrier_id"], 0)
        self.assertEqual(original["items"][0]["carrier_id"], None)
        wounded = initial_state(battlefield)
        wounded["units"][0].update(x=4, y=5, health=1)
        wounded["units"][1].update(x=4, y=4, health=1)
        wounded["items"][0].update(x=None, y=None, carrier_id=0)
        house = default_map()
        house["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4,
                             "door": {"x": 5, "y": 4}}]
        heal = {"type": "use_item", "unit_id": 0, "item_id": 0, "target_id": 1}
        with self.assertRaises(InvalidAction):
            apply_action(wounded, heal, house)
        wounded["units"][1].update(x=5, y=5)
        house["elevation"] = [{"x": 5, "y": 5, "height": 1, "access": "ramp"}]
        with self.assertRaises(InvalidAction):
            apply_action(wounded, heal, house)
        del house["elevation"]
        wounded["units"][1].update(x=4, y=4)
        house["houses"][0]["door"] = {"x": 4, "y": 4}
        self.assertEqual(apply_action(wounded, heal, house)["units"][1]["health"], 3)

    def test_carried_potions_drop_on_casualty_and_old_states_have_no_items(self):
        battlefield = self.potion_map()
        state = initial_state(battlefield)
        state["items"][0].update(x=None, y=None, carrier_id=0)
        state["units"] = [state["units"][0], state["units"][1], state["units"][6]]
        state["units"][0].update(x=12, y=6, health=1)
        state["units"][2].update(x=12, y=5)
        ended = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual((ended["items"][0]["x"], ended["items"][0]["y"],
                          ended["items"][0]["carrier_id"]), (12, 6, None))
        self.assertFalse(ended["defeated"])
        ended["units"][0].update(x=12, y=6)
        recovered = apply_action(ended, {"type": "pickup_item", "unit_id": 1, "item_id": 0}, battlefield)
        self.assertEqual(recovered["items"][0]["carrier_id"], 1)
        self.assertIsNone(state["items"][0]["x"])
        legacy = initial_state()
        del legacy["items"]
        self.assertEqual(apply_action(legacy, {"type": "end_turn"})["items"], [])


class VillageTests(TestCase):
    def enterable_map(self):
        battlefield = default_map()
        battlefield["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4,
                                   "door": {"x": 4, "y": 4}}]
        return battlefield

    def test_enterable_houses_require_valid_access_and_keep_legacy_houses_solid(self):
        battlefield = self.enterable_map()
        validate_map(battlefield)
        self.assertTrue(is_walkable(5, 3, battlefield))
        self.assertEqual(find_path((4, 5), (5, 4), battlefield), [(4, 4), (5, 4)])
        self.assertIn((4, 4), find_path((5, 5), (5, 4), battlefield))
        solid = default_map()
        solid["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4}]
        self.assertFalse(is_walkable(5, 3, solid))
        self.assertFalse(has_line_of_sight((3, 4), (6, 4), solid))
        adjacent = self.enterable_map()
        adjacent["houses"].append({"left": 6, "right": 7, "top": 3, "bottom": 4,
                                   "door": {"x": 7, "y": 4}})
        validate_map(adjacent)
        self.assertFalse(can_step((5, 4), (6, 4), adjacent))
        self.assertNotEqual(find_path((5, 4), (6, 4), adjacent)[0], (6, 4))
        malformed = self.enterable_map()
        malformed["houses"].append("invalid")
        with self.assertRaises(InvalidMap):
            validate_map(malformed)
        for door in ({"x": 6, "y": 4}, {"x": 4, "y": 5}, {"x": True, "y": 4},
                     {"x": 4}, "north", None):
            broken = self.enterable_map()
            broken["houses"][0]["door"] = door
            with self.subTest(door=door), self.assertRaises(InvalidMap):
                validate_map(broken)
        enclosed = self.enterable_map()
        enclosed["objects"] = [{"x": 4, "y": 5, "type": "rock"},
                               {"x": 3, "y": 4, "type": "rock"}]
        with self.assertRaisesRegex(InvalidMap, "unobstructed"):
            validate_map(enclosed)

    def test_doorways_cost_normal_move_points_and_block_occupied_routes(self):
        battlefield = self.enterable_map()
        state = initial_state(battlefield)
        state["units"][0].update(x=4, y=5)
        entered = apply_action(state, {"type": "move", "units": [0], "x": 5, "y": 4}, battlefield)
        self.assertEqual((entered["units"][0]["x"], entered["units"][0]["y"],
                          entered["units"][0]["move_points"]), (5, 4, 2))
        self.assertEqual((state["units"][0]["x"], state["units"][0]["move_points"]), (4, 4))
        exited = apply_action(entered, {"type": "move", "units": [0], "x": 4, "y": 5}, battlefield)
        self.assertEqual((exited["units"][0]["x"], exited["units"][0]["y"],
                          exited["units"][0]["move_points"]), (4, 5, 0))
        state["units"][1].update(x=4, y=4)
        self.assertIsNone(find_path((4, 5), (5, 4), battlefield, blocked={(4, 4)}))
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 5, "y": 4}, battlefield)

    def test_house_walls_separate_combat_except_melee_at_the_door(self):
        battlefield = self.enterable_map()
        battlefield["houses"].append({"left": 7, "right": 8, "top": 3, "bottom": 4,
                                      "door": {"x": 7, "y": 4}})
        validate_map(battlefield)
        self.assertTrue(has_line_of_sight((4, 3), (5, 4), battlefield))
        self.assertFalse(has_line_of_sight((4, 5), (4, 4), battlefield))
        self.assertFalse(has_line_of_sight((4, 3), (7, 3), battlefield))
        self.assertFalse(has_line_of_sight((3, 3), (6, 3), battlefield))
        state = initial_state(battlefield)
        state["units"] = [state["units"][0], state["units"][2], state["units"][6]]
        state["units"][0].update(x=5, y=5)
        state["units"][1].update(x=3, y=4)
        state["units"][2].update(x=5, y=4)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)
        state["units"][0].update(x=4, y=5)
        state["units"][2].update(x=4, y=4)
        hit = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        self.assertEqual(hit["units"][-1]["health"], 2)
        state["units"][0].update(x=5, y=4)
        state["units"][1].update(x=4, y=3)
        state["units"][2].update(x=5, y=3)
        shot = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)
        self.assertEqual(shot["units"][-1]["health"], 2)

    def test_defender_can_enter_and_exit_but_cannot_attack_through_walls(self):
        battlefield = self.enterable_map()
        state = initial_state(battlefield)
        state["units"] = [state["units"][0], state["units"][6]]
        state["units"][0].update(x=5, y=5)
        state["units"][1].update(x=4, y=5, weapon="sword")
        self.assertIn((4, 4), defender_destinations(state["units"][1], battlefield))
        state["units"][1].update(x=5, y=4)
        self.assertNotIn((5, 5), defender_destinations(state["units"][1], battlefield, blocked={(4, 4)}))
        held = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(held["units"][0]["health"], 3)
        state["units"][1].update(x=4, y=4)
        state["units"][0].update(x=4, y=5)
        struck = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(struck["units"][0]["health"], 2)

    def test_roof_shields_occupants_from_catapult_stones(self):
        battlefield = self.enterable_map()
        state = initial_state(battlefield)
        state["units"][6].update(x=4, y=4)
        state["units"][1]["fight_points"] = 2
        aimed = apply_action(state, {"type": "aim_catapult", "unit_id": 1,
                                     "catapult_id": 0, "x": 4, "y": 4}, battlefield)
        fired = apply_action(aimed, {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0}, battlefield)
        self.assertEqual(fired["units"][6]["health"], 3)
        self.assertEqual(fired["history"][-1]["type"], "catapult_miss")

    def test_house_footprints_block_movement_and_shots_but_lanes_remain_open(self):
        battlefield = default_map()
        battlefield["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4}]
        battlefield["lanes"] = [{"x": 3, "y": 5}, {"x": 4, "y": 5}]
        validate_map(battlefield)
        self.assertFalse(is_walkable(4, 4, battlefield))
        self.assertTrue(is_walkable(4, 5, battlefield))
        self.assertIsNone(find_path((3, 4), (4, 4), battlefield))
        self.assertFalse(has_line_of_sight((3, 4), (6, 4), battlefield))
        self.assertIsNotNone(find_path((3, 4), (6, 4), battlefield))
        state = initial_state(battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 5, "y": 4}, battlefield)
        state["units"][2].update(x=3, y=4)
        state["units"][6].update(x=6, y=4)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)

    def test_fence_allows_shots_but_blocks_movement_and_grants_cover(self):
        battlefield = default_map()
        battlefield["objects"] = [{"x": 5, "y": 4, "type": "fence"}]
        validate_map(battlefield)
        self.assertFalse(is_walkable(5, 4, battlefield))
        self.assertTrue(has_line_of_sight((4, 4), (6, 4), battlefield))
        state = initial_state(battlefield)
        state["units"][2].update(x=3, y=5)
        state["units"][3].update(x=4, y=5)
        state["units"][6].update(x=6, y=5)
        blocked = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)
        self.assertEqual(blocked["history"][-1]["cover"], "fence")
        self.assertEqual(blocked["units"][6]["health"], 3)
        hit = apply_action(blocked, {"type": "ranged_attack", "unit_id": 3, "target_id": 6}, battlefield)
        self.assertEqual(hit["units"][6]["health"], 2)

    def test_house_and_well_provide_cover_while_well_blocks_sight(self):
        for kind in ("house", "well"):
            with self.subTest(kind=kind):
                battlefield = default_map()
                if kind == "house":
                    battlefield["houses"] = [{"left": 4, "right": 5, "top": 3, "bottom": 4}]
                else:
                    battlefield["objects"] = [{"x": 5, "y": 4, "type": "well"}]
                validate_map(battlefield)
                self.assertFalse(has_line_of_sight((4, 4), (6, 4), battlefield))
                state = initial_state(battlefield)
                state["units"][2].update(x=3, y=5)
                state["units"][6].update(x=6, y=5)
                result = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)
                self.assertEqual(result["history"][-1]["cover"], kind)

    def test_rejects_bad_house_lane_and_object_placements(self):
        valid = {"left": 6, "right": 7, "top": 2, "bottom": 3}
        for houses in ("house", [valid] * 33, [valid, valid],
                       [{**valid, "left": True}], [{**valid, "right": 10}],
                       [{**valid, "top": -1}], [{**valid, "right": 7, "bottom": 2}],
                       [{**valid, "left": 11, "right": 12}],
                       [{**valid, "right": 9, "bottom": 6}],
                       [{**valid, "door": {"x": 8, "y": 3}}]):
            battlefield = default_map()
            battlefield["houses"] = houses
            with self.subTest(houses=houses), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        for lanes in ("road", [{"x": 3, "y": 5}] * 2,
                      [{"x": True, "y": 5}], [{"x": -1, "y": 5}],
                      [{"x": 11, "y": 5}], [{"x": 4, "y": 4, "type": "road"}]):
            battlefield = default_map()
            battlefield["lanes"] = lanes
            with self.subTest(lanes=lanes), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield = default_map()
        battlefield["houses"] = [valid]
        for field, value in (("objects", [{"x": 6, "y": 2, "type": "fence"}]),
                             ("elevation", [{"x": 6, "y": 2, "height": 1}]),
                             ("lanes", [{"x": 6, "y": 2}]),
                             ("startPositions", [{"x": 6, "y": 2, "type": "vanguard"}]),
                             ("catapults", [{"x": 6, "y": 2}])):
            changed = default_map()
            changed["houses"] = [valid]
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(InvalidMap):
                validate_map(changed)
        battlefield = default_map()
        battlefield["lanes"] = [{"x": 3, "y": 5}]
        battlefield["elevation"] = [{"x": 3, "y": 5, "height": 1, "access": "ramp"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        battlefield = default_map()
        battlefield["houses"] = [{"left": 10, "right": 12, "top": 0, "bottom": 13}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)


class ThroneRoomTests(TestCase):
    def throne_map(self):
        battlefield = default_map()
        battlefield["mission"] = "capture_king"
        battlefield["enemyStartPositions"] = [
            {"x": 14, "y": 7, "type": "king"},
            {"x": 13, "y": 7, "type": "vanguard"},
        ]
        return battlefield

    def test_map_requires_one_king_on_throne_and_at_least_one_guard(self):
        battlefield = self.throne_map()
        validate_map(battlefield)
        for update in (
            lambda data: data.pop("enemyStartPositions"),
            lambda data: data["enemyStartPositions"].pop(),
            lambda data: data["enemyStartPositions"].append({"x": 12, "y": 5, "type": "king"}),
            lambda data: data["enemyStartPositions"][0].update(x=12, y=5),
            lambda data: data["enemyStartPositions"][1].update(x=14, y=7),
            lambda data: data["startPositions"][0].update(weapon=None, is_king=True),
            lambda data: data.update(objective={"x": 7, "y": 7}),
        ):
            changed = self.throne_map()
            update(changed)
            with self.subTest(changed=changed), self.assertRaises(InvalidMap):
                validate_map(changed)
        for mission in ("unknown", None, 12):
            battlefield["mission"] = mission
            with self.subTest(mission=mission), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        courtyard = default_map()
        courtyard["enemyStartPositions"][0].update(weapon=None, is_king=True)
        with self.assertRaises(InvalidMap):
            validate_map(courtyard)

    def test_capture_requires_vanguard_range_height_fight_point_and_no_adjacent_guard(self):
        battlefield = self.throne_map()
        state = initial_state(battlefield)
        state["units"][0].update(x=14, y=8)
        king_id = len(battlefield["startPositions"])
        guard_id = king_id + 1
        self.assertEqual(capture_status(state, battlefield), "KING GUARDED")
        action = {"type": "capture", "unit_id": 0}
        with self.assertRaisesRegex(InvalidAction, "guards"):
            apply_action(state, action, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "capture", "unit_id": True}, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "capture", "unit_id": 2}, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "capture", "unit_id": 99}, battlefield)
        self.assertEqual(state["units"][0]["fight_points"], 1)

        state["units"] = [unit for unit in state["units"] if unit["id"] != guard_id]
        self.assertEqual(capture_status(state, battlefield), "CAPTURE THE KING")
        for change in ({"x": 14, "y": 9}, {"fight_points": 0}, {"elevation": True}):
            layout = self.throne_map()
            if change.get("elevation"):
                layout["elevation"] = [{"x": 14, "y": 7, "height": 1, "access": "ramp"}]
            altered = initial_state(layout)
            altered["units"] = [unit for unit in altered["units"] if unit["id"] != guard_id]
            altered["units"][0].update({"x": 14, "y": 8})
            altered["units"][0].update({key: value for key, value in change.items() if key != "elevation"})
            with self.subTest(change=change), self.assertRaises(InvalidAction):
                apply_action(altered, action, layout)
        captured = apply_action(state, action, battlefield)
        self.assertTrue(captured["captured"])
        self.assertFalse(captured["defeated"])
        self.assertEqual(captured["units"][0]["fight_points"], 0)
        self.assertIn(king_id, [unit["id"] for unit in captured["units"]])
        self.assertEqual(captured["capture_progress"], 1)
        self.assertEqual(capture_status(captured, battlefield), "KING CAPTURED")
        self.assertEqual(captured["history"][-1]["type"], "capture")
        self.assertEqual(state["units"][0]["fight_points"], 1)
        with self.assertRaises(InvalidAction):
            apply_action(captured, {"type": "end_turn"}, battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(initial_state(), action)

    def test_killing_king_fails_and_throne_occupation_does_not_win(self):
        battlefield = self.throne_map()
        state = initial_state(battlefield)
        state["units"][0].update(x=14, y=8)
        king = state["units"][6]
        king["health"] = 1
        dead = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": king["id"]}, battlefield)
        self.assertTrue(dead["defeated"])
        self.assertFalse(dead["captured"])
        self.assertEqual(capture_status(dead, battlefield), "DEFEATED")
        self.assertTrue(dead["history"][-1]["target_is_king"])
        with self.assertRaises(InvalidAction):
            apply_action(dead, {"type": "end_turn"}, battlefield)
        state = initial_state(battlefield)
        state["units"][0].update(x=14, y=7)
        self.assertFalse(apply_action(state, {"type": "end_turn"}, battlefield)["captured"])

    def test_king_never_moves_attacks_or_accepts_ai_orders(self):
        battlefield = self.throne_map()
        state = initial_state(battlefield)
        king = state["units"][6]
        state["units"][0].update(x=14, y=8, health=1)
        with self.assertRaises(InvalidAction):
            resolve_defender_goals(state, [{"unit_id": king["id"], "x": 14, "y": 8}], battlefield)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "end_turn"}, battlefield,
                         enemy_orders=[{"unit_id": king["id"], "x": 14, "y": 8}])
        state["units"] = [unit for unit in state["units"] if unit["id"] != 7]
        ended = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual((ended["units"][0]["health"], ended["units"][-1]["x"]), (1, 14))
        self.assertEqual(ended["units"][-1]["fight_points"], 1)


class CatapultTests(TestCase):
    def test_map_validation_and_legacy_maps(self):
        battlefield = default_map()
        validate_map(battlefield)
        for points in ("invalid", [{"x": 3, "y": 7}] * 2,
                       [{"x": True, "y": 7}], [{"x": -1, "y": 7}],
                       [{"x": 11, "y": 7}], [{"x": 14, "y": 7}],
                       [{"x": 2, "y": 7, "ammo": 100}]):
            battlefield["catapults"] = points
            with self.subTest(points=points), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield["catapults"] = [{"x": 3, "y": 5}]
        battlefield["elevation"] = [{"x": 3, "y": 5, "height": 1, "access": "ramp"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        del battlefield["catapults"]
        validate_map(battlefield)
        self.assertEqual(initial_state(battlefield)["catapults"], [])

    def test_only_crew_with_fight_point_can_aim_and_fire(self):
        state = initial_state()
        aim = {"type": "aim_catapult", "unit_id": 1, "catapult_id": 0, "x": 11, "y": 7}
        original = initial_state()
        for action in (
            {**aim, "unit_id": 0}, {**aim, "unit_id": 6}, {**aim, "unit_id": True},
            {**aim, "catapult_id": 42}, {**aim, "x": True}, {**aim, "x": -1},
            {**aim, "x": 3, "y": 7}, {**aim, "x": 17}, {**aim, "extra": 1},
            {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0},
        ):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action)
        self.assertEqual(state, original)
        empty = initial_state()
        empty["catapults"][0]["ammo"] = 0
        with self.assertRaisesRegex(InvalidAction, "ammunition"):
            apply_action(empty, aim)
        empty["catapults"][0]["aim"] = {"x": 11, "y": 7}
        with self.assertRaisesRegex(InvalidAction, "ammunition"):
            apply_action(empty, {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0})
        aimed = apply_action(state, aim)
        self.assertEqual(aimed["catapults"][0]["aim"], {"x": 11, "y": 7})
        self.assertEqual(aimed["units"][1]["fight_points"], 0)
        self.assertIsNone(state["catapults"][0]["aim"])
        with self.assertRaises(InvalidAction):
            apply_action(aimed, {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0})
        with self.assertRaises(InvalidAction):
            apply_action(aimed, {"type": "fire_catapult", "unit_id": 0, "catapult_id": 0})
        legacy = initial_state()
        for field in ("catapults", "wall_damage", "breaches"):
            del legacy[field]
        self.assertEqual(apply_action(legacy, {"type": "end_turn"})["catapults"], [])

    def test_fire_spends_ammo_reload_and_damages_wall_until_breached(self):
        state = initial_state()
        aim = {"type": "aim_catapult", "unit_id": 1, "catapult_id": 0, "x": 11, "y": 7}
        fire = {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0}
        events = []
        state = apply_action(state, aim)
        state = apply_action(state, {"type": "end_turn"})
        state = apply_action(state, fire, combat_events=events)
        self.assertEqual(events, [{"type": "projectile", "weapon": "catapult",
                                   "from": {"x": 3, "y": 7}, "to": {"x": 11, "y": 7}}])
        self.assertEqual((state["catapults"][0]["ammo"], state["catapults"][0]["reload_turns"]), (2, 2))
        self.assertEqual(state["wall_damage"], [{"x": 11, "y": 7, "damage": 1}])
        self.assertFalse(is_walkable(11, 7))
        state = apply_action(state, {"type": "end_turn"})
        state = apply_action(state, aim)
        with self.assertRaises(InvalidAction):
            apply_action(state, fire)
        state = apply_action(state, {"type": "end_turn"})
        state = apply_action(state, fire)
        self.assertEqual(state["wall_damage"], [])
        self.assertEqual(state["breaches"], [{"x": 11, "y": 7}])
        self.assertTrue(state["history"][-1]["breached"])
        self.assertEqual(state["catapults"][0]["ammo"], 1)
        moved = apply_action(state, {"type": "move", "units": [0], "x": 11, "y": 7})
        self.assertNotEqual((moved["units"][0]["x"], moved["units"][0]["y"]), (11, 7))
        self.assertTrue(is_walkable(11, 7, {**MAP, "breaches": {(11, 7)}}))
        self.assertFalse(has_line_of_sight((10, 7), (12, 7)))
        self.assertTrue(has_line_of_sight((10, 7), (12, 7), {**MAP, "breaches": {(11, 7)}}))
        self.assertEqual(find_path((10, 7), (12, 7), {**MAP, "breaches": {(11, 7)}}),
                         [(11, 7), (12, 7)])
        self.assertEqual(initial_state()["breaches"], [])

    def test_stones_hit_units_including_friends_and_king(self):
        state = initial_state()
        state["units"][6].update(x=6, y=7, health=2)
        state["units"][1]["fight_points"] = 2
        aim = {"type": "aim_catapult", "unit_id": 1, "catapult_id": 0, "x": 6, "y": 7}
        fire = {"type": "fire_catapult", "unit_id": 1, "catapult_id": 0}
        hit = apply_action(apply_action(state, aim), fire)
        self.assertNotIn(6, [unit["id"] for unit in hit["units"]])
        self.assertEqual(hit["history"][-1]["weapon"], "catapult")
        self.assertEqual(hit["history"][-1]["damage"], 2)
        self.assertEqual(hit["history"][-1]["killed"], True)
        state["units"][6].update(x=12, y=5)
        state["units"][0].update(x=6, y=7, health=1)
        friendly = apply_action(apply_action(state, aim), fire)
        self.assertNotIn(0, [unit["id"] for unit in friendly["units"]])
        throne = default_map()
        throne["mission"] = "capture_king"
        throne["catapults"] = [{"x": 8, "y": 7}]
        throne["enemyStartPositions"] = [{"x": 14, "y": 7, "type": "king"},
                                         {"x": 13, "y": 7, "type": "vanguard"}]
        validate_map(throne)
        state = initial_state(throne)
        state["units"][0].update(x=8, y=7, fight_points=2)
        state["units"][6]["health"] = 2
        lost = apply_action(apply_action(state, {**aim, "unit_id": 0, "x": 14}, throne),
                            {**fire, "unit_id": 0}, throne)
        self.assertTrue(lost["defeated"])
        self.assertNotIn(6, [unit["id"] for unit in lost["units"]])


class TerrainMovementTests(TestCase):
    def test_terrain_validation_rejects_bad_types_positions_and_untraversable_rosters(self):
        battlefield = default_map()
        battlefield["terrain"] = [{"x": 3, "y": 5, "type": "mud"},
                                  {"x": 4, "y": 5, "type": "road"}]
        validate_map(battlefield)
        for tiles in ("mud", [{"x": 3, "y": 5, "type": "bog"}],
                      [{"x": 3, "y": 5, "type": ["mud"]}],
                      [{"x": 3, "y": 5, "type": "road", "cost": 1}],
                      [{"x": True, "y": 5, "type": "mud"}],
                      [{"x": 3, "y": 5, "type": "mud"}] * 2,
                      [{"x": 11, "y": 3, "type": "mud"}],
                      [{"x": 99, "y": 5, "type": "mud"}]):
            battlefield["terrain"] = tiles
            with self.subTest(tiles=tiles), self.assertRaises(InvalidMap):
                validate_map(battlefield)

        battlefield = default_map()
        battlefield["startPositions"] = [{"x": 2, "y": 6, "weapon": "crossbow", "armor": "mail"}]
        battlefield["terrain"] = [{"x": 14, "y": 10, "type": "swamp"}]
        with self.assertRaisesRegex(InvalidMap, "reach the objective"):
            validate_map(battlefield)

    def test_cheaper_detour_and_spending_stop_before_unaffordable_tile(self):
        battlefield = default_map()
        battlefield["terrain"] = [{"x": 3, "y": 6, "type": "swamp"},
                                  {"x": 4, "y": 6, "type": "mud"}]
        validate_map(battlefield)
        path = find_path((2, 6), (4, 6), battlefield)
        self.assertEqual(path, [(2, 7), (3, 7), (4, 7), (4, 6)])
        state = initial_state(battlefield)
        state["units"] = [state["units"][0]]
        result = apply_action(state, {"type": "move", "units": [0], "x": 4, "y": 6}, battlefield)
        self.assertEqual((result["units"][0]["x"], result["units"][0]["y"], result["units"][0]["move_points"]),
                         (4, 7, 1))
        with self.assertRaises(InvalidAction):
            apply_action(result, {"type": "move", "units": [0], "x": 4, "y": 6}, battlefield)
        next_turn = apply_action(result, {"type": "end_turn"}, battlefield)
        arrived = apply_action(next_turn, {"type": "move", "units": [0], "x": 4, "y": 6}, battlefield)
        self.assertEqual((arrived["units"][0]["y"], arrived["units"][0]["move_points"]), (6, 1))
        self.assertEqual(state["units"][0]["move_points"], 4)

    def test_weight_restricts_swamp_and_defenders_spend_terrain_cost(self):
        battlefield = default_map()
        battlefield["terrain"] = [{"x": 12, "y": 6, "type": "mud"},
                                  {"x": 12, "y": 7, "type": "grass"},
                                  {"x": 12, "y": 8, "type": "swamp"}]
        validate_map(battlefield)
        state = initial_state(battlefield)
        guard = state["units"][6]
        guard.update(x=12, y=5, weapon="crossbow", armor="mail", move_points=2)
        self.assertEqual(move_allowance(guard), 2)
        self.assertNotIn((12, 6), defender_destinations({**guard, "move_points": 2}, battlefield))
        guard.update(weapon="sword", armor=None)
        self.assertIn((12, 6), defender_destinations(guard, battlefield))
        moved = apply_action(state, {"type": "end_turn"}, battlefield,
                             enemy_orders=[{"unit_id": 6, "x": 12, "y": 6}])
        self.assertEqual((moved["units"][6]["y"], moved["units"][6]["move_points"]), (6, 1))
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "end_turn"}, battlefield,
                         enemy_orders=[{"unit_id": 6, "x": 12, "y": 8}])


class TurnEngineTests(TestCase):
    def test_combat_history_records_player_attack_casualty_and_morale(self):
        state = initial_state()
        self.assertEqual(state["history"], [])
        state["units"][0].update(x=12, y=4, morale=4)
        state["units"][6]["health"] = 1
        state["units"][7].update(x=12, y=7)
        result = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual(result["history"], [{
            "turn": 1, "type": "attack", "actor_id": 0, "actor_side": "attackers",
            "actor_weapon": "sword", "target_id": 6, "target_side": "defenders",
            "target_weapon": "sword", "target_is_king": False, "damage": 1, "killed": True,
            "morale_changes": [{"unit_id": 0, "change": 1}, {"unit_id": 7, "change": -1}],
        }])
        self.assertEqual(state["history"], [])
        with self.assertRaises(InvalidAction):
            apply_action(result, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual(len(result["history"]), 1)

    def test_history_tracks_defender_shots_in_order_before_turn_increments(self):
        state = initial_state()
        state["units"][0].update(x=4, y=6, health=1)
        state["units"][1].update(x=5, y=7)
        state["units"][6].update(x=6, y=6, weapon="longbow")
        state["units"][7].update(x=7, y=7, weapon="crossbow")
        result = apply_action(state, {"type": "end_turn"})
        self.assertEqual(result["turn"], 2)
        self.assertEqual([(event["turn"], event["type"], event["actor_id"],
                           event["target_id"], event["killed"]) for event in result["history"]],
                         [(1, "ranged_attack", 6, 0, True), (1, "ranged_attack", 7, 1, False)])
        self.assertEqual(state["history"], [])

    def test_history_records_promotion_and_preserves_legacy_states(self):
        state = initial_state()
        del state["history"]
        state["units"][0]["morale"] = 5
        promoted = apply_action(state, {"type": "promote", "unit_id": 0})
        self.assertEqual(promoted["history"], [{
            "turn": 1, "type": "promote", "actor_id": 0,
            "actor_side": "attackers", "actor_weapon": "sword", "morale_change": -2,
        }])
        self.assertNotIn("history", state)

    def test_combat_history_is_bounded_and_unrelated_actions_do_not_add_entries(self):
        state = initial_state()
        state["history"] = [{"turn": turn} for turn in range(HISTORY_LIMIT)]
        state["units"][0].update(x=12, y=4)
        moved = apply_action(state, {"type": "move", "units": [1], "x": 4, "y": 7})
        self.assertEqual(moved["history"], state["history"])
        result = apply_action(moved, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual(len(result["history"]), HISTORY_LIMIT)
        self.assertEqual(result["history"][0], {"turn": 1})
        self.assertEqual(state["history"][0], {"turn": 0})

    def test_elevation_requires_connector_for_climbing_and_descending(self):
        battlefield = default_map()
        battlefield["elevation"] = [{"x": 3, "y": 5, "height": 1},
                                    {"x": 4, "y": 5, "height": 2, "access": "ladder"}]
        self.assertIsNone(find_path((2, 5), (4, 5), battlefield))
        battlefield["elevation"][0]["access"] = "ramp"
        self.assertEqual(find_path((2, 5), (4, 5), battlefield), [(3, 5), (4, 5)])
        self.assertEqual(find_path((4, 5), (2, 5), battlefield), [(3, 5), (2, 5)])
        self.assertIsNone(find_path((2, 5), (4, 5), battlefield,
                                    blocked={(3, 5)}))

    def test_map_objects_block_movement_and_both_sides_ranged_attacks(self):
        battlefield = default_map()
        battlefield["objects"] = [{"x": 4, "y": 5, "type": "tree"},
                                  {"x": 5, "y": 6, "type": "rock"}]
        validate_map(battlefield)
        self.assertFalse(is_walkable(4, 5, battlefield))
        self.assertIsNone(find_path((3, 5), (4, 5), battlefield))
        self.assertNotIn((5, 6), defender_destinations({"x": 6, "y": 6}, battlefield))
        self.assertFalse(has_line_of_sight((3, 5), (5, 5), battlefield))
        self.assertFalse(has_line_of_sight((4, 6), (6, 6), battlefield))
        state = initial_state(battlefield)
        state["units"] = [state["units"][2], state["units"][6]]
        state["units"][0].update(x=3, y=5)
        state["units"][1].update(x=5, y=5, weapon="longbow")
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, battlefield)
        ended = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(ended["units"][0]["health"], 3)
        self.assertEqual(ended["units"][1]["fight_points"], 1)

    def test_strongpoint_gate_blocks_walls_but_allows_entry(self):
        battlefield = default_map()
        battlefield["strongpoints"] = [{"left": 6, "right": 9, "top": 3, "bottom": 6,
                                        "gate": {"x": 7, "y": 6}},
                                       {"left": 6, "right": 9, "top": 9, "bottom": 12,
                                        "gate": {"x": 7, "y": 9}}]
        validate_map(battlefield)
        self.assertFalse(is_walkable(6, 4, battlefield))
        self.assertTrue(is_walkable(7, 6, battlefield))
        self.assertTrue(is_walkable(7, 5, battlefield))
        self.assertEqual(find_path((7, 7), (7, 5), battlefield), [(7, 6), (7, 5)])
        self.assertIsNone(find_path((7, 7), (6, 4), battlefield))
        self.assertFalse(has_line_of_sight((5, 4), (7, 4), battlefield))
        self.assertFalse(has_line_of_sight((5, 10), (7, 10), battlefield))
        self.assertTrue(is_walkable(7, 9, battlefield))
        self.assertTrue(has_line_of_sight((7, 7), (7, 5), battlefield))
        state = initial_state(battlefield)
        state["units"][0].update(x=7, y=7)
        moved = apply_action(state, {"type": "move", "units": [0], "x": 7, "y": 5}, battlefield)
        self.assertEqual((moved["units"][0]["x"], moved["units"][0]["y"]), (7, 5))
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 6, "y": 4}, battlefield)

    def test_strongpoint_validation_rejects_bad_bounds_gates_overlaps_and_placements(self):
        battlefield = default_map()
        valid = {"left": 6, "right": 9, "top": 3, "bottom": 6, "gate": {"x": 7, "y": 6}}
        for points in ("invalid", [valid] * 17,
                       [{**valid, "left": True}], [{**valid, "right": 17}],
                       [{**valid, "gate": {"x": 7, "y": 5}}],
                       [{**valid, "gate": {"x": True, "y": 6}}],
                       [valid, valid], [{**valid, "unknown": 1}]):
            battlefield["strongpoints"] = points
            with self.subTest(points=points), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield["strongpoints"] = [valid]
        battlefield["objects"] = [{"x": 6, "y": 4, "type": "tree"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        battlefield.pop("objects")
        battlefield["elevation"] = [{"x": 6, "y": 4, "height": 1}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        battlefield.pop("elevation")
        battlefield["strongpoints"] = [{"left": 6, "right": 10, "top": 0, "bottom": 13,
                                        "gate": {"x": 6, "y": 0}}]
        with self.assertRaisesRegex(InvalidMap, "reach the objective"):
            validate_map(battlefield)

    def test_map_objects_reject_invalid_placements_and_blocked_routes(self):
        battlefield = default_map()
        for objects in ("tree", [{"x": 2, "y": 4, "type": "water"}],
                        [{"x": True, "y": 4, "type": "tree"}],
                        [{"x": 11, "y": 3, "type": "rock"}],
                        [{"x": 14, "y": 10, "type": "rock"}],
                        [{"x": 14, "y": 7, "type": "tree"}],
                        [{"x": 2, "y": 6, "type": "tree"}],
                        [{"x": 3, "y": 5, "type": "rock"}] * 2):
            battlefield["objects"] = objects
            with self.subTest(objects=objects), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield["objects"] = [{"x": 3, "y": 5, "type": "tree"}]
        battlefield["elevation"] = [{"x": 3, "y": 5, "height": 1}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)
        battlefield = default_map()
        battlefield["objects"] = [{"x": 14, "y": 11, "type": "rock"},
                                  {"x": 13, "y": 10, "type": "tree"},
                                  {"x": 15, "y": 10, "type": "tree"}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)

    def test_elevation_moves_and_captures_at_height_with_normal_move_cost(self):
        battlefield = default_map()
        battlefield["startPositions"] = [{"x": 2, "y": 5, "type": "vanguard"}]
        battlefield["objective"] = {"x": 4, "y": 5}
        battlefield["elevation"] = [{"x": 3, "y": 5, "height": 1, "access": "ramp"},
                                    {"x": 4, "y": 5, "height": 2, "access": "ladder"}]
        validate_map(battlefield)
        state = initial_state(battlefield)
        self.assertEqual(state["units"][0]["z"], 0)
        climbed = apply_action(state, {"type": "move", "units": [0], "x": 4, "y": 5}, battlefield)
        self.assertEqual((climbed["units"][0]["x"], climbed["units"][0]["z"],
                          climbed["units"][0]["move_points"]), (4, 2, 2))
        self.assertEqual(state["units"][0]["z"], 0)
        self.assertEqual(apply_action(climbed, {"type": "end_turn"}, battlefield)["capture_progress"], .5)
        descended = apply_action(climbed, {"type": "move", "units": [0], "x": 2, "y": 5}, battlefield)
        self.assertEqual((descended["units"][0]["z"], descended["units"][0]["move_points"]), (0, 0))

    def test_invalid_elevation_is_rejected(self):
        for tiles in ([{"x": 3, "y": 5, "height": 0}],
                      [{"x": 3, "y": 5, "height": True}],
                      [{"x": 11, "y": 3, "height": 1}],
                      [{"x": 3, "y": 5, "height": 1, "access": "stairs"}],
                      [{"x": 3, "y": 5, "height": 1}] * 2):
            battlefield = default_map()
            battlefield["elevation"] = tiles
            with self.subTest(tiles=tiles), self.assertRaises(InvalidMap):
                validate_map(battlefield)
        battlefield = default_map()
        battlefield["objective"] = {"x": 4, "y": 5}
        battlefield["elevation"] = [{"x": 4, "y": 5, "height": 1}]
        with self.assertRaises(InvalidMap):
            validate_map(battlefield)

    def test_defender_can_descend_and_melee_requires_same_height(self):
        battlefield = default_map()
        battlefield["elevation"] = [{"x": 12, "y": 5, "height": 1, "access": "ladder"}]
        state = initial_state(battlefield)
        state["units"][0].update(x=12, y=4)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6}, battlefield)
        self.assertIn((12, 6), defender_destinations(state["units"][6], battlefield))
        moved = apply_action(state, {"type": "end_turn"}, battlefield, enemy_orders=[
            {"unit_id": 6, "x": 12, "y": 6}])
        self.assertEqual((moved["units"][6]["y"], moved["units"][6]["z"]), (6, 0))

    def test_units_start_with_health_and_fight_points(self):
        state = initial_state()
        self.assertEqual(
            (state["units"][0]["health"], state["units"][0]["max_health"],
             state["units"][0]["fight_points"]),
            (3, 3, 1),
        )
        self.assertTrue(all(unit["morale"] == 3 and unit["rank"] == "recruit"
                            for unit in state["units"]))

    def test_killing_a_defender_rallies_killer_and_demoralizes_nearby_defenders(self):
        state = initial_state()
        state["units"][0].update(x=12, y=4, morale=4)
        state["units"][6].update(health=1)
        state["units"][7].update(x=12, y=7)
        result = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual(result["units"][0]["morale"], 5)
        self.assertEqual(next(unit for unit in result["units"] if unit["id"] == 7)["morale"], 2)
        self.assertEqual(state["units"][0]["morale"], 4)
        self.assertEqual(state["units"][6]["health"], 1)

    def test_defender_kill_reduces_nearby_attacker_morale_but_not_distant_allies(self):
        state = initial_state()
        victim, ally, distant, defender = (state["units"][i] for i in (0, 1, 2, 6))
        state["units"] = [victim, ally, distant, defender]
        victim.update(x=12, y=6, health=1)
        ally.update(x=12, y=7)
        distant.update(x=2, y=6)
        result = apply_action(state, {"type": "end_turn"})
        self.assertEqual({unit["id"]: unit["morale"] for unit in result["units"]},
                         {1: 2, 2: 3, 6: 4})
        self.assertFalse(result["defeated"])

    def test_morale_changes_next_turn_movement_for_both_sides(self):
        state = initial_state()
        state["units"][0]["morale"] = 0
        state["units"][1]["morale"] = 5
        state["units"][6].update(x=2, y=2, morale=5)
        state["units"][7].update(x=2, y=3, morale=0)
        result = apply_action(state, {"type": "end_turn"}, enemy_orders=[
            {"unit_id": 6, "x": 7, "y": 2}, {"unit_id": 7, "x": 5, "y": 3},
        ])
        self.assertEqual((result["units"][0]["move_points"], result["units"][1]["move_points"]), (3, 5))
        self.assertEqual((result["units"][6]["x"], result["units"][6]["move_points"]), (7, 0))
        self.assertEqual((result["units"][7]["x"], result["units"][7]["move_points"]), (5, 0))
        self.assertEqual((result["units"][0]["move_capacity"], result["units"][1]["move_capacity"]), (3, 5))
        self.assertEqual((result["units"][6]["move_capacity"], result["units"][7]["move_capacity"]), (5, 3))

    def test_turn_capacities_do_not_change_mid_turn_after_morale_or_promotion(self):
        state = initial_state()
        self.assertEqual((state["units"][0]["move_capacity"], state["units"][0]["fight_capacity"]), (4, 1))
        state["units"][0].update(morale=5, move_points=2, fight_points=0)
        promoted = apply_action(state, {"type": "promote", "unit_id": 0})
        self.assertEqual((promoted["units"][0]["move_points"], promoted["units"][0]["move_capacity"],
                          promoted["units"][0]["fight_points"], promoted["units"][0]["fight_capacity"]),
                         (2, 4, 0, 1))
        following = apply_action(promoted, {"type": "end_turn"})
        self.assertEqual((following["units"][0]["move_points"], following["units"][0]["move_capacity"],
                          following["units"][0]["fight_points"], following["units"][0]["fight_capacity"]),
                         (5, 5, 2, 2))
        old = initial_state()
        for unit in old["units"]:
            del unit["move_capacity"]
            del unit["fight_capacity"]
        resumed = apply_action(old, {"type": "end_turn"})
        self.assertTrue(all("move_capacity" in unit and "fight_capacity" in unit
                            for unit in resumed["units"] if unit["side"] == "attackers"))

    def test_promotion_requires_full_morale_and_grants_points_next_turn(self):
        state = initial_state()
        state["units"][0].update(morale=5, move_points=1, fight_points=0)
        promoted = apply_action(state, {"type": "promote", "unit_id": 0})
        self.assertEqual((promoted["units"][0]["rank"], promoted["units"][0]["morale"]), ("veteran", 3))
        self.assertEqual((promoted["units"][0]["move_points"], promoted["units"][0]["fight_points"]), (1, 0))
        self.assertEqual(state["units"][0]["rank"], "recruit")
        following = apply_action(promoted, {"type": "end_turn"})
        self.assertEqual((following["units"][0]["move_points"], following["units"][0]["fight_points"]), (5, 2))
        self.assertEqual(apply_action(following, {"type": "end_turn"})["units"][0]["rank"], "veteran")

    def test_veteran_can_spend_both_fight_points_without_bypassing_reload(self):
        state = initial_state()
        state["units"][0].update(x=12, y=4, rank="veteran", fight_points=2)
        once = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6})
        twice = apply_action(once, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual((twice["units"][0]["fight_points"], twice["units"][6]["health"]), (0, 1))
        with self.assertRaises(InvalidAction):
            apply_action(twice, {"type": "attack", "unit_id": 0, "target_id": 6})
        state["units"][2].update(x=2, y=6, rank="veteran", fight_points=2)
        state["units"][6].update(x=6, y=6)
        fired = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        with self.assertRaises(InvalidAction):
            apply_action(fired, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})

    def test_invalid_promotions_do_not_change_state(self):
        state = initial_state()
        state["units"][0]["morale"] = 5
        for action in ({"type": "promote", "unit_id": True}, {"type": "promote", "unit_id": 99},
                       {"type": "promote", "unit_id": 6}, {"type": "promote", "unit_id": 1},
                       {"type": "promote", "unit_id": 0, "rank": "veteran"}):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action)
        promoted = apply_action(state, {"type": "promote", "unit_id": 0})
        with self.assertRaises(InvalidAction):
            apply_action(promoted, {"type": "promote", "unit_id": 0})
        self.assertEqual(state["units"][0]["rank"], "recruit")

    def test_legacy_units_gain_morale_and_rank_when_next_action_is_applied(self):
        state = initial_state()
        for unit in state["units"]:
            del unit["morale"]
            del unit["rank"]
        updated = apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 6})
        self.assertTrue(all(unit["morale"] == 3 and unit["rank"] == "recruit"
                            for unit in updated["units"]))

    def test_melee_attack_spends_a_fight_point_and_damages_adjacent_defender(self):
        state = initial_state()
        state["units"][0].update(x=12, y=4)
        original = state["units"][6]["health"]
        attacked = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertEqual(attacked["units"][0]["fight_points"], 0)
        self.assertEqual(attacked["units"][6]["health"], original - 1)
        self.assertEqual(state["units"][0]["fight_points"], 1)
        with self.assertRaises(InvalidAction):
            apply_action(attacked, {"type": "attack", "unit_id": 0, "target_id": 6})

    def test_melee_attack_removes_defeated_defender(self):
        state = initial_state()
        state["units"][0].update(x=12, y=4)
        state["units"][6]["health"] = 1
        attacked = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 6})
        self.assertNotIn(6, [unit["id"] for unit in attacked["units"]])
        self.assertIn(6, [unit["id"] for unit in state["units"]])

    def test_melee_rejects_nonadjacent_friendly_or_invalid_targets(self):
        state = initial_state()
        for action in (
            {"type": "attack", "unit_id": 0, "target_id": 6},
            {"type": "attack", "unit_id": 6, "target_id": 0},
            {"type": "attack", "unit_id": 0, "target_id": 1},
            {"type": "attack", "unit_id": True, "target_id": 6},
        ):
            with self.subTest(action=action), self.assertRaises(InvalidAction):
                apply_action(state, action)
        self.assertEqual(state["units"][0]["fight_points"], 1)

    def test_ranged_attack_uses_unit_range_and_spends_fight_point(self):
        state = initial_state()
        attacker, target = state["units"][2], state["units"][6]
        attacker.update(x=2, y=6)
        target.update(x=6, y=6)
        attacked = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        self.assertEqual(attacked["units"][2]["fight_points"], 0)
        self.assertEqual(attacked["units"][2]["reload_turns"], 2)
        self.assertEqual(attacked["units"][6]["health"], 2)

    def test_ranged_attack_rejects_out_of_range_blocked_and_wrong_unit(self):
        state = initial_state()
        attacker, target = state["units"][2], state["units"][6]
        attacker.update(x=2, y=6)
        target.update(x=8, y=6)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        self.assertFalse(has_line_of_sight((10, 7), (12, 7)))
        self.assertTrue(has_line_of_sight((2, 6), (6, 6)))
        state["units"][0].update(x=5, y=6)
        target.update(x=6, y=6)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "ranged_attack", "unit_id": 0, "target_id": 6})
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "attack", "unit_id": 2, "target_id": 6})

    def test_ranged_reload_blocks_next_turn_then_recovers(self):
        state = initial_state()
        state["units"][2].update(x=2, y=6)
        state["units"][6].update(x=6, y=6)
        state = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        state = apply_action(state, {"type": "end_turn"})
        self.assertEqual(state["units"][2]["reload_turns"], 1)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        state = apply_action(state, {"type": "end_turn"})
        self.assertEqual(state["units"][2]["reload_turns"], 0)
        self.assertEqual(
            apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})["units"][6]["health"],
            1,
        )

    def test_gate_walls_block_first_ranged_hit_from_outside_not_inside(self):
        state = initial_state()
        state["units"][2].update(x=14, y=11)
        state["units"][6].update(x=14, y=9)
        blocked = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        self.assertEqual(blocked["units"][6]["health"], 3)
        self.assertEqual(blocked["units"][2]["fight_points"], 0)
        self.assertEqual(blocked["units"][2]["reload_turns"], 2)
        self.assertEqual(blocked["history"][-1]["cover"], "wall")
        self.assertEqual(blocked["history"][-1]["damage"], 0)
        self.assertNotIn("cover_turn", state["units"][6])

        state["units"][2].update(x=14, y=8)
        clear = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6})
        self.assertEqual(clear["units"][6]["health"], 2)
        self.assertNotIn("cover", clear["history"][-1])

    def test_tree_and_rock_cover_block_only_one_ranged_shot_per_turn(self):
        for kind in ("tree", "rock"):
            with self.subTest(kind=kind):
                battlefield = default_map()
                battlefield["objects"] = [{"x": 5, "y": 4, "type": kind}]
                state = initial_state(battlefield)
                state["units"][2].update(x=3, y=5)
                state["units"][6].update(x=6, y=5)
                action = lambda unit_id: {"type": "ranged_attack", "unit_id": unit_id, "target_id": 6}
                state = apply_action(state, action(2), battlefield)
                self.assertEqual(state["history"][-1]["cover"], kind)
                state = apply_action(state, action(3), battlefield)
                self.assertEqual(state["units"][6]["health"], 2)
                self.assertNotIn("cover", state["history"][-1])
                state = apply_action(state, {"type": "end_turn"}, battlefield)
                state = apply_action(state, {"type": "end_turn"}, battlefield)
                state = apply_action(state, action(2), battlefield)
                self.assertEqual(state["history"][-1]["cover"], kind)
                self.assertEqual(state["units"][6]["health"], 2)

    def test_cover_protects_attackers_but_not_against_melee_or_on_high_ground(self):
        battlefield = default_map()
        battlefield["objects"] = [{"x": 5, "y": 4, "type": "tree"}]
        state = initial_state(battlefield)
        state["units"] = [state["units"][0], state["units"][6]]
        state["units"][0].update(x=6, y=5)
        state["units"][1].update(x=3, y=5, weapon="longbow")
        blocked = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(blocked["units"][0]["health"], 3)
        self.assertEqual(blocked["history"][-1]["cover"], "tree")

        state["units"][1].update(x=6, y=6, weapon="sword")
        struck = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(struck["units"][0]["health"], 2)
        self.assertNotIn("cover", struck["history"][-1])

        raised = default_map()
        raised["objects"] = battlefield["objects"]
        raised["elevation"] = [{"x": 6, "y": 5, "height": 1, "access": "ramp"}]
        state = initial_state(raised)
        state["units"][2].update(x=3, y=5)
        state["units"][6].update(x=6, y=5, z=1)
        result = apply_action(state, {"type": "ranged_attack", "unit_id": 2, "target_id": 6}, raised)
        self.assertEqual(result["units"][6]["health"], 2)

    def test_defender_counterattacks_and_can_defeat_the_attacking_company(self):
        state = initial_state()
        attacker, defender = state["units"][0], state["units"][6]
        state["units"] = [attacker, defender]
        attacker.update(x=12, y=6, health=1)
        defender.update(x=12, y=5)
        ended = apply_action(state, {"type": "end_turn"})
        self.assertTrue(ended["defeated"])
        self.assertEqual(ended["units"], [ended["units"][0]])
        self.assertEqual(ended["units"][0]["side"], "defenders")
        with self.assertRaises(InvalidAction):
            apply_action(ended, {"type": "end_turn"})

    def test_defender_counterattack_reduces_health_without_defeat(self):
        state = initial_state()
        attacker, defender = state["units"][0], state["units"][6]
        state["units"] = [attacker, defender]
        attacker.update(x=12, y=6)
        defender.update(x=12, y=5)
        ended = apply_action(state, {"type": "end_turn"})
        self.assertEqual(ended["units"][0]["health"], 2)
        self.assertFalse(ended["defeated"])

    def test_ranged_defender_attacks_from_range_during_its_turn(self):
        state = initial_state()
        attacker, defender = state["units"][0], state["units"][6]
        state["units"] = [attacker, defender]
        attacker.update(x=2, y=6)
        defender.update(x=6, y=6, weapon="longbow")
        ended = apply_action(state, {"type": "end_turn"})
        self.assertEqual(ended["units"][0]["health"], 2)
        self.assertEqual(ended["units"][1]["reload_turns"], 2)

    def test_path_to_courtyard_uses_gate_and_walls_block_moves(self):
        path = find_path((10, 9), (MAP["objective"]["x"], MAP["objective"]["y"]))
        self.assertIn((MAP["gate"]["x"], MAP["gate"]["y"]), path)
        self.assertTrue(all(is_walkable(*point) for point in path))
        self.assertIsNone(find_path((2, 6), (MAP["keep"]["left"], MAP["keep"]["top"])))

    def test_map_rejects_duplicate_start_tiles_on_either_side(self):
        for side in ("startPositions", "enemyStartPositions"):
            battlefield = default_map()
            battlefield[side][1].update(x=battlefield[side][0]["x"],
                                        y=battlefield[side][0]["y"])
            with self.subTest(side=side), self.assertRaises(InvalidMap):
                validate_map(battlefield)

    def test_player_cannot_enter_occupied_tile_but_can_use_vacated_tile(self):
        state = initial_state()
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 3, "y": 7})
        self.assertEqual((state["units"][0]["x"], state["units"][0]["y"]), (2, 6))
        moved = apply_action(state, {"type": "move", "units": [1], "x": 4, "y": 7})
        moved = apply_action(moved, {"type": "move", "units": [0], "x": 3, "y": 7})
        self.assertEqual((moved["units"][0]["x"], moved["units"][0]["y"]), (3, 7))
        self.assertEqual(len({(unit["x"], unit["y"]) for unit in moved["units"]}), len(moved["units"]))

    def test_player_routes_around_units_and_cannot_pass_blocked_gate(self):
        state = initial_state()
        state["units"] = [unit for unit in state["units"] if unit["id"] in (0, 1, 6, 7)]
        state["units"][1].update(x=3, y=6)
        moved = apply_action(state, {"type": "move", "units": [0], "x": 4, "y": 6})
        self.assertEqual((moved["units"][0]["x"], moved["units"][0]["y"]), (4, 6))
        self.assertEqual(moved["units"][0]["move_points"], 0)  # Two steps around the blocker.
        state["units"][1].update(x=14, y=10)
        state["units"][0].update(x=14, y=11)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 14, "y": 7})

    def test_group_orders_leave_units_on_distinct_tiles(self):
        state = initial_state()
        moved = apply_action(state, {"type": "move", "units": [0, 1], "x": 3, "y": 6})
        self.assertNotEqual((moved["units"][0]["x"], moved["units"][0]["y"]),
                            (moved["units"][1]["x"], moved["units"][1]["y"]))
        self.assertEqual(len({(unit["x"], unit["y"]) for unit in moved["units"]}), len(moved["units"]))

    def test_movement_spends_points_and_end_turn_restores_them(self):
        state = initial_state()
        state = apply_action(state, {"type": "move", "units": [0], "x": 8, "y": 6})
        self.assertEqual((state["units"][0]["x"], state["units"][0]["y"]), (5, 5))
        self.assertEqual(state["units"][0]["move_points"], 0)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [0], "x": 7, "y": 6})
        state = apply_action(state, {"type": "end_turn"})
        self.assertEqual(state["turn"], 2)
        self.assertEqual(state["units"][0]["move_points"], 4)

    def test_objective_capture_advances_only_on_end_turn(self):
        state = initial_state()
        state["units"][0]["x"] = MAP["objective"]["x"]
        state["units"][0]["y"] = MAP["objective"]["y"]
        first = apply_action(state, {"type": "end_turn"})
        self.assertEqual(first["capture_progress"], 0.5)
        self.assertFalse(first["captured"])
        second = apply_action(first, {"type": "end_turn"})
        self.assertTrue(second["captured"])
        with self.assertRaises(InvalidAction):
            apply_action(second, {"type": "end_turn"})

    def test_spawned_unit_can_reach_objective_and_capture(self):
        battlefield = default_map()
        battlefield["enemyStartPositions"] = battlefield["enemyStartPositions"][:2]
        state = initial_state(battlefield)
        for _ in range(10):
            state = apply_action(state, {
                "type": "move", "units": [0],
                "x": battlefield["objective"]["x"], "y": battlefield["objective"]["y"],
            }, battlefield)
            if (state["units"][0]["x"], state["units"][0]["y"]) == (
                battlefield["objective"]["x"], battlefield["objective"]["y"]
            ):
                break
            state = apply_action(state, {"type": "end_turn"}, battlefield)
        else:
            self.fail("The courtyard was not reachable from the starting position.")
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertTrue(state["captured"])

    def test_seeded_gate_guard_forces_combat_but_can_be_cleared(self):
        battlefield = default_map()
        validate_map(battlefield)
        self.assertEqual(battlefield["enemyStartPositions"][2],
                         {"x": 14, "y": 9, "weapon": "crossbow"})
        state = initial_state(battlefield)
        guard = state["units"][8]
        self.assertEqual((guard["x"], guard["y"]), (14, 9))
        # Isolate the gate duel: the other soldiers do not affect its outcome.
        state["units"] = [state["units"][0], guard]
        state["units"][0].update(x=14, y=10)
        move = {"type": "move", "units": [0], "x": 14, "y": 7}
        with self.assertRaisesRegex(InvalidAction, "blocked"):
            apply_action(state, move, battlefield)
        for strike in range(3):
            state = apply_action(state, {"type": "attack", "unit_id": 0, "target_id": 8}, battlefield)
            if strike < 2:
                state = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertNotIn(8, [unit["id"] for unit in state["units"]])
        self.assertEqual(state["units"][0]["health"], 2)
        state = apply_action(state, move, battlefield)
        self.assertEqual((state["units"][0]["x"], state["units"][0]["y"]), (14, 7))
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        state = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertTrue(state["captured"])

    def test_invalid_movements_cannot_change_existing_state(self):
        state = initial_state()
        for action in (
            {"type": "move", "units": [0], "x": 11, "y": 3},
            {"type": "move", "units": [0, 0], "x": 3, "y": 6},
            {"type": "move", "units": [True], "x": 3, "y": 6},
            {"type": "move", "units": [0], "x": True, "y": 6},
        ):
            with self.assertRaises(InvalidAction):
                apply_action(state, action)
        self.assertEqual(state, initial_state())

    def test_custom_map_routes_and_capture_use_its_objective(self):
        map_data = default_map()
        map_data["objective"] = {"x": 4, "y": 5}
        map_data["startPositions"] = [{"x": 2, "y": 5, "type": "longbow"}]
        state = initial_state(map_data)
        state = apply_action(state, {"type": "move", "units": [0], "x": 4, "y": 5}, map_data)
        self.assertEqual((state["units"][0]["x"], state["units"][0]["y"]), (4, 5))
        state = apply_action(state, {"type": "end_turn"}, map_data)
        self.assertEqual(state["capture_progress"], 0.5)

    def test_custom_keep_controls_wall_collision_and_gate_route(self):
        map_data = default_map()
        map_data["keep"] = {"left": 4, "right": 9, "top": 3, "bottom": 10}
        map_data["gate"] = {"x": 6, "y": 10}
        map_data["objective"] = {"x": 6, "y": 7}
        path = find_path((2, 8), (6, 7), map_data)
        self.assertIn((6, 10), path)
        self.assertFalse(is_walkable(4, 4, map_data))
        self.assertTrue(is_walkable(11, 3, map_data))

    def test_defender_orders_move_on_end_turn_but_players_cannot_order_them(self):
        state = initial_state()
        defender = state["units"][6]
        self.assertEqual(defender["side"], "defenders")
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "move", "units": [defender["id"]], "x": 12, "y": 6})
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=[
            {"unit_id": defender["id"], "x": 12, "y": 6},
        ])
        self.assertEqual((moved["units"][6]["x"], moved["units"][6]["y"]), (12, 6))
        self.assertEqual(moved["units"][6]["move_points"], 3)
        self.assertEqual(moved["units"][0]["move_points"], 4)
        self.assertEqual((defender["x"], defender["y"]), (12, 5))

    def test_invalid_defender_orders_do_not_change_state_or_capture(self):
        state = initial_state()
        state["units"][0].update(x=14, y=7)
        for orders in (
            [{"unit_id": 0, "x": 12, "y": 6}],
            [{"unit_id": 6, "x": 14, "y": 7}],
            [{"unit_id": 6, "x": 11, "y": 3}],
            [{"unit_id": 6, "x": 2, "y": 6}],
            [{"unit_id": 6, "x": 12, "y": 6}, {"unit_id": 6, "x": 12, "y": 7}],
            [{"unit_id": True, "x": 12, "y": 6}],
        ):
            with self.subTest(orders=orders), self.assertRaises(InvalidAction):
                apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        self.assertEqual(state["turn"], 1)
        self.assertEqual(state["capture_progress"], 0)
        self.assertEqual(state["units"][6]["move_points"], 4)

    def test_defender_orders_cannot_enter_or_cross_occupied_tiles(self):
        state = initial_state()
        state["units"][0].update(x=12, y=6)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "end_turn"}, enemy_orders=[
                {"unit_id": 6, "x": 12, "y": 6}])
        state["units"][0].update(x=2, y=6)
        state["units"][7].update(x=12, y=6)
        with self.assertRaises(InvalidAction):
            apply_action(state, {"type": "end_turn"}, enemy_orders=[
                {"unit_id": 6, "x": 12, "y": 6}])
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=[
            {"unit_id": 7, "x": 13, "y": 6}, {"unit_id": 6, "x": 12, "y": 6}])
        self.assertEqual((moved["units"][6]["x"], moved["units"][6]["y"]), (12, 6))
        self.assertEqual(len({(unit["x"], unit["y"]) for unit in moved["units"]}), len(moved["units"]))

    def test_defender_goals_reserve_tiles_for_sequential_orders(self):
        state = initial_state()
        state["units"][7].update(x=12, y=6)
        goals = [{"unit_id": 6, "x": 12, "y": 6}, {"unit_id": 7, "x": 13, "y": 6}]
        orders = resolve_defender_goals(state, goals)
        self.assertEqual(len(orders), 2)
        self.assertNotEqual((orders[0]["x"], orders[0]["y"]), (12, 6))
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        self.assertEqual(len({(unit["x"], unit["y"]) for unit in moved["units"]}), len(moved["units"]))

    def test_last_objective_guard_stays_nearby_despite_a_distant_goal(self):
        state = initial_state()
        state["units"] = [unit for unit in state["units"] if unit["id"] != 8]
        state["units"][6].update(x=14, y=6)
        orders = resolve_defender_goals(state, [{"unit_id": 6, "x": 12, "y": 5}])
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        guard = moved["units"][6]
        self.assertLessEqual(abs(guard["x"] - 14) + abs(guard["y"] - 7), 2)
        self.assertNotEqual((guard["x"], guard["y"]), (12, 5))

    def test_seeded_crossbow_stays_on_garrison_duty_when_ordered_away(self):
        state = initial_state()
        orders = resolve_defender_goals(state, [{"unit_id": 8, "x": 2, "y": 6}])
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        guard = next(unit for unit in moved["units"] if unit["id"] == 8)
        self.assertLessEqual(abs(guard["x"] - 14) + abs(guard["y"] - 7), 2)

    def test_objective_guard_can_leave_after_another_takes_over(self):
        state = initial_state()
        state["units"] = [unit for unit in state["units"] if unit["id"] != 8]
        state["units"][6].update(x=14, y=6)
        orders = resolve_defender_goals(state, [
            {"unit_id": 7, "x": 15, "y": 8}, {"unit_id": 6, "x": 12, "y": 5},
        ])
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        self.assertEqual((moved["units"][6]["x"], moved["units"][6]["y"]), (12, 5))
        self.assertEqual((moved["units"][7]["x"], moved["units"][7]["y"]), (15, 8))

    def test_two_guards_cannot_both_abandon_the_objective(self):
        state = initial_state()
        state["units"] = [unit for unit in state["units"] if unit["id"] != 8]
        state["units"][6].update(x=14, y=6)
        state["units"][7].update(x=15, y=7)
        orders = resolve_defender_goals(state, [
            {"unit_id": 6, "x": 12, "y": 5}, {"unit_id": 7, "x": 16, "y": 8},
        ])
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        self.assertTrue(any(
            abs(unit["x"] - 14) + abs(unit["y"] - 7) <= 2
            for unit in moved["units"] if unit["side"] == "defenders"
        ))

    def test_defenders_prioritize_capturer_over_wounded_nonoccupier(self):
        for weapon, position in (("sword", (14, 6)), ("longbow", (14, 4))):
            with self.subTest(weapon=weapon):
                state = initial_state()
                state["units"] = [unit for unit in state["units"] if unit["id"] != 8]
                state["units"][6].update(x=position[0], y=position[1], weapon=weapon)
                state["units"][0].update(x=14, y=7)
                state["units"][1].update(x=13, y=6, health=1)
                result = apply_action(state, {"type": "end_turn"})
                shot = next(event for event in result["history"] if event["actor_id"] == 6)
                self.assertEqual(shot["target_id"], 0)
                self.assertEqual(result["capture_progress"], 0.5)

    def test_defender_destinations_match_legal_reachable_tiles(self):
        state = initial_state()
        unit = state["units"][6]
        destinations = defender_destinations(unit)
        self.assertIn((13, 7), destinations)
        self.assertNotIn((unit["x"], unit["y"]), destinations)
        self.assertNotIn((MAP["objective"]["x"], MAP["objective"]["y"]), destinations)
        self.assertNotIn((11, 3), destinations)
        objective = (MAP["objective"]["x"], MAP["objective"]["y"])
        self.assertTrue(all(
            0 < len(find_path((unit["x"], unit["y"]), tile, blocked={objective})) <= 4
            for tile in destinations
        ))

    def test_defender_goals_are_routed_around_the_objective(self):
        state = initial_state()
        state["units"][6].update(x=14, y=6)
        orders = resolve_defender_goals(state, [{"unit_id": 6, "x": 14, "y": 7}])
        self.assertEqual(len(orders), 1)
        self.assertNotEqual((orders[0]["x"], orders[0]["y"]), (14, 7))
        moved = apply_action(state, {"type": "end_turn"}, enemy_orders=orders)
        self.assertEqual(moved["turn"], 2)
        self.assertNotEqual((moved["units"][6]["x"], moved["units"][6]["y"]), (14, 7))
        self.assertEqual(
            len(find_path((14, 6), (14, 8), blocked={(14, 7)})), 4
        )
        self.assertIn((14, 8), defender_destinations(state["units"][6]))
        for goals in (
            [{"unit_id": 0, "x": 14, "y": 7}],
            [{"unit_id": 6, "x": True, "y": 7}],
            [{"unit_id": 6, "x": MAP["cols"], "y": 7}],
            [{"unit_id": 6, "x": 14, "y": 7}, {"unit_id": 6, "x": 13, "y": 7}],
        ):
            with self.subTest(goals=goals), self.assertRaises(InvalidAction):
                resolve_defender_goals(state, goals)

    def test_older_maps_receive_a_defender_without_changing_their_definition(self):
        map_data = default_map()
        del map_data["enemyStartPositions"]
        state = initial_state(map_data)
        self.assertEqual(len([unit for unit in state["units"] if unit["side"] == "defenders"]), 1)
        self.assertNotEqual(
            (state["units"][-1]["x"], state["units"][-1]["y"]),
            (map_data["objective"]["x"], map_data["objective"]["y"]),
        )
        self.assertNotIn("enemyStartPositions", map_data)
