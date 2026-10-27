"""Small, deterministic rules kernel. All costs are single-square box pushes."""

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256

from .budget import spend


class Invalid(ValueError):
    """A board, solution, or certificate fails validation."""


DIRECTIONS = {"u": (0, -1), "d": (0, 1), "l": (-1, 0), "r": (1, 0)}
WHITESPACE = " \t\r\n"
MAX_CELLS = 4096
MAX_MOVES = 2_000_000
INFINITY = 10**9
State = tuple[tuple[int, ...], int]


@dataclass(frozen=True)
class Board:
    width: int
    height: int
    floor: frozenset[int]
    goals: frozenset[int]
    boxes: tuple[int, ...]
    player: int

    @classmethod
    def parse(cls, text: str) -> "Board":
        lines = text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            raise Invalid("empty board")
        width, height = max(map(len, lines)), len(lines)
        if width * height > MAX_CELLS:
            raise Invalid("board exceeds cell limit")
        if any(c not in "# .$*@+-_" for line in lines for c in line):
            raise Invalid("unknown board character")
        cells = "".join(line.ljust(width) for line in lines)
        floor = {i for i, c in enumerate(cells) if c != "#"}
        exterior = {i for i in floor if i % width in (0, width-1) or i // width in (0, height-1)}
        queue = deque(exterior)
        while queue:
            pos = queue.popleft()
            for dx, dy in DIRECTIONS.values():
                x, y = pos % width + dx, pos // width + dy
                nxt = y * width + x
                if 0 <= x < width and 0 <= y < height and nxt in floor and nxt not in exterior:
                    exterior.add(nxt)
                    queue.append(nxt)
        if any(cells[i] in ".$*@+" for i in exterior):
            raise Invalid("board is open to the exterior")
        floor -= exterior
        players = [i for i, c in enumerate(cells) if c in "@+"]
        boxes = tuple(i for i, c in enumerate(cells) if c in "$*")
        goals = frozenset(i for i, c in enumerate(cells) if c in ".*+")
        if len(players) != 1:
            raise Invalid("board must have exactly one player")
        if not boxes or len(boxes) != len(goals):
            raise Invalid("board must have equally many boxes and goals, at least one")
        return cls(width, height, frozenset(floor), goals, boxes, players[0])

    def text(self) -> str:
        cells = ["#"] * (self.width * self.height)
        for pos in self.floor:
            cells[pos] = "." if pos in self.goals else " "
        for pos in self.boxes:
            cells[pos] = "*" if pos in self.goals else "$"
        cells[self.player] = "+" if self.player in self.goals else "@"
        return "\n".join("".join(cells[i:i+self.width]) for i in range(0, len(cells), self.width)) + "\n"

    @property
    def digest(self) -> str:
        return sha256(self.text().encode("ascii")).hexdigest()

    @property
    def push_parity(self) -> int:
        """Every push flips one box's checkerboard color; goals fix the endpoint."""
        def color_sum(positions):
            return sum(pos % self.width + pos // self.width for pos in positions)
        return (color_sum(self.goals) - color_sum(self.boxes)) % 2

    def step(self, pos: int, direction: str) -> int | None:
        dx, dy = DIRECTIONS[direction]
        x, y = pos % self.width + dx, pos // self.width + dy
        nxt = y * self.width + x
        return nxt if 0 <= x < self.width and 0 <= y < self.height and nxt in self.floor else None

    def reachable(self, boxes: tuple[int, ...] | frozenset[int], player: int) -> frozenset[int]:
        occupied = frozenset(boxes)
        if player not in self.floor or player in occupied:
            raise Invalid("invalid player position")
        seen = {player}
        queue = deque([player])
        while queue:
            for direction in DIRECTIONS:
                nxt = self.step(queue[0], direction)
                if nxt is not None and nxt not in occupied and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
            queue.popleft()
        return frozenset(seen)

    def state(self, boxes: tuple[int, ...], player: int) -> State:
        return tuple(sorted(boxes)), min(self.reachable(boxes, player))

    @property
    def initial(self) -> State:
        return self.state(self.boxes, self.player)

    def successors(self, state: State) -> list[State]:
        """Enumerate every legal one-push successor, with free walking collapsed."""
        boxes, player = state
        occupied = frozenset(boxes)
        reachable = self.reachable(boxes, player)
        opposite = {"u": "d", "d": "u", "l": "r", "r": "l"}
        result = []
        for box in boxes:
            for direction in DIRECTIONS:
                dest = self.step(box, direction)
                behind = self.step(box, opposite[direction])
                if dest is not None and dest not in occupied and behind in reachable:
                    spend("push_transitions")
                    result.append(self.state(tuple((occupied - {box}) | {dest}), box))
        return result


@dataclass(frozen=True)
class Replay:
    moves: int
    pushes: int


def replay(board: Board, text: str) -> Replay:
    """Accept only a complete legal LURD trace. Case never determines cost."""
    if len(text) > 2 * MAX_MOVES:
        raise Invalid("solution exceeds input limit")
    boxes = set(board.boxes)
    player = board.player
    moves = pushes = 0
    for char in text:
        if char in WHITESPACE:
            continue
        direction = char.lower()
        if direction not in DIRECTIONS:
            raise Invalid(f"invalid solution character {char!r}")
        if boxes == board.goals:
            raise Invalid("solution contains actions after completion")
        moves += 1
        if moves > MAX_MOVES:
            raise Invalid("solution exceeds move limit")
        dest = board.step(player, direction)
        if dest is None:
            raise Invalid(f"move {moves} hits a wall")
        if dest in boxes:
            beyond = board.step(dest, direction)
            if beyond is None or beyond in boxes:
                raise Invalid(f"move {moves} is an illegal push")
            boxes.remove(dest)
            boxes.add(beyond)
            pushes += 1
        player = dest
    if boxes != board.goals:
        raise Invalid("trace ends before every box is on a goal")
    return Replay(moves, pushes)


def assignment_cost(costs: list[list[int]]) -> int:
    """Minimum perfect matching via integer Hungarian algorithm, O(n^3)."""
    n = len(costs)
    if not n or any(len(row) != n for row in costs):
        raise Invalid("expected a nonempty square cost matrix")
    u, v, p, way = ([0] * (n+1) for _ in range(4))
    for i in range(1, n+1):
        p[0] = i
        j0 = 0
        minv = [INFINITY * (n+1)] * (n+1)
        used = [False] * (n+1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = INFINITY * (n+1), 0
            for j in range(1, n+1):
                if not used[j]:
                    cur = costs[i0-1][j-1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return -v[0]


class MatchingBound:
    """Ignore other boxes and player access; retain walls and push support."""

    def __init__(self, board: Board):
        self.board = board
        self.distances = []
        for goal in sorted(board.goals):
            distances = {goal: 0}
            queue = deque([goal])
            while queue:
                pos = queue.popleft()
                for direction in DIRECTIONS:
                    prev = board.step(pos, direction)
                    support = board.step(prev, direction) if prev is not None else None
                    if support is not None and prev not in distances:
                        distances[prev] = distances[pos] + 1
                        queue.append(prev)
            self.distances.append(distances)
        self.cost = lru_cache(maxsize=100_000)(self._cost)

    def _cost(self, boxes: tuple[int, ...]) -> int:
        spend("matching_evaluations")
        return assignment_cost([[d.get(box, INFINITY) for d in self.distances] for box in boxes])
