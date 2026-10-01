"""Threaded capture/inference coordination, independent of Qt."""

__all__ = ["Pipeline"]


def __getattr__(name: str):
    if name == "Pipeline":
        from .pipeline import Pipeline
        return Pipeline
    raise AttributeError(name)
