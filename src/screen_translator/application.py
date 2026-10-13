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
from collections.abc import Mapping

from . import __version__
from .paths import data_root, install_root, model_root


def hotkey_status(message: str, configured: Mapping[str, str],
                  effective: Mapping[str, str]) -> str:
    """Keep registration failures visible after later ready/saved/worker statuses."""
    labels = {"select": "框选", "toggle": "启停", "clear": "清空"}
    unavailable = [f"{label}({configured.get(action, '')})"
                   for action, label in labels.items() if action not in effective]
    if unavailable:
        return "快捷键不可用：" + "、".join(unavailable) + "；可从托盘操作 | " + message
    return message


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
                command = f'"{sys.executable}" --background'
            else:
                command = f'"{sys.executable}" "{install_root() / "launcher.py"}" --background'
            winreg.SetValueEx(key, "ScreenTranslator", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "ScreenTranslator")
            except FileNotFoundError:
                pass


def show_startup_card(settings: object, *, background: bool = False,
                      diagnostic: bool = False, suppress_once: bool = False,
                      hotkeys_ready: bool = True) -> object | None:
    """Optional decoration only: no timers are awaited and inference stays lazy."""
    from .core.startup_policy import startup_presentation
    preliminary = startup_presentation(enabled=settings.startup_animation,
        background=background, diagnostic=diagnostic, suppress_once=suppress_once,
        hotkeys_ready=hotkeys_ready)
    if not preliminary.show:
        return None
    card = None
    try:
        from .platform.windows.startup_environment import query_startup_environment
        environment = query_startup_environment()
        presentation = startup_presentation(enabled=settings.startup_animation,
            foreground_covers_monitor=environment.foreground_covers_monitor,
            animations_enabled=environment.animations_enabled, hotkeys_ready=hotkeys_ready)
        if not presentation.show:
            return None
        from .ui.startup_card import StartupCard
        card = StartupCard(status=presentation.status,
                           animations_enabled=presentation.animate)
        card.start()
        return card
    except Exception:
        logging.exception("Optional startup presentation unavailable; continuing to tray")
        if card is not None:
            try:
                card.finish_now()
            except Exception:
                logging.exception("Could not close optional startup presentation")
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows offline screen translator")
    parser.add_argument("--self-test", action="store_true", help="Run synthetic offline OCR/translation diagnostics")
    parser.add_argument("--smoke-test", action="store_true", help="Initialize desktop integration, then exit")
    parser.add_argument("--capture-test", action="store_true", help="Check the saved region using local capture/OCR/translation; do not save images or text")
    parser.add_argument("--startup-self-test", action="store_true",
                        help="Check startup-card painting/lifecycle without screen capture or hotkeys; use QT_QPA_PLATFORM=offscreen for headless diagnostics")
    parser.add_argument("--capture-samples", type=int, default=3)
    parser.add_argument("--capture-delay", type=float, default=3.0,
                        help="Wait 0-10 seconds before capture, so the game can be foreground")
    parser.add_argument("--accept-runtime-terms", action="store_true",
                        help="Explicitly accept the shipped Microsoft runtime terms for an authorized diagnostic run; requires a diagnostic mode")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--background", action="store_true",
                        help="Start directly in the tray without startup presentation")
    parser.add_argument("--no-startup-animation", action="store_true",
                        help="Suppress startup presentation for this launch only")
    args = parser.parse_args(argv)
    if sum((args.self_test, args.smoke_test, args.capture_test, args.startup_self_test)) > 1:
        parser.error("Choose only one diagnostic mode")
    if args.capture_test and (not args.report or not 1 <= args.capture_samples <= 5
                             or not 0 <= args.capture_delay <= 10):
        parser.error("--capture-test requires --report, 1-5 samples and a 0-10 second delay")
    if args.accept_runtime_terms and not (args.self_test or args.smoke_test or args.capture_test or args.startup_self_test):
        parser.error("--accept-runtime-terms requires a diagnostic mode; normal first use requires the consent dialog")
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
    from .storage.settings import SettingsStore
    from .runtime_terms import authorize_runtime_terms
    store = SettingsStore()
    settings = store.load()
    diagnostic = args.self_test or args.smoke_test or args.capture_test or args.startup_self_test
    consent = None
    if diagnostic:
        # Automated tests do not implicitly accept legal terms and do not open a
        # blocking first-run dialog. A deliberate flag or matching saved choice
        # is required before any desktop integration or inference is initialized.
        consent = authorize_runtime_terms(settings, store, explicit_accept=args.accept_runtime_terms)
        if not consent.accepted:
            report = {"passed": False, "failure": "runtime_terms_" + consent.failure,
                      "detail": consent.error, "required_runtime_terms_version": consent.version}
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 3
    from .platform.windows.dpi import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QObject, Signal, QTimer
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ScreenTranslator")
    app.setApplicationDisplayName("本地屏幕翻译器")
    app.setOrganizationName("ScreenTranslator")
    app.setQuitOnLastWindowClosed(False)
    from .ui.fonts import register_chinese_fallback
    try:
        register_chinese_fallback(app)
    except RuntimeError as exc:
        logging.error("Application font initialization failed: %s", exc)
        if diagnostic:
            report = {"passed": False, "failure": "display_font", "detail": str(exc)}
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            QMessageBox.critical(None, "ScreenTranslator could not start", str(exc))
        return 4
    if not diagnostic:
        from .ui.runtime_terms_dialog import prompt_runtime_terms
        consent = authorize_runtime_terms(settings, store, prompt=prompt_runtime_terms)
        if not consent.accepted:
            if consent.failure != "declined":
                QMessageBox.critical(None, "程序未启动", consent.error)
            return 3
    if args.self_test:
        from .diagnostics import run_self_test
        report = run_self_test()
        report.update(runtime_terms_version=consent.version,
                      runtime_terms_acceptance=consent.acceptance)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    if args.startup_self_test:
        from .ui.startup_diagnostics import run_startup_self_test
        report = run_startup_self_test()
        report.update(version=__version__, runtime_terms_version=consent.version,
                      runtime_terms_acceptance=consent.acceptance)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    if args.capture_test:
        from .capture_diagnostics import run_capture_test
        from .diagnostics import no_network
        from .platform.windows.monitors import validate_region
        if not settings.region or not validate_region(settings.region):
            report = {"completed": False, "failure_codes": ["saved_region_missing_or_invalid"],
                      "overlay_display_tested": False, "game_compatibility_tested": False}
        else:
            with no_network() as attempts:
                report = run_capture_test(settings, samples=args.capture_samples,
                                          delay=args.capture_delay)
            report["network_attempt_count"] = len(attempts)
            if attempts:
                report["completed"] = False
                report["failure_codes"].append("network_attempt_blocked")
        report["version"] = __version__
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["completed"] else 1

    from .platform.windows.single_instance import SingleInstance
    from .platform.windows.hotkeys import WindowsHotkeys
    from .platform.windows.monitors import region_availability, validate_region
    from .ui.main import MainUI
    from .ui.settings_window import merge_settings_changes
    from .storage.translation_cache import TranslationCache
    from .inference.ocr.rapidocr_engine import RapidOCREngine
    from .inference.translation.ctranslate2_engine import CTranslate2Engine
    from .core.pipeline import Pipeline

    guard = SingleInstance("ScreenTranslator-0.1" if not args.smoke_test else "ScreenTranslator-smoke")
    if not guard.acquired:
        QMessageBox.information(None, "本地屏幕翻译器", "程序已经在运行，请通过右下角托盘图标操作。")
        guard.close()
        return 0
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
    startup_card = None

    def allow_startup_settings() -> bool:
        if shutting_down or ui.is_closed or pipeline.is_running:
            return False
        from .platform.windows.startup_environment import query_startup_environment
        return not query_startup_environment().foreground_covers_monitor

    from .core.startup_flow import StartupSettingsFlow
    startup_flow = StartupSettingsFlow(schedule=lambda callback: QTimer.singleShot(0, callback),
        open_settings=ui.open_settings, allow_open=allow_startup_settings)

    def dismiss_startup_card(*unused: object) -> None:
        nonlocal startup_card
        startup_flow.cancel()
        card, startup_card = startup_card, None
        if card is not None:
            card.finish_now()

    def release_startup_card() -> None:
        nonlocal startup_card
        startup_card = None

    def status(message: str) -> None:
        ui.set_status(hotkey_status(message, settings.hotkeys, hotkeys.effective_hotkeys),
                      pipeline.is_running)

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
        dismiss_startup_card()
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
        dismiss_startup_card()
        resume_after_selection = resume_after_selection or pipeline.is_running
        pipeline.stop()
        hotkeys.set_monitoring(False)
        hotkeys.set_selecting(True)
        ui.set_hidden(True)
        status("拖动鼠标框选文字区域；Esc 取消")

    def selection_finished(region: object) -> None:
        nonlocal resume_after_selection, hidden, has_caption
        # Selection windows are already gone. Always release Escape suppression,
        # including when persistence fails on a full/read-only user data disk.
        hotkeys.set_selecting(False)
        settings.region = region
        # Selecting a new region returns the overlay to its safe automatic position.
        settings.overlay_position = None
        saved = True
        try:
            store.save(settings)
        except OSError:
            saved = False
            logging.exception("Could not persist selected region")
            ui.notify("区域未能保存", "选区本次可以使用，但下次启动需要重新框选。请检查磁盘空间和用户数据目录权限。", warning=True)
        ui.update_settings(settings)
        ui.clear_result()
        has_caption = False
        hidden = False
        ui.set_hidden(False)
        status(f"区域{'已保存' if saved else '仅本次生效'}：{region.width} × {region.height}；{settings.hotkeys['toggle']} 开启翻译")
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
        dismiss_startup_card()
        pipeline.clear()
        has_caption = False
        ui.clear_result()
        hotkeys.set_monitoring(pipeline.is_running)
        status("字幕已清空；文字变化后显示新译文" if pipeline.is_running else "字幕已清空")

    def hide() -> None:
        nonlocal hidden
        dismiss_startup_card()
        hidden = not hidden
        ui.set_hidden(hidden)
        status(("字幕已隐藏；Esc 恢复" + ("，监控继续" if pipeline.is_running else ""))
               if hidden else "字幕已恢复")

    def apply_settings(updated: object) -> None:
        nonlocal settings
        old = copy.deepcopy(settings)
        try:
            candidate = merge_settings_changes(settings, updated)
        except (ValueError, TypeError, OverflowError):
            QMessageBox.warning(None, "设置未保存", "设置更新格式无效，请重新打开设置窗口。")
            return
        try:
            if old.auto_start != candidate.auto_start:
                set_auto_start(candidate.auto_start)
        except OSError:
            candidate.auto_start = old.auto_start
            logging.exception("Could not change auto-start")
            QMessageBox.warning(None, "开机启动未更改", "开机启动设置未能写入，该项保持原值。")
        try:
            store.save(candidate)
        except OSError:
            logging.exception("Could not save settings")
            if old.auto_start != candidate.auto_start:
                try:
                    set_auto_start(old.auto_start)
                except OSError:
                    logging.exception("Could not restore auto-start after settings save failure")
            QMessageBox.warning(None, "设置未保存", "无法写入用户设置，请检查磁盘空间和用户数据目录权限。原设置仍在使用。")
            return
        settings = candidate
        pipeline.update_settings(settings)
        ui.update_settings(settings)
        hotkey_errors.clear()
        hotkeys.update(settings)
        ui.set_effective_hotkeys(hotkeys.effective_hotkeys)
        hotkeys.set_monitoring(pipeline.is_running or has_caption)
        status("设置已保存")

    def quit_app() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        dismiss_startup_card()
        monitor_timer.stop()
        hotkeys.close()
        pipeline.shutdown(timeout=3.0)
        cache.close()
        ui.close()
        guard.close()
        app.quit()

    def validate_current_region() -> None:
        nonlocal has_caption
        # A sleeping/locked desktop may temporarily have no readable monitor
        # snapshot. Only a confirmed invalid region cancels the user's intent;
        # the capture worker owns cancellable low-frequency recovery otherwise.
        if (pipeline.is_running and settings.region
                and region_availability(settings.region) is False):
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
    ui.settings_opening.connect(dismiss_startup_card)
    ui.menu.aboutToShow.connect(dismiss_startup_card)
    ui.tray.activated.connect(dismiss_startup_card)
    actions = {"select": ui.select_region, "toggle": toggle, "clear": clear, "hide": hide}
    hotkeys.action.connect(lambda action: actions.get(action, lambda: None)())
    def hotkey_error(message: str) -> None:
        hotkey_errors.append(message)
        status(message)
        ui.notify("快捷键未生效", message, warning=True)

    hotkeys.error.connect(hotkey_error)

    def effective_binding_changed(action: str, effective_key: str) -> None:
        settings.hotkeys[action] = effective_key
        try:
            store.save(settings)
        except OSError:
            logging.exception("Could not persist effective hotkey")
            ui.notify("快捷键调整未能保存", "本次已启用备用快捷键，但无法写入设置；下次启动会重新检测。", warning=True)
        ui.update_settings(settings)
        ui.notify("框选快捷键已调整", f"Alt+R 已被占用，已为本程序改用 {effective_key}。可在设置中修改。")

    hotkeys.binding_changed.connect(effective_binding_changed)
    hotkeys.start(settings)
    ui.set_effective_hotkeys(hotkeys.effective_hotkeys)
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
    startup_card = show_startup_card(settings, background=args.background,
        diagnostic=diagnostic, suppress_once=args.no_startup_animation,
        hotkeys_ready=all(key in hotkeys.effective_hotkeys for key in settings.hotkeys))
    if startup_card is not None:
        # Avoid keeping the deleted QWidget wrapper alive for the tray lifetime.
        startup_flow.arm()
        startup_card.finished.connect(release_startup_card)
        startup_card.completed.connect(startup_flow.completed)
    smoke_passed = True
    if args.smoke_test:
        missing = check_models()
        region_valid = settings.region is None or validate_region(settings.region)
        smoke_passed = not missing and region_valid and not hotkey_errors
        report = {"passed": smoke_passed, "version": __version__, "models_missing": missing,
                  "region_valid": region_valid, "hotkey_errors": hotkey_errors,
                  "effective_hotkeys": hotkeys.effective_hotkeys,
                  "interactive_selection_tested": False,
                  "runtime_terms_version": consent.version,
                  "runtime_terms_acceptance": consent.acceptance}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        QTimer.singleShot(1000, quit_app)
    exit_code = app.exec()
    quit_app()
    return exit_code if smoke_passed else 1

