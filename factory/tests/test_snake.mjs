import test from 'node:test';
import assert from 'node:assert/strict';
import { newGame, turn, step } from '../pipeline/web/snake.mjs';

test('food grows the snake and increases score', () => {
  const game = newGame(12);
  game.food = { x: 7, y: 6 };
  const next = step(game, () => 0);
  assert.equal(next.score, 10);
  assert.equal(next.body.length, game.body.length + 1);
  assert.deepEqual(next.body[0], { x: 7, y: 6 });
  assert.ok(!next.body.some(p => p.x === next.food.x && p.y === next.food.y));
});

test('opposite direction and a second turn in one tick are ignored', () => {
  const game = newGame(12);
  assert.equal(turn(game, 'left').direction, 'right');
  const up = turn(game, 'up');
  assert.equal(turn(up, 'left').direction, 'up');
  assert.equal(turn(step(up), 'left').direction, 'left');
});

test('wall and self collisions end the game', () => {
  const game = newGame(12);
  game.body[0] = { x: 11, y: 6 };
  assert.equal(step(game).over, true);
  game.body = [{x:4,y:4}, {x:4,y:3}, {x:5,y:3}, {x:5,y:4}, {x:6,y:4}];
  assert.equal(step(game).over, true);
});

test('moving into the vacated tail is allowed', () => {
  const game = newGame(12);
  game.body = [{x:4,y:4}, {x:4,y:3}, {x:5,y:3}, {x:5,y:4}];
  assert.equal(step(game).over, false);
});

test('a full board wins without trying forever to place food', () => {
  const game = { size:2, body:[{x:0,y:0},{x:0,y:1},{x:1,y:1}],
    food:{x:1,y:0}, direction:'right', turned:false, score:0, over:false };
  const next = step(game);
  assert.equal(next.won, true);
  assert.equal(next.over, true);
  assert.equal(next.food, null);
});
