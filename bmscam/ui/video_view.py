"""Zobrazovací plocha živého obrazu: zoom, posun, překryvy a výběr ROI."""

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QImage, QPainter, QPalette, QPen,
                         QPixmap)
from PyQt5.QtWidgets import QSizePolicy, QWidget


class VideoView(QWidget):
    """Živý náhled s možností přiblížení, posunu a výběru oblasti."""

    roiSelected = pyqtSignal(QRect)      # v souřadnicích obrazu
    zoomChanged = pyqtSignal(float)

    MIN_ZOOM = 0.05
    MAX_ZOOM = 16.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(24, 24, 26))
        self.setPalette(pal)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._image = QImage()
        self._fit = True
        self._zoom = 1.0
        self._offset = QPointF(0, 0)
        self._drag_from = None
        self._drag_offset = None

        self.show_grid = False
        self.show_cross = False
        self.show_scale = False
        self.um_per_px = 1.0

        self.roi_mode = False
        self._roi = QRect()
        self._roi_drag = None
        self._cursor_pos = None

    # -------------------------------------------------------------- vstup ---
    def setImage(self, image: QImage) -> None:
        first = self._image.isNull()
        self._image = image
        if first:
            self.fitToWindow()
        self.update()

    def clear(self) -> None:
        self._image = QImage()
        self._roi = QRect()
        self.update()

    def hasImage(self) -> bool:
        return not self._image.isNull()

    def image(self) -> QImage:
        return self._image

    # --------------------------------------------------------------- zoom ---
    def fitToWindow(self) -> None:
        self._fit = True
        self._offset = QPointF(0, 0)
        self.update()
        self.zoomChanged.emit(self.currentScale())

    def setZoom(self, factor: float) -> None:
        self._fit = False
        self._zoom = max(self.MIN_ZOOM, min(float(factor), self.MAX_ZOOM))
        self.update()
        self.zoomChanged.emit(self._zoom)

    def zoomBy(self, ratio: float) -> None:
        self.setZoom(self.currentScale() * ratio)

    def isFit(self) -> bool:
        return self._fit

    def currentScale(self) -> float:
        if self._image.isNull():
            return 1.0
        if not self._fit:
            return self._zoom
        return min(self.width() / self._image.width(),
                   self.height() / self._image.height())

    # ------------------------------------------------------------ geometrie -
    def _targetRect(self) -> QRectF:
        s = self.currentScale()
        w = self._image.width() * s
        h = self._image.height() * s
        x = (self.width() - w) / 2 + self._offset.x()
        y = (self.height() - h) / 2 + self._offset.y()
        return QRectF(x, y, w, h)

    def _toImage(self, pos) -> QPoint:
        rect = self._targetRect()
        s = self.currentScale() or 1.0
        return QPoint(int((pos.x() - rect.x()) / s), int((pos.y() - rect.y()) / s))

    # ------------------------------------------------------------ vykreslení
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().window())
        if self._image.isNull():
            p.setPen(QColor(150, 150, 155))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Žádný obraz\n\nPřipojte kameru a stiskněte „Připojit“ (F5).")
            return

        rect = self._targetRect()
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.currentScale() < 1.0)
        p.drawImage(rect, self._image)

        if self.show_grid:
            self._drawGrid(p, rect)
        if self.show_cross:
            self._drawCross(p, rect)
        if not self._roi.isNull():
            self._drawRoi(p, rect)
        if self.show_scale:
            self._drawScaleBar(p)
        if self._cursor_pos is not None:
            self._drawReadout(p)

    def _drawGrid(self, p: QPainter, rect: QRectF) -> None:
        for pen in (QPen(QColor(0, 0, 0, 90), 3), QPen(QColor(255, 255, 255, 170), 1, Qt.DashLine)):
            p.setPen(pen)
            for i in (1, 2):
                x = rect.x() + rect.width() * i / 3
                y = rect.y() + rect.height() * i / 3
                p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
                p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

    def _drawCross(self, p: QPainter, rect: QRectF) -> None:
        cx, cy = rect.center().x(), rect.center().y()
        p.setPen(QPen(QColor(220, 30, 30, 220), 1))
        p.drawLine(int(cx), int(rect.top()), int(cx), int(rect.bottom()))
        p.drawLine(int(rect.left()), int(cy), int(rect.right()), int(cy))
        p.drawEllipse(QPointF(cx, cy), 18, 18)

    def _drawRoi(self, p: QPainter, rect: QRectF) -> None:
        s = self.currentScale()
        r = QRectF(rect.x() + self._roi.x() * s, rect.y() + self._roi.y() * s,
                   self._roi.width() * s, self._roi.height() * s)
        p.setPen(QPen(QColor(80, 200, 120), 2))
        p.setBrush(QColor(80, 200, 120, 40))
        p.drawRect(r)
        p.setBrush(Qt.NoBrush)

    def _drawScaleBar(self, p: QPainter) -> None:
        s = self.currentScale()
        if s <= 0:
            return
        target_px = min(220, self.width() * 0.28)
        microns = target_px / s * self.um_per_px
        nice = _nice_number(microns)
        length = nice / self.um_per_px * s
        if length < 10 or length > self.width():
            return
        x2 = self.width() - 20
        x1 = x2 - length
        y = self.height() - 26
        p.setPen(QPen(QColor(0, 0, 0, 160), 5))
        p.drawLine(int(x1), y, int(x2), y)
        p.setPen(QPen(Qt.white, 2))
        p.drawLine(int(x1), y, int(x2), y)
        p.drawLine(int(x1), y - 5, int(x1), y + 5)
        p.drawLine(int(x2), y - 5, int(x2), y + 5)
        label = f"{nice:g} µm" if nice < 1000 else f"{nice / 1000:g} mm"
        p.setPen(Qt.white)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawText(int(x1), y - 26, int(length), 16, Qt.AlignCenter, label)
        p.setPen(Qt.white)
        p.drawText(int(x1), y - 27, int(length), 16, Qt.AlignCenter, label)

    def _drawReadout(self, p: QPainter) -> None:
        ip = self._toImage(self._cursor_pos)
        if not (0 <= ip.x() < self._image.width() and 0 <= ip.y() < self._image.height()):
            return
        color = self._image.pixelColor(ip)
        text = f"{ip.x()}, {ip.y()}   RGB {color.red()},{color.green()},{color.blue()}"
        if self.um_per_px != 1.0:
            text += f"   ({ip.x() * self.um_per_px:.1f}, {ip.y() * self.um_per_px:.1f} µm)"
        p.fillRect(6, 6, p.fontMetrics().horizontalAdvance(text) + 12, 20, QColor(0, 0, 0, 140))
        p.setPen(Qt.white)
        p.drawText(12, 21, text)

    # ---------------------------------------------------------------- myš ---
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self.roi_mode:
            self._roi_drag = self._toImage(ev.pos())
            self._roi = QRect(self._roi_drag, self._roi_drag)
        elif ev.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag_from = ev.pos()
            self._drag_offset = QPointF(self._offset)
            self.setCursor(Qt.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        self._cursor_pos = ev.pos()
        if self._roi_drag is not None:
            self._roi = QRect(self._roi_drag, self._toImage(ev.pos())).normalized()
        elif self._drag_from is not None:
            delta = ev.pos() - self._drag_from
            self._fit = False if self._fit else self._fit
            self._offset = self._drag_offset + QPointF(delta)
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if self._roi_drag is not None:
            self._roi_drag = None
            if self._roi.width() > 4 and self._roi.height() > 4:
                self.roiSelected.emit(self._roi)
        self._drag_from = None
        self.unsetCursor()
        self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.fitToWindow()

    def leaveEvent(self, ev) -> None:
        self._cursor_pos = None
        self.update()

    def wheelEvent(self, ev) -> None:
        if self._image.isNull():
            return
        steps = ev.angleDelta().y() / 120.0
        if steps:
            self.zoomBy(1.15 ** steps)

    def clearRoi(self) -> None:
        self._roi = QRect()
        self.update()

    def roi(self) -> QRect:
        return QRect(self._roi)


def _nice_number(value: float) -> float:
    """Zaokrouhlí na „hezkou“ hodnotu 1/2/5 × 10ⁿ."""
    if value <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(value))
    base = value / (10 ** exp)
    for cand in (1, 2, 5, 10):
        if base <= cand:
            return cand * (10 ** exp)
    return 10 ** (exp + 1)
