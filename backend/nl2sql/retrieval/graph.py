"""Bounded join context from approved catalog metadata, never row contents."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nl2sql.schema import Table

MAX_JOIN_HOPS = 5
MAX_EXTRA_TABLES = 8
MAX_CONNECT_ANCHORS = 12


def join_graph(tables: Mapping[str, Table]) -> dict[str, frozenset[str]]:
    """Build both directions once in O(tables + columns + references)."""
    graph: dict[str, set[str]] = {name: set() for name in tables}
    for name, table in tables.items():
        links = set(table.references)
        links.update(
            column.name[:-3] for column in table.columns if column.name.endswith("_id")
        )
        for link in links:
            if link in graph and link != name:
                graph[name].add(link)
                graph[link].add(name)
    return {name: frozenset(links) for name, links in graph.items()}


def _component(
    start: str, selected: set[str], graph: Mapping[str, frozenset[str]]
) -> set[str]:
    found, queue = {start}, deque([start])
    while queue:
        for name in graph[queue.popleft()] & selected - found:
            found.add(name)
            queue.append(name)
    return found


def _path(
    target: str, connected: set[str], graph: Mapping[str, frozenset[str]]
) -> set[str]:
    queue = deque([(target, 0)])
    parents: dict[str, str | None] = {target: None}
    while queue:
        name, depth = queue.popleft()
        if name in connected:
            path = set()
            while name is not None:
                path.add(name)
                name = parents[name]
            return path
        if depth == MAX_JOIN_HOPS:
            continue
        for link in sorted(graph[name]):
            if link not in parents:
                parents[link] = name
                queue.append((link, depth + 1))
    return set()


def select_tables(
    tables: Mapping[str, Table], nearest: Iterable[str], example_tables: Iterable[str]
) -> set[str]:
    """Retain existing bridges, then fill short missing join paths deterministically.

    New path work is capped at twelve anchors, five hops per path and eight
    additional tables in total. Disconnected catalogs remain disconnected. The
    graph is request-local so catalog or owner changes cannot reuse stale edges.
    """
    chosen = {
        name.lower() for name in [*nearest, *example_tables] if name.lower() in tables
    }
    if not chosen:
        return set()
    graph = join_graph(tables)
    selected = chosen | {
        name
        for name, links in graph.items()
        if name not in chosen and len(links & chosen) >= 2
    }
    if len(chosen) > MAX_CONNECT_ANCHORS:
        return selected
    baseline = set(selected)
    start = min(chosen)
    connected = _component(start, selected, graph)
    for target in sorted(chosen):
        if target in connected:
            continue
        path = _path(target, connected, graph)
        if path and len((selected | path) - baseline) <= MAX_EXTRA_TABLES:
            selected.update(path)
            connected = _component(start, selected, graph)
    return selected
