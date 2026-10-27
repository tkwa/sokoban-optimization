"""Independently recomputed additive one/two/three-box lower bounds.

A pattern retains one to three original boxes and removes all other boxes.  Player
walking is free; each state records the component reachable around the retained
boxes.  This finite relaxation can only make a projected solution easier.

The certificate partitions the original boxes into disjoint patterns, and gives
an integer price for each goal.  For pattern P we compute exactly

    d(P) = min_path (pushes - sum(prices of its final goals)).

Each real push belongs to exactly one pattern.  At completion the patterns
occupy every goal exactly once, so sum_P d(P) + sum_g price(g) is a lower bound.
Goal prices enforce some competition for goals without assuming a particular
assignment.  All distances and transitions are rebuilt by this checker; the
certificate supplies no trusted distances or optimizer output.
"""

from heapq import heappop, heappush
from functools import lru_cache
from itertools import combinations
from math import comb

from .core import Board, Invalid, MatchingBound
from .budget import spend

FORMAT = "sokogap-abstraction-v1"
POTENTIAL_FORMAT = "sokogap-abstraction-v2"
MAX_PATTERN_PROOF_STATES = 100_000
MAX_PATTERN_POTENTIAL = 10_000_000
MAX_ABSTRACT_FLOOR = 192
MAX_ABSTRACT_BOXES = 32
MAX_ABSTRACT_STATES = 600_000
MAX_BOX_PATTERNS = 300_000
MAX_PRICE = 2_000_000
MAX_BOUND = 2_000_000


def _integer(value, name, minimum=0, maximum=MAX_BOUND):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise Invalid(f"invalid {name}")
    return value


def positions(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


class AbstractGraph:
    """Complete reverse push graph on the reverse-live cells, for k=1, 2, or 3.

    Cells from which no box can reach any goal even with all other boxes removed
    are omitted.  A successful real solution cannot enter such a cell.  The
    reverse-live calculation retains every successful abstract path as well.
    """

    def __init__(self, board: Board, size: int):
        if size not in (1, 2, 3):
            raise Invalid("abstract patterns must contain one to three boxes")
        if len(board.floor) > MAX_ABSTRACT_FLOOR or len(board.boxes) > MAX_ABSTRACT_BOXES:
            raise Invalid("board exceeds abstraction resource limits")
        self.board = board
        self.size = size
        self.floor_mask = sum(1 << p for p in board.floor)
        self.goal_mask = sum(1 << p for p in board.goals)
        self.goals = tuple(sorted(board.goals))
        self.live = tuple(sorted(set().union(*[set(d) for d in MatchingBound(board).distances])))
        if comb(len(self.live), size) > MAX_BOX_PATTERNS:
            raise Invalid("too many abstract box configurations")
        # Mask horizontal edges before shifting, including for manually built
        # Board objects whose floor happens to touch a rectangular boundary.
        self.left_sources = sum(1 << p for p in board.floor if p % board.width > 0)
        self.right_sources = sum(1 << p for p in board.floor if p % board.width + 1 < board.width)
        self.components = {}
        self.nodes = []
        self.index = {}
        self.terminals = {}
        for box_tuple in combinations(self.live, size):
            occupied = sum(1 << p for p in box_tuple)
            components = self._components(occupied)
            self.components[occupied] = components
            for region in components:
                node = len(self.nodes)
                if node >= MAX_ABSTRACT_STATES:
                    raise Invalid("too many abstract player states")
                self.nodes.append((occupied, region))
                self.index[(occupied, region & -region)] = node
                if occupied & ~self.goal_mask == 0:
                    self.terminals.setdefault(occupied, []).append(node)
        self.reverse = [[] for _ in self.nodes]
        live_mask = sum(1 << p for p in self.live)
        # A reversed push c -> b requires that the current player can reach b;
        # before the forward push, the player stood one more cell beyond b.
        reverse_steps = {}
        for box in self.live:
            choices = []
            for direction in ("u", "d", "l", "r"):
                previous = board.step(box, direction)
                support = board.step(previous, direction) if previous is not None else None
                if previous is not None and support is not None and (1 << previous) & live_mask:
                    choices.append((1 << previous, 1 << support))
            reverse_steps[box] = choices
        for node, (occupied, region) in enumerate(self.nodes):
            for box in positions(occupied):
                box_bit = 1 << box
                for previous_bit, support_bit in reverse_steps[box]:
                    if not (previous_bit & region) or support_bit & (occupied ^ box_bit):
                        continue
                    predecessor_boxes = occupied ^ box_bit ^ previous_bit
                    predecessor_region = self.region(predecessor_boxes, support_bit)
                    spend("push_transitions")
                    self.reverse[node].append(self.index[(predecessor_boxes, predecessor_region & -predecessor_region)])

    def _components(self, occupied):
        free = self.floor_mask & ~occupied
        remaining = free
        result = []
        while remaining:
            reached = remaining & -remaining
            while True:
                expanded = (reached | ((reached & self.right_sources) << 1)
                            | ((reached & self.left_sources) >> 1)
                            | (reached << self.board.width) | (reached >> self.board.width)) & free
                if expanded == reached:
                    break
                reached = expanded
            result.append(reached)
            remaining &= ~reached
        return tuple(result)

    def region(self, occupied, player_bit):
        for region in self.components[occupied]:
            if region & player_bit:
                return region
        raise Invalid("abstract player overlaps a box or is outside the floor")

    def initial_node(self, group):
        return self.node(group, self.board.player)

    def node(self, boxes, player):
        occupied = sum(1 << p for p in boxes)
        if occupied not in self.components:
            raise Invalid("abstract initial box cannot reach any goal")
        region = self.region(occupied, 1 << player)
        return self.index[(occupied, region & -region)]

    def distances(self, goal_prices, with_targets=False):
        """Multi-source Dijkstra with arbitrary integer terminal potentials."""
        if len(goal_prices) != len(self.goals):
            raise Invalid("incorrect number of goal prices")
        price_by_goal = dict(zip(self.goals, goal_prices))
        best = [None] * len(self.nodes)
        targets = [None] * len(self.nodes) if with_targets else None
        queue = []
        for goal_mask, nodes in self.terminals.items():
            value = -sum(price_by_goal[p] for p in positions(goal_mask))
            for node in nodes:
                best[node] = value
                if targets is not None:
                    targets[node] = goal_mask
                heappush(queue, (value, node))
        while queue:
            cost, node = heappop(queue)
            if best[node] != cost:
                continue
            child_cost = cost + 1
            for child in self.reverse[node]:
                if best[child] is None or child_cost < best[child]:
                    best[child] = child_cost
                    if targets is not None:
                        targets[child] = targets[node]
                    heappush(queue, (child_cost, child))
        return (best, targets) if with_targets else best


class PatternHeuristic:
    """Admissible four-box potential from all disjoint 3+1 and 2+2 splits.

    Each constituent distance already includes the negative prices of its final
    goals.  Their sum is admissible for the retained four boxes; maximizing over
    partitions preserves admissibility.  Removing the other boxes also relaxes
    player reachability.  Missing abstract states are provable deadlocks.
    """

    def __init__(self, board, prices, graphs=None, distances=None):
        self.board = board
        self.prices = dict(zip(sorted(board.goals), prices))
        self.graphs = graphs if graphs is not None else {k:AbstractGraph(board,k) for k in (1,2,3)}
        self.distances = distances if distances is not None else {k:g.distances(prices) for k,g in self.graphs.items()}
        self.value = lru_cache(maxsize=100_000)(self._value)

    def _part(self, boxes, player):
        graph=self.graphs[len(boxes)]
        try:
            node=graph.node(boxes,player)
        except Invalid:
            return None
        return self.distances[len(boxes)][node]

    def _value(self, state):
        boxes,player=state
        values=[]
        for i in range(4):
            a=self._part(boxes[:i]+boxes[i+1:],player)
            b=self._part((boxes[i],),player)
            if a is None or b is None:
                return 10**12  # No abstract path implies no real solution.
            values.append(a+b)
        for j in (1,2,3):
            pair=(boxes[0],boxes[j])
            other=tuple(b for b in boxes if b not in pair)
            a,b=self._part(pair,player),self._part(other,player)
            if a is None or b is None:
                return 10**12
            values.append(a+b)
        return max(values)

    def terminal(self, boxes):
        return -sum(self.prices[b] for b in boxes) if set(boxes)<=self.board.goals else None


def verify_pattern_potentials(board, group, rows, heuristic):
    if not isinstance(rows,list) or len(rows)>MAX_PATTERN_PROOF_STATES:
        raise Invalid("invalid abstract potential count")
    potentials={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={"boxes","player","h"}:
            raise Invalid("invalid abstract potential fields")
        boxes=row["boxes"]
        if not isinstance(boxes,list) or len(boxes)!=4:
            raise Invalid("abstract potential must retain exactly four boxes")
        for box in boxes:
            _integer(box,"abstract box cell",maximum=board.width*board.height-1)
        if boxes!=sorted(set(boxes)) or any(b not in board.floor for b in boxes):
            raise Invalid("abstract potential boxes must be distinct sorted floor cells")
        player=_integer(row["player"],"abstract player cell",maximum=board.width*board.height-1)
        state=board.state(tuple(boxes),player)
        if state[1]!=player:
            raise Invalid("abstract player must be the minimum reachable cell")
        h=_integer(row["h"],"abstract potential",minimum=-MAX_PATTERN_POTENTIAL,maximum=MAX_PATTERN_POTENTIAL)
        if state in potentials:
            raise Invalid("duplicate abstract potential state")
        potentials[state]=h
    def value(state):
        return potentials[state] if state in potentials else heuristic.value(state)
    for state,h in potentials.items():
        terminal=heuristic.terminal(state[0])
        if terminal is not None and h>terminal:
            raise Invalid("abstract goal potential exceeds terminal goal prices")
        for child in board.successors(state):
            if h>1+value(child):
                raise Invalid("abstract potential violates a legal push transition")
    initial=board.state(tuple(group),board.player)
    return max(value(initial),heuristic.value(initial))


def verify_abstraction(board: Board, certificate: dict) -> int:
    """Return the strongest integer bound this exact abstraction proves."""
    fields = {"format", "board_sha256", "lower", "groups", "goal_prices"}
    if not isinstance(certificate, dict):
        raise Invalid("invalid abstraction certificate fields")
    version=certificate.get("format")
    if version==POTENTIAL_FORMAT:
        fields.add("pattern_potentials")
    if set(certificate)!=fields:
        raise Invalid("invalid abstraction certificate fields")
    if version not in (FORMAT,POTENTIAL_FORMAT):
        raise Invalid("unsupported abstraction certificate format")
    if certificate["board_sha256"] != board.digest:
        raise Invalid("abstraction certificate is for a different board")
    claimed = _integer(certificate["lower"], "claimed lower bound")
    groups = certificate["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_ABSTRACT_BOXES:
        raise Invalid("invalid abstraction pattern count")
    flattened = []
    for group in groups:
        if not isinstance(group, list) or len(group) not in ((1,2,3,4) if version==POTENTIAL_FORMAT else (1,2,3)):
            raise Invalid("invalid number of abstract pattern boxes")
        for box in group:
            _integer(box, "abstract box cell", maximum=board.width * board.height - 1)
        if group != sorted(set(group)):
            raise Invalid("abstract boxes must be distinct and sorted")
        flattened.extend(group)
    if sorted(flattened) != sorted(board.boxes):
        raise Invalid("patterns must partition the original boxes exactly once")
    prices = certificate["goal_prices"]
    if not isinstance(prices, list) or len(prices) != len(board.goals):
        raise Invalid("incorrect number of goal prices")
    for price in prices:
        _integer(price, "goal price", minimum=-MAX_PRICE, maximum=MAX_PRICE)
    proofs={}
    if version==POTENTIAL_FORMAT:
        entries=certificate["pattern_potentials"]
        if not isinstance(entries,list) or len(entries)>MAX_ABSTRACT_BOXES//4:
            raise Invalid("invalid abstract pattern proof count")
        count=0
        for entry in entries:
            if not isinstance(entry,dict) or set(entry)!={"group","states"}:
                raise Invalid("invalid abstract pattern proof fields")
            if not isinstance(entry["group"],list) or entry["group"] not in groups or len(entry["group"])!=4:
                raise Invalid("abstract potential proof has an unknown four-box group")
            group=tuple(entry["group"])
            if group in proofs or not isinstance(entry["states"],list):
                raise Invalid("invalid or duplicate abstract pattern proof")
            count+=len(entry["states"])
            proofs[group]=entry["states"]
        if count>MAX_PATTERN_PROOF_STATES or set(proofs)!={tuple(g) for g in groups if len(g)==4}:
            raise Invalid("missing abstract pattern proof or excessive total state count")
    sizes=set(map(len,groups))
    sizes=({1,2,3}|(sizes-{4})) if 4 in sizes else sizes
    graphs={size:AbstractGraph(board,size) for size in sorted(sizes)}
    distances={size:graph.distances(prices) for size,graph in graphs.items()}
    heuristic=PatternHeuristic(board,prices,graphs,distances) if proofs else None
    computed=sum(prices)
    for group in groups:
        if len(group)==4:
            value=verify_pattern_potentials(board,group,proofs[tuple(group)],heuristic)
        else:
            value=distances[len(group)][graphs[len(group)].initial_node(group)]
        if value is None:
            raise Invalid("abstract pattern has no solution")
        computed+=value
    computed=max(0,computed)
    computed+=(board.push_parity-computed)%2
    if computed>MAX_BOUND:
        raise Invalid("computed abstraction lower bound exceeds limit")
    if claimed>computed:
        raise Invalid("claimed lower bound exceeds recomputed abstraction bound")
    return computed
