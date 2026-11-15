"""早押しボタンのケース (3D プリント用) を生成するスクリプト

    pip install build123d
    python enclosure.py            # ../stl と ../step に全パーツを出力

寸法は下の Params を書き換えると全パーツに反映されます。
手持ちのボタンや半球カバーに合わせて、まず button_hole_d と cover_od を確認してください。

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
    # 採用している 60mm ボタン (12V LED, マイクロスイッチ付き) の取付穴は 23.5mm。
    # 3D プリントの穴は少し小さく仕上がるので 0.5mm 大きくしている。別のボタンを使うときは実物を測って合わせる。
    button_hole_d: float = 24.0

    # ---- ランプ (中央に WS2812B 7 連丸型基板 + 乳白の半球カバー) ----
    cover_od: float = 68.0  # 半球カバーのふちの外径 (購入品は 68mm。届いたら測って合わせる)
    socket_h: float = 6.0  # カバーのふちを差し込む受けの高さ
    socket_wall: float = 2.0  # 受けの壁の厚さ
    fit: float = 0.3  # カバーと受けのすき間 (片側)。ゆるければ小さく、入らなければ大きく
    led_board_d: float = 23.0  # WS2812B 7 連丸型基板の直径
    led_board_t: float = 1.6  # 基板の厚さ (くぼみの深さ)
    pedestal_h: float = 4.0  # 基板を載せる台の高さ (LED がカバーの中心付近にくるように)
    # 半球カバーの代わりに 3D プリントするドーム (購入品と同じ外径で、同じ受けに入る)
    dome_wall: float = 1.6  # 白/半透明の PLA・PETG で印刷すると光が拡散する
    dome_cyl_h: float = 16.0  # 円筒部の高さ
    dome_top_d: float = 24.0  # 頂部の平らな部分の直径 (斜面は 45° でサポート不要)

    # ---- 電源 (電池・充電・電源ボタン) ----
    # 18650 電池ボックス (1 本用) を挟むレール
    # 並列タイプの 18650 電池ボックス (子機は 1 本用、親機は 3 本用) の幅。届いたら測って合わせる
    child_holder_w: float = 21.0
    master_holder_w: float = 61.0
    cell_rail_len: float = 60.0
    cell_rail_h: float = 8.0
    rail_t: float = 1.6
    # TP4056 Type-C 充電モジュール (保護回路付き, 約 28 x 17mm) を置く台
    charger_w: float = 17.4  # 基板の幅 + すき間
    charger_l: float = 28.0  # 基板の長さ (短い基板はホットボンドで押さえる)
    charger_ledge_h: float = 3.0  # 基板を載せる段の高さ
    charger_rail_h: float = 6.5
    # Type-C の穴 (基板上のコネクタの中心は 床 + 段 + 基板厚 + 1.65mm あたり)
    usbc_w: float = 10.0
    usbc_h: float = 4.6
    usbc_z: float = 5.9  # 床の上面からコネクタ中心までの高さ
    usbc_recess_w: float = 13.5  # 外側のくぼみ (プラグの根元が奥まで入るように)
    usbc_recess_h: float = 7.5
    usbc_recess_d: float = 1.0
    # 電源ボタン (16mm 金属押しボタン, 自己保持型)
    power_button_d: float = 16.2
    power_button_z: float = 34.0  # 箱の底からの高さ


# 子機の箱: 幅 x 奥行き x 高さ (天板を除く)
CHILD_SIZE = (110.0, 180.0, 60.0)
CHILD_BUTTON = (0.0, -42.0)
CHILD_LAMP = (0.0, 45.0)
# 電源まわりの配置 (電池は左の壁沿い, 充電口と電源ボタンは背面)
CHILD_CELLS = dict(center=(-39.5, -10.0), axis="y", holder="child")
CHILD_CHARGER_X = -22.0  # 背面の壁での充電口の位置
CHILD_POWER_X = 24.0  # 背面の壁での電源ボタンの位置

# 親機の箱
MASTER_SIZE = (210.0, 160.0, 60.0)
MASTER_BUTTONS = [(-50.0, -38.0), (50.0, -38.0)]  # 司会者から見て 左: 不正解(青) / 右: 正解(赤)
MASTER_LAMPS = [(0.0, 38.0)]  # 中央のランプ 1 個 (正解 = 赤 / 不正解 = 青 に光る)
DISPLAY_WINDOW = (31.0, 15.0)  # TM1637 0.36 インチ 4 桁表示の窓
SPEAKER_SLOTS = (7, 2.6, 30.0, 5.2)  # 本数, 幅, 高さ, 間隔
# 電源まわりの配置 (3 本用の並列電池ボックスを左奥に, 充電口と電源ボタンは右の壁)
# 電池は左のボタンの真下を避け、スピーカーにも当たらない位置にしている
MASTER_CELLS = dict(center=(-55.0, 17.6), axis="x", holder="master")
MASTER_CHARGER_Y = 0.0  # 右の壁での充電口の位置
MASTER_POWER_Y = 40.0  # 右の壁での電源ボタンの位置


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


def lamp_seat(p: Params) -> Part:
    """天板の上のランプ部分: 半球カバーのふちを差し込む丸い受けと、中央の LED 基板の台。"""
    r_in = p.cover_od / 2 + p.fit
    socket = Cylinder(r_in + p.socket_wall, p.socket_h, align=MIN) - Pos(0, 0, -1) * Cylinder(
        r_in, p.socket_h + 2, align=MIN
    )
    # 受けの内側の上端を面取りしてカバーを差し込みやすくする
    socket -= Pos(0, 0, p.socket_h - 1.0) * Cone(r_in, r_in + 1.0, 1.01, align=MIN)

    # LED 基板の台 (上面のくぼみに基板を置く)
    pedestal = Cylinder(p.led_board_d / 2 + 3.0, p.pedestal_h, align=MIN)
    pedestal -= Pos(0, 0, p.pedestal_h - p.led_board_t) * Cylinder(
        p.led_board_d / 2 + 0.3, p.led_board_t + 1, align=MIN
    )
    return socket + pedestal


def lamp_hole(p: Params, height: float) -> Part:
    """天板と台を貫通する配線穴。LED 基板は 3 本のリブで下から支える。"""
    r_hole = p.led_board_d / 2 - 0.5
    hole = Pos(0, 0, -1) * Cylinder(r_hole, height + 2, align=MIN)
    rib_len = 2.5
    for angle in (90, 210, 330):
        rib = Rot(0, 0, angle) * Pos(r_hole - rib_len / 2 + 0.5, 0, -1) * Box(
            rib_len + 1.0, 3.0, height - p.led_board_t + 1, align=MIN
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
        plate += Pos(x, y, t) * lamp_seat(p)
        plate -= Pos(x, y, 0) * lamp_hole(p, t + p.pedestal_h)
    return plate


def lamp_dome(p: Params) -> Part:
    """半球カバーの代わりに 3D プリントするドーム (任意)。購入品と同じ外径なので同じ受けに入る。
    開口部を下にしてそのまま印刷できる (サポート不要)。"""
    r = p.cover_od / 2
    top_r = p.dome_top_d / 2
    cone_h = r - top_r  # 45°
    solid = Cylinder(r, p.dome_cyl_h, align=MIN) + Pos(0, 0, p.dome_cyl_h) * Cone(
        r, top_r, cone_h, align=MIN
    )
    solid = solid.clean()
    bottom = solid.faces().sort_by(Axis.Z)[0]
    return offset(solid, amount=-p.dome_wall, openings=bottom)


# ---------------------------------------------------------------------------
#  電源まわりの部品
#  局所座標: 壁の内側の面が y = 0、箱の内側が y < 0、床の上面が z = 0
#  place_on_wall() で実際の壁の位置・向きに移す
# ---------------------------------------------------------------------------
def place_on_wall(part: Part, wall: str, along: float, size: tuple[float, float, float], p: Params) -> Part:
    """wall: "+y" (背面) / "-y" (手前) / "+x" (右) / "-x" (左)。
    along = 壁に沿った位置 (前後の壁なら X 座標、左右の壁なら Y 座標)。
    部品は局所 x について左右対称に作るので、回転で左右が入れ替わっても問題ない。"""
    w, d, _ = size
    if wall == "+y":
        return Pos(along, d / 2 - p.wall, p.floor) * part
    if wall == "-y":
        return Pos(along, -d / 2 + p.wall, p.floor) * Rot(0, 0, 180) * part
    if wall == "+x":
        return Pos(w / 2 - p.wall, along, p.floor) * Rot(0, 0, -90) * part
    if wall == "-x":
        return Pos(-w / 2 + p.wall, along, p.floor) * Rot(0, 0, 90) * part
    raise ValueError(wall)


def charger_cradle(p: Params) -> Part:
    """TP4056 Type-C モジュールを載せる台。コネクタ側を壁に突き当てて差し込む。"""
    w, length, t = p.charger_w, p.charger_l + 1.0, p.rail_t
    rails = Part()
    for sx in (-1, 1):
        rails += Pos(sx * (w / 2 + t / 2), -length / 2, 0) * Box(t, length, p.charger_rail_h, align=MIN)
        # 基板を載せる段
        rails += Pos(sx * (w / 2 - 0.6), -length / 2, 0) * Box(1.2, length, p.charger_ledge_h, align=MIN)
    # 奥のストッパー (プラグを挿すときに基板が逃げないように)
    rails += Pos(0, -length - t / 2, 0) * Box(w + 2 * t, t, p.charger_rail_h, align=MIN)
    return rails


def charger_port_cut(p: Params) -> Part:
    """壁を貫通する Type-C の穴と、外側のくぼみ"""
    hole = Pos(0, p.wall / 2, p.usbc_z - p.usbc_h / 2) * Box(p.usbc_w, p.wall * 3, p.usbc_h, align=MIN)
    recess = Pos(0, p.wall - p.usbc_recess_d / 2 + 0.5, p.usbc_z - p.usbc_recess_h / 2) * Box(
        p.usbc_recess_w, p.usbc_recess_d + 1.0, p.usbc_recess_h, align=MIN
    )
    return hole + recess


def power_button_cut(p: Params) -> Part:
    """壁を貫通する電源ボタンの丸穴"""
    z = p.power_button_z - p.floor
    return Pos(0, p.wall / 2, z) * Rot(90, 0, 0) * Cylinder(p.power_button_d / 2, p.wall * 3)


def cell_rails(p: Params, holder_w: float, axis: str) -> Part:
    """電池ボックスを両側から挟むレール。axis = 電池の向き"""
    gap = holder_w + 0.6
    rails = Part()
    for sy in (-1, 1):
        rails += Pos(0, sy * (gap / 2 + p.rail_t / 2), 0) * Box(
            p.cell_rail_len, p.rail_t, p.cell_rail_h, align=MIN
        )
    if axis == "y":
        rails = Rot(0, 0, 90) * rails
    return rails


def charger_vents(p: Params) -> Part:
    """充電モジュールの熱を逃がす穴: 基板の下の床に 3 本、Type-C の上の壁に 5 本 (局所座標)"""
    vents = Part()
    for x in (-5.0, 0.0, 5.0):
        vents += Pos(x, -p.charger_l / 2 - 1, -p.floor - 1) * Box(2.0, p.charger_l - 8, p.floor + 2, align=MIN)
    z0 = p.usbc_z + p.usbc_recess_h / 2 + 3
    for x in (-6.0, -3.0, 0.0, 3.0, 6.0):
        vents += Pos(x, p.wall / 2, z0) * Box(1.8, p.wall * 3, 10.0, align=MIN)
    return vents


def battery_features(
    body: Part,
    size: tuple[float, float, float],
    cells: dict,
    charger_wall: str,
    charger_along: float,
    power_wall: str,
    power_along: float,
    p: Params,
) -> Part:
    # 電池ボックスのレール (center = 並べた電池全体の中心)
    cx, cy = cells["center"]
    holder_w = p.child_holder_w if cells["holder"] == "child" else p.master_holder_w
    body += Pos(cx, cy, p.floor) * cell_rails(p, holder_w, cells["axis"])
    body += place_on_wall(charger_cradle(p), charger_wall, charger_along, size, p)
    body -= place_on_wall(charger_port_cut(p), charger_wall, charger_along, size, p)
    body -= place_on_wall(charger_vents(p), charger_wall, charger_along, size, p)
    body -= place_on_wall(power_button_cut(p), power_wall, power_along, size, p)
    return body


# ---------------------------------------------------------------------------
#  組み合わせ
# ---------------------------------------------------------------------------
def child_base(p: Params) -> Part:
    body = base_box(CHILD_SIZE, p)
    # 背面: Type-C 充電口と電源ボタン / 左の壁沿い: 電池
    return battery_features(
        body, CHILD_SIZE, CHILD_CELLS, "+y", CHILD_CHARGER_X, "+y", CHILD_POWER_X, p
    )


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
    # 右の壁: Type-C 充電口と電源ボタン / 左奥: 電池 3 本
    return battery_features(
        body, MASTER_SIZE, MASTER_CELLS, "+x", MASTER_CHARGER_Y, "+x", MASTER_POWER_Y, p
    )


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
