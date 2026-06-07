from __future__ import annotations

import os
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

_weave = None


DEFAULT_WEAVE_PROJECT = "Agentic-Civilization-Persona-Generator"


@dataclass
class WeaveState:
    initialized: bool = False
    project_name: str | None = None


_STATE = WeaveState()


class _NoopWeave:
    @staticmethod
    def op(*args, **kwargs):
        def decorator(func):
            return func

        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]
        return decorator


weave = _NoopWeave()


def traceable_op(*decorator_args, **decorator_kwargs):
    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        traced_func: Callable[..., Any] | None = None

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal traced_func
            if _STATE.initialized:
                global _weave, weave
                if _weave is None:
                    try:
                        import weave as imported_weave
                    except ImportError:
                        return func(*args, **kwargs)
                    _weave = imported_weave
                    weave = _weave
                if traced_func is None:
                    traced_func = _weave.op(*decorator_args, **decorator_kwargs)(func)
                return traced_func(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    if decorator_args and callable(decorator_args[0]) and len(decorator_args) == 1 and not decorator_kwargs:
        return decorate(decorator_args[0])
    return decorate


def init_weave(project_name: str | None = None) -> bool:
    resolved = (
        project_name
        or os.getenv("WEAVE_PROJECT")
        or os.getenv("WEAVE_PROJECT_NAME")
        or os.getenv("WANDB_PROJECT")
        or ""
    ).strip()
    if not resolved:
        return False

    if _STATE.initialized and _STATE.project_name == resolved:
        return True

    global _weave, weave
    api_key = os.getenv("WEAVE_API_KEY") or os.getenv("WANDB_API_KEY")
    if api_key:
        os.environ.setdefault("WANDB_API_KEY", api_key)
    if _weave is None:
        try:
            import weave as imported_weave
        except ImportError:
            return False
        _weave = imported_weave
        weave = _weave

    try:
        _weave.init(resolved)
    except Exception:
        return False
    _STATE.initialized = True
    _STATE.project_name = resolved
    return True


def recommended_project_name() -> str:
    return (
        os.getenv("WEAVE_PROJECT")
        or os.getenv("WEAVE_PROJECT_NAME")
        or os.getenv("WANDB_PROJECT")
        or DEFAULT_WEAVE_PROJECT
    )
