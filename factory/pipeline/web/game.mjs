import { newGame, turn, step } from "./snake.mjs";

export function mountGame() {
  const canvas = document.querySelector("#snake");
  const context = canvas.getContext("2d");
  const overlay = document.querySelector("#game-overlay");
  const message = document.querySelector("#game-message");
  const subtitle = document.querySelector("#game-subtitle");
  const start = document.querySelector("#game-start");
  const pauseButton = document.querySelector("#game-pause");
  const status = document.querySelector("#snake-status");
  let game = newGame();
  let timer = null;
  let started = false;
  let best = 0;
  try {
    best = Math.max(0, Number(localStorage.getItem("siesta.snake.best")) || 0);
  } catch {
    /* Private browsing may disable storage. */
  }
  const scoreText = (value) => String(value).padStart(3, "0");
  document.querySelector("#best").textContent = scoreText(best);

  function draw() {
    const unit = canvas.width / game.size;
    context.fillStyle = "#c4ce9c";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#b8c591";
    for (let x = 0; x < game.size; x++) {
      for (let y = 0; y < game.size; y++)
        context.fillRect(x * unit, y * unit, 1, 1);
    }
    context.fillStyle = "#7c5136";
    if (game.food)
      context.fillRect(
        game.food.x * unit + 3,
        game.food.y * unit + 3,
        unit - 6,
        unit - 6,
      );
    game.body.forEach((p, index) => {
      context.fillStyle = index === 0 ? "#273f2c" : "#47613b";
      context.fillRect(p.x * unit + 1, p.y * unit + 1, unit - 2, unit - 2);
    });
    document.querySelector("#score").textContent = scoreText(game.score);
    if (game.score > best) {
      best = game.score;
      document.querySelector("#best").textContent = scoreText(best);
      try {
        localStorage.setItem("siesta.snake.best", String(best));
      } catch {
        /* Playing does not require storage. */
      }
    }
  }

  function pause() {
    if (timer === null) return;
    clearInterval(timer);
    timer = null;
    overlay.hidden = false;
    message.textContent = game.over
      ? game.won
        ? "You filled the board!"
        : "One more round?"
      : "Taking a breather.";
    subtitle.textContent = game.over
      ? `Final score: ${game.score}. Nicely played.`
      : "Your game will be right here.";
    start.textContent = game.over ? "Play again →" : "Resume →";
    pauseButton.textContent = "Resume";
    status.textContent = game.over ? "Game over" : "Paused";
  }

  function play(reset = false) {
    if (timer !== null) clearInterval(timer);
    if (reset || game.over) game = newGame();
    started = true;
    overlay.hidden = true;
    pauseButton.disabled = false;
    pauseButton.textContent = "Pause";
    status.textContent = "Playing · Space to pause";
    canvas.focus({ preventScroll: true });
    draw();
    timer = setInterval(() => {
      game = step(game);
      draw();
      if (game.over) pause();
    }, 140);
  }

  const keys = {
    ArrowUp: "up",
    w: "up",
    ArrowDown: "down",
    s: "down",
    ArrowLeft: "left",
    a: "left",
    ArrowRight: "right",
    d: "right",
  };
  canvas.addEventListener("keydown", (event) => {
    const direction = keys[event.key] || keys[event.key.toLowerCase()];
    if (direction) {
      event.preventDefault();
      if (timer !== null) game = turn(game, direction);
    } else if (event.code === "Space") {
      event.preventDefault();
      if (timer === null) play();
      else pause();
    }
  });
  start.addEventListener("click", () => play());
  document
    .querySelector("#game-restart")
    .addEventListener("click", () => play(true));
  pauseButton.addEventListener("click", () => {
    if (timer === null) play();
    else pause();
  });
  document.querySelectorAll("[data-direction]").forEach((button) => {
    // Keep keyboard focus on the board while using the touch controls.
    button.addEventListener("pointerdown", (event) => event.preventDefault());
    button.addEventListener("click", () => {
      if (timer === null && !game.over && started) play();
      game = turn(game, button.dataset.direction);
    });
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pause();
  });
  window.addEventListener("blur", pause);
  document.addEventListener("focusin", (event) => {
    if (!document.querySelector("#snake-window").contains(event.target))
      pause();
  });
  draw();
  return { pause };
}
