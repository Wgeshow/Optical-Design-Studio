"""Dependency-free studio lighting for the live, native device preview.

These brushes affect presentation only. Geometry, material properties and
electrical contact boundaries remain in the canonical device document.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QLinearGradient


def mix_color(first, second, fraction):
    """Blend RGB without QColor.lighter's abrupt clipping of bright metals."""
    first, second = QColor(first), QColor(second)
    fraction = min(1., max(0., fraction))
    return QColor(*(round(a*(1.-fraction)+b*fraction) for a, b in zip(
        (first.red(), first.green(), first.blue(), first.alpha()),
        (second.red(), second.green(), second.blue(), second.alpha()))))


def studio_brush(color, bounds, normal=(0., 0., -1.), yaw=0., metal=False,
                 top=False, cavity=False, reflections=True):
    """Shade a face using its real normal and a camera-space studio softbox.

    z is device depth, so an upward facing surface has normal (0, 0, -1).
    The broad reflection bands mimic an environment light without a GPU,
    and remain deterministic on offscreen Qt and Windows raster paint engines.
    """
    color = QColor(color)
    nx, ny, nz = normal
    cosine, sine = math.cos(yaw), math.sin(yaw)
    # A large softbox above/left of the camera, with a cool fill on the right.
    camera_nx, camera_ny = nx*cosine-ny*sine, nx*sine+ny*cosine
    diffuse = max(0., -.42*camera_nx-.28*camera_ny-.86*nz)
    fill = max(0., .65*camera_nx+.30*camera_ny-.35*nz)
    illumination = min(1.35, .39+.62*diffuse+.22*fill)
    if cavity:
        illumination *= .57
    base = QColor(min(255, round(color.red()*illumination)),
                  min(255, round(color.green()*illumination)),
                  min(255, round(color.blue()*illumination)), color.alpha())
    gradient = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    if cavity:
        gradient=QLinearGradient(QPointF(bounds.center().x(),bounds.top()),
            QPointF(bounds.center().x(),bounds.bottom()))
        gradient.setColorAt(0, mix_color(base, '#75a6bf', .22))
        gradient.setColorAt(.52, base)
        gradient.setColorAt(1, mix_color(base, '#07121b', .72))
    elif metal and reflections:
        # Multiple reflected softboxes give gold its recognizable metal finish.
        gradient.setColorAt(0, mix_color(base, '#fff1ac', .78 if top else .40))
        gradient.setColorAt(.19, mix_color(base, '#ffda69', .56))
        gradient.setColorAt(.33, mix_color(base, '#976221', .42))
        gradient.setColorAt(.46, mix_color(base, '#fff4be', .82 if top else .38))
        gradient.setColorAt(.63, mix_color(base, '#df9d36', .40))
        gradient.setColorAt(1, mix_color(base, '#80521d', .44))
    else:
        # Cool reflected surroundings keep the surface smooth and readable,
        # while retaining each material / doping color used by the legend.
        gradient.setColorAt(0, mix_color(base, '#d5f3ff', .40 if top else .14))
        gradient.setColorAt(.35, mix_color(base, '#76bfe7', .35 if top else .06))
        gradient.setColorAt(1, mix_color(base, '#0d2940', .27 if top else .28))
    return gradient


def sheen_brush(bounds, metal=False, intensity=1.):
    """A broad, clipped environment reflection, not a replacement image."""
    start = QPointF(bounds.left(), bounds.top()+bounds.height()*.10)
    end = QPointF(bounds.right(), bounds.bottom())
    gradient = QLinearGradient(start, end)
    for position, alpha in ((0., 7), (.24, 12), (.36, 64 if metal else 36),
                            (.44, 9), (.72, 0), (1., 0)):
        gradient.setColorAt(position, QColor(218, 244, 255, round(alpha*intensity)))
    return gradient
