#!/usr/bin/env python3
"""Find small additive-pattern certificates; the judge trusts none of this search.

Requires numpy, scipy, and networkx for the offline optimization only.  The
certificate checker uses the Python standard library and recomputes distances.
"""

import argparse
from itertools import combinations
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import networkx as nx
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from sokogap.abstraction import AbstractGraph, FORMAT, positions, verify_abstraction
from sokogap.core import Board


def distance_matrix(board, size, directory):
    """Exact initial-pattern to final-goal-set distances, cached for optimization."""
    cache = directory / f"{board.digest[:16]}-k{size}.npz"
    groups = tuple(combinations(board.boxes, size))
    goal_sets = tuple(combinations(sorted(board.goals), size))
    if cache.exists():
        with np.load(cache, allow_pickle=False) as saved:
            if str(saved['board_sha256']) == board.digest:
                return groups, goal_sets, saved['costs']
    graph = AbstractGraph(board, size)
    rows, cols = [], []
    for node, children in enumerate(graph.reverse):
        rows.extend([node] * len(children))
        cols.extend(children)
    adjacency = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(graph.nodes), len(graph.nodes))).tocsr()
    terminal_nodes = [node for nodes in graph.terminals.values() for node in nodes]
    terminal_index = {node: i for i, node in enumerate(terminal_nodes)}
    # All edge weights are one.  The minimum over terminal player components
    # gives exact costs to each unordered goal set, independently of goal prices.
    distances = dijkstra(adjacency, directed=True, indices=terminal_nodes, unweighted=True)
    starts = [graph.initial_node(group) for group in groups]
    costs = np.empty((len(groups), len(goal_sets)))
    for j, goals in enumerate(goal_sets):
        goal_mask = sum(1 << p for p in goals)
        indices = [terminal_index[node] for node in graph.terminals[goal_mask]]
        costs[:, j] = np.min(distances[np.ix_(indices, starts)], axis=0)
    np.savez_compressed(cache, board_sha256=board.digest, costs=costs)
    return groups, goal_sets, costs


class Optimizer:
    def __init__(self, board, directory):
        self.board = board
        self.boxes = list(board.boxes)
        self.goals = sorted(board.goals)
        self.goal_index = {p: i for i, p in enumerate(self.goals)}
        self.groups = {}
        self.goal_sets = {}
        self.costs = {}
        self.group_index = {}
        self.goal_incidence = {}
        for size in (1, 2):
            groups, goals, costs = distance_matrix(board, size, directory)
            self.groups[size], self.goal_sets[size], self.costs[size] = groups, goals, costs
            self.group_index[size] = {g: i for i, g in enumerate(groups)}
            incidence = np.zeros((len(goals), len(self.goals)))
            for j, goal_set in enumerate(goals):
                for goal in goal_set:
                    incidence[j, self.goal_index[goal]] = 1
            self.goal_incidence[size] = incidence

    def values(self, prices):
        return {size: np.min(self.costs[size] - self.goal_incidence[size] @ prices, axis=1) for size in (1, 2)}

    def value(self, groups, prices):
        v = self.values(prices)
        return float(sum(prices) + sum(v[len(g)][self.group_index[len(g)][tuple(g)]] for g in groups))

    def pairing(self, prices):
        values = self.values(prices)
        graph = nx.Graph()
        graph.add_nodes_from(self.boxes)
        single = dict(zip(self.boxes, values[1]))
        for (a, b), value in zip(self.groups[2], values[2]):
            graph.add_edge(a, b, weight=float(value - single[a] - single[b]))
        pairs = nx.max_weight_matching(graph, maxcardinality=True)
        used = set().union(*pairs) if pairs else set()
        return sorted([tuple(sorted(pair)) for pair in pairs] + [(b,) for b in self.boxes if b not in used])

    def price_lp(self, groups):
        n, m = len(self.goals), len(groups)
        rows, cols, values, rhs = [], [], [], []
        for index, group in enumerate(groups):
            size = len(group)
            costs = self.costs[size][self.group_index[size][tuple(group)]]
            for goal_set, cost in zip(self.goal_sets[size], costs):
                if not np.isfinite(cost):
                    continue
                row = len(rhs)
                rhs.append(cost)
                for goal in goal_set:
                    rows.append(row); cols.append(self.goal_index[goal]); values.append(1)
                rows.append(row); cols.append(n + index); values.append(1)
        matrix = coo_matrix((values, (rows, cols)), shape=(len(rhs), n+m)).tocsr()
        bounds = [(0, 0)] + [(None, None)] * (n+m-1)
        result = linprog(-np.ones(n+m), A_ub=matrix, b_ub=rhs, bounds=bounds, method='highs')
        if not result.success:
            raise RuntimeError(result.message)
        return result.x[:n], -result.fun

    def integer_prices(self, groups, prices, rng):
        candidates = [np.rint(prices), np.floor(prices), np.ceil(prices)]
        for _ in range(12):
            candidates.append(np.floor(prices) + np.array([int(rng.random() < p % 1) for p in prices]))
        best = max(candidates, key=lambda p: self.value(groups, p)).astype(int)
        score = self.value(groups, best)
        # Integer coordinate ascent, accepting only a strict increase.
        changed = True
        while changed:
            changed = False
            for i in range(len(best)):
                for delta in (-1, 1):
                    candidate = best.copy(); candidate[i] += delta
                    value = self.value(groups, candidate)
                    if value > score + 0.01:
                        best, score, changed = candidate, value, True
        return best, score

    def optimize(self, restarts=12):
        rng = random.Random(271828)
        singles = [(b,) for b in self.boxes]
        single_prices, single_lp = self.price_lp(singles)
        best = (float('-inf'), None, None)
        records = []
        for restart in range(restarts):
            if restart == 0:
                prices = np.rint(single_prices)
            else:
                prices = np.rint(single_prices) + np.array([rng.randrange(-5, 6) for _ in self.goals])
            seen = set()
            for iteration in range(12):
                groups = self.pairing(prices)
                key = tuple(groups)
                if key in seen:
                    break
                seen.add(key)
                fractional, lp_value = self.price_lp(groups)
                prices, value = self.integer_prices(groups, fractional, rng)
                records.append({'restart':restart, 'iteration':iteration, 'bound':value, 'lp_bound':lp_value})
                if value > best[0]:
                    best = value, groups, prices.copy()
        value, groups, prices = best
        lower = int(round(value))
        lower += (self.board.push_parity-lower) % 2
        certificate = {'format':FORMAT, 'board_sha256':self.board.digest, 'lower':lower,
                       'groups':[list(g) for g in groups], 'goal_prices':prices.tolist()}
        checked = verify_abstraction(self.board, certificate)
        if checked != lower:
            raise RuntimeError(f'optimizer/checker disagreement: {lower} != {checked}')
        return certificate, {'single_box_assignment':single_lp, 'raw_additive_bound':value, 'search':records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--levels', nargs='*', type=int)
    parser.add_argument('--restarts', type=int, default=12)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--triples', action='store_true')
    mode.add_argument('--four', action='store_true')
    parser.add_argument('--patterns', type=int, default=1500)
    parser.add_argument('--expansions', type=int, default=100)
    args = parser.parse_args()
    manifest = json.loads((ROOT/'benchmark.draft.json').read_text())
    directory = ROOT/'research'/'abstraction'
    directory.mkdir(parents=True, exist_ok=True)
    for instance in manifest['instances']:
        level = int(instance['id'].rsplit('-',1)[1])
        if args.levels and level not in args.levels:
            continue
        if args.four:
            optimize_four(level, limit=args.patterns, expansions=args.expansions)
            continue
        begin = time.monotonic()
        board = Board.parse((ROOT/instance['board']).read_text())
        optimizer = (TripleOptimizer if args.triples else Optimizer)(board, directory)
        certificate, research = optimizer.optimize(args.restarts)
        research.update({'id':instance['id'], 'board_sha256':board.digest,
                         'published_lower':instance['lower'], 'certified_lower':certificate['lower'],
                         'elapsed_seconds':time.monotonic()-begin})
        certificate_path = ROOT/'evidence'/'lower'/f"{instance['id']}-abstraction.json"
        previous = json.loads(certificate_path.read_text()) if certificate_path.exists() else None
        if previous is None or certificate['lower'] >= previous['lower']:
            certificate_path.write_text(json.dumps(certificate,indent=2)+'\n')
        (directory/f"{instance['id']}.json").write_text(json.dumps(research,indent=2)+'\n')
        print(json.dumps({k:v for k,v in research.items() if k != 'search'}), flush=True)



class TripleOptimizer(Optimizer):
    """Optimize three-box duals through exact separation, without a huge matrix."""

    def __init__(self, board, directory):
        super().__init__(board, directory)
        self.triple_graph = AbstractGraph(board, 3)
        self.groups[3] = tuple(combinations(board.boxes, 3))
        self.group_index[3] = {group:i for i,group in enumerate(self.groups[3])}
        self.triple_starts = [self.triple_graph.initial_node(g) for g in self.groups[3]]
        self.last_prices = None
        self.last_distances = None
        self.last_targets = None

    def triple_values(self, prices):
        key = tuple(prices)
        if key != self.last_prices:
            self.last_distances, self.last_targets = self.triple_graph.distances(prices, with_targets=True)
            self.last_prices = key
        return np.array([self.last_distances[s] for s in self.triple_starts], dtype=float)

    def values(self, prices):
        return super().values(prices) | {3:self.triple_values(prices)}

    def pairing(self, prices):
        from scipy.optimize import milp, Bounds, LinearConstraint
        values = self.values(prices)
        single = dict(zip(self.boxes, values[1]))
        box_index = {b:i for i,b in enumerate(self.boxes)}
        groups = [g for size in (1,2,3) for g in self.groups[size]]
        gains = [values[len(g)][self.group_index[len(g)][g]] - sum(single[b] for b in g) for g in groups]
        rows, cols = [], []
        for j,g in enumerate(groups):
            rows.extend(box_index[b] for b in g); cols.extend([j]*len(g))
        matrix = coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(len(self.boxes),len(groups))).tocsc()
        result = milp(-np.array(gains), integrality=np.ones(len(groups)),
                      bounds=Bounds(0,1), constraints=LinearConstraint(matrix,1,1),
                      options={'time_limit':3})
        if result.x is None:
            return super().pairing(prices)
        chosen = sorted(g for g,x in zip(groups,result.x) if x > 0.5)
        if sorted(b for g in chosen for b in g) != sorted(self.boxes):
            raise RuntimeError('MILP partition failed validation')
        return chosen

    def separate(self, groups, prices):
        value = sum(prices)
        cuts = []
        for group in groups:
            size = len(group)
            if size < 3:
                row = self.costs[size][self.group_index[size][tuple(group)]]
                adjusted = row-self.goal_incidence[size]@prices
                j = int(np.argmin(adjusted))
                goals, cost, dual = self.goal_sets[size][j], row[j], adjusted[j]
            else:
                self.triple_values(prices)
                node = self.triple_starts[self.group_index[3][tuple(group)]]
                dual = self.last_distances[node]
                goals = tuple(positions(self.last_targets[node]))
                cost = dual + sum(prices[self.goal_index[g]] for g in goals)
            cuts.append((goals, float(cost)))
            value += dual
        return float(value), cuts

    def triple_price_lp(self, groups, start):
        n,m=len(self.goals),len(groups)
        cuts = [{} for g in groups]
        def remember(prices):
            value,new = self.separate(groups,prices)
            for store,(goals,cost) in zip(cuts,new):
                if cost < store.get(goals,float('inf')):
                    store[goals] = cost
            return value
        remember(start)
        # A local price box keeps separation efficient. Any resulting prices
        # remain valid; the generator need not prove the dual is optimal.
        bounds = [(float(p-24),float(p+24)) for p in start] + [(-10000,10000)]*m
        best = self.separate(groups,start)[0], np.array(start)
        for iteration in range(120):
            rows,cols,vals,rhs=[],[],[],[]
            for j,store in enumerate(cuts):
                for goals,cost in store.items():
                    r=len(rhs); rhs.append(cost)
                    for goal in goals:
                        rows.append(r);cols.append(self.goal_index[goal]);vals.append(1)
                    rows.append(r);cols.append(n+j);vals.append(1)
            matrix=coo_matrix((vals,(rows,cols)),shape=(len(rhs),n+m)).tocsr()
            result=linprog(-np.ones(n+m),A_ub=matrix,b_ub=rhs,bounds=bounds,method='highs')
            if not result.success: raise RuntimeError(result.message)
            prices=result.x[:n]
            actual=remember(prices)
            if actual > best[0]+1e-6: best=actual,prices
            if -result.fun-actual < 1e-6: break
        return best[1],best[0]

    def optimize(self, restarts=4):
        rng = random.Random(271828)
        singles = [(b,) for b in self.boxes]
        single_prices,single_lp=self.price_lp(singles)
        best = float('-inf'),None,None
        records=[]
        for restart in range(restarts):
            prices=np.rint(single_prices)
            if restart:
                prices += np.array([rng.randrange(-4,5) for _ in self.goals])
            seen=set()
            for iteration in range(6):
                groups=self.pairing(prices)
                key=tuple(groups)
                if key in seen: break
                seen.add(key)
                fractional,lp_value=self.triple_price_lp(groups,prices)
                choices=[np.rint(fractional),np.floor(fractional),np.ceil(fractional)]
                prices=max(choices,key=lambda p:self.value(groups,p)).astype(int)
                value=self.value(groups,prices)
                records.append({'restart':restart,'iteration':iteration,'bound':value,'lp_bound':lp_value})
                if value>best[0]:best=value,groups,prices.copy()
        value,groups,prices=best
        lower=int(round(value));lower+=(self.board.push_parity-lower)%2
        certificate={'format':FORMAT,'board_sha256':self.board.digest,'lower':lower,
                     'groups':[list(g) for g in groups],'goal_prices':prices.tolist()}
        checked=verify_abstraction(self.board,certificate)
        if checked!=lower:raise RuntimeError(f'optimizer/checker disagreement: {lower} != {checked}')
        return certificate,{'single_box_assignment':single_lp,'raw_additive_bound':value,'search':records,
                            'abstract_states':len(self.triple_graph.nodes),
                            'abstract_edges':sum(map(len,self.triple_graph.reverse))}


class FastFourSearch:
    def __init__(self, board, heuristic):
        self.board=board
        self.heuristic=heuristic
        self.bitgraph=heuristic.graphs[3]
        self.steps={p:[(board.step(p,d),board.step(p,o)) for d,o in (("u","d"),("d","u"),("l","r"),("r","l"))] for p in board.floor}
        self.reach_cache={}

    def state(self,boxes,player):
        occupied=sum(1<<b for b in boxes)
        key=(occupied,player)
        if key in self.reach_cache:
            region=self.reach_cache[key]
        else:
            free=self.bitgraph.floor_mask & ~occupied
            reached=1<<player
            while True:
                expanded=(reached|((reached & self.bitgraph.right_sources)<<1)|((reached & self.bitgraph.left_sources)>>1)
                          |(reached<<self.board.width)|(reached>>self.board.width)) & free
                if expanded==reached:break
                reached=expanded
            region=reached
            if len(self.reach_cache)<200000:self.reach_cache[key]=region
        return (tuple(sorted(boxes)),(region & -region).bit_length()-1),region

    def successors(self,state):
        boxes,player=state
        state,region=self.state(boxes,player)
        occupied=set(boxes)
        result=[]
        for box in boxes:
            for dest,behind in self.steps[box]:
                if dest is not None and dest not in occupied and behind is not None and region & (1<<behind):
                    child,_=self.state(tuple((occupied-{box})|{dest}),box)
                    result.append(child)
        return result

    def prove(self,group,expansions=1000,target=None):
        from heapq import heappop,heappush
        initial,_=self.state(tuple(group),self.board.player)
        base=self.heuristic.value
        start=base(initial)
        heap=[(start,0,initial)]
        best={initial:0}
        closed={}
        incumbent=float('inf')
        lower=start
        while heap:
            f,g,state=heappop(heap)
            if best.get(state)!=g or state in closed:continue
            lower=min(f,incumbent)
            if f>=incumbent or len(closed)>=expansions or (target is not None and lower>=target):
                break
            closed[state]=g
            terminal=self.heuristic.terminal(state[0])
            if terminal is not None:
                incumbent=min(incumbent,g+terminal)
            for child in self.successors(state):
                candidate=g+1
                if candidate<best.get(child,float('inf')):
                    h=base(child)
                    if h>=10**12:continue
                    best[child]=candidate
                    heappush(heap,(candidate+h,candidate,child))
        else:
            lower=incumbent
        if not np.isfinite(lower):raise RuntimeError('four-box abstraction unsolvable')
        rows=[]
        for state,g in closed.items():
            h=lower-g
            if h>base(state):
                rows.append({'boxes':list(state[0]),'player':state[1],'h':int(h)})
        return int(lower),rows,len(closed)


def four_partition(optimizer,prices,quad_values):
    from scipy.optimize import milp,Bounds,LinearConstraint
    values=optimizer.values(prices)
    singles=dict(zip(optimizer.boxes,values[1]))
    box_index={b:i for i,b in enumerate(optimizer.boxes)}
    groups=[g for size in (1,2,3) for g in optimizer.groups[size]]+list(quad_values)
    gains=[]
    for group in groups:
        val=quad_values[group] if len(group)==4 else values[len(group)][optimizer.group_index[len(group)][group]]
        gains.append(val-sum(singles[b] for b in group))
    rows,cols=[],[]
    for j,g in enumerate(groups):
        rows.extend(box_index[b] for b in g);cols.extend([j]*len(g))
    matrix=coo_matrix((np.ones(len(rows)),(rows,cols)),shape=(len(optimizer.boxes),len(groups))).tocsc()
    result=milp(-np.array(gains),integrality=np.ones(len(groups)),bounds=Bounds(0,1),
                constraints=LinearConstraint(matrix,1,1),options={'time_limit':5})
    if result.x is None:raise RuntimeError('no partition found')
    chosen=sorted(g for g,x in zip(groups,result.x) if x>0.5)
    if sorted(b for g in chosen for b in g)!=sorted(optimizer.boxes):raise RuntimeError('invalid four-box partition')
    value=sum(prices)+sum(quad_values[g] if len(g)==4 else values[len(g)][optimizer.group_index[len(g)][g]] for g in chosen)
    return int(value),chosen


def compactness(board,group):
    # Minimum spanning tree of Manhattan distances; used only to schedule work.
    connected={group[0]}
    rest=set(group[1:])
    total=0
    while rest:
        distance,node=min((abs(a%board.width-b%board.width)+abs(a//board.width-b//board.width),b) for a in connected for b in rest)
        connected.add(node);rest.remove(node);total+=distance
    return total


def optimize_four(level,limit=500,expansions=100):
    from sokogap.abstraction import PatternHeuristic,POTENTIAL_FORMAT,verify_pattern_potentials
    instance=next(i for i in json.loads((ROOT/'benchmark.draft.json').read_text())['instances'] if i['id']==f'xsokoban-{level}')
    board=Board.parse((ROOT/instance['board']).read_text())
    cert_path=ROOT/'evidence'/'lower'/f"{instance['id']}-abstraction.json"
    existing=json.loads(cert_path.read_text())
    begin=time.monotonic()
    optimizer=TripleOptimizer(board,ROOT/'research'/'abstraction')
    prices=np.array(existing['goal_prices'],dtype=int)
    graphs={1:AbstractGraph(board,1),2:AbstractGraph(board,2),3:optimizer.triple_graph}
    distances={k:g.distances(prices) for k,g in graphs.items()}
    heuristic=PatternHeuristic(board,prices,graphs,distances)
    search=FastFourSearch(board,heuristic)
    quads=sorted(combinations(board.boxes,4),key=lambda g:(compactness(board,g),g))[:limit]
    quad_values={}
    proofs={}
    total_expansions=0
    for index,group in enumerate(quads):
        value,rows,expanded=search.prove(group,expansions=expansions)
        quad_values[group]=value
        proofs[group]=rows
        total_expansions+=expanded
        if (index+1)%100==0:
            lower,chosen=four_partition(optimizer,prices,quad_values)
            lower+=(board.push_parity-lower)%2
            print(json.dumps({'level':level,'patterns':index+1,'expansions':total_expansions,'lower':lower,
                              'elapsed':time.monotonic()-begin}),flush=True)
            if lower>=instance['lower']:
                break
    lower,chosen=four_partition(optimizer,prices,quad_values)
    lower+=(board.push_parity-lower)%2
    cert={'format':POTENTIAL_FORMAT,'board_sha256':board.digest,'lower':lower,
          'groups':[list(g) for g in chosen],'goal_prices':prices.tolist(),
          'pattern_potentials':[{'group':list(g),'states':proofs[g]} for g in chosen if len(g)==4]}
    checked=verify_abstraction(board,cert)
    if checked!=lower:raise RuntimeError(f'fourbox checker mismatch {checked}!={lower}')
    if lower>existing['lower']:
        cert_path.write_text(json.dumps(cert,indent=2)+'\n')
    research={'id':instance['id'],'certified_lower':lower,'published_lower':instance['lower'],
              'patterns_searched':len(quad_values),'total_expansions':total_expansions,
              'elapsed_seconds':time.monotonic()-begin,
              'potential_states':sum(len(e['states']) for e in cert['pattern_potentials'])}
    (ROOT/'research'/'abstraction'/f"{instance['id']}-four.json").write_text(json.dumps(research,indent=2)+'\n')
    print(json.dumps(research),flush=True)
    return cert


if __name__ == '__main__':
    main()
