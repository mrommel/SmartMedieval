import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..engine import default_map, normalize_map
from ..models import GameInstance, Scenario, SingleGame


class GameEditorTests(TestCase):
    def test_preview_unsaved_map_without_saving_or_starting_game(self):
        editor = get_user_model().objects.create_superuser("editor", "editor@example.test", "password")
        self.client.force_login(editor)
        url = reverse("admin:game_singlegame_preview")
        add_page = self.client.get(reverse("admin:game_singlegame_add"))
        self.assertContains(add_page, url)
        self.assertContains(add_page, "Validate and preview map")
        game_count = SingleGame.objects.count()
        unsaved = default_map()
        unsaved["startPositions"][0] = {"x": 2, "y": 6, "type": "vanguard"}
        unsaved["houses"] = [{"left": 6, "right": 7, "top": 9, "bottom": 10,
                              "door": {"x": 6, "y": 9, "hidden": True}}]
        response = self.client.post(url, {"map_definition": json.dumps(unsaved)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["map"], normalize_map(unsaved))
        self.assertEqual(response.json()["map"]["startPositions"][0]["weapon"], "sword")
        self.assertEqual(SingleGame.objects.count(), game_count)
        self.assertFalse(GameInstance.objects.exists())
        self.assertNotIn("active_game_id", self.client.session)

    def test_preview_reports_invalid_json_and_map_errors(self):
        editor = get_user_model().objects.create_superuser("editor", "editor@example.test", "password")
        self.client.force_login(editor)
        url = reverse("admin:game_singlegame_preview")
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, {"map_definition": "{bad"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("valid map JSON", response.json()["error"])
        invalid = default_map()
        invalid["gate"] = {"x": 1, "y": 1}
        response = self.client.post(url, {"map_definition": json.dumps(invalid)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("gate must lie on the keep wall", response.json()["error"])
        response = self.client.post(url, {"map_definition": " " * 250_001})
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.json()["error"])

    def test_preview_requires_staff_editor_permission_and_csrf(self):
        url = reverse("admin:game_singlegame_preview")
        data = {"map_definition": json.dumps(default_map())}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        user = get_user_model().objects.create_user("staff", "staff@example.test", "password", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        user.is_superuser = True
        user.save()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        self.assertEqual(csrf_client.post(url, data).status_code, 403)
        self.assertFalse(GameInstance.objects.exists())

    def test_staff_playtest_starts_saved_match_and_resumes_it(self):
        editor = get_user_model().objects.create_superuser("editor", "editor@example.test", "password")
        self.client.force_login(editor)
        saved = default_map()
        game = SingleGame.objects.create(name="Test map", slug="test-map", description="Playtest",
                                         map_definition=saved)
        url = reverse("admin:game_singlegame_playtest", args=[game.pk])
        change = self.client.get(reverse("admin:game_singlegame_change", args=[game.pk]))
        self.assertContains(change, url)
        self.assertContains(change, "Playtest saved game")
        self.assertEqual(self.client.get(url).status_code, 405)

        response = self.client.post(url)
        self.assertRedirects(response, reverse("home") + "?playtest=1", fetch_redirect_response=False)
        instance = GameInstance.objects.get(pk=self.client.session["active_game_id"])
        self.assertEqual(instance.map_definition, normalize_map(saved))
        self.assertEqual(instance.single_game, game)
        self.assertEqual(instance.source_game, game)
        self.assertEqual(instance.revision, 0)
        self.assertEqual(self.client.get(reverse("current-game")).json()["id"], str(instance.pk))

        # A saved edit only affects the next playtest, not the current snapshot.
        changed = default_map()
        changed["startPositions"][0]["weapon"] = "crossbow"
        game.map_definition = changed
        game.save()
        self.assertEqual(self.client.post(url).status_code, 302)
        fresh = GameInstance.objects.get(pk=self.client.session["active_game_id"])
        self.assertNotEqual(fresh.pk, instance.pk)
        self.assertEqual(fresh.map_definition, normalize_map(changed))
        instance.refresh_from_db()
        self.assertEqual(instance.map_definition, normalize_map(saved))

    def test_playtest_requires_change_permission_csrf_and_available_saved_game(self):
        game = SingleGame.objects.create(name="Draft", slug="draft", description="Draft")
        url = reverse("admin:game_singlegame_playtest", args=[game.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        editor = get_user_model().objects.create_user("staff", "staff@example.test", "password", is_staff=True)
        self.client.force_login(editor)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertFalse(GameInstance.objects.exists())
        editor.is_superuser = True
        editor.save()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(editor)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        game.is_available = False
        game.save()
        self.assertNotContains(self.client.get(reverse("admin:game_singlegame_change", args=[game.pk])),
                               "Playtest saved game")
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertFalse(GameInstance.objects.exists())

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

    @override_settings(ENEMY_AI_API_KEY=None)
    def test_editor_to_scenario_play_resume_and_restart_keeps_saved_snapshots(self):
        editor = get_user_model().objects.create_superuser("editor", "editor@example.test", "password")
        self.client.force_login(editor)
        player = Client()
        original = default_map()
        original.update(fog_of_war=True,
                        objective={"x": 4, "y": 5},
                        startPositions=[{"x": 2, "y": 5, "type": "vanguard"}])
        game_form = {
            "name": "Scout assault", "slug": "scout-assault", "description": "A short approach.",
            "introduction": "Advance carefully.", "sort_order": 1,
            "is_available": "on", "map_definition": json.dumps(original), "_save": "Save",
        }
        response = self.client.post(reverse("admin:game_singlegame_add"), game_form)
        self.assertEqual(response.status_code, 302)
        game = SingleGame.objects.get(slug="scout-assault")
        self.assertEqual(game.map_definition, normalize_map(original))

        response = self.client.post(reverse("admin:game_scenario_add"), {
            "name": "Scout mission", "slug": "scout-mission", "description": "One assault.",
            "introduction": "Find the objective.", "sort_order": 1,
            "is_available": "on", "games": [game.pk], "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        scenario = Scenario.objects.get(slug="scout-mission")
        self.assertEqual(player.get(reverse("scenarios-api")).json()[0]["games"][0]["id"], game.pk)
        start_url = reverse("start-game", args=["scenarios", scenario.pk])
        started_response = player.post(start_url, data="{}", content_type="application/json")
        self.assertEqual(started_response.status_code, 201)
        started = started_response.json()
        self.assertEqual((started["kind"], started["game_id"]), ("scenarios", game.pk))
        self.assertNotIn("enemyStartPositions", started["map"])
        self.assertEqual([unit["id"] for unit in started["state"]["units"]], [0])
        self.assertEqual(started["map"]["startPositions"][0]["weapon"], "sword")

        action_url = reverse("game-action")

        def action(revision, order):
            return player.post(action_url, data=json.dumps({"revision": revision, "action": order}),
                               content_type="application/json")

        moved_response = action(0, {"type": "move", "units": [0], "x": 3, "y": 5})
        self.assertEqual(moved_response.status_code, 200)
        moved = moved_response.json()
        self.assertEqual(moved["revision"], 1)
        self.assertEqual((moved["state"]["units"][0]["x"], moved["state"]["units"][0]["y"]), (3, 5))
        self.assertEqual(action(0, {"type": "end_turn", "offline": True}).status_code, 409)
        self.assertEqual(action(1, {"type": "end_turn"}).status_code, 503)
        self.assertEqual(player.get(reverse("current-game")).json(),
                         {key: value for key, value in moved.items() if key != "combat_events"})
        offline = action(1, {"type": "end_turn", "offline": True})
        self.assertEqual(offline.status_code, 200)
        self.assertEqual(offline.json()["revision"], 2)
        self.assertEqual(offline.json()["state"]["turn"], 2)
        self.assertEqual(player.get(reverse("current-game")).json(),
                         {key: value for key, value in offline.json().items() if key != "combat_events"})

        # Editor updates and catalog removal must not rewrite or strand a running session.
        changed = default_map()
        changed["fog_of_war"] = True
        changed["startPositions"] = [{"x": 2, "y": 6, "weapon": "crossbow"}]
        edit_url = reverse("admin:game_singlegame_change", args=[game.pk])
        self.assertEqual(self.client.post(edit_url, {**game_form, "map_definition": json.dumps(changed)}).status_code,
                         302)
        self.assertEqual(player.get(reverse("current-game")).json()["map"]["objective"], {"x": 4, "y": 5})
        self.assertEqual(self.client.post(edit_url, {**game_form, "map_definition": json.dumps(changed),
                                                         "is_available": ""}).status_code, 302)
        self.assertEqual(player.get(reverse("scenarios-api")).json()[0]["games"], [])
        self.assertEqual(player.post(start_url, data="{}", content_type="application/json").status_code, 400)
        self.assertEqual(player.get(reverse("current-game")).json()["id"], started["id"])
        advanced = action(2, {"type": "move", "units": [0], "x": 4, "y": 5})
        self.assertEqual(advanced.status_code, 200)
        self.assertEqual(advanced.json()["state"]["capture_status"], "CAPTURING")
        self.assertEqual(GameInstance.objects.get(pk=started["id"]).revision, 3)

        self.assertEqual(self.client.post(edit_url, {**game_form, "map_definition": json.dumps(changed)}).status_code,
                         302)
        restarted = player.post(start_url, data="{}", content_type="application/json")
        self.assertEqual(restarted.status_code, 201)
        self.assertNotEqual(restarted.json()["id"], started["id"])
        self.assertEqual(restarted.json()["map"],
                         {key: value for key, value in normalize_map(changed).items()
                          if key not in ("enemyStartPositions", "items", "horses")}
                         | {"has_items": False})
        self.assertEqual(restarted.json()["revision"], 0)
        self.assertEqual(player.get(reverse("current-game")).json()["id"], restarted.json()["id"])

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
