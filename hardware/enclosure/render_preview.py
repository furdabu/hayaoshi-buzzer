"""組み立て後の見た目と断面のプレビュー画像を作る (docs/images に出力)

    pip install build123d matplotlib
    python render_preview.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from build123d import Box, Cylinder, Part, Pos, Rot, Sphere  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

import enclosure as enc  # noqa: E402

LIGHT = np.array([0.35, -0.55, 0.75])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def subdivide(tris: np.ndarray, max_edge: float) -> np.ndarray:
    """matplotlib は三角形単位で奥行きを並べるので、大きな三角形を細かく割って表示崩れを防ぐ"""
    while True:
        e = np.stack(
            [
                np.linalg.norm(tris[:, 0] - tris[:, 1], axis=1),
                np.linalg.norm(tris[:, 1] - tris[:, 2], axis=1),
                np.linalg.norm(tris[:, 2] - tris[:, 0], axis=1),
            ],
            axis=1,
        ).max(axis=1)
        big = e > max_edge
        if not big.any():
            return tris
        t = tris[big]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        split = np.concatenate(
            [
                np.stack([a, ab, ca], 1),
                np.stack([ab, b, bc], 1),
                np.stack([ca, bc, c], 1),
                np.stack([ab, bc, ca], 1),
            ]
        )
        tris = np.concatenate([tris[~big], split])


def triangles(part: Part, tol: float = 0.15) -> np.ndarray:
    verts, tris = part.tessellate(tol, 0.25)
    v = np.array([[p.X, p.Y, p.Z] for p in verts])
    return subdivide(v[np.array(tris)], 6.0)


def shaded(tris: np.ndarray, rgb: tuple[float, float, float], alpha: float) -> np.ndarray:
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    shade = 0.38 + 0.62 * np.clip(n @ LIGHT, 0, 1)
    rgba = np.empty((len(tris), 4))
    rgba[:, :3] = np.array(rgb)[None, :] * shade[:, None]
    rgba[:, 3] = alpha
    return rgba


def render(items, path: Path, elev: float, azim: float, title: str) -> None:
    all_tris, all_cols = [], []
    for part, rgb, alpha in items:
        t = triangles(part)
        all_tris.append(t)
        all_cols.append(shaded(t, rgb, alpha))
    tris = np.concatenate(all_tris)
    cols = np.concatenate(all_cols)

    fig = plt.figure(figsize=(8, 6), dpi=110)
    ax = fig.add_subplot(projection="3d")
    ax.add_collection3d(Poly3DCollection(tris, facecolors=cols, edgecolors="none"))
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    ax.set_xlim(lo[0], hi[0])
    ax.set_ylim(lo[1], hi[1])
    ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(hi - lo)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_title(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print("wrote", path)


def arcade_button(x: float, y: float, z: float, rgb_part_only: bool = False) -> Part:
    """プレビュー用の 60mm ボタン (形だけ)"""
    rim = Pos(x, y, z) * Cylinder(32, 6, align=enc.MIN)
    cap = Pos(x, y, z + 6) * (Sphere(27) & Pos(0, 0, 13.5) * Box(60, 60, 27))
    return rim, cap


GRAY_DARK = (0.30, 0.32, 0.36)
GRAY = (0.78, 0.79, 0.82)
DOME = (1.0, 0.97, 0.90)


def child_assembly(p: enc.Params):
    w, d, h = enc.CHILD_SIZE
    top_z = h
    lx, ly = enc.CHILD_LAMP
    bx, by = enc.CHILD_BUTTON
    rim, cap = arcade_button(bx, by, top_z + p.plate_t)
    return [
        (enc.child_base(p), GRAY_DARK, 1.0),
        (Pos(0, 0, top_z) * enc.child_top(p), GRAY, 1.0),
        (rim, (0.15, 0.15, 0.15), 1.0),
        (cap, (0.95, 0.20, 0.15), 1.0),
        (Pos(lx, ly, top_z + p.plate_t) * enc.lamp_dome(p), (1.0, 0.62, 0.15), 0.85),
    ]


def master_assembly(p: enc.Params):
    w, d, h = enc.MASTER_SIZE
    top_z = h
    items = [
        (enc.master_base(p), GRAY_DARK, 1.0),
        (Pos(0, 0, top_z) * enc.master_top(p), GRAY, 1.0),
    ]
    colors = [(0.15, 0.75, 0.25), (0.90, 0.15, 0.15)]
    for (bx, by), c in zip(enc.MASTER_BUTTONS, colors):
        rim, cap = arcade_button(bx, by, top_z + p.plate_t)
        items += [(rim, (0.15, 0.15, 0.15), 1.0), (cap, c, 1.0)]
    for (lx, ly), c in zip(enc.MASTER_LAMPS, colors):
        tint = tuple(0.55 + 0.45 * v for v in c)
        items.append((Pos(lx, ly, top_z + p.plate_t) * enc.lamp_dome(p), tint, 0.85))
    return items


def box_at(x: float, y: float, z: float, sx: float, sy: float, sz: float) -> Part:
    return Pos(x, y, z) * Box(sx, sy, sz, align=enc.MIN)


BATTERY = (0.20, 0.45, 0.85)
BOARD = (0.10, 0.55, 0.30)
BOOST = (0.85, 0.35, 0.15)
METAL = (0.70, 0.70, 0.72)
BUTTON_BODY = (0.60, 0.20, 0.20)


def child_inside(p: enc.Params):
    """子機の中身の配置例 (天板を外して上から見た図)"""
    w, d, h = enc.CHILD_SIZE
    f = p.floor
    cx, cy = enc.CHILD_CELLS["center"]
    wall_y = d / 2 - p.wall
    bx, by = enc.CHILD_BUTTON
    return [
        (enc.child_base(p), GRAY_DARK, 1.0),
        (box_at(cx, cy, f, 20.5, 77, 19), BATTERY, 1.0),  # 18650 電池ボックス
        (box_at(enc.CHILD_CHARGER_X, wall_y - 14.5, f + p.charger_ledge_h, 17, 28, 1.2), BOARD, 1.0),
        (Pos(enc.CHILD_POWER_X, wall_y - 14, p.power_button_z) * Rot(90, 0, 0) * Cylinder(9, 28), METAL, 1.0),
        (box_at(5, 18, f, 17, 36, 6), BOOST, 1.0),  # MT3608 (5V)
        (box_at(5, 62, f, 17, 36, 6), BOOST, 1.0),  # MT3608 (12V, ボタン LED 用)
        (box_at(36, 0, f, 18, 23, 6), BOARD, 1.0),  # ESP32-C3 SuperMini
        (Pos(bx, by, h - 40) * Cylinder(15, 40, align=enc.MIN), BUTTON_BODY, 1.0),  # ボタンの胴体
    ]


def master_inside(p: enc.Params):
    """親機の中身の配置例 (天板を外して上から見た図)"""
    w, d, h = enc.MASTER_SIZE
    f = p.floor
    cx, cy = enc.MASTER_CELLS["center"]
    pitch = p.cell_holder_w + 0.6 + p.rail_t
    wall_x = w / 2 - p.wall
    items = [(enc.master_base(p), GRAY_DARK, 1.0)]
    for i in (-1, 0, 1):
        items.append((box_at(cx, cy + i * pitch, f, 77, 20.5, 19), BATTERY, 1.0))
    items += [
        (box_at(wall_x - 14.5, enc.MASTER_CHARGER_Y, f + p.charger_ledge_h, 28, 17, 1.2), BOARD, 1.0),
        (Pos(wall_x - 14, enc.MASTER_POWER_Y, p.power_button_z) * Rot(0, 90, 0) * Cylinder(9, 28), METAL, 1.0),
        (box_at(86, -48, f, 28, 55, 10), BOARD, 1.0),  # ESP32
        (box_at(-88, -50, f, 21, 21, 8), BOARD, 1.0),  # DFPlayer
        (box_at(5, -30, f, 36, 17, 6), BOOST, 1.0),  # MT3608 (5V)
        (box_at(5, -55, f, 36, 17, 6), BOOST, 1.0),  # MT3608 (12V, ボタン LED 用)
        (Pos(0, d / 2 - p.wall - 8, h / 2) * Rot(90, 0, 0) * Cylinder(20, 16), METAL, 1.0),  # スピーカー
        (box_at(0, -d / 2 + p.wall + 4, h / 2 - 12, 42, 8, 24), BOARD, 1.0),  # 4 桁表示
    ]
    for bx, by in enc.MASTER_BUTTONS:
        items.append((Pos(bx, by, h - 40) * Cylinder(15, 40, align=enc.MIN), BUTTON_BODY, 1.0))
    return items


def lamp_section(p: enc.Params):
    """ランプ部分の断面 (はめあい確認用)"""
    plate = Box(90, 90, p.plate_t, align=enc.MIN)
    plate = plate + Pos(0, 0, p.plate_t) * enc.lamp_collar(p)
    plate -= enc.lamp_hole(p, p.plate_t + p.collar_h)
    dome = Pos(0, 0, p.plate_t) * enc.lamp_dome(p)
    ring = Pos(0, 0, p.plate_t + p.collar_h - p.ring_t) * (
        Cylinder(p.ring_od / 2, 1.6, align=enc.MIN) - Cylinder(p.ring_od / 2 - 6, 2, align=enc.MIN)
    )
    cut = Pos(0, 50, 0) * Box(200, 100, 200)
    return [
        (plate - cut, GRAY, 1.0),
        (dome - cut, (1.0, 0.62, 0.15), 1.0),
        (ring - cut, (0.1, 0.35, 0.8), 1.0),
    ]


def main() -> None:
    out = Path(__file__).resolve().parents[2] / "docs" / "images"
    p = enc.Params()
    render(child_assembly(p), out / "child.png", 24, -62, "Child unit")
    render(master_assembly(p), out / "master.png", 28, -58, "Master unit")
    render(lamp_section(p), out / "lamp_section.png", 12, 90, "Lamp section")
    render(child_inside(p), out / "child_inside.png", 62, -70, "Child unit - inside (battery)")
    render(master_inside(p), out / "master_inside.png", 62, -65, "Master unit - inside (battery)")


if __name__ == "__main__":
    main()
