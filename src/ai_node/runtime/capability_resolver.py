import json
from pathlib import Path

from ai_node.providers.model_feature_schema import create_default_feature_flags


DEFAULT_TASK_GRAPH_PATH = "capabilities/task_graph.json"


def load_task_graph(*, path: str = DEFAULT_TASK_GRAPH_PATH) -> dict:
    graph_path = Path(path)
    if not graph_path.exists():
        raise ValueError(f"task_graph_missing:{path}")
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("task_graph_invalid")
    tasks = payload.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("task_graph_tasks_invalid")
    return payload


def build_feature_union(*, model_feature_entries: list[dict], enabled_models: list[str] | None = None) -> dict[str, bool]:
    feature_union = create_default_feature_flags()
    enabled_set = {
        str(model_id or "").strip().lower()
        for model_id in (enabled_models or [])
        if str(model_id or "").strip()
    }
    for entry in model_feature_entries:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("model_id") or "").strip().lower()
        if enabled_set and model_id not in enabled_set:
            continue
        features = entry.get("features")
        if not isinstance(features, dict):
            continue
        for feature_name, value in features.items():
            key = str(feature_name or "").strip()
            if key in feature_union and bool(value):
                feature_union[key] = True
    return feature_union


def resolve_task_capabilities(*, feature_union: dict[str, bool], task_graph: dict) -> list[str]:
    tasks = task_graph.get("tasks") if isinstance(task_graph, dict) else None
    if not isinstance(tasks, dict):
        raise ValueError("task_graph_tasks_invalid")
    resolved: list[str] = []
    for task_name, rule in tasks.items():
        if not isinstance(rule, dict):
            continue
        all_of = _normalize_feature_list(rule.get("all_of"))
        any_of = _normalize_feature_list(rule.get("any_of"))
        none_of = _normalize_feature_list(rule.get("none_of"))

        all_of_ok = all(feature_union.get(feature, False) for feature in all_of) if all_of else True
        any_of_ok = any(feature_union.get(feature, False) for feature in any_of) if any_of else True
        none_of_ok = all(not feature_union.get(feature, False) for feature in none_of) if none_of else True
        if all_of_ok and any_of_ok and none_of_ok:
            resolved.append(str(task_name).strip())
    return sorted({task for task in resolved if task})


def resolve_node_capabilities(
    *,
    enabled_models: list[str],
    model_feature_catalog: dict,
    task_graph: dict,
) -> dict:
    entries = model_feature_catalog.get("entries") if isinstance(model_feature_catalog, dict) else []
    feature_union = build_feature_union(
        model_feature_entries=entries if isinstance(entries, list) else [],
        enabled_models=enabled_models,
    )
    resolved_tasks = resolve_task_capabilities(feature_union=feature_union, task_graph=task_graph)
    return {
        "schema_version": "1.0",
        "capability_graph_version": str(task_graph.get("capability_graph_version") or "1.0"),
        "enabled_models": sorted(
            {
                str(model_id or "").strip().lower()
                for model_id in enabled_models
                if str(model_id or "").strip()
            }
        ),
        "feature_union": feature_union,
        "resolved_tasks": resolved_tasks,
    }


def _normalize_feature_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]
