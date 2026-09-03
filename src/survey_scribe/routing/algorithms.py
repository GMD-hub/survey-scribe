"""Iterative deterministic graph algorithms for questionnaire routing."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def iterative_reachable(
    start_node_ids: Iterable[str],
    adjacency: Mapping[str, Iterable[str]],
) -> tuple[str, ...]:
    """Return reachable nodes in deterministic depth-first discovery order."""
    starts = tuple(dict.fromkeys(start_node_ids))
    known = set(adjacency)
    visited: set[str] = set()
    discovered: list[str] = []
    stack = list(reversed(tuple(node_id for node_id in starts if node_id in known)))
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        discovered.append(node_id)
        neighbors = tuple(adjacency.get(node_id, ()))
        stack.extend(
            neighbor
            for neighbor in reversed(neighbors)
            if neighbor in known and neighbor not in visited
        )
    return tuple(discovered)


def iterative_strongly_connected_components(
    node_ids: Iterable[str],
    adjacency: Mapping[str, Iterable[str]],
) -> tuple[tuple[str, ...], ...]:
    """Return SCCs in source order using iterative Kosaraju traversal."""
    ordered_nodes = tuple(dict.fromkeys(node_ids))
    order = {node_id: position for position, node_id in enumerate(ordered_nodes)}
    normalized = {
        node_id: tuple(
            sorted(
                {target for target in adjacency.get(node_id, ()) if target in order},
                key=order.__getitem__,
            )
        )
        for node_id in ordered_nodes
    }

    finished: list[str] = []
    visited: set[str] = set()
    for root in ordered_nodes:
        if root in visited:
            continue
        visited.add(root)
        stack: list[tuple[str, int]] = [(root, 0)]
        while stack:
            node_id, next_index = stack[-1]
            neighbors = normalized[node_id]
            if next_index < len(neighbors):
                target = neighbors[next_index]
                stack[-1] = (node_id, next_index + 1)
                if target not in visited:
                    visited.add(target)
                    stack.append((target, 0))
                continue
            stack.pop()
            finished.append(node_id)

    reverse: dict[str, list[str]] = {node_id: [] for node_id in ordered_nodes}
    for source, targets in normalized.items():
        for target in targets:
            reverse[target].append(source)
    for targets in reverse.values():
        targets.sort(key=order.__getitem__)

    assigned: set[str] = set()
    components: list[tuple[str, ...]] = []
    for root in reversed(finished):
        if root in assigned:
            continue
        assigned.add(root)
        members: list[str] = []
        component_stack = [root]
        while component_stack:
            node_id = component_stack.pop()
            members.append(node_id)
            for source in reversed(reverse[node_id]):
                if source not in assigned:
                    assigned.add(source)
                    component_stack.append(source)
        components.append(tuple(sorted(members, key=order.__getitem__)))
    components.sort(key=lambda component: order[component[0]])
    return tuple(components)


def reverse_adjacency(
    node_ids: Iterable[str],
    adjacency: Mapping[str, Iterable[str]],
) -> dict[str, tuple[str, ...]]:
    """Return a deterministic reverse adjacency over the supplied node set."""
    ordered_nodes = tuple(dict.fromkeys(node_ids))
    order = {node_id: position for position, node_id in enumerate(ordered_nodes)}
    reverse: dict[str, list[str]] = {node_id: [] for node_id in ordered_nodes}
    for source in ordered_nodes:
        for target in adjacency.get(source, ()):
            if target in reverse and source not in reverse[target]:
                reverse[target].append(source)
    return {
        node_id: tuple(sorted(sources, key=order.__getitem__))
        for node_id, sources in reverse.items()
    }


__all__ = [
    "iterative_reachable",
    "iterative_strongly_connected_components",
    "reverse_adjacency",
]
