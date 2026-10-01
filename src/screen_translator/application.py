from __future__ import annotations

import argparse
import copy
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time

from . import __version__
from .paths import data_root, install_root, model_root


def configure_logging() -> None:
    root = data_root() / "logs"
    root.mkdir(exist_ok=True)
    handler = RotatingFileHandler(root / "application.log", maxBytes=1_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


def check_models() -> list[str]:
    root = model_root()
    needed = ["ocr/det.onnx", "ocr/rec.onnx", "ocr/keys.txt"]
    for direction in ("zh-en", "en-zh"):
        needed.extend(f"translation/{direction}-int8/{name}" for name in
                      ("model.bin", "config.json", "source.spm", "target.spm", "vocab.json"))
    return [name for name in needed if not (root / name).is_file() or (root / name).stat().st_size == 0]


def set_auto_start(enabled: bool) -> None:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                command = f'"{sys.executable}"'
            else:
                command = f'"{sys.executable}" "{install_root() / "launcher.py"}"'
            winreg.SetValueEx(key, "ScreenTranslator", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "ScreenTranslator")
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows offline screen translator")
    parser.add_argument("--self-test", action="store_true", help="Run synthetic offline OCR/translation diagnostics")
    parser.add_argument("--smoke-test", action="store_true", help="Initialize desktop integration, then exit")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ["SCREEN_TRANSLATOR_DATA"] = str(args.data_dir.resolve())
    if sys.platform != "win32":
        print("This application supports Windows only.", file=sys.stderr)
        return 2
    # Windowed frozen executables have no standard streams. Some native runtimes
    # and their logging handlers still expect file-like objects.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    configure_logging()
    from .platform.windows.dpi import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QObject, Signal, QTimer
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ScreenTranslator")
    app.setApplicationDisplayName("本地屏幕翻译器")
    app.setOrganizationName("ScreenTranslator")
    app.setQuitOnLastWindowClosed(False)
    if args.self_test:
        from .diagnostics import run_self_test
        report = run_self_test()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    from .platform.windows.single_instance import SingleInstance
    from .platform.windows.hotkeys import WindowsHotkeys
    from .platform.windows.monitors import validate_region
    from .ui.main import MainUI
    from .storage.settings import SettingsStore
    from .storage.translation_cache import TranslationCache
    from .inference.ocr.rapidocr_engine import RapidOCREngine
    from .inference.translation.ctranslate2_engine import CTranslate2Engine
    from .core.pipeline import Pipeline

    guard = SingleInstance("ScreenTranslator-0.1" if not args.smoke_test else "ScreenTranslator-smoke")
    if not guard.acquired:
        QMessageBox.information(None, "本地屏幕翻译器", "程序已经在运行，请通过右下角托盘图标操作。")
        guard.close()
        return 0
    store = SettingsStore()
    settings = store.load()
    ui = MainUI(settings)
    hotkeys = WindowsHotkeys()
    hotkey_errors: list[str] = []

    class Bridge(QObject):
        result = Signal(object)
        status = Signal(str)

    bridge = Bridge()
    cache = TranslationCache()
    cache.set_persistence(settings.cache_enabled)
    pipeline = Pipeline(settings, RapidOCREngine(cpu_threads=settings.cpu_threads),
                        CTranslate2Engine(cpu_threads=settings.cpu_threads), cache,
                        bridge.result.emit, bridge.status.emit)
    hidden = False
    has_caption = False
    resume_after_selection = False
    shutting_down = False

    def status(message: str) -> None:
        ui.set_status(message, pipeline.is_running)

    def worker_status(message: str) -> None:
        status(message)
        hotkeys.set_monitoring(pipeline.is_running or has_caption)

    bridge.status.connect(worker_status)

    def receive_result(result: object) -> None:
        nonlocal has_caption
        if result.generation != pipeline.generation:
            return
        has_caption = bool(result.translation)
        if result.translation:
            ui.show_result(result)
        else:
            ui.clear_result()
        ui.set_hidden(hidden)
        hotkeys.set_monitoring(pipeline.is_running or has_caption)

    bridge.result.connect(receive_result)

    def toggle() -> None:
        nonlocal hidden, resume_after_selection
        if pipeline.is_running:
            pipeline.stop()
            hotkeys.set_monitoring(has_caption)
            status("已停止；当前字幕保留，Alt+C 可清空")
            return
        missing = check_models()
        if missing:
            status("离线模型不完整，暂时无法开启翻译")
            QMessageBox.warning(None, "缺少离线模型", "模型文件缺失，请重新解压完整发布包。\n\n" + "\n".join(missing[:5]))
            return
        if not settings.region or not validate_region(settings.region):
            resume_after_selection = True
            ui.select_region()
            return
        hidden = False
        ui.set_hidden(False)
        pipeline.start(settings.region)
        hotkeys.set_monitoring(True)
        status("监控中；首次翻译正在加载本地模型")

    def selection_started() -> None:
        nonlocal resume_after_selection
        resume_after_selection = resume_after_selection or pipeline.is_running
        pipeline.stop()
        hotkeys.set_monitoring(False)
        hotkeys.set_selecting(True)
        ui.set_hidden(True)
        status("拖动鼠标框选文字区域；Esc 取消")

    def selection_finished(region: object) -> None:
        nonlocal resume_after_selection, hidden, has_caption
        settings.region = region
        # Selecting a new region returns the overlay to its safe automatic position.
        settings.overlay_position = None
        store.save(settings)
        ui.update_settings(settings)
        hotkeys.set_selecting(False)
        ui.clear_result()
        has_caption = False
        hidden = False
        ui.set_hidden(False)
        status(f"区域已保存：{region.width} × {region.height}；Alt+T 开启翻译")
        resume = resume_after_selection
        resume_after_selection = False
        if resume:
            toggle()

    def selection_cancelled() -> None:
        nonlocal resume_after_selection
        hotkeys.set_selecting(False)
        ui.set_hidden(hidden)
        hotkeys.set_monitoring(pipeline.is_running or has_caption)
        resume = resume_after_selection
        resume_after_selection = False
        status("已取消框选，保留原区域")
        if resume and settings.region and validate_region(settings.region):
            pipeline.start(settings.region)
            hotkeys.set_monitoring(True)
            ui.set_hidden(hidden)
            status("已恢复原区域监控" + ("；字幕保持隐藏" if hidden else ""))

    def clear() -> None:
        nonlocal has_caption
        pipeline.clear()
        has_caption = False
        ui.clear_result()
        hotkeys.set_monitoring(pipeline.is_running)
        status("字幕已清空；文字变化后显示新译文" if pipeline.is_running else "字幕已清空")

    def hide() -> None:
        nonlocal hidden
        hidden = not hidden
        ui.set_hidden(hidden)
        status(("字幕已隐藏；Esc 恢复" + ("，监控继续" if pipeline.is_running else ""))
               if hidden else "字幕已恢复")

    def apply_settings(updated: object) -> None:
        nonlocal settings
        old = copy.deepcopy(settings)
        settings = updated
        try:
            if old.auto_start != settings.auto_start:
                set_auto_start(settings.auto_start)
        except OSError:
            settings.auto_start = old.auto_start
            logging.exception("Could not change auto-start")
            QMessageBox.warning(None, "设置未生效", "开机启动设置未能写入，其他设置已保存。")
        store.save(settings)
        pipeline.update_settings(settings)
        ui.update_settings(settings)
        hotkeys.update(settings)
        hotkeys.set_monitoring(pipeline.is_running or has_caption)
        status("设置已保存")

    def quit_app() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        monitor_timer.stop()
        hotkeys.close()
        pipeline.shutdown(timeout=3.0)
        cache.close()
        ui.close()
        guard.close()
        app.quit()

    def validate_current_region() -> None:
        nonlocal has_caption
        if pipeline.is_running and settings.region and not validate_region(settings.region):
            pipeline.stop()
            hotkeys.set_monitoring(False)
            ui.clear_result()
            has_caption = False
            status(f"显示器布局已变化，请按 {settings.hotkeys['select']} 重新框选")

    ui.selection_started.connect(selection_started)
    ui.selection_cancelled.connect(selection_cancelled)
    ui.region_selected.connect(selection_finished)
    ui.toggle_requested.connect(toggle)
    ui.clear_requested.connect(clear)
    ui.hide_requested.connect(hide)
    ui.quit_requested.connect(quit_app)
    ui.settings_changed.connect(apply_settings)
    actions = {"select": ui.select_region, "toggle": toggle, "clear": clear, "hide": hide}
    hotkeys.action.connect(lambda action: actions.get(action, lambda: None)())
    def hotkey_error(message: str) -> None:
        hotkey_errors.append(message)
        status(message)
        ui.notify("快捷键未生效", message, warning=True)

    hotkeys.error.connect(hotkey_error)

    def effective_binding_changed(action: str, effective_key: str) -> None:
        settings.hotkeys[action] = effective_key
        store.save(settings)
        ui.update_settings(settings)
        ui.notify("框选快捷键已调整", f"Alt+R 已被占用，已为本程序改用 {effective_key}。可在设置中修改。")

    hotkeys.binding_changed.connect(effective_binding_changed)
    hotkeys.start(settings)
    monitor_timer = QTimer()
    monitor_timer.setInterval(2500)
    monitor_timer.timeout.connect(validate_current_region)
    monitor_timer.start()
    status(f"已就绪：{settings.hotkeys['select']} 框选，"
           f"{settings.hotkeys['toggle']} 开始/停止，{settings.hotkeys['clear']} 清空")

    def exception_hook(kind: type, value: BaseException, tb: object) -> None:
        logging.getLogger(__name__).error("Unhandled error", exc_info=(kind, value, tb))
        status("发生错误，请通过托盘退出并重新打开；详情见诊断日志")

    sys.excepthook = exception_hook
    smoke_passed = True
    if args.smoke_test:
        missing = check_models()
        region_valid = settings.region is None or validate_region(settings.region)
        smoke_passed = not missing and region_valid and not hotkey_errors
        report = {"passed": smoke_passed, "version": __version__, "models_missing": missing,
                  "region_valid": region_valid, "hotkey_errors": hotkey_errors,
                  "effective_hotkeys": hotkeys.effective_hotkeys,
                  "interactive_selection_tested": False}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        QTimer.singleShot(1000, quit_app)
    exit_code = app.exec()
    quit_app()
    return exit_code if smoke_passed else 1

