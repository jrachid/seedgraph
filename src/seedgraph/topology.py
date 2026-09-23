"""FK-graph topology from model metadata: dependency edges, strict parent-first order, cycle refusal."""

import heapq

from sqlalchemy import MetaData
from sqlalchemy.exc import NoReferencedTableError

from seedgraph.exceptions import SeedgraphError

__all__ = ["CyclicFKGraphError", "dependency_graph", "metadata_of", "topological_order"]


class CyclicFKGraphError(SeedgraphError):
    """No strict parent-first order exists: tables reference each other in a closed loop."""

    def __init__(self, groups):
        self.groups = tuple(tuple(group) for group in groups)
        names = " ; ".join("(" + ", ".join(group) + ")" for group in self.groups)
        super().__init__(f"cyclic FK groups prevent a strict parent-first order: {names}")


def dependency_graph(source):
    """Map every table key to the set of table keys it references through declared FK constraints."""
    metadata = metadata_of(source)
    graph = {key: set() for key in metadata.tables}
    for child, parent, _use_alter in _declared_edges(metadata):
        graph[child].add(parent)
    return graph


def topological_order(source):
    """Return the metadata's tables in strict parent-first order, or raise CyclicFKGraphError."""
    metadata = metadata_of(source)
    parent_sets = _ordering_edges(metadata)
    order, remaining = _kahn_order(parent_sets)
    if remaining:
        raise CyclicFKGraphError(_cyclic_groups(remaining, parent_sets))
    return [metadata.tables[key] for key in order]


def metadata_of(source):
    """Return the MetaData behind a mapped class, or pass a MetaData through."""
    if isinstance(source, MetaData):
        return source
    metadata = getattr(source, "metadata", None)
    if isinstance(metadata, MetaData):
        return metadata
    raise TypeError("source must be a SQLAlchemy mapped class or a MetaData object")


def _declared_edges(metadata):
    """Yield (child_key, parent_key, use_alter) for each FK constraint whose target table is in the metadata."""
    for table in metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            targets = set()
            for foreign_key in constraint.elements:
                try:
                    targets.add(foreign_key.column.table.key)
                except NoReferencedTableError:
                    targets.clear()
                    break
            for parent_key in targets:
                if parent_key in metadata.tables:
                    yield table.key, parent_key, constraint.use_alter


def _ordering_edges(metadata):
    """Map every table key to the parents that must precede it: FK edges minus self-references and use_alter."""
    parent_sets = {key: set() for key in metadata.tables}
    for child, parent, use_alter in _declared_edges(metadata):
        if child == parent or use_alter:
            continue
        parent_sets[child].add(parent)
    return parent_sets


def _kahn_order(parent_sets):
    """Return (parents-first order, unorderable leftovers); alphabetical tie-break, fully iterative."""
    indegree = {node: len(parents) for node, parents in parent_sets.items()}
    children = {node: [] for node in parent_sets}
    for child, parents in parent_sets.items():
        for parent in parents:
            children[parent].append(child)
    ready = [node for node, pending in indegree.items() if pending == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    remaining = [node for node, pending in indegree.items() if pending > 0]
    return order, remaining


def _cyclic_groups(remaining, parent_sets):
    """Return the closed-loop table groups among remaining nodes, sorted inside and out, without recursion."""
    nodeset = set(remaining)
    forward = {node: [] for node in remaining}
    backward = {node: [] for node in remaining}
    for child in remaining:
        for parent in parent_sets[child]:
            if parent in nodeset:
                forward[child].append(parent)
                backward[parent].append(child)
    visited = set()
    postorder = []
    for start in remaining:
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(forward[start]))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                postorder.append(node)
                stack.pop()
            elif neighbor not in visited:
                visited.add(neighbor)
                stack.append((neighbor, iter(forward[neighbor])))
    assigned = set()
    groups = []
    for start in reversed(postorder):
        if start in assigned:
            continue
        group = []
        assigned.add(start)
        stack = [start]
        while stack:
            node = stack.pop()
            group.append(node)
            for neighbor in backward[node]:
                if neighbor not in assigned:
                    assigned.add(neighbor)
                    stack.append(neighbor)
        groups.append(group)
    return sorted(sorted(group) for group in groups if len(group) > 1)
