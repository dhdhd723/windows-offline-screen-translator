from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int
    monitor_id: str = ""
    monitor_bounds: tuple[int, int, int, int] | None = None

    def valid(self) -> bool:
        return self.width >= 12 and self.height >= 12

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Region:
        bounds = data.get("monitor_bounds")
        return cls(int(data["x"]), int(data["y"]), int(data["width"]),
                   int(data["height"]), str(data.get("monitor_id", "")),
                   tuple(int(v) for v in bounds) if bounds else None)


@dataclass
class Settings:
    schema_version: int = 1
    region: Region | None = None
    direction: str = "auto"
    capture_fps: float = 6.0
    idle_fps: float = 2.0
    debounce_ms: int = 180
    min_ocr_interval_ms: int = 450
    cpu_threads: int = 2
    font_size: int = 22
    opacity: float = 0.80
    show_source: bool = False
    esc_enabled: bool = True
    hotkeys: dict[str, str] = field(default_factory=lambda: {
        "select": "Alt+R", "toggle": "Alt+T", "clear": "Alt+C"
    })
    overlay_position: tuple[int, int] | None = None
    cache_enabled: bool = False
    auto_start: bool = False
    runtime_terms_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        allowed = cls.__dataclass_fields__
        values = {k: v for k, v in data.items() if k in allowed}
        if values.get("region"):
            values["region"] = Region.from_dict(values["region"])
        if values.get("overlay_position"):
            values["overlay_position"] = tuple(values["overlay_position"])
        obj = cls(**values)
        if obj.direction not in {"auto", "zh-en", "en-zh"}:
            obj.direction = "auto"
        obj.capture_fps = max(1.0, min(12.0, float(obj.capture_fps)))
        obj.idle_fps = max(0.5, min(obj.capture_fps, float(obj.idle_fps)))
        obj.debounce_ms = max(80, min(1000, int(obj.debounce_ms)))
        obj.min_ocr_interval_ms = max(200, min(3000, int(obj.min_ocr_interval_ms)))
        obj.cpu_threads = max(1, min(4, int(obj.cpu_threads)))
        obj.font_size = max(12, min(48, int(obj.font_size)))
        obj.opacity = max(0.25, min(1.0, float(obj.opacity)))
        return obj


@dataclass(frozen=True)
class TextLine:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class OCRResult:
    text: str
    lines: tuple[TextLine, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class TranslationResult:
    source: str
    translation: str
    direction: str
    generation: int
    elapsed_ms: float = 0.0
    cache_hit: bool = False

