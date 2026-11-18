"""互供核算单元测试（标准库 unittest，无需外部服务）。"""
import time
import unittest
from fractions import Fraction

from src.services.reciprocal.rational import parse_rational, fraction_str, decimal_str
from src.services.reciprocal.graph import detect_closed_sets
from src.services.reciprocal.solvers import (
    fraction_forward_solve,
    fraction_gauss_solve,
    bareiss_solve,
    ReciprocalTimeout,
)
from src.services.reciprocal.rounding import largest_remainder
from src.services.reciprocal.engine import validate_rule, reciprocal_allocate, RuleValidationError


def rule_with(services, beneficiaries, rows, version='互供-v1'):
    return validate_rule({
        'version': version,
        'services': services,
        'beneficiaries': beneficiaries,
        'rows': [
            {'source': source, 'allocations': [
                {'target': target, 'ratio': ratio} for target, ratio in allocations
            ]}
            for source, allocations in rows
        ],
    })


class RationalTests(unittest.TestCase):
    def test_parse_forms(self):
        self.assertEqual(parse_rational('1/3'), Fraction(1, 3))
        self.assertEqual(parse_rational('0.125'), Fraction(1, 8))
        self.assertEqual(parse_rational(7), Fraction(7))
        self.assertEqual(parse_rational(0.5), Fraction(1, 2))
        self.assertEqual(fraction_str(Fraction(3, 6)), '1/2')
        self.assertEqual(decimal_str(Fraction(1, 3), 6), '0.333333')

    def test_parse_rejects_bad(self):
        for bad in ('', '-1/2', 'abc', '1/0', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                parse_rational(bad)


class RoundingTests(unittest.TestCase):
    def test_largest_remainder_conservation_and_tie(self):
        # 绝对份额各 100/3，余数相等时按部门名升序：B1 得额外 1 分
        shares = {'B1': Fraction(100, 3), 'B2': Fraction(100, 3), 'B3': Fraction(100, 3)}
        result = largest_remainder(shares, 100)
        self.assertEqual(sum(result.values()), 100)
        self.assertEqual(result, {'B1': 34, 'B2': 33, 'B3': 33})

    def test_zero_total(self):
        self.assertEqual(
            largest_remainder({'甲': Fraction(0), '乙': Fraction(0)}, 0),
            {'甲': 0, '乙': 0},
        )


class GraphTests(unittest.TestCase):
    def test_closed_cycle_detected_even_at_zero_cost(self):
        # S1、S2 互相转入且全部比例都在服务部门内部，无任何外流
        rule = rule_with(
            ['S1', 'S2'], ['B1'],
            [('S1', [('S2', 1)]),
             ('S2', [('S1', 1)])],
        )
        detection = detect_closed_sets(rule['services'], rule['beneficiaries'], rule['proportions'])
        self.assertEqual(detection['trapped'], ['S1', 'S2'])
        self.assertEqual(detection['closed_groups'], [['S1', 'S2']])
        with self.assertRaises(RuleValidationError) as ctx:
            reciprocal_allocate([], rule)
        self.assertIn('无外流', str(ctx.exception))

    def test_open_graph_passes(self):
        rule = rule_with(
            ['S1', 'S2'], ['B1'],
            [('S1', [('S2', '1/2'), ('B1', '1/2')]),
             ('S2', [('B1', 1)])],
        )
        detection = detect_closed_sets(rule['services'], rule['beneficiaries'], rule['proportions'])
        self.assertEqual(detection['trapped'], [])


class SolverTests(unittest.TestCase):
    def test_three_solvers_agree(self):
        # (I - Aᵀ) 风格整数矩阵
        matrix = [[6, -3], [-2, 6]]
        rhs = [[300, 240]]
        forward = fraction_forward_solve(matrix, rhs)
        gauss = fraction_gauss_solve(matrix, rhs)
        bareiss = bareiss_solve(matrix, rhs)
        self.assertEqual(forward, gauss)
        self.assertEqual(forward, bareiss)
        # 手算：6x-3y=300, -2x+6y=240 → 10x=840 → x=84, y=68
        self.assertEqual(forward[0][0], Fraction(84))
        self.assertEqual(forward[0][1], Fraction(68))

    def test_multiple_rhs_solved_together(self):
        matrix = [[2, -1], [0, 3]]
        rhs = [[10, 9], [4, 3]]
        result = fraction_forward_solve(matrix, rhs)
        self.assertEqual(len(result), 2)
        # 第一列：3y=9 → y=3；2x-3=10 → x=13/2
        self.assertEqual(result[0], [Fraction(13, 2), Fraction(3)])
        # 第二列：3y=3 → y=1；2x-1=4 → x=5/2
        self.assertEqual(result[1], [Fraction(5, 2), Fraction(1)])

    def test_bareiss_pivot_swap_with_fraction_scaling(self):
        # 首列为 0 强制主元交换，且含分母触发逐行 LCM 缩放
        matrix = [
            [Fraction(0), Fraction(1), Fraction(1, 2)],
            [Fraction(1), Fraction(1, 3), Fraction(0)],
            [Fraction(1, 2), Fraction(0), Fraction(1)],
        ]
        rhs = [[Fraction(7, 2), Fraction(4, 3), Fraction(3, 2)]]
        forward = fraction_forward_solve(matrix, rhs)
        gauss = fraction_gauss_solve(matrix, rhs)
        bareiss = bareiss_solve(matrix, rhs)
        self.assertEqual(forward, gauss)
        self.assertEqual(forward, bareiss)
        for sol in (forward[0],):
            for i in range(3):
                self.assertEqual(
                    sum(matrix[i][j] * sol[j] for j in range(3)),
                    rhs[0][i],
                )

    def test_singular_rejected(self):
        matrix = [[1, -1], [-1, 1]]
        with self.assertRaises(ValueError):
            fraction_forward_solve(matrix, [[1, 1]])
        with self.assertRaises(ValueError):
            fraction_gauss_solve(matrix, [[1, 1]])
        with self.assertRaises(ValueError):
            bareiss_solve(matrix, [[1, 1]])

    def test_timeout(self):
        # 稠密矩阵制造足够工作量，令已过期的时限在主循环被拒绝
        n = 80
        matrix = [[1 if i == j else (i + j + 1) % 7 - 3 for j in range(n)] for i in range(n)]
        deadline = time.monotonic() - 1
        with self.assertRaises(ReciprocalTimeout):
            fraction_forward_solve(matrix, [[1] * n], deadline=deadline)
        with self.assertRaises(ReciprocalTimeout):
            fraction_gauss_solve(matrix, [[1] * n], deadline=deadline)
        with self.assertRaises(ReciprocalTimeout):
            bareiss_solve(matrix, [[1] * n], deadline=deadline)


class EngineTests(unittest.TestCase):
    def _two_service_rule(self):
        # S1 一半给 S2 一半外流；S2 全部外流
        return rule_with(
            ['后勤', '车队'], ['生产一厂', '生产二厂'],
            [
                ('后勤', [('车队', '1/2'), ('生产一厂', '1/4'), ('生产二厂', '1/4')]),
                ('车队', [('生产一厂', '1/2'), ('生产二厂', '1/2')]),
            ],
        )

    def test_basic_reciprocal_exact_and_conservation(self):
        rule = self._two_service_rule()
        entries = [
            {'period': '2026-11', 'department': '后勤', 'category': '水电费', 'amount_cents': 1000},
            {'period': '2026-11', 'department': '车队', 'category': '水电费', 'amount_cents': 400},
        ]
        result = reciprocal_allocate(entries, rule)
        # 方程：后勤 x=1000；车队 y=400+x/2=900
        totals = {(r['服务部门']): r['总成本精确分'] for r in result['service_rows']}
        self.assertEqual(totals['后勤'], '1000')
        self.assertEqual(totals['车队'], '900')
        # 受益精确份额：一厂=250+450=700；二厂=250+450=700
        shares = {(r['受益部门']): r['精确份额分'] for r in result['share_rows']}
        self.assertEqual(shares, {'生产一厂': '700', '生产二厂': '700'})
        rounded = {r['受益部门']: r['分摊金额分'] for r in result['rows']}
        self.assertEqual(sum(rounded.values()), 1400)
        self.assertEqual(result['summary']['守恒差额分'], 0)
        self.assertTrue(result['cross_check']['performed'])
        self.assertTrue(result['cross_check']['matched'])

    def test_rounding_only_at_beneficiaries_with_remainder(self):
        rule = rule_with(
            ['S1'], ['B1', 'B2', 'B3'],
            [('S1', [('B1', '1/3'), ('B2', '1/3'), ('B3', '1/3')])],
        )
        entries = [{'period': 'P1', 'department': 'S1', 'category': 'C1', 'amount_cents': 100}]
        result = reciprocal_allocate(entries, rule)
        amounts = sorted(r['分摊金额分'] for r in result['rows'])
        self.assertEqual(amounts, [33, 33, 34])
        self.assertEqual(sum(amounts), 100)
        # 余分按部门名升序：B1 拿额外 1 分
        bonus = {r['受益部门']: r['余分调整分'] for r in result['rows']}
        self.assertEqual(bonus['B1'], 1)
        self.assertEqual(bonus['B2'], 0)

    def test_multi_period_category_grouped_separately(self):
        rule = rule_with(
            ['S1'], ['B1', 'B2'],
            [('S1', [('B1', '1/2'), ('B2', '1/2')])],
        )
        entries = [
            {'period': 'P1', 'department': 'S1', 'category': 'C1', 'amount_cents': 101},
            {'period': 'P2', 'department': 'S1', 'category': 'C1', 'amount_cents': 203},
        ]
        result = reciprocal_allocate(entries, rule)
        by_group = {}
        for row in result['rows']:
            by_group.setdefault(row['期间'], []).append(row['分摊金额分'])
        self.assertEqual(sum(by_group['P1']), 101)
        self.assertEqual(sum(by_group['P2']), 203)
        self.assertEqual(sum(sum(v) for v in by_group.values()), 304)

    def test_direct_beneficiary_entries_passthrough(self):
        rule = self._two_service_rule()
        entries = [
            {'period': '2026-11', 'department': '生产一厂', 'category': '耗材', 'amount_cents': 555},
            {'period': '2026-11', 'department': '后勤', 'category': '耗材', 'amount_cents': 100},
        ]
        result = reciprocal_allocate(entries, rule)
        self.assertEqual(result['summary']['受益部门直归分'], 555)
        self.assertEqual(sum(r['分摊金额分'] for r in result['rows']), 655)

    def test_unknown_department_rejected(self):
        rule = self._two_service_rule()
        with self.assertRaises(RuleValidationError):
            reciprocal_allocate(
                [{'period': 'P1', 'department': '幽灵部门', 'category': 'C', 'amount_cents': 1}],
                rule,
            )

    def test_rule_row_must_sum_to_one(self):
        with self.assertRaises(RuleValidationError):
            rule_with(['S1'], ['B1'], [('S1', [('B1', '1/2')])])

    def test_near_closed_loop_forces_cross_check(self):
        # 百万分之一外流，构成近封闭环
        rule = rule_with(
            ['S1', 'S2'], ['B1'],
            [
                ('S1', [('S2', Fraction(999999, 1000000)), ('B1', Fraction(1, 1000000))]),
                ('S2', [('B1', 1)]),
            ],
        )
        entries = [
            {'period': 'P1', 'department': 'S1', 'category': 'C', 'amount_cents': 1_000_000},
            {'period': 'P1', 'department': 'S2', 'category': 'C', 'amount_cents': 0},
        ]
        result = reciprocal_allocate(entries, rule)
        self.assertTrue(result['summary']['近封闭环'])
        self.assertTrue(result['cross_check']['performed'])
        self.assertTrue(result['cross_check']['matched'])
        self.assertTrue(result['warnings'])
        # 守恒：总外流恰为 1,000,000 分
        self.assertEqual(sum(r['分摊金额分'] for r in result['rows']), 1_000_000)


if __name__ == '__main__':
    unittest.main()
