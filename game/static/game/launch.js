export function createLaunchUI({ api, onStart, onResume, onLeaveGame }) {
  const startScreen = document.getElementById("start-screen");
  const mainMenu = document.getElementById("main-menu");
  const catalogScreen = document.getElementById("catalog-screen");
  const gameScreen = document.getElementById("game-screen");
  const catalogList = document.getElementById("catalog-list");
  const catalogTitle = document.getElementById("catalog-title");
  const catalogKicker = document.getElementById("catalog-kicker");
  const gameTitle = document.getElementById("game-title");
  const startTitle = document.getElementById("start-title");
  const menuTitle = document.getElementById("menu-title");
  const briefingCopy = document.getElementById("briefing-copy");
  const missionLabel = document.getElementById("mission-label");
  const continueButton = document.getElementById("continue-game");
  const launchError = document.getElementById("launch-error");
  let currentCatalog = "scenarios";
  let catalogRequest = 0;

  function showLaunchScreen(screen) {
    catalogRequest++;
    onLeaveGame();
    startScreen.hidden = screen !== startScreen;
    mainMenu.hidden = screen !== mainMenu;
    catalogScreen.hidden = screen !== catalogScreen;
    gameScreen.hidden = true;
    (screen === startScreen ? startTitle : screen === mainMenu ? menuTitle : catalogTitle).focus();
  }

  function enterGame(snapshot) {
    const { entry, kind } = snapshot;
    gameTitle.textContent = entry.name;
    briefingCopy.textContent = entry.introduction || entry.description;
    missionLabel.textContent = kind === "scenarios" ? "SCENARIO" : "SINGLE GAME";
    startScreen.hidden = true;
    mainMenu.hidden = true;
    catalogScreen.hidden = true;
    gameScreen.hidden = false;
    catalogRequest++;
    launchError.hidden = true;
    continueButton.hidden = false;
    gameTitle.focus();
  }

  function renderCatalogMessage(message, isError = false) {
    const paragraph = document.createElement("p");
    paragraph.className = "catalog-message";
    paragraph.textContent = message;
    catalogList.replaceChildren(paragraph);
    if (isError) {
      const retry = document.createElement("button");
      retry.className = "menu-back";
      retry.type = "button";
      retry.textContent = "Try again";
      retry.addEventListener("click", () => loadCatalog(currentCatalog));
      catalogList.append(retry);
    }
  }

  async function loadCatalog(kind) {
    currentCatalog = kind;
    const request = ++catalogRequest;
    const catalog = kind === "scenarios"
      ? { title: "Scenarios", endpoint: "/api/scenarios/", noun: "scenarios" }
      : { title: "Single games", endpoint: "/api/single-games/", noun: "single games" };
    catalogTitle.textContent = catalog.title;
    catalogKicker.textContent = `AVAILABLE ${catalog.title.toUpperCase()}`;
    renderCatalogMessage("Loading...");
    try {
      const entries = await api(catalog.endpoint);
      if (request !== catalogRequest) return;
      if (!Array.isArray(entries)) throw new Error("The catalog response is invalid.");
      if (!entries.length) {
        renderCatalogMessage(`No ${catalog.noun} are available yet.`);
        return;
      }
      const cards = entries.map(entry => {
        if (kind === "scenarios") {
          const group = document.createElement("div");
          group.className = "catalog-group";
          const name = document.createElement("strong");
          name.textContent = entry.name;
          const description = document.createElement("p");
          description.textContent = entry.description;
          group.append(name, description);
          if (!entry.games.length) {
            const empty = document.createElement("p");
            empty.textContent = "No available games in this scenario.";
            group.append(empty);
          }
          for (const game of entry.games) {
            const button = document.createElement("button");
            button.className = "catalog-entry";
            button.type = "button";
            const label = document.createElement("strong");
            label.textContent = game.name;
            const summary = document.createElement("span");
            summary.textContent = game.description;
            button.append(label, summary);
            button.addEventListener("click", () => onStart(entry, kind, game.id));
            group.append(button);
          }
          return group;
        }
        const button = document.createElement("button");
        button.className = "catalog-entry";
        button.type = "button";
        const name = document.createElement("strong");
        name.textContent = entry.name;
        const description = document.createElement("span");
        description.textContent = entry.description;
        button.append(name, description);
        button.addEventListener("click", () => onStart(entry, kind));
        return button;
      });
      catalogList.replaceChildren(...cards);
    } catch (error) {
      if (request === catalogRequest) renderCatalogMessage(`Could not load ${catalog.noun}: ${error.message}`, true);
    }
  }

  continueButton.addEventListener("click", async () => {
    try {
      await onResume();
      launchError.hidden = true;
    } catch (error) {
      launchError.textContent = `Could not resume game: ${error.message}`;
      launchError.hidden = false;
    }
  });
  document.getElementById("play-game").addEventListener("click", () => showLaunchScreen(mainMenu));
  document.getElementById("menu-back").addEventListener("click", () => showLaunchScreen(startScreen));
  document.getElementById("catalog-back").addEventListener("click", () => showLaunchScreen(mainMenu));
  document.getElementById("main-menu-button").addEventListener("click", () => showLaunchScreen(mainMenu));
  document.querySelectorAll("[data-catalog]").forEach(button => {
    button.addEventListener("click", () => {
      showLaunchScreen(catalogScreen);
      return loadCatalog(button.dataset.catalog);
    });
  });
  const playtest = new URLSearchParams(window.location.search).has("playtest");
  api("/api/games/current/").then(snapshot => {
    continueButton.hidden = false;
    if (playtest) return onResume(snapshot);
  }).catch(error => {
    if (error.status === 404 && !playtest) return;
    launchError.textContent = `${playtest ? "Could not open playtest" : "Could not check saved game"}: ${error.message}`;
    launchError.hidden = false;
  });

  return { enterGame, renderCatalogMessage };
}
