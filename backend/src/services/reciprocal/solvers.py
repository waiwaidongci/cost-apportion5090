"""互供方程的精确求解器（全程 Fraction 有理数，无浮点），稀疏字典表示。

方程（服务部门总成本 = 自身费用 + 转入费用）：
    (I - Aᵀ) x = b
其中 A[i][j] 为服务部门 i 转给服务部门 j 的比例，b[k] 为服务部门 k 自身归集费用。

三条相互独立的实现路径，用于交叉校验近封闭环：
1. fraction_forward_solve（主解）：Fraction 前向消元 + 最小度数主元 + 回代，
   行以 {列: Fraction} 稀疏存储，零元不参与运算，多 RHS 同轮消元；
2. fraction_gauss_solve（独立对照，小规模）：Fraction 高斯-若尔当完整消元直接得 RREF；
3. bareiss_solve（独立对照，小规模）：逐行公分母整数化后的 Bareiss 无分数整数消元。
大规模近封闭环的独立对照仍走前向消元，但使用自然序主元（min_degree=False），
与主解的最小度数主元是不同的求解路径。
"""
import time
from fractions import Fraction
from math import gcd


class ReciprocalTimeout(Exception):
    """超过核算时限（默认 30 秒），拒绝并提示复核。"""


def _check_deadline(deadline, n, step):
    if deadline is not None and step % max(1, n) == 0 and time.monotonic() > deadline:
        raise ReciprocalTimeout('互供核算超过30秒时限，已拒绝，请复核比例规模或缩小范围后重试')


def _to_sparse(matrix):
    """稠密矩阵 → 稀疏行字典列表（丢弃零元）。"""
    return [{j: Fraction(value) for j, value in enumerate(row) if value != 0}
            for row in matrix]


def fraction_forward_solve(matrix, rhs_vectors, deadline=None, min_degree=True):
    """主解：稀疏前向消元 + 回代，多 RHS 同轮消元。

    min_degree=True 使用最小度数主元（控制填充与分数位数增长）；
    min_degree=False 使用自然列主元，作为相互独立的对照求解路径。
    返回 list[list[Fraction]]，每个输入列对应一组解。
    """
    n = len(matrix)
    rows = _to_sparse(matrix)
    rhs = [[Fraction(column[i]) for i in range(n)] for column in rhs_vectors]
    ticks = 0

    for k in range(n):
        if deadline is not None and time.monotonic() > deadline:
            raise ReciprocalTimeout('互供核算超过30秒时限，已拒绝，请复核比例规模或缩小范围后重试')
        candidates = [r for r in range(k, n) if k in rows[r]]
        if not candidates:
            raise ValueError('系数矩阵奇异，互供关系不可求解（请检查封闭循环）')
        if min_degree:
            pivot_row = min(candidates, key=lambda r: sum(1 for j in rows[r] if j >= k))
        else:
            pivot_row = candidates[0]
        if pivot_row != k:
            rows[k], rows[pivot_row] = rows[pivot_row], rows[k]
            for column in rhs:
                column[k], column[pivot_row] = column[pivot_row], column[k]

        pivot = rows[k][k]
        # 主元行归一化（仅遍历非零列）
        rows[k] = {j: value / pivot for j, value in rows[k].items() if j >= k}
        rows[k].pop(k, None)
        for column in rhs:
            column[k] /= pivot

        for i in range(k + 1, n):
            factor = rows[i].get(k)
            if factor is None:
                continue
            for j, value in rows[k].items():
                updated = rows[i].get(j, Fraction(0)) - factor * value
                if updated != 0:
                    rows[i][j] = updated
                else:
                    rows[i].pop(j, None)
            rows[i].pop(k, None)
            for column in rhs:
                column[i] -= factor * column[k]
            ticks += 1
            _check_deadline(deadline, n, ticks)

    solutions = []
    for column in rhs:
        x = [Fraction(0)] * n
        for i in range(n - 1, -1, -1):
            x[i] = column[i] - sum(value * x[j] for j, value in rows[i].items())
        solutions.append(x)
    return solutions


def fraction_gauss_solve(matrix, rhs_vectors, deadline=None):
    """独立对照解：Fraction 高斯-若尔当完整消元（自然列主元交换），直接得到 RREF。"""
    n = len(matrix)
    width = n + len(rhs_vectors)
    table = []
    for i in range(n):
        table.append([Fraction(v) for v in matrix[i]]
                     + [Fraction(column[i]) for column in rhs_vectors])
    ticks = 0
    row = 0
    for col in range(n):
        if deadline is not None and time.monotonic() > deadline:
            raise ReciprocalTimeout('互供核算超过30秒时限，已拒绝，请复核比例规模或缩小范围后重试')
        pivot = next((r for r in range(row, n) if table[r][col] != 0), None)
        if pivot is None:
            raise ValueError('系数矩阵奇异，互供关系不可求解（请检查封闭循环）')
        table[row], table[pivot] = table[pivot], table[row]
        pivot_value = table[row][col]
        table[row] = [v / pivot_value for v in table[row]]
        for r in range(n):
            if r == row or table[r][col] == 0:
                continue
            factor = table[r][col]
            table[r] = [table[r][j] - factor * table[row][j] for j in range(width)]
            ticks += 1
            _check_deadline(deadline, n, ticks)
        row += 1

    solutions = []
    for offset in range(len(rhs_vectors)):
        solutions.append([table[i][n + offset] for i in range(n)])
    return solutions


def _row_scaled_integer_matrix(matrix):
    """把矩阵按逐行 LCM 放大为整数矩阵（仅小规模 Bareiss 对照使用）。"""
    fraction_rows = [[Fraction(value) for value in row] for row in matrix]
    integer_rows = []
    row_scales = []
    for row in fraction_rows:
        scale = 1
        for value in row:
            scale = scale * value.denominator // gcd(scale, value.denominator)
        row_scales.append(scale)
        integer_rows.append([value.numerator * (scale // value.denominator) for value in row])
    return integer_rows, row_scales


def bareiss_solve(matrix, rhs_vectors, deadline=None):
    """Bareiss 无分数整数消元（仅整数除法）+ 分数回代；作为小规模第三条独立路径。

    矩阵按逐行 LCM 放大为整数矩阵（每行方程整体乘 L_i，RHS 第 i 个分量同步乘 L_i）。
    缩放后的系数与 RHS 组成增广行绑定在一起，主元交换整行，避免行缩放因子错位。
    """
    integer_matrix, row_scales = _row_scaled_integer_matrix(matrix)
    n = len(integer_matrix)
    ticks = 0
    # 每个增广行 = 缩放后的系数行 + 各 RHS 列在该行缩放后的分量
    augmented = [
        list(integer_matrix[i])
        + [column[i] * row_scales[i] for column in rhs_vectors]
        for i in range(n)
    ]
    rhs_count = len(rhs_vectors)
    previous_pivot = 1

    for k in range(n - 1):
        if deadline is not None and time.monotonic() > deadline:
            raise ReciprocalTimeout('互供核算超过30秒时限，已拒绝，请复核比例规模或缩小范围后重试')
        pivot_row = next((r for r in range(k, n) if augmented[r][k] != 0), None)
        if pivot_row is None:
            raise ValueError('系数矩阵奇异，互供关系不可求解（请检查封闭循环）')
        if pivot_row != k:
            augmented[k], augmented[pivot_row] = augmented[pivot_row], augmented[k]

        pivot = augmented[k][k]
        for i in range(k + 1, n):
            factor = augmented[i][k]
            # 统一 Bareiss 公式：所有子矩阵元素都按 previous_pivot 整除归一化，
            # 不允许对零因子行提前 continue，否则破坏后续主元
            for j in range(k + 1, n + rhs_count):
                if factor == 0:
                    value = augmented[i][j] * pivot
                else:
                    value = augmented[i][j] * pivot - factor * augmented[k][j]
                augmented[i][j] = value // previous_pivot
            augmented[i][k] = 0
            ticks += 1
            _check_deadline(deadline, n, ticks)
        previous_pivot = pivot

    if augmented[n - 1][n - 1] == 0:
        raise ValueError('系数矩阵奇异，互供关系不可求解（请检查封闭循环）')

    solutions = []
    for offset in range(rhs_count):
        column = n + offset
        x = [Fraction(0)] * n
        for i in range(n - 1, -1, -1):
            residual = augmented[i][column] - sum(
                augmented[i][j] * x[j] for j in range(i + 1, n)
            )
            x[i] = Fraction(residual, augmented[i][i])
        solutions.append(x)
    return solutions
