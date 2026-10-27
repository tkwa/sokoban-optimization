"""Exact, deterministic bounded-push SAT encoding (walking costs zero).

At each time there is a box bit and a unique player position. One legal push
or a no-op advances time. A rooted, ranked forest witnesses free walking to
the support of a push. Ranks increase by one away from the player, without
overflow, so a disconnected region cannot invent its own reachability.
"""

from array import array
from collections.abc import Sequence
from hashlib import sha256
from math import ceil, log2

from .budget import Exhausted, spend
from .core import Board, Invalid

ENCODING = "sokogap-push-cnf-v1"
MAX_FLOOR = 512
MAX_PUSHES = 2048
MAX_VARIABLES = 4_000_000
MAX_CLAUSES = 20_000_000
MAX_LITERALS = 120_000_000


class CNF(Sequence):
    """Packed clauses; original LRAT clause IDs are index + 1."""

    def __init__(self):
        self.nvars = 0
        self._lits = array("i")
        self._ends = array("I", [0])
        self._digest = None

    @property
    def clauses(self):
        return self

    def __len__(self):
        return len(self._ends) - 1

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self))) ]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return tuple(self._lits[self._ends[index]:self._ends[index + 1]])

    def var(self):
        self.nvars += 1
        self._digest = None
        if self.nvars > MAX_VARIABLES:
            raise Exhausted("SAT variable limit exceeded")
        return self.nvars

    def add(self, *clause):
        if len(self) >= MAX_CLAUSES or len(self._lits) + len(clause) > MAX_LITERALS:
            raise Exhausted("SAT formula size limit exceeded")
        spend("cnf_literals", len(clause) + 1)
        self._lits.extend(clause)
        self._ends.append(len(self._lits))
        self._digest = None

    def exactly_one(self, values):
        self.add(*values)
        if len(values) < 2:
            return
        previous = self.var()
        self.add(-values[0], previous)
        for value in values[1:-1]:
            current = self.var()
            self.add(-value, current)
            self.add(-previous, current)
            self.add(-value, -previous)
            previous = current
        self.add(-values[-1], -previous)

    def dimacs(self):
        yield f"p cnf {self.nvars} {len(self)}\n"
        for clause in self:
            yield " ".join(map(str, clause)) + (" " if clause else "") + "0\n"

    @property
    def digest(self):
        if self._digest is None:
            digest = sha256()
            for line in self.dimacs():
                digest.update(line.encode("ascii"))
            self._digest = digest.hexdigest()
        return self._digest


def encode_push_bound(board: Board, max_pushes: int) -> CNF:
    """SAT iff a solution with at most max_pushes pushes exists.

    No-ops pad shorter solutions. Box occupancy is fixed on every goal at the
    last time, including K=0. Walking after the last push is unnecessary.
    """
    if type(max_pushes) is not int or max_pushes < 0:
        raise Invalid("SAT push limit must be a nonnegative integer")
    cells = sorted(board.floor)
    if len(cells) > MAX_FLOOR or max_pushes > MAX_PUSHES:
        raise Exhausted("SAT encoding dimensions exceed automatic checking limits")
    cnf = CNF()
    adjacent = {c: [d for direction in "udlr" if (d := board.step(c, direction)) is not None]
                for c in cells}
    # (old box cell, new box cell, required walking support)
    pushes = []
    opposite = {"u": "d", "d": "u", "l": "r", "r": "l"}
    for c in cells:
        for direction in "udlr":
            dest, support = board.step(c, direction), board.step(c, opposite[direction])
            if dest is not None and support is not None:
                pushes.append((c, dest, support))
    boxes = [{c: cnf.var() for c in cells} for _ in range(max_pushes + 1)]
    players = [{c: cnf.var() for c in cells} for _ in range(max_pushes + 1)]
    for t in range(max_pushes + 1):
        cnf.exactly_one(list(players[t].values()))
        for c in cells:
            cnf.add(-players[t][c], -boxes[t][c])
    for c in cells:
        cnf.add(boxes[0][c] if c in board.boxes else -boxes[0][c])
        cnf.add(players[0][c] if c == board.player else -players[0][c])
        cnf.add(boxes[-1][c] if c in board.goals else -boxes[-1][c])
    width = max(1, ceil(log2(len(cells))))
    for t in range(max_pushes):
        reachable = {c: cnf.var() for c in cells}
        ranks = {c: [cnf.var() for _ in range(width)] for c in cells}
        carries = {}
        for c in cells:
            cnf.add(-reachable[c], -boxes[t][c])
            cnf.add(-players[t][c], reachable[c])
            for bit in ranks[c]:
                cnf.add(-players[t][c], -bit)
            # Carry into bit i for binary increment of this cell's rank.
            carry = [None, ranks[c][0]]
            for i in range(2, width):
                value = cnf.var()
                cnf.add(-value, carry[-1])
                cnf.add(-value, ranks[c][i - 1])
                cnf.add(value, -carry[-1], -ranks[c][i - 1])
                carry.append(value)
            carries[c] = carry
        for c in cells:
            parents = []
            for parent in adjacent[c]:
                edge = cnf.var()
                parents.append(edge)
                cnf.add(-edge, reachable[c])
                cnf.add(-edge, reachable[parent])
                child_bits, parent_bits = ranks[c], ranks[parent]
                # child = parent + 1, forbidding wraparound.
                cnf.add(-edge, *(-bit for bit in parent_bits))
                a, b = child_bits[0], parent_bits[0]
                cnf.add(-edge, a, b)
                cnf.add(-edge, -a, -b)
                for i in range(1, width):
                    a, b, carry = child_bits[i], parent_bits[i], carries[parent][i]
                    cnf.add(-edge, b, carry, -a)
                    cnf.add(-edge, b, -carry, a)
                    cnf.add(-edge, -b, carry, a)
                    cnf.add(-edge, -b, -carry, -a)
            cnf.add(-reachable[c], players[t][c], *parents)
        noop = cnf.var()
        actions = [cnf.var() for _ in pushes]
        cnf.exactly_one([noop, *actions])
        outgoing = {c: [] for c in cells}
        incoming = {c: [] for c in cells}
        for action, (src, dest, support) in zip(actions, pushes):
            outgoing[src].append(action)
            incoming[dest].append(action)
            for consequence in (boxes[t][src], -boxes[t][dest], -boxes[t + 1][src],
                                boxes[t + 1][dest], players[t + 1][src], reachable[support]):
                cnf.add(-action, consequence)
        for c in cells:
            cnf.add(-boxes[t][c], boxes[t + 1][c], *outgoing[c])
            cnf.add(boxes[t][c], -boxes[t + 1][c], *incoming[c])
            cnf.add(-noop, -players[t][c], players[t + 1][c])
    return cnf
