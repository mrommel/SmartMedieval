from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/scenarios/", views.scenarios_api, name="scenarios-api"),
    path("api/single-games/", views.single_games_api, name="single-games-api"),
    path("api/games/<str:kind>/<int:entry_id>/start/", views.start_game, name="start-game"),
    path("api/games/current/", views.current_game, name="current-game"),
    path("api/games/actions/", views.game_action, name="game-action"),
]
