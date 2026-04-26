from __future__ import annotations

from typing import Any

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - 运行环境未安装时使用兜底顺序执行
    END = "__end__"
    START = "__start__"
    StateGraph = None


def compile_graph(
    *,
    state_schema: type,
    nodes: list[tuple[str, Any]],
    edges: list[tuple[str, str]],
    input_schema: type | None = None,
    output_schema: type | None = None,
    name: str | None = None,
):
    if StateGraph is None:
        return None
    graph = StateGraph(
        state_schema,
        input_schema=input_schema or state_schema,
        output_schema=output_schema or state_schema,
    )
    for name, node in nodes:
        graph.add_node(name, node)
    for source, target in edges:
        graph.add_edge(source, target)
    graph.add_edge(START, nodes[0][0])
    graph.add_edge(nodes[-1][0], END)
    return graph.compile(name=name)
