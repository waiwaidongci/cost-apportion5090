"""服务部门外流图：检测无外流（封闭）的部门集合。

边 i -> j 当且仅当服务部门 i 对目标 j 的转出比例严格为正。
任何能沿正比例边到达受益部门的服务部门视为有外流；
剩余节点构成无外流集合，其中没有出边离开集合的强连通分量即封闭环。
"""


def _sink_sccs(nodes, successors):
    """Tarjan 强连通分量，返回汇点（无出边离开自身）SCC 列表，每个 SCC 内节点已排序。"""
    index = {}
    low = {}
    stack = []
    on_stack = set()
    counter = 0
    sccs = []

    def strongconnect(v):
        nonlocal counter
        index[v] = low[v] = counter
        counter += 1
        stack.append(v)
        on_stack.add(v)
        for w in successors.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            sccs.append(sorted(component))

    for v in nodes:
        if v not in index:
            strongconnect(v)

    sink = []
    for component in sccs:
        members = set(component)
        if not any(w not in members for v in component for w in successors.get(v, ())):
            sink.append(component)
    return sorted(sink, key=lambda component: component[0])


def detect_closed_sets(services, beneficiaries, proportions):
    """返回 {'trapped': [...], 'closed_groups': [[...]], 'has_outflow': {...}}。

    proportions: {service: {target: Fraction}}，target 可为服务或受益部门。
    """
    service_set = set(services)
    beneficiary_set = set(beneficiaries)
    successors = {}
    has_outflow = {}
    for svc in services:
        row = proportions.get(svc, {})
        edges = [target for target, ratio in row.items() if ratio > 0]
        successors[svc] = edges
        has_outflow[svc] = any(target in beneficiary_set for target in edges)

    # 反向 BFS：从有直接外流的服务部门出发，沿 i->j 反方向标记全部可外流部门
    reverse = {svc: [] for svc in services}
    for svc in services:
        for target in successors[svc]:
            if target in service_set:
                reverse[target].append(svc)
    reachable = {svc for svc in services if has_outflow[svc]}
    frontier = list(reachable)
    while frontier:
        node = frontier.pop()
        for predecessor in reverse[node]:
            if predecessor not in reachable:
                reachable.add(predecessor)
                frontier.append(predecessor)

    trapped = sorted(service_set - reachable)
    trapped_set = set(trapped)
    trapped_successors = {
        svc: [target for target in successors.get(svc, ()) if target in trapped_set]
        for svc in trapped
    }
    closed_groups = _sink_sccs(trapped, trapped_successors) if trapped else []
    return {
        'trapped': trapped,
        'closed_groups': closed_groups,
        'has_outflow': {svc: svc in reachable for svc in services},
    }


def format_closed_error(detection):
    """构造拒绝信息，指出无外流的部门集合与封闭环。"""
    trapped = '、'.join(detection['trapped'])
    groups = '；'.join('（' + '、'.join(group) + '）' for group in detection['closed_groups'])
    message = f'存在无外流的服务部门集合，封闭循环即使零费用也拒绝：[{trapped}]'
    if groups:
        message += f'；封闭环分组：{groups}'
    return message
