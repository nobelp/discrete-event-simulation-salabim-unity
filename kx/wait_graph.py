"""Snapshot diagnosis of explicit finite-resource waits; never a real-plant proof."""


def diagnose(resources, records):
    actors = list(records)
    graph = {}
    labels = {}
    for index, actor in enumerate(actors):
        node = 'a:' + str(index)
        labels[node] = actor
        graph.setdefault(node, set())
        target = actor.get('waitingFor')
        if target in resources and resources[target]['occupancy'] >= resources[target]['capacity']:
            graph[node].add('r:' + target)
        for key in actor.get('held', []):
            graph.setdefault('r:' + key, set()).add(node)
    # Iterative Kosaraju avoids recursion limits on long transport queues.
    for targets in list(graph.values()):
        for target in targets:
            graph.setdefault(target, set())
    seen, order = set(), []
    for root in sorted(graph):
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(sorted(graph[root])))]
        while stack:
            node, targets = stack[-1]
            target = next(targets, None)
            if target is None:
                order.append(node)
                stack.pop()
            elif target not in seen:
                seen.add(target)
                stack.append((target, iter(sorted(graph[target]))))
    reverse = {node: set() for node in graph}
    for node, targets in graph.items():
        for target in targets:
            reverse[target].add(node)
    seen, cycles = set(), []
    for root in reversed(order):
        if root in seen:
            continue
        component, pending = set(), [root]
        seen.add(root)
        while pending:
            node = pending.pop()
            component.add(node)
            for target in sorted(reverse[node]):
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        if len(component) <= 1:
            continue
        closed = all(graph[node] and graph[node] <= component for node in component)
        cycles.append(dict(closed=closed, resources=sorted(n[2:] for n in component if n.startswith('r:')),
                           participants=[dict(id=labels[n]['id'], type=labels[n].get('type'),
                                              waitingFor=labels[n].get('waitingFor'), held=list(labels[n].get('held', [])))
                                         for n in sorted(component) if n.startswith('a:')]))
    cycles.sort(key=lambda c: (not c['closed'], c['resources']))
    return dict(circularWaitCount=len(cycles), closedCircularWaitCount=sum(c['closed'] for c in cycles),
                cycles=cycles[:20], detailsTruncated=len(cycles)>20,
                scope='Measurement-end snapshot of explicit full finite resources and their holders. Closed means every outgoing wait/holder edge remains inside the cycle. No real-WCS or real-plant deadlock proof; rack/stock waits and external recovery are not covered.')
