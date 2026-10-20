"""Small, iOS-like motion toolkit shared by every DeskIsle widget.

Everything here is driven by ``QVariantAnimation`` on the GUI thread and only
asks widgets to repaint the area that changes.  No timers run while nothing is
animating, so idle CPU usage stays at zero.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QVariantAnimation

# Durations in milliseconds.  They are deliberately short: desktop pointer
# interactions feel sluggish with phone-length (500 ms+) springs.
COLLAPSE_MS = 300
HOVER_MS = 170
PRESS_MS = 90
RELEASE_MS = 340
ZOOM_MS = 240
FADE_MS = 180
SLIDE_MS = 260
# Reshuffling several islands at once reads better a touch slower than a single
# control response, but still fast enough to feel connected to the drag.
RELAYOUT_MS = 320

_reduce_motion = False


def set_reduce_motion(enabled: bool) -> None:
    """Globally replace animations with (near) instant state changes."""
    global _reduce_motion
    _reduce_motion = bool(enabled)


def reduce_motion() -> bool:
    return _reduce_motion


def duration(ms: float) -> int:
    """Return an animation duration that respects “减弱动态效果”."""
    return 1 if _reduce_motion else max(1, int(ms))


def ios_curve() -> QEasingCurve:
    """UIKit's default spring-like ease-out: cubic-bezier(0.32, 0.72, 0, 1)."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.32, 0.72), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
    return curve


def page_curve() -> QEasingCurve:
    """Easing for a whole page sliding across the screen.

    ``ios_curve`` front-loads the motion far too hard for this: it places 78 %
    of the travel in the first quarter and 95 % in the first half.  Over a
    half-second page change that reads as "snap across, then sit still", which is
    exactly the "not smooth" feeling it produced.  This curve keeps the speed
    near constant through the middle and only eases at the very ends.
    """

    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.42, 0.0), QPointF(0.58, 1.0), QPointF(1.0, 1.0))
    return curve


def soft_curve() -> QEasingCurve:
    """Gentle ease-in-out for opacity and colour changes."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.25, 0.1), QPointF(0.25, 1.0), QPointF(1.0, 1.0))
    return curve


def spring_curve(overshoot: float = 1.15) -> QEasingCurve:
    """A lightly damped spring used when a pressed control is released."""
    curve = QEasingCurve(QEasingCurve.Type.OutBack)
    curve.setOvershoot(overshoot)
    return curve


def mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


class Tween(QObject):
    """Interruptible float animation.

    ``to()`` always starts from the value currently on screen, so reversing a
    hover or a collapse half-way never jumps.  The duration is scaled by the
    remaining distance, which keeps short reversals snappy.
    """

    def __init__(
        self,
        parent: QObject,
        callback: Callable[[float], None],
        value: float = 0.0,
        ms: int = HOVER_MS,
        curve: QEasingCurve | None = None,
        span: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self.value = float(value)
        self.target = float(value)
        self._callback = callback
        self._ms = ms
        self._span = max(1e-6, float(span))
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(curve or ios_curve())
        self._animation.valueChanged.connect(self._step)
        self._finished_callback: Callable[[], None] | None = None
        self._animation.finished.connect(self._done)

    def _step(self, value) -> None:
        self.value = float(value)
        self._callback(self.value)

    def _done(self) -> None:
        self.value = self.target
        callback, self._finished_callback = self._finished_callback, None
        if callback is not None:
            callback()

    def is_running(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running

    def set_curve(self, curve: QEasingCurve) -> None:
        self._animation.setEasingCurve(curve)

    def set_immediate(self, value: float) -> None:
        self._animation.stop()
        self.value = self.target = float(value)
        self._callback(self.value)

    def to(
        self,
        target: float,
        ms: int | None = None,
        curve: QEasingCurve | None = None,
        on_finished: Callable[[], None] | None = None,
        proportional: bool = True,
    ) -> None:
        target = float(target)
        self._animation.stop()
        if curve is not None:
            self._animation.setEasingCurve(curve)
        self.target = target
        self._finished_callback = on_finished
        distance = abs(target - self.value)
        if distance < 1e-4 or _reduce_motion:
            self.value = target
            self._callback(target)
            callback, self._finished_callback = self._finished_callback, None
            if callback is not None:
                callback()
            return
        total = self._ms if ms is None else ms
        if proportional:
            total = total * max(0.4, min(1.0, distance / self._span))
        self._animation.setDuration(duration(total))
        self._animation.setStartValue(self.value)
        self._animation.setEndValue(target)
        self._animation.start()

    def stop(self) -> None:
        self._animation.stop()
        self._finished_callback = None


def tween_point(t: float, start, end) -> tuple[float, float]:
    """Interpolate two (x, y) pairs at progress *t*."""

    return (mix(start[0], end[0], t), mix(start[1], end[1], t))


class GeometryTween(QObject):
    """Animate a widget's position and size along a shared curve.

    Used when the arrangement mode reshuffles a page: every island travels on
    the same curve for the same time, so the board re-flows as one gesture
    instead of a queue of independent moves.
    """

    def __init__(self, parent: QObject, apply, ms: int = RELAYOUT_MS) -> None:
        super().__init__(parent)
        self._apply = apply
        self._ms = ms
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(ios_curve())
        self._animation.valueChanged.connect(self._step)
        self._start: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._end: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def _step(self, value) -> None:
        t = float(value)
        sx, sy, sw, sh = self._start
        ex, ey, ew, eh = self._end
        self._apply(mix(sx, ex, t), mix(sy, ey, t), mix(sw, ew, t), mix(sh, eh, t))

    def is_running(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running

    def to(self, start: tuple[float, float, float, float],
           end: tuple[float, float, float, float]) -> None:
        """Animate from *start* to *end*, each a ``(x, y, w, h)`` tuple."""

        self._animation.stop()
        distance = abs(end[0] - start[0]) + abs(end[1] - start[1])
        distance += abs(end[2] - start[2]) + abs(end[3] - start[3])
        if distance < 1.0 or reduce_motion():
            self._apply(*[float(value) for value in end])
            return
        self._start, self._end = start, end
        self._animation.setDuration(duration(self._ms))
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()

    def finish(self) -> None:
        """Jump to the target immediately (used when a new drag interrupts)."""

        if self._animation.state() == QVariantAnimation.State.Running:
            self._animation.stop()
            self._apply(*[float(value) for value in self._end])

    def stop(self) -> None:
        self._animation.stop()


__all__ = [
    "COLLAPSE_MS",
    "FADE_MS",
    "HOVER_MS",
    "PRESS_MS",
    "RELAYOUT_MS",
    "RELEASE_MS",
    "SLIDE_MS",
    "ZOOM_MS",
    "GeometryTween",
    "Tween",
    "clamp01",
    "duration",
    "ios_curve",
    "mix",
    "reduce_motion",
    "set_reduce_motion",
    "soft_curve",
    "spring_curve",
    "tween_point",
]
