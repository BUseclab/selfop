"""Task registry — maps task names to Task subclasses."""

from __future__ import annotations

from tasks.base import Task

_REGISTRY: dict[str, type] = {}


def _ensure_registry() -> None:
    if _REGISTRY:
        return
    from tasks.cybergym import CyberGymTask
    _REGISTRY["cybergym"] = CyberGymTask


def get_task(name: str, **kwargs) -> Task:
    """Instantiate a task by name, forwarding kwargs to the constructor."""
    _ensure_registry()
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown task {name!r}; available: {sorted(_REGISTRY)}"
        ) from exc
    return cls(**kwargs)
