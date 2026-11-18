"""互供核算主引擎：登记比例 → 封闭拒绝 → 精确求解 → 交叉校验 → 受益取整守恒。"""
from collections import defaultdict
from fractions import Fraction

from src.services.reciprocal.rational import parse_rational, fraction_str, decimal_str
from src.services.reciprocal.graph import detect_closed_sets, format_closed_error
from src.services.reciprocal.solvers import (
    fraction_forward_solve,
    fraction_gauss_solve,
    bareiss_solve,
    ReciprocalTimeout,
)
from src.services.reciprocal.rounding import largest_remainder

SOLVE_LIMIT_SECONDS = 30.0
# 小规模追加 Bareiss 第三条求解路径的阈值；近封闭环始终强制独立解对照
BAREISS_CHECK_LIMIT = 15


class RuleValidationError(ValueError):
    pass


def validate_rule(rule):
    """校验互供关系：部门名合法、比例为非负有理数、每个服务部门行合计恰为 1。"""
    if not isinstance(rule, dict):
        raise RuleValidationError('互供关系必须为对象')
    version = rule.get('version')
    if not isinstance(version, str) or not 2 <= len(version) <= 120:
        raise RuleValidationError('互供关系版本名长度需在2到120之间')
    services = rule.get('services')
    beneficiaries = rule.get('beneficiaries')
    if not isinstance(services, list) or not services or len(services) > 100:
        raise RuleValidationError('服务部门需为1到100个的非空列表')
    if not isinstance(beneficiaries, list) or not beneficiaries or len(beneficiaries) > 20:
        raise RuleValidationError('受益部门需为1到20个的非空列表')
    if any(not isinstance(name, str) or not name.strip() for name in services + beneficiaries):
        raise RuleValidationError('部门名必须为非空字符串')
    if len(set(services)) != len(services) or len(set(beneficiaries)) != len(beneficiaries):
        raise RuleValidationError('同类型部门名不可重复')
    if set(services) & set(beneficiaries):
        raise RuleValidationError('同一部门不可同时登记为服务部门与受益部门')

    rows = rule.get('rows')
    if not isinstance(rows, list) or len(rows) != len(services):
        raise RuleValidationError('每个服务部门必须恰好登记一行比例')
    known = set(services) | set(beneficiaries)
    proportions = {}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuleValidationError('比例行必须为对象')
        source = row.get('source')
        if source not in services or source in seen:
            raise RuleValidationError('比例行来源必须为服务部门且不可重复')
        seen.add(source)
        allocations = row.get('allocations')
        if not isinstance(allocations, list) or not allocations:
            raise RuleValidationError('每个服务部门至少登记一条转出比例')
        parsed = {}
        targets = set()
        for item in allocations:
            if not isinstance(item, dict):
                raise RuleValidationError('比例条目必须为对象')
            target = item.get('target')
            if target not in known or target in targets:
                raise RuleValidationError('比例目标必须为已登记部门且不可重复')
            targets.add(target)
            ratio = parse_rational(item.get('ratio'), f'{source}→{target}比例')
            parsed[target] = ratio
        if sum(parsed.values()) != 1:
            raise RuleValidationError(f'服务部门 {source} 的转出比例合计必须恰好为1')
        proportions[source] = parsed
    if seen != set(services):
        raise RuleValidationError('每个服务部门都必须登记比例行')
    return {
        'version': version,
        'services': list(services),
        'beneficiaries': list(beneficiaries),
        'proportions': proportions,
    }


def _build_fraction_system(services, proportions):
    """直接构造 (I - Aᵀ) 的 Fraction 矩阵，避免全局公分母 LCM 导致的大整数膨胀。"""
    n = len(services)
    index = {name: i for i, name in enumerate(services)}
    matrix = [[Fraction(0) for _ in range(n)] for _ in range(n)]
    for i in range(n):
        matrix[i][i] = Fraction(1)
    for source in services:
        for target, ratio in proportions[source].items():
            if target in index:
                matrix[index[target]][index[source]] -= ratio
    return matrix


def diagnose(services, beneficiaries, proportions):
    """封闭环诊断，供预检接口与核算引擎共用。"""
    return detect_closed_sets(services, beneficiaries, proportions)


def reciprocal_allocate(entries, rule, deadline_seconds=SOLVE_LIMIT_SECONDS, cross_check=None):
    """执行互供核算。

    entries: [{period, department, category, amount_cents}]，金额为非负整数分。
    rule: validate_rule 返回的规范化关系。
    cross_check: None 时按规模/近封闭自动决定；True 强制独立解对照。
    返回完整结果字典（分数份额以字符串保存，可 JSON 序列化）。
    """
    import time
    started = time.monotonic()
    hard_deadline = started + deadline_seconds
    # 时限预算：主解 55%、独立交叉校验 35%、取整与结果整理 10%，任何阶段超时均明确拒绝
    primary_deadline = started + deadline_seconds * 0.55
    cross_deadline = started + deadline_seconds * 0.90
    services = rule['services']
    beneficiaries = rule['beneficiaries']
    proportions = rule['proportions']
    service_set, beneficiary_set = set(services), set(beneficiaries)

    # 1. 封闭循环检测：即使全部费用为零也拒绝
    detection = detect_closed_sets(services, beneficiaries, proportions)
    if detection['trapped']:
        error = RuleValidationError(format_closed_error(detection))
        error.detection = detection
        raise error

    # 2. 底稿分组与字段校验
    own_cost = defaultdict(int)       # (period, category, service) -> 自身费用
    group_total = defaultdict(int)    # (period, category) -> 服务部门自身费用合计
    direct = defaultdict(int)         # (period, category, beneficiary) -> 受益部门直归费用
    unknown = defaultdict(int)
    source_total = 0
    for entry in entries:
        amount = entry.get('amount_cents')
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise RuleValidationError('底稿金额必须为非负整数分')
        department = entry.get('department')
        period, category = entry.get('period'), entry.get('category')
        if not isinstance(period, str) or not period or not isinstance(category, str) or not category:
            raise RuleValidationError('底稿期间与费用类别不能为空')
        source_total += amount
        if department in service_set:
            own_cost[(period, category, department)] += amount
            group_total[(period, category)] += amount
        elif department in beneficiary_set:
            direct[(period, category, department)] += amount
        else:
            unknown[department] += amount
    if unknown:
        raise RuleValidationError('底稿存在未登记为服务或受益部门的部门：' + '、'.join(sorted(map(str, unknown))))

    matrix = _build_fraction_system(services, proportions)
    n = len(services)
    groups = sorted(group_total)
    # 每个期间×类别分组一个 RHS 列向量（长度 n）：服务部门自身费用，未知分量为 0
    rhs_vectors = [
        [Fraction(own_cost[(key[0], key[1], services[i])]) for i in range(n)]
        for key in groups
    ]

    # 3. 主精确解：Fraction 前向消元 + 最小度数主元 + 回代，多分组同轮消元
    primary_columns = fraction_forward_solve(matrix, rhs_vectors, deadline=primary_deadline)
    totals_by_group = {
        key: {services[i]: primary_columns[g][i] for i in range(n)}
        for g, key in enumerate(groups)
    }

    # 4. 近封闭诊断：最小外流比例
    outflow_ratios = sorted(
        ratio
        for source in services
        for target, ratio in proportions[source].items()
        if target in beneficiary_set
    )
    min_outflow = outflow_ratios[0] if outflow_ratios else Fraction(0)
    # 需求边界：外流比例可低至百万分之一，不高于 1/1000000 即视为近封闭环
    near_closed = bool(outflow_ratios) and min_outflow <= Fraction(1, 1_000_000)

    # 5. 独立精确解交叉校验（近封闭环强制；默认小规模也对照）
    do_cross = cross_check if cross_check is not None else (near_closed or n <= BAREISS_CHECK_LIMIT)
    cross = {'performed': False, 'matched': None, 'solver': None, 'solvers': []}

    def _matches(independent):
        return all(
            independent[g][i] == primary_columns[g][i]
            for g in range(len(groups)) for i in range(n)
        )

    if do_cross:
        matched = True
        if n <= BAREISS_CHECK_LIMIT:
            # 小规模：两条完全独立的实现——高斯-若尔当 RREF 与 Bareiss 整数消元
            matched = matched and _matches(fraction_gauss_solve(matrix, rhs_vectors, deadline=cross_deadline))
            cross['solvers'].append('fraction-gauss-jordan')
            matched = matched and _matches(bareiss_solve(matrix, rhs_vectors, deadline=cross_deadline))
            cross['solvers'].append('bareiss-integer-elimination')
        else:
            # 大规模近封闭环：改用自然序前向消元（与主解最小度数主元策略相互独立），
            # 避免完整 RREF 的 O(n³) 分数运算在时限内无法完成
            matched = matched and _matches(
                fraction_forward_solve(matrix, rhs_vectors, deadline=cross_deadline, min_degree=False)
            )
            cross['solvers'].append('fraction-forward-natural-pivot')
        cross.update(performed=True, matched=matched, solver='+'.join(cross['solvers']))
        if not matched:
            raise RuleValidationError('独立精确解与主解不一致，已拒绝出表，请复核互供比例')

    # 6. 主解自检：固定点方程 x_i = 自身费用 b_i + 转入费用（精确），逐组外流守恒
    for key in groups:
        totals = totals_by_group[key]
        for i, name in enumerate(services):
            inflow = sum(
                proportions[source].get(name, Fraction(0)) * totals[source]
                for source in services
            )
            if totals[name] != own_cost[(key[0], key[1], name)] + inflow:
                raise RuleValidationError(f'{key} 服务部门 {name} 固定点校验失败')
        outflow = sum(
            proportions[source].get(beneficiary, Fraction(0)) * totals[source]
            for source in services for beneficiary in beneficiaries
        )
        if outflow != group_total[key]:
            raise RuleValidationError(f'{key} 外流合计与自身费用不守恒')

    # 7. 受益部门份额与按期间×类别取整（只在受益部门取整，余分稳定分配）
    share_rows = []
    rounded_rows = []
    for key in groups:
        period, category = key
        totals = totals_by_group[key]
        group_exact = {}
        for beneficiary in beneficiaries:
            share = sum(
                proportions[source].get(beneficiary, Fraction(0)) * totals[source]
                for source in services
            )
            group_exact[beneficiary] = share
            share_rows.append({
                '期间': period,
                '费用类别': category,
                '受益部门': beneficiary,
                '精确份额分': fraction_str(share),
                '小数预览': decimal_str(share),
            })
        rounded = largest_remainder(group_exact, group_total[key])
        for beneficiary in beneficiaries:
            rounded_rows.append({
                '期间': period,
                '费用类别': category,
                '受益部门': beneficiary,
                '分摊金额分': rounded[beneficiary],
                '精确份额分': fraction_str(group_exact[beneficiary]),
                '余分调整分': rounded[beneficiary] - (
                    group_exact[beneficiary].numerator // group_exact[beneficiary].denominator
                ),
            })

    # 受益部门直归费用保持整数分原样
    for period, category, beneficiary in sorted(direct):
        rounded_rows.append({
            '期间': period,
            '费用类别': category,
            '受益部门': beneficiary,
            '分摊金额分': direct[(period, category, beneficiary)],
            '精确份额分': str(direct[(period, category, beneficiary)]),
            '余分调整分': 0,
        })
    rounded_rows.sort(key=lambda r: (r['期间'], r['费用类别'], r['受益部门']))

    # 服务部门总成本（自身+转入）逐组逐部门输出
    service_rows = []
    for key in groups:
        period, category = key
        for name in services:
            value = totals_by_group[key][name]
            service_rows.append({
                '期间': period,
                '费用类别': category,
                '服务部门': name,
                '总成本精确分': fraction_str(value),
                '小数预览': decimal_str(value),
            })

    allocated_total = sum(row['分摊金额分'] for row in rounded_rows)
    if allocated_total != source_total:
        raise RuleValidationError(
            f'取整后总额 {allocated_total} 与底稿总额 {source_total} 不守恒'
        )
    if time.monotonic() > hard_deadline:
        raise ReciprocalTimeout('互供核算超过30秒时限，已拒绝，请复核比例规模或缩小范围后重试')

    return {
        'method': '互供代数分配法：按服务部门自身费用加转入费用建立线性方程 (I-A转置)x=b，全程Fraction有理数、前向消元（最小度数主元）+回代求精确解；仅受益部门按期间×类别取整，最大余数法按部门名升序稳定补齐余分，总额守恒；近封闭环用独立高斯-若尔当精确解交叉校验。',
        'summary': {
            '底稿金额分': source_total,
            '服务部门自身费用分': sum(group_total.values()),
            '受益部门直归分': sum(direct.values()),
            '取整后分摊金额分': allocated_total,
            '守恒差额分': allocated_total - source_total,
            '服务部门数': n,
            '受益部门数': len(beneficiaries),
            '最小外流比例': fraction_str(min_outflow),
            '近封闭环': near_closed,
            '交叉校验通过': cross['matched'],
        },
        'service_rows': service_rows,
        'share_rows': share_rows,
        'rows': rounded_rows,
        'cross_check': cross,
        'diagnosis': {
            'trapped': detection['trapped'],
            'closed_groups': detection['closed_groups'],
            'has_outflow': detection['has_outflow'],
        },
        'system': _system_block(matrix),
        'warnings': [
            '检测到外流比例不高于百万分之一的近封闭环，已用相互独立的第二套精确求解路径交叉校验通过'
        ] if near_closed and cross.get('matched') else [],
    }


def _system_block(matrix):
    """小尺寸内嵌完整分数矩阵；大尺寸只存维度与稀疏度，避免结果 JSON 膨胀。

    大尺寸时矩阵可由快照中的互供比例完全重建，无需随结果冗余存储。
    """
    n = len(matrix)
    nonzero = sum(1 for row in matrix for value in row if value != 0)
    block = {
        '矩阵说明': '(I - A转置) 的有理数矩阵；大尺寸不内嵌，可由快照互供比例重建',
        '阶数': n,
        '非零元数': nonzero,
        '稀疏度': round(nonzero / (n * n), 6) if n else 0,
    }
    if n <= 20:
        block['分数矩阵'] = [[fraction_str(value) for value in row] for row in matrix]
    return block
