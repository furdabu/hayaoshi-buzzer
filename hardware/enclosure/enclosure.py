"""早押しボタンのケース (3D プリント用) を生成するスクリプト

    pip install build123d
    python enclosure.py            # ../stl と ../step に全パーツを出力

寸法は下の Params を書き換えると全パーツに反映されます。
手持ちのボタンや LED リングに合わせて、まず BUTTON_HOLE_D と RING_OD を確認してください。

座標系: X = 左右, Y = 奥行き (マイナス側 = 手前 / 操作する人の側), Z = 高さ
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

from build123d import (
    Align,
    Box,
    Cone,
    Cylinder,
    Part,
    Pos,
    RectangleRounded,
    Rot,
    export_step,
    export_stl,
    extrude,
    offset,
    Axis,
)

MIN = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass
class Params:
    # ---- 箱 ----
    wall: float = 2.4  # 側面の厚さ
    floor: float = 2.4  # 底の厚さ
    plate_t: float = 3.0  # 天板の厚さ (アーケードボタンは 3mm 前後の板に取り付ける想定)
    corner_r: float = 6.0  # 角の丸み

    # ---- ネジ (M3 タッピングビス x 10mm 程度) ----
    post_d: float = 8.0  # 箱の四隅のネジ柱
    pilot_d: float = 2.6  # 下穴 (M3 タッピング)
    clear_d: float = 3.4  # 天板側の通し穴
    csink_d: float = 6.6  # 皿ネジの頭

    # ---- ボタン ----
    # 60mm アーケードボタンの取付穴は製品により 22〜30mm 程度。実物のネジ部を測って合わせる。
    button_hole_d: float = 24.5

    # ---- ランプ (WS2812B リング + 半透明ドーム) ----
    ring_od: float = 44.0  # LED リングの外径 (16 連は 44mm 前後, 12 連は 37mm 前後)
    ring_t: float = 1.8  # LED リング基板を収めるくぼみの深さ
    dome_od: float = 70.0  # ドームの外径
    dome_wall: float = 1.6  # ドームの厚さ (白/半透明の PLA・PETG で印刷すると光が拡散する)
    dome_cyl_h: float = 26.0  # ドームの円筒部の高さ
    dome_top_d: float = 24.0  # ドーム頂部の平らな部分の直径 (斜面は 45° でサポート不要)
    collar_h: float = 12.0  # 天板から立ち上がるドーム受けの高さ
    fit: float = 0.2  # はめあいのすき間 (片側)
    nub: float = 0.6  # ドームの爪の出っ張り

    # ---- ケーブル ----
    usb_slot_w: float = 13.0
    usb_slot_h: float = 8.0


# 子機の箱: 幅 x 奥行き x 高さ (天板を除く)
CHILD_SIZE = (110.0, 180.0, 60.0)
CHILD_BUTTON = (0.0, -42.0)
CHILD_LAMP = (0.0, 45.0)

# 親機の箱
MASTER_SIZE = (210.0, 160.0, 60.0)
MASTER_BUTTONS = [(-50.0, -38.0), (50.0, -38.0)]  # 左: 正解(緑) / 右: 不正解(赤)
MASTER_LAMPS = [(-50.0, 38.0), (50.0, 38.0)]  # 左: 緑ランプ / 右: 赤ランプ
DISPLAY_WINDOW = (31.0, 15.0)  # TM1637 0.36 インチ 4 桁表示の窓
SPEAKER_SLOTS = (7, 2.6, 30.0, 5.2)  # 本数, 幅, 高さ, 間隔


# ---------------------------------------------------------------------------
#  部品
# ---------------------------------------------------------------------------
def rounded_prism(w: float, d: float, h: float, r: float) -> Part:
    return extrude(RectangleRounded(w, d, r), amount=h)


def post_positions(w: float, d: float, p: Params) -> list[tuple[float, float]]:
    inset = p.wall + p.post_d / 2 - 1.0
    return [(sx * (w / 2 - inset), sy * (d / 2 - inset)) for sx in (-1, 1) for sy in (-1, 1)]


def base_box(size: tuple[float, float, float], p: Params) -> Part:
    """底と側面。天板は上からネジで留める。"""
    w, d, h = size
    outer = rounded_prism(w, d, h, p.corner_r)
    inner = Pos(0, 0, p.floor) * rounded_prism(
        w - 2 * p.wall, d - 2 * p.wall, h, max(p.corner_r - p.wall, 0.5)
    )
    body = outer - inner

    for x, y in post_positions(w, d, p):
        sx, sy = math.copysign(1, x), math.copysign(1, y)
        post = Pos(x, y, 0) * Cylinder(p.post_d / 2, h, align=MIN)
        # 柱と角の壁の間を埋める
        gusset_w = w / 2 - abs(x)
        gusset_d = d / 2 - abs(y)
        gusset = Pos(x + sx * gusset_w / 2, y + sy * gusset_d / 2, 0) * Box(
            gusset_w, gusset_d, h, align=MIN
        )
        body += post + (gusset & outer)
        body -= Pos(x, y, p.floor + 1.0) * Cylinder(p.pilot_d / 2, h, align=MIN)
    return body


def wall_cutout_y(x: float, wall_y: float, z: float, w: float, h: float, p: Params) -> Part:
    """前後の壁 (Y 方向に垂直な壁) の四角い穴"""
    return Pos(x, wall_y, z) * Box(w, p.wall * 4, h)


def wall_cutout_x(wall_x: float, y: float, z: float, w: float, h: float, p: Params) -> Part:
    """左右の壁 (X 方向に垂直な壁) の四角い穴"""
    return Pos(wall_x, y, z) * Box(p.wall * 4, w, h)


def lamp_collar(p: Params) -> Part:
    """天板の上に立つドーム受け。上面のくぼみに LED リングを置き、配線は中央の穴から箱の中へ。"""
    od = p.dome_od - 2 * p.dome_wall - 2 * p.fit
    h = p.collar_h
    collar = Cylinder(od / 2, h, align=MIN)
    # 上端の外周を面取りしてドームの爪が乗り越えやすくする
    top_edge = collar.edges().sort_by(Axis.Z)[-1]
    from build123d import chamfer

    collar = chamfer(top_edge, length=1.0)

    # ドームの爪が入る溝
    groove_z, groove_h, groove_depth = 1.2, 2.2, p.nub + 0.3
    groove = Pos(0, 0, groove_z) * (
        Cylinder(od / 2 + 1, groove_h, align=MIN) - Cylinder(od / 2 - groove_depth, groove_h, align=MIN)
    )
    collar -= groove

    # LED リングのくぼみ
    collar -= Pos(0, 0, h - p.ring_t) * Cylinder(p.ring_od / 2 + 0.3, p.ring_t + 1, align=MIN)
    return collar


def lamp_hole(p: Params, height: float) -> Part:
    """天板とドーム受けを貫通する配線穴。LED リングは 3 本のリブで下から支える。"""
    r_hole = p.ring_od / 2 - 0.5
    hole = Pos(0, 0, -1) * Cylinder(r_hole, height + 2, align=MIN)
    rib_len = 3.0
    for angle in (90, 210, 330):
        rib = Rot(0, 0, angle) * Pos(r_hole - rib_len / 2 + 0.5, 0, -1) * Box(
            rib_len + 1.0, 4.0, height - p.ring_t + 1, align=MIN
        )
        hole -= rib
    return hole


def top_plate(
    size: tuple[float, float, float],
    buttons: list[tuple[float, float]],
    lamps: list[tuple[float, float]],
    p: Params,
) -> Part:
    w, d, _ = size
    t = p.plate_t
    plate = rounded_prism(w, d, t, p.corner_r)

    for x, y in post_positions(w, d, p):
        plate -= Pos(x, y, -1) * Cylinder(p.clear_d / 2, t + 2, align=MIN)
        # 皿ネジ用の面取り (90°)
        cs_h = (p.csink_d - p.clear_d) / 2
        plate -= Pos(x, y, t - cs_h) * Cone(p.clear_d / 2, p.csink_d / 2 + 0.01, cs_h + 0.01, align=MIN)

    for x, y in buttons:
        plate -= Pos(x, y, -1) * Cylinder(p.button_hole_d / 2, t + 2, align=MIN)

    for x, y in lamps:
        plate += Pos(x, y, t) * lamp_collar(p)
        plate -= Pos(x, y, 0) * lamp_hole(p, t + p.collar_h)
    return plate


def lamp_dome(p: Params) -> Part:
    """半透明ドーム。開口部を下にしてそのまま印刷できる (サポート不要)。"""
    r = p.dome_od / 2
    top_r = p.dome_top_d / 2
    cone_h = r - top_r  # 45°
    solid = Cylinder(r, p.dome_cyl_h, align=MIN) + Pos(0, 0, p.dome_cyl_h) * Cone(
        r, top_r, cone_h, align=MIN
    )
    solid = solid.clean()
    bottom = solid.faces().sort_by(Axis.Z)[0]
    dome = offset(solid, amount=-p.dome_wall, openings=bottom)

    # ドーム受けの溝に引っかかる爪 x3
    nub_w, nub_z0, nub_h = 8.0, 1.5, 1.5
    r_in = r - p.dome_wall
    for angle in (30, 150, 270):
        nub = Rot(0, 0, angle) * Pos(r_in - p.nub / 2 + 0.2, 0, nub_z0) * Box(
            p.nub + 0.4, nub_w, nub_h, align=MIN
        )
        dome += nub
    return dome


def child_base(p: Params) -> Part:
    w, d, h = CHILD_SIZE
    body = base_box(CHILD_SIZE, p)
    # 背面: USB ケーブルの穴
    body -= wall_cutout_y(0, d / 2 - p.wall / 2, p.floor + 10, p.usb_slot_w, p.usb_slot_h, p)
    return body


def child_top(p: Params) -> Part:
    return top_plate(CHILD_SIZE, [CHILD_BUTTON], [CHILD_LAMP], p)


def master_base(p: Params) -> Part:
    w, d, h = MASTER_SIZE
    body = base_box(MASTER_SIZE, p)
    # 手前の壁: 4 桁表示の窓 (司会者から見える)
    dw, dh = DISPLAY_WINDOW
    body -= wall_cutout_y(0, -d / 2 + p.wall / 2, h / 2, dw, dh, p)
    # 奥の壁: スピーカーのスリット (観客側)
    n, sw, sh, pitch = SPEAKER_SLOTS
    for i in range(n):
        x = (i - (n - 1) / 2) * pitch
        body -= wall_cutout_y(x, d / 2 - p.wall / 2, h / 2, sw, sh, p)
    # 右の壁: USB ケーブルの穴
    body -= wall_cutout_x(w / 2 - p.wall / 2, 0, p.floor + 10, p.usb_slot_w, p.usb_slot_h, p)
    return body


def master_top(p: Params) -> Part:
    return top_plate(MASTER_SIZE, MASTER_BUTTONS, MASTER_LAMPS, p)


PARTS = {
    "child_base": child_base,
    "child_top": child_top,
    "master_base": master_base,
    "master_top": master_top,
    "lamp_dome": lamp_dome,
}


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stl", type=Path, default=here.parent / "stl")
    ap.add_argument("--step", type=Path, default=here.parent / "step")
    ap.add_argument("parts", nargs="*", default=list(PARTS))
    args = ap.parse_args()

    p = Params()
    args.stl.mkdir(parents=True, exist_ok=True)
    args.step.mkdir(parents=True, exist_ok=True)
    for name in args.parts:
        part = PARTS[name](p)
        bb = part.bounding_box()
        print(
            f"{name:12s}  {bb.size.X:6.1f} x {bb.size.Y:6.1f} x {bb.size.Z:6.1f} mm"
            f"  volume {part.volume / 1000:6.1f} cm3  valid={part.is_valid}"
        )
        export_stl(part, str(args.stl / f"{name}.stl"), tolerance=0.02, angular_tolerance=0.15)
        export_step(part, str(args.step / f"{name}.step"))


if __name__ == "__main__":
    main()
