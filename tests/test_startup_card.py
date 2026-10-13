"""Own-widget offscreen checks: no desktop input, capture or model loading."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QElapsedTimer, QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from screen_translator.ui.startup_card import PRESENTATION_MS, StartupCard, card_geometry


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def _paint(card, progress):
    card.set_progress(progress)
    image = QImage(card.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    card.render(painter, QPoint())
    painter.end()
    return bytes(image.bits())


def test_card_is_non_focusable_non_topmost_mouse_passthrough(qapp):
    card = StartupCard()
    flags = card.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowType.WindowTransparentForInput
    assert not flags & Qt.WindowType.WindowStaysOnTopHint
    assert card.focusPolicy() == Qt.FocusPolicy.NoFocus
    for attribute in (Qt.WidgetAttribute.WA_TranslucentBackground,
                      Qt.WidgetAttribute.WA_ShowWithoutActivating,
                      Qt.WidgetAttribute.WA_TransparentForMouseEvents):
        assert card.testAttribute(attribute)
    assert not card.isVisible()
    card.finish_now()


def test_animation_changes_paint_and_progress_is_clamped(qapp):
    card = StartupCard()
    assert _paint(card, 0.25) != _paint(card, 0.65)
    card.progress = -1.0
    assert card.get_progress() == 0.0
    card.set_progress(4.0)
    assert card.progress == 1.0
    card.set_progress(float("nan"))
    assert card.progress == 0.0
    assert card.windowOpacity() == 1.0
    card.finish_now()


def test_reduced_motion_paint_remains_static(qapp):
    card = StartupCard(animations_enabled=False)
    assert _paint(card, 0.25) == _paint(card, 0.65)
    card.start()
    assert card._animation.state() == QAbstractAnimation.State.Stopped
    assert card._watchdog.isActive()
    assert card._watchdog.isSingleShot()
    assert card._watchdog.timerType() == Qt.TimerType.PreciseTimer
    assert card._watchdog.parent() is card
    card.finish_now()


def test_start_is_nonblocking_and_only_once(qapp):
    card = StartupCard()
    card.start()
    assert card.isVisible()
    assert card._animation.state() == QAbstractAnimation.State.Running
    card._animation.setCurrentTime(350)
    before = card._animation.currentTime()
    card.start()
    assert card._animation.currentTime() == before
    assert card.findChildren(QTimer) == [card._watchdog]
    card.finish_now()


def test_finish_is_reentrant_and_queues_widget_deletion(qapp):
    card = StartupCard()
    events = []

    def on_finished():
        assert card._finished
        assert not card._watchdog.isActive()
        assert card._animation.state() == QAbstractAnimation.State.Stopped
        assert not card.isVisible()
        events.append("finished")
        card.finish_now()

    card.finished.connect(on_finished)
    card.completed.connect(lambda: events.append("completed"))
    card.start()
    card.finish_now()
    card.finish_now()
    card.start()
    assert events == ["finished"]
    assert not card.isVisible()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(card)


@pytest.mark.parametrize("animated", [True, False])
def test_card_expires_after_single_two_second_presentation(qapp, animated):
    card = StartupCard(animations_enabled=animated)
    events = []
    elapsed = QElapsedTimer()
    elapsed.start()
    card.finished.connect(lambda: events.append("finished"))

    def completed():
        assert elapsed.elapsed() >= PRESENTATION_MS
        assert card._finished
        assert not card.isVisible()
        assert not card._watchdog.isActive()
        assert card._animation.state() == QAbstractAnimation.State.Stopped
        events.append("completed")
        card.finish_now()
        card._complete()

    card.completed.connect(completed)
    card.start()
    QTest.qWait(300)
    assert events == []
    assert card.isVisible()
    QTest.qWait(PRESENTATION_MS + 160)
    assert events == ["finished", "completed"]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(card)


def test_external_close_cleans_animation_and_timer(qapp):
    card = StartupCard()
    events = []
    card.finished.connect(lambda: events.append("finished"))
    card.completed.connect(lambda: events.append("completed"))
    card.start()
    card.close()
    assert card._finished
    assert not card._watchdog.isActive()
    assert card._animation.state() == QAbstractAnimation.State.Stopped
    assert events == ["finished"]


def test_cancel_before_start_never_completes_or_starts(qapp):
    card = StartupCard()
    events = []
    card.finished.connect(lambda: events.append("finished"))
    card.completed.connect(lambda: events.append("completed"))
    card.finish_now()
    card.start()
    card._complete()
    assert events == ["finished"]
    assert not card.isVisible()
    assert not card._started


def test_animation_finished_cannot_complete_before_two_seconds(qapp):
    card = StartupCard()
    events = []
    card.completed.connect(lambda: events.append("completed"))
    card.start()
    card._animation.setCurrentTime(PRESENTATION_MS)
    assert events == []
    assert not card._finished
    assert card.isVisible()
    assert card._watchdog.isActive()
    card.finish_now()


def test_completion_handles_finished_callback_reentrancy(qapp):
    card = StartupCard(animations_enabled=False)
    events = []

    def finished():
        events.append("finished")
        assert shiboken6.isValid(card)
        assert not card.isVisible()
        card.finish_now()
        card.close()
        card._complete()
        card.start()

    card.finished.connect(finished)
    card.completed.connect(lambda: events.append("completed"))
    card.start()
    QTest.qWait(PRESENTATION_MS + 160)
    assert events == ["finished", "completed"]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(card)


@pytest.mark.parametrize("available", [QRect(0, 0, 1920, 1040),
                                       QRect(-1440, -300, 1440, 860),
                                       QRect(-20, 50, 240, 140),
                                       QRect(30, 40, 1, 1)])
def test_card_geometry_stays_inside_one_logical_monitor(available):
    geometry = card_geometry(available)
    assert available.contains(geometry)
    assert geometry.width() <= 360
    assert geometry.height() <= 196
    assert abs(geometry.center().x() - available.center().x()) <= 1
    assert abs(geometry.center().y() - available.center().y()) <= 1
