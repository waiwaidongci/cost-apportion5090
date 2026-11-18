"""整数分最大余数法：只在受益部门取整，余分按部门名稳定分配，总额守恒。"""


def largest_remainder(shares, total_cents, tie_key=lambda name: name):
    """shares: {受益部门: Fraction 绝对精确份额（单位：分）}；total_cents: 待分配整数分。

    份额合计必须恰等于 total_cents（精确）。向下取整后，按余数降序、部门名升序
    补齐剩余分；返回 {部门: int}，合计恒等于总额。
    """
    if isinstance(total_cents, bool) or not isinstance(total_cents, int) or total_cents < 0:
        raise ValueError('待分配金额必须为非负整数分')
    if not shares:
        raise ValueError('没有可承接费用的受益部门')
    if sum(shares.values()) != total_cents:
        raise ValueError('精确份额合计必须等于待分配金额')
    floors = {}
    remainders = {}
    for name, share in shares.items():
        if share < 0:
            raise ValueError('份额不能为负数')
        floors[name], remainders[name] = divmod(share.numerator, share.denominator)
    allocated = sum(floors.values())
    leftover = total_cents - allocated
    if leftover < 0:
        raise ValueError('取整基准异常')
    order = sorted(shares, key=lambda name: (-remainders[name], tie_key(name)))
    result = dict(floors)
    for name in order[:leftover]:
        result[name] += 1
    assert sum(result.values()) == total_cents
    return result
