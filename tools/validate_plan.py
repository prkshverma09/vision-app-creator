"""Validate the canonical task table, and only that table."""
import re, sys
from pathlib import Path
EXPECTED_COUNT = 42

def parse(path: Path) -> dict[str, list[str]]:
    text = path.read_text(); section = text.split("### 3.1 Task table", 1)[1].split("### 3.2", 1)[0]
    graph = {}
    for line in section.splitlines():
        match = re.match(r"\| ([A-Z][0-9]{2}) \|.*?\| ([^|]+) \|", line)
        if match:
            task, raw = match.groups(); graph[task] = [] if raw.strip() == "—" else [x.strip() for x in raw.split(",")]
    return graph

def validate(graph: dict[str, list[str]]) -> list[str]:
    errors=[]
    if len(graph) != EXPECTED_COUNT: errors.append(f"expected {EXPECTED_COUNT} tasks, found {len(graph)}")
    for task, deps in graph.items():
        for dep in deps:
            if dep not in graph: errors.append(f"{task}: unknown dependency {dep}")
    visiting:set[str]=set(); visited:set[str]=set()
    def visit(node: str) -> None:
        if node in visiting: errors.append(f"cycle at {node}"); return
        if node in visited: return
        visiting.add(node)
        for dep in graph.get(node, []): visit(dep)
        visiting.remove(node); visited.add(node)
    for node in graph: visit(node)
    return errors

def main() -> int:
    path=Path(__file__).resolve().parents[1]/"IMPLEMENTATION_PLAN.md"; graph=parse(path); errors=validate(graph)
    if errors: print("\n".join(errors), file=sys.stderr); return 1
    print(f"validated {len(graph)} task IDs and dependency graph"); return 0
if __name__ == "__main__": raise SystemExit(main())
