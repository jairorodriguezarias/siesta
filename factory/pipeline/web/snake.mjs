const vectors = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const same = (a, b) => a.x === b.x && a.y === b.y;

function placeFood(body, size, random) {
  const free = [];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (!body.some((p) => same(p, { x, y }))) free.push({ x, y });
    }
  }
  return free.length ? free[Math.floor(random() * free.length)] : null;
}

export function newGame(size = 20, random = Math.random) {
  const middle = Math.floor(size / 2);
  const body = [0, 1, 2].map((offset) => ({ x: middle - offset, y: middle }));
  return {
    size,
    body,
    food: placeFood(body, size, random),
    direction: "right",
    turned: false,
    score: 0,
    over: false,
    won: false,
  };
}

export function turn(game, direction) {
  if (!vectors[direction] || game.turned || game.over) return game;
  const [dx, dy] = vectors[direction];
  const [oldX, oldY] = vectors[game.direction];
  if (dx === -oldX && dy === -oldY) return game;
  return { ...game, direction, turned: true };
}

export function step(game, random = Math.random) {
  if (game.over) return game;
  const [dx, dy] = vectors[game.direction];
  const head = { x: game.body[0].x + dx, y: game.body[0].y + dy };
  const eating = game.food && same(head, game.food);
  const occupied = eating ? game.body : game.body.slice(0, -1);
  if (
    head.x < 0 ||
    head.y < 0 ||
    head.x >= game.size ||
    head.y >= game.size ||
    occupied.some((p) => same(p, head))
  )
    return { ...game, over: true };
  const body = [head, ...occupied];
  const food = eating ? placeFood(body, game.size, random) : game.food;
  return {
    ...game,
    body,
    food,
    turned: false,
    score: game.score + (eating ? 10 : 0),
    over: food === null,
    won: food === null,
  };
}
