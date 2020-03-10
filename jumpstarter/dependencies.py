"""Dependency resolution for steps."""
import typing
from collections import abc

from networkx import DiGraph
from networkx import is_directed_acyclic_graph


class ExecutionOrder(abc.Iterator):
    """An iterator over a directed acyclic graph of steps that calculates the execution order."""

    def __init__(self, steps_dependency_graph: DiGraph):
        self._steps_dependency_graph = steps_dependency_graph
        self._current_steps_dependency_graph: DiGraph = self._steps_dependency_graph
        self._execution_order: typing.List[typing.Any] = []
        self._steps_without_dependencies: typing.Set[typing.Any] = self.steps_without_dependencies

    @property
    def steps_without_dependencies(self) -> typing.Set[typing.Any]:
        """Find all current steps without any dependencies."""
        return {
            step
            for step in self._current_steps_dependency_graph
            if not any(self._current_steps_dependency_graph.neighbors(step))
        }

    def mark_as_pending_execution(self, steps: typing.Set[typing.Any]) -> None:
        """Mark the following steps as steps that are about to be executed."""
        self._current_steps_dependency_graph = self._current_steps_dependency_graph.subgraph(
            self._current_steps_dependency_graph.nodes - steps
        )
        self._execution_order.append(steps)

    @property
    def done(self) -> bool:
        """Report whether we exhausted the dependency graph or not."""
        return not self._current_steps_dependency_graph.order()

    def __next__(self) -> typing.Set[typing.Any]:
        """Calculate the next steps for execution."""
        assert is_directed_acyclic_graph(self._current_steps_dependency_graph)

        # Continue looping while the graph is not empty.
        if self.done:
            raise StopIteration

        # Execute all nodes without dependencies since they can now run.
        steps = self._steps_without_dependencies
        self.mark_as_pending_execution(steps)

        self._steps_without_dependencies = self.steps_without_dependencies

        return steps

    def __iter__(self) -> abc.Iterator:
        """Iterate over the execution order.

        The execution order is cached after being calculated once.
        """
        return iter(self._execution_order) if self._execution_order else self
