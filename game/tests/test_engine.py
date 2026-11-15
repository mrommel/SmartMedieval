from django.test import TestCase

from ..engine import (
    MAP, InvalidAction, apply_action, default_map, defender_destinations, find_path,
    has_line_of_sight, initial_state, is_walkable, resolve_defender_goals,
)


class TurnEngineTests(TestCase):
    def test_units_start_with_health_and_fight_points(self):
        state = initial_state()
        self.assertEqual(
            (state["units"][0]["health"], state["units"][0]["max_health"],
             state["units"][0]["fight_points"]),
            (3, 3, 1),
        )

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

    def test_movement_spends_points_and_end_turn_restores_them(self):
        state = initial_state()
        state = apply_action(state, {"type": "move", "units": [0], "x": 8, "y": 6})
        self.assertEqual((state["units"][0]["x"], state["units"][0]["y"]), (6, 6))
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
        state = initial_state()
        for _ in range(10):
            state = apply_action(state, {
                "type": "move", "units": [0],
                "x": MAP["objective"]["x"], "y": MAP["objective"]["y"],
            })
            if (state["units"][0]["x"], state["units"][0]["y"]) == (
                MAP["objective"]["x"], MAP["objective"]["y"]
            ):
                break
            state = apply_action(state, {"type": "end_turn"})
        else:
            self.fail("The courtyard was not reachable from the starting position.")
        state = apply_action(state, {"type": "end_turn"})
        state = apply_action(state, {"type": "end_turn"})
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
