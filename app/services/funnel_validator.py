from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Node:
    id: str
    title: str
    kind: str
    config: dict[str, Any]


class FunnelGraphValidator:
    """Algorithmic validator for React Flow-style funnel graphs."""

    START_KINDS = {"start", "trigger", "generic_trigger"}
    FINISH_KINDS = {"finish", "end", "success", "generic_finish"}
    DELAY_KINDS = {
        "timer",
        "wait",
        "delay",
        "generic_delay",
        "timeout",
        "input_timeout",
        "no_reply_timeout",
        "reply_timeout",
    }

    def validate_graph(self, nodes: list[dict], edges: list[dict]) -> dict:
        parsed_nodes = self._parse_nodes(nodes)
        adjacency = self._build_adjacency(parsed_nodes, edges)
        automatic_adjacency = self._automatic_adjacency(parsed_nodes, adjacency)
        errors: list[str] = []
        warnings: list[str] = []

        if not parsed_nodes:
            return {
                "is_valid": False,
                "errors": ["Воронка пуста: добавьте стартовый блок."],
                "warnings": [],
            }

        start_ids = [
            node_id
            for node_id, node in parsed_nodes.items()
            if self._is_start(node)
        ]
        if not start_ids:
            errors.append("Воронка должна содержать стартовый блок.")
        elif len(start_ids) > 1:
            warnings.append("Воронка содержит несколько стартовых блоков; runtime начнет с первого найденного.")

        reachable = self._reachable(start_ids, adjacency)
        for node_id, node in parsed_nodes.items():
            if start_ids and node_id not in reachable:
                warnings.append(
                    f"Блок '{node.title}' недостижим из стартовой точки и будет храниться как черновой/неиспользуемый"
                )

        for node_id, node in parsed_nodes.items():
            if start_ids and node_id not in reachable:
                continue
            if self._is_finish(node):
                continue
            if not adjacency.get(node_id):
                errors.append(
                    f"Блок '{node.title}' является тупиковым (нет связи для следующего шага)"
                )

        for cycle in self._find_cycles(automatic_adjacency):
            if not cycle:
                continue
            titles = [parsed_nodes[node_id].title for node_id in cycle]
            if len(titles) == 1:
                cycle_label = f"{titles[0]} -> {titles[0]}"
            else:
                cycle_label = " -> ".join([*titles, titles[0]])
            errors.append(
                "Обнаружен бесконечный автоматический цикл без ожидания пользователя "
                "или задержки между блоками "
                f"{cycle_label}, это приведет к перегрузке процессора"
            )

        return {
            "is_valid": not errors,
            "errors": errors,
            "warnings": warnings,
        }

    def _parse_nodes(self, nodes: list[dict]) -> dict[str, _Node]:
        parsed: dict[str, _Node] = {}
        for raw in nodes:
            if not isinstance(raw, dict):
                continue
            node_id = self._string_value(raw.get("id") or raw.get("step_id"))
            if not node_id:
                data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
                node_id = self._string_value(data.get("id") or data.get("step_id"))
            if not node_id:
                continue

            data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
            step_type = self._string_value(raw.get("step_type") or data.get("step_type"))
            block_type = self._string_value(raw.get("block_type") or data.get("block_type"))
            render_type = self._string_value(raw.get("type") or data.get("type"))
            kind = self._normalize_kind(step_type or block_type or render_type)
            config = (
                raw.get("config_json")
                if isinstance(raw.get("config_json"), dict)
                else data.get("config_json")
                if isinstance(data.get("config_json"), dict)
                else {}
            )
            title = self._string_value(
                raw.get("title")
                or raw.get("label")
                or data.get("title")
                or data.get("label")
                or node_id
            )
            parsed[node_id] = _Node(
                id=node_id,
                title=title,
                kind=kind,
                config=config,
            )
        return parsed

    def _build_adjacency(
        self,
        nodes: dict[str, _Node],
        edges: list[dict],
    ) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        for raw in edges:
            if not isinstance(raw, dict):
                continue
            source = self._string_value(raw.get("source") or raw.get("from_step_id"))
            target = self._string_value(raw.get("target") or raw.get("to_step_id"))
            if source in nodes and target in nodes:
                adjacency[source].append(target)

        for node_id, node in nodes.items():
            for target in self._iter_config_targets(node.config):
                if target in nodes:
                    adjacency[node_id].append(target)

        return {node_id: list(dict.fromkeys(targets)) for node_id, targets in adjacency.items()}

    def _automatic_adjacency(
        self,
        nodes: dict[str, _Node],
        adjacency: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        """Return only transitions that runtime can traverse without pausing.

        React Flow stores button targets as regular graph edges. A backward button
        therefore forms a graph cycle, but not an automatic runtime cycle: the
        message/input block stops and waits for a user action before following it.
        Removing outgoing transitions from runtime boundaries keeps those funnels
        valid while preserving protection against CPU-bound action/condition loops.
        """

        return {
            node_id: [] if self._is_runtime_boundary(nodes[node_id]) else list(targets)
            for node_id, targets in adjacency.items()
        }

    def _reachable(self, start_ids: list[str], adjacency: dict[str, list[str]]) -> set[str]:
        seen: set[str] = set()
        queue: deque[str] = deque(start_ids)
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            for target in adjacency.get(current, []):
                if target not in seen:
                    queue.append(target)
        return seen

    def _find_cycles(self, adjacency: dict[str, list[str]]) -> list[list[str]]:
        color: dict[str, str] = {node_id: "white" for node_id in adjacency}
        stack: list[str] = []
        seen_cycles: set[tuple[str, ...]] = set()
        cycles: list[list[str]] = []

        def canonical(cycle: list[str]) -> tuple[str, ...]:
            if not cycle:
                return tuple()
            rotations = [tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))]
            return min(rotations)

        def visit(node_id: str) -> None:
            color[node_id] = "gray"
            stack.append(node_id)
            for target in adjacency.get(node_id, []):
                if color.get(target) == "white":
                    visit(target)
                    continue
                if color.get(target) != "gray":
                    continue
                try:
                    start_index = stack.index(target)
                except ValueError:
                    continue
                cycle = stack[start_index:].copy()
                key = canonical(cycle)
                if key and key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(cycle)
            stack.pop()
            color[node_id] = "black"

        for node_id in adjacency:
            if color[node_id] == "white":
                visit(node_id)
        return cycles

    def _iter_config_targets(self, config: dict[str, Any]) -> list[str]:
        targets: list[str] = []

        def add(value: Any) -> None:
            target = self._string_value(value)
            if target:
                targets.append(target)

        def add_from_mapping(mapping: Any, key: str) -> None:
            if isinstance(mapping, dict):
                add(mapping.get(key))

        def add_from_list(items: Any, key: str) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                add_from_mapping(item, key)

        for key in ("target_step_id", "timeout_target_step_id", "fallback_target_step_id"):
            add(config.get(key))
        for key in ("buttons", "choices", "outcomes", "variants"):
            add_from_list(config.get(key), "target_step_id")
        messages = config.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict):
                    add_from_list(message.get("buttons"), "target_step_id")
        return targets

    def _is_start(self, node: _Node) -> bool:
        return node.kind in self.START_KINDS

    def _is_finish(self, node: _Node) -> bool:
        return node.kind in self.FINISH_KINDS

    def _is_delay(self, node: _Node) -> bool:
        return node.kind in self.DELAY_KINDS

    def _is_runtime_boundary(self, node: _Node) -> bool:
        if self._is_delay(node):
            return True
        if node.kind == "input":
            return True
        if node.kind == "operator":
            return True
        if node.kind != "message":
            return False

        config = node.config
        if config.get("wait_for_answer") is True:
            return True
        if self._has_buttons(config.get("buttons")):
            return True

        messages = config.get("messages")
        if not isinstance(messages, list):
            return False
        return any(
            isinstance(message, dict)
            and (
                message.get("wait_for_answer") is True
                or message.get("waitForAnswer") is True
                or self._has_buttons(message.get("buttons"))
            )
            for message in messages
        )

    @staticmethod
    def _has_buttons(value: Any) -> bool:
        return isinstance(value, list) and any(
            isinstance(button, (dict, str)) for button in value
        )

    @staticmethod
    def _normalize_kind(value: str) -> str:
        return value.strip().lower().replace("-", "_")

    @staticmethod
    def _string_value(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()
