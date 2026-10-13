"""Presentation-only decisions; never delay startup or initialize inference."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartupPresentation:
    show: bool
    animate: bool
    status: str


def startup_presentation(*, enabled: bool, background: bool = False,
                         diagnostic: bool = False, suppress_once: bool = False,
                         foreground_covers_monitor: bool = False,
                         animations_enabled: bool = True,
                         hotkeys_ready: bool = True) -> StartupPresentation:
    status = ("快捷键已就绪 · 程序已驻留托盘" if hotkeys_ready
              else "程序已驻留托盘 · 部分快捷键不可用")
    show = (enabled is True and not background and not diagnostic
            and not suppress_once and not foreground_covers_monitor)
    return StartupPresentation(show, show and animations_enabled, status)
