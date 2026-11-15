from django.test import TestCase

from ..engine import (
    HISTORY_LIMIT, MAP, InvalidAction, InvalidMap, apply_action, capture_status, default_map, defender_destinations, find_path,
    has_line_of_sight, initial_state, is_walkable, resolve_defender_goals, validate_map,
)


class VillageTests(TestCase):
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
                       [{**valid, "door": {"x": 6, "y": 3}}]):
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
            lambda data: data["startPositions"][0].update(type="king"),
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
        courtyard["enemyStartPositions"][0]["type"] = "king"
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
        self.assertEqual(dead["history"][-1]["target_type"], "king")
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
            "actor_type": "vanguard", "target_id": 6, "target_side": "defenders",
            "target_type": "vanguard", "damage": 1, "killed": True,
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
        state["units"][6].update(x=6, y=6, type="longbow")
        state["units"][7].update(x=7, y=7, type="crossbow")
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
            "actor_side": "attackers", "actor_type": "vanguard", "morale_change": -2,
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
        state["units"][1].update(x=5, y=5, type="longbow")
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
        state["units"][1].update(x=3, y=5, type="longbow")
        blocked = apply_action(state, {"type": "end_turn"}, battlefield)
        self.assertEqual(blocked["units"][0]["health"], 3)
        self.assertEqual(blocked["history"][-1]["cover"], "tree")

        state["units"][1].update(x=6, y=6, type="vanguard")
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
        defender.update(x=6, y=6, type="longbow")
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
                         {"x": 14, "y": 9, "type": "crossbow"})
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
        for weapon, position in (("vanguard", (14, 6)), ("longbow", (14, 4))):
            with self.subTest(weapon=weapon):
                state = initial_state()
                state["units"] = [unit for unit in state["units"] if unit["id"] != 8]
                state["units"][6].update(x=position[0], y=position[1], type=weapon)
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
