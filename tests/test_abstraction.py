from collections import deque
import random
import unittest

from sokogap.abstraction import AbstractGraph, FORMAT, POTENTIAL_FORMAT, MAX_ABSTRACT_FLOOR, verify_abstraction
from sokogap.core import Board, Invalid


def independent_pattern_cost(board, retained, prices):
    """Exhaust player-step 0-1 BFS, then minimize over all final goal sets.

    This reference uses explicit coordinates and individual walking steps.  It
    neither collapses player components nor uses the reverse graph under test.
    """
    start = frozenset(retained), board.player
    distance = {start:0}
    queue = deque([start])
    goal_prices = dict(zip(sorted(board.goals),prices))
    answer = None
    while queue:
        boxes,player = queue.popleft()
        cost = distance[(boxes,player)]
        if boxes <= board.goals:
            value = cost-sum(goal_prices[b] for b in boxes)
            answer = value if answer is None else min(answer,value)
        x,y = player%board.width,player//board.width
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny=x+dx,y+dy
            target=ny*board.width+nx
            if not (0<=nx<board.width and 0<=ny<board.height) or target not in board.floor:
                continue
            pushed=0
            new_boxes=boxes
            if target in boxes:
                bx,by=nx+dx,ny+dy
                beyond=by*board.width+bx
                if not (0<=bx<board.width and 0<=by<board.height) or beyond not in board.floor or beyond in boxes:
                    continue
                new_boxes=(boxes-{target})|{beyond}
                pushed=1
            child=(new_boxes,target)
            candidate=cost+pushed
            if candidate<distance.get(child,10**9):
                distance[child]=candidate
                (queue.append if pushed else queue.appendleft)(child)
    return answer


class AbstractionTests(unittest.TestCase):
    def test_exact_abstract_distances_against_player_step_search(self):
        rng=random.Random(4172)
        comparisons=solvable=0
        for sample in range(48):
            floor={y*6+x for y in range(1,4) for x in range(1,5)}
            for p in rng.sample(sorted(floor),rng.randrange(3)):
                floor.remove(p)
            pieces=rng.sample(sorted(floor),7)
            board=Board(6,5,frozenset(floor),frozenset(pieces[:3]),tuple(sorted(pieces[3:6])),pieces[6])
            prices=[rng.randrange(-5,6) for _ in range(3)]
            for size in (1,2,3):
                retained=board.boxes[:size]
                expected=independent_pattern_cost(board,retained,prices)
                graph=AbstractGraph(board,size)
                try:
                    node=graph.initial_node(retained)
                except Invalid:
                    actual=None
                else:
                    actual=graph.distances(prices)[node]
                with self.subTest(sample=sample,size=size):
                    self.assertEqual(actual,expected)
                comparisons+=1
                solvable+=expected is not None
        self.assertEqual(comparisons,144)
        self.assertGreater(solvable,20)

    def test_additive_bound_does_not_double_count_pushes(self):
        board=Board.parse('########\n# . . .#\n# $ $ $#\n#  @   #\n########\n')
        optimum=independent_pattern_cost(board,board.boxes,[0,0,0])
        self.assertEqual(optimum,3)
        partitions=[[[b] for b in board.boxes],[list(board.boxes[:2]),[board.boxes[2]]],[list(board.boxes)]]
        for groups in partitions:
            for prices in ([0,0,0],[12,-4,7],[-3,-1,-8]):
                cert={'format':FORMAT,'board_sha256':board.digest,'lower':0,'groups':groups,'goal_prices':prices}
                bound=verify_abstraction(board,cert)
                self.assertLessEqual(bound,optimum)
                self.assertEqual(bound%2,board.push_parity)

    def test_checker_recomputes_bound_and_rejects_false_claims(self):
        board=Board.parse('#######\n#.@ # #\n#  $$ #\n#   # #\n#    .#\n#######\n')
        cert={'format':FORMAT,'board_sha256':board.digest,'lower':0,'groups':[list(board.boxes)],'goal_prices':[0,0]}
        self.assertEqual(independent_pattern_cost(board,board.boxes,[0,0]),8)
        self.assertEqual(verify_abstraction(board,cert),8)
        self.assertEqual(verify_abstraction(board,cert|{'lower':8}),8)
        for alteration in ({'lower':9},{'lower':True},{'board_sha256':'wrong'},
                           {'groups':[[board.boxes[0]],[board.boxes[0]]]},
                           {'groups':[[board.boxes[1],board.boxes[0]]]},
                           {'groups':[[True],[board.boxes[1]]]},
                           {'goal_prices':[0]}, {'goal_prices':[0,False]},
                           {'goal_prices':[0,3_000_000]}, {'unexpected':1}):
            with self.subTest(alteration=alteration),self.assertRaises(Invalid):
                verify_abstraction(board,cert|alteration)

    def test_four_box_signed_potentials_and_every_terminal_obligation(self):
        board=Board.parse('#########\n# . . . #\n# $ $ $ #\n# @  *  #\n#########\n')
        self.assertEqual(independent_pattern_cost(board,board.boxes,[0,0,0,0]),3)
        group=list(board.boxes)
        initial=board.state(board.boxes,board.player)
        row={'boxes':list(initial[0]),'player':initial[1],'h':-4}
        cert={'format':POTENTIAL_FORMAT,'board_sha256':board.digest,'lower':0,
              'groups':[group],'goal_prices':[7,0,0,0],
              'pattern_potentials':[{'group':group,'states':[row]}]}
        self.assertEqual(verify_abstraction(board,cert),3)
        understated=cert|{'pattern_potentials':[{'group':group,'states':[row|{'h':-100}]}]}
        self.assertEqual(verify_abstraction(board,understated),3)
        bad_transition=cert|{'pattern_potentials':[{'group':group,'states':[row|{'h':-3}]}]}
        with self.assertRaisesRegex(Invalid,'transition'):
            verify_abstraction(board,bad_transition)
        goal=board.state(tuple(sorted(board.goals)),board.player)
        goal_row={'boxes':list(goal[0]),'player':goal[1],'h':-6}
        bad_goal=cert|{'pattern_potentials':[{'group':group,'states':[goal_row]}]}
        with self.assertRaisesRegex(Invalid,'goal potential'):
            verify_abstraction(board,bad_goal)
        for change in ({'pattern_potentials':[]},
                       {'pattern_potentials':[{'group':group,'states':[row,row]}]},
                       {'pattern_potentials':[{'group':group,'states':[row|{'h':True}]}]},
                       {'format':FORMAT}):
            with self.subTest(change=change),self.assertRaises(Invalid):
                verify_abstraction(board,cert|change)

    def test_resource_limits_reject_before_graph_expansion(self):
        board=Board(200,3,frozenset(range(200,200+MAX_ABSTRACT_FLOOR+1)),frozenset([201]),(202,),203)
        with self.assertRaisesRegex(Invalid,'resource'):
            AbstractGraph(board,1)


if __name__=='__main__':
    unittest.main()
