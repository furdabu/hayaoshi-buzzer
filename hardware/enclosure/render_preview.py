"""組み立て後の見た目と断面のプレビュー画像を作る (docs/images に出力)

    pip install build123d matplotlib
    python render_preview.py

小さなソフトウェアレンダラー (奥行きバッファ + なめらかな陰影 + 輪郭線 + アンチエイリアス) で描画する。
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402
import numpy as np  # noqa: E402
from build123d import Axis, Box, Cylinder, Part, Pos, Rot, Sphere, fillet  # noqa: E402

import enclosure as enc  # noqa: E402

WIDTH, HEIGHT = 1000, 750  # 出力画像の大きさ (px)
SSAA = 3  # この倍率で描いてから縮小してギザギザを消す
BACKGROUND = np.array([1.0, 1.0, 1.0])


def mesh(part: Part) -> tuple[np.ndarray, np.ndarray]:
    """三角形 (n,3,3) と、各頂点のなめらかな法線 (n,3,3) を返す。
    同じ面の中では法線を平均して丸みをなめらかに、面と面の境目は角をはっきり残す。"""
    verts, tris = part.tessellate(0.05, 0.15)
    v = np.array([[p.X, p.Y, p.Z] for p in verts])
    t = np.array(tris)
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, t[:, k], fn)
    vn /= np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12
    return v[t], vn[t]


def camera(elev: float, azim: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    e, a = math.radians(elev), math.radians(azim)
    to_cam = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    right = np.cross(-to_cam, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, -to_cam)
    return right, up, to_cam


def render(items, path: Path, elev: float, azim: float, title: str = "") -> None:
    right, up, to_cam = camera(elev, azim)
    light_key = 0.55 * up - 0.45 * right + 0.70 * to_cam
    light_key /= np.linalg.norm(light_key)
    light_fill = -0.2 * up + 0.6 * right + 0.5 * to_cam
    light_fill /= np.linalg.norm(light_fill)

    meshes = []
    for obj_id, (part, rgb, _alpha) in enumerate(items, start=1):
        tri, nrm = mesh(part)
        meshes.append((obj_id, np.array(rgb, dtype=float), tri, nrm))

    # 画面座標へ (正射影)。全体が画像に収まるように拡大率を決める
    all_pts = np.concatenate([m[2].reshape(-1, 3) for m in meshes])
    sx, sy = all_pts @ right, all_pts @ up
    W, H = WIDTH * SSAA, HEIGHT * SSAA
    margin = 0.06
    scale = min(W * (1 - 2 * margin) / (sx.max() - sx.min()), H * (1 - 2 * margin) / (sy.max() - sy.min()))
    cx, cy = (sx.max() + sx.min()) / 2, (sy.max() + sy.min()) / 2

    zbuf = np.full((H, W), -np.inf)
    color = np.tile(BACKGROUND, (H, W, 1))
    normal = np.zeros((H, W, 3))
    ids = np.zeros((H, W), dtype=np.int32)

    for obj_id, rgb, tri, nrm in meshes:
        px = (tri @ right - cx) * scale + W / 2
        py = H / 2 - (tri @ up - cy) * scale
        pz = tri @ to_cam
        for i in range(len(tri)):
            x0, x1, x2 = px[i]
            y0, y1, y2 = py[i]
            xmin, xmax = int(max(math.floor(min(x0, x1, x2)), 0)), int(min(math.ceil(max(x0, x1, x2)), W - 1))
            ymin, ymax = int(max(math.floor(min(y0, y1, y2)), 0)), int(min(math.ceil(max(y0, y1, y2)), H - 1))
            if xmin > xmax or ymin > ymax:
                continue
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue
            gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
            w0 = ((x1 - gx) * (y2 - gy) - (x2 - gx) * (y1 - gy)) / area
            w1 = ((x2 - gx) * (y0 - gy) - (x0 - gx) * (y2 - gy)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * pz[i, 0] + w1 * pz[i, 1] + w2 * pz[i, 2]
            zslice = zbuf[ymin : ymax + 1, xmin : xmax + 1]
            win = inside & (z > zslice)
            if not win.any():
                continue
            zslice[win] = z[win]
            n = w0[..., None] * nrm[i, 0] + w1[..., None] * nrm[i, 1] + w2[..., None] * nrm[i, 2]
            n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-12
            # 裏から見えている面は法線を反転 (断面図などで内側が見えるとき)
            facing = n @ to_cam
            n[facing < 0] *= -1
            nslice = normal[ymin : ymax + 1, xmin : xmax + 1]
            nslice[win] = n[win]
            ids[ymin : ymax + 1, xmin : xmax + 1][win] = obj_id
            color[ymin : ymax + 1, xmin : xmax + 1][win] = rgb

    # 陰影 (環境光 + 主光源 + 補助光 + ハイライト)
    hit = ids > 0
    n = normal[hit]
    diffuse = 0.42 + 0.50 * np.clip(n @ light_key, 0, 1) + 0.15 * np.clip(n @ light_fill, 0, 1)
    half = light_key + to_cam
    half /= np.linalg.norm(half)
    spec = 0.18 * np.clip(n @ half, 0, 1) ** 40
    color[hit] = np.clip(color[hit] * diffuse[:, None] + spec[:, None], 0, 1)

    # 輪郭線: 部品の境目・奥行きの段差・面の向きが大きく変わるところ
    edge = np.zeros((H, W), dtype=bool)
    depth = np.where(hit, zbuf, -1e6)
    for dy, dx in ((0, 1), (1, 0)):
        a_id, b_id = ids[: H - dy, : W - dx], ids[dy:, dx:]
        a_z, b_z = depth[: H - dy, : W - dx], depth[dy:, dx:]
        a_n, b_n = normal[: H - dy, : W - dx], normal[dy:, dx:]
        e = (a_id != b_id) | (np.abs(a_z - b_z) > 1.5) | (np.sum(a_n * b_n, axis=-1) < 0.85)
        e &= (a_id > 0) | (b_id > 0)
        edge[: H - dy, : W - dx] |= e
        edge[dy:, dx:] |= e
    color[edge] *= 0.45

    # 縮小してアンチエイリアス
    img = color.reshape(HEIGHT, SSAA, WIDTH, SSAA, 3).mean(axis=(1, 3))
    path.parent.mkdir(parents=True, exist_ok=True)
    mpimg.imsave(path, img)
    print("wrote", path)


def arcade_button(x: float, y: float, z: float) -> tuple[Part, Part]:
    """プレビュー用の 60mm ボタン (形だけ)。採用品は天板から少しだけ出る、薄くて平らな形"""
    rim = Pos(x, y, z) * Cylinder(32, 3, align=enc.MIN)  # 黒い縁
    cap = Cylinder(28.5, 4, align=enc.MIN)  # 色のついた平らなボタン面
    cap = fillet(cap.edges().sort_by(Axis.Z)[-1], radius=1.5)
    return rim, Pos(x, y, z + 3) * cap


GRAY_DARK = (0.30, 0.32, 0.36)
GRAY = (0.78, 0.79, 0.82)
COVER = (0.97, 0.96, 0.93)  # 乳白の半球カバー (光の色は LED で決まるので、消灯時の白で描く)


def pc_cover(p: enc.Params) -> Part:
    """プレビュー用の購入品の半球カバー (外径 68mm, 高さ 40mm, 乳白 PC)"""
    r = p.cover_od / 2
    h_cyl = 40.0 - r
    outer = Cylinder(r, h_cyl, align=enc.MIN) + Pos(0, 0, h_cyl) * (Sphere(r) & Box(2 * r, 2 * r, r, align=enc.MIN))
    inner = Pos(0, 0, -1) * Cylinder(r - 1.5, h_cyl + 1, align=enc.MIN) + Pos(0, 0, h_cyl) * Sphere(r - 1.5)
    return outer - inner


def led_board(p: enc.Params) -> Part:
    """プレビュー用の WS2812B 7 連丸型基板"""
    board = Cylinder(p.led_board_d / 2, p.led_board_t, align=enc.MIN)
    for i in range(7):
        x, y = (0.0, 0.0) if i == 0 else (8 * math.cos(math.radians(60 * i)), 8 * math.sin(math.radians(60 * i)))
        board += Pos(x, y, p.led_board_t) * Box(5, 5, 1.6, align=enc.MIN)
    return board


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
        (Pos(lx, ly, top_z + p.plate_t) * pc_cover(p), COVER, 1.0),
    ]


def master_assembly(p: enc.Params):
    w, d, h = enc.MASTER_SIZE
    top_z = h
    items = [
        (enc.master_base(p), GRAY_DARK, 1.0),
        (Pos(0, 0, top_z) * enc.master_top(p), GRAY, 1.0),
    ]
    # 司会者から見て 左: 不正解 (青) / 右: 正解 (赤)
    colors = [(0.15, 0.35, 0.90), (0.90, 0.15, 0.15)]
    for (bx, by), c in zip(enc.MASTER_BUTTONS, colors):
        rim, cap = arcade_button(bx, by, top_z + p.plate_t)
        items += [(rim, (0.15, 0.15, 0.15), 1.0), (cap, c, 1.0)]
    # 中央のランプ
    for lx, ly in enc.MASTER_LAMPS:
        items.append((Pos(lx, ly, top_z + p.plate_t) * pc_cover(p), COVER, 1.0))
    return items


def box_at(x: float, y: float, z: float, sx: float, sy: float, sz: float) -> Part:
    return Pos(x, y, z) * Box(sx, sy, sz, align=enc.MIN)


BATTERY = (0.20, 0.45, 0.85)
BOARD = (0.10, 0.55, 0.30)
BOOST = (0.85, 0.35, 0.15)
HUB = (0.90, 0.78, 0.45)  # 中継基板 (抵抗などをまとめる小さな基板)
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
        (box_at(cx, cy, f, p.child_holder_w - 0.5, 77, 20), BATTERY, 1.0),  # 18650 電池ボックス (1 本用)
        (box_at(enc.CHILD_CHARGER_X, wall_y - 14.5, f + p.charger_ledge_h, 17, 28, 1.2), BOARD, 1.0),
        (Pos(enc.CHILD_POWER_X, wall_y - 14, p.power_button_z) * Rot(90, 0, 0) * Cylinder(9, 28), METAL, 1.0),
        (box_at(5, 18, f, 17, 36, 6), BOOST, 1.0),  # MT3608 (5V)
        (box_at(5, 62, f, 17, 36, 6), BOOST, 1.0),  # MT3608 (12V, ボタン LED 用)
        (box_at(38, -45, f, 21, 17.5, 6), BOARD, 1.0),  # XIAO ESP32C6 (アンテナを右の壁へ向ける)
        (box_at(35.7, 21, f, 33, 51, 5), HUB, 1.0),  # 中継基板 (注文した基板の大きさ 51 x 33mm。ストリップ基板はこれより小さい)
        (Pos(bx, by, h - 40) * Cylinder(15, 40, align=enc.MIN), BUTTON_BODY, 1.0),  # ボタンの胴体
    ]


def master_inside(p: enc.Params):
    """親機の中身の配置例 (天板を外して上から見た図)"""
    w, d, h = enc.MASTER_SIZE
    f = p.floor
    cx, cy = enc.MASTER_CELLS["center"]
    wall_x = w / 2 - p.wall
    items = [(enc.master_base(p), GRAY_DARK, 1.0)]
    items.append((box_at(cx, cy, f, 77, p.master_holder_w - 0.5, 20), BATTERY, 1.0))  # 3 本用並列ボックス
    items += [
        (box_at(wall_x - 14.5, enc.MASTER_CHARGER_Y, f + p.charger_ledge_h, 28, 17, 1.2), BOARD, 1.0),
        (Pos(wall_x - 23, enc.MASTER_POWER_Y, p.power_button_z) * Rot(0, 90, 0) * Cylinder(11, 46), METAL, 1.0),  # 電源ボタン (LA16)
        (box_at(83, -43, f, 28, 55, 10), BOARD, 1.0),  # ESP32
        (box_at(-88, -50, f, 21, 21, 8), BOARD, 1.0),  # DFPlayer
        (box_at(24, 20, f, 52, 48, 5), HUB, 1.0),  # 中継基板 (注文した基板の大きさ 52 x 48mm。ストリップ基板はこれより小さい)
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
    plate = plate + Pos(0, 0, p.plate_t) * enc.lamp_seat(p)
    plate -= enc.lamp_hole(p, p.plate_t + p.pedestal_h)
    cover = Pos(0, 0, p.plate_t) * pc_cover(p)
    board = Pos(0, 0, p.plate_t + p.pedestal_h - p.led_board_t) * led_board(p)
    cut = Pos(0, 50, 0) * Box(200, 100, 200)
    return [
        (plate - cut, GRAY, 1.0),
        (cover - cut, COVER, 1.0),
        (board - cut, (0.1, 0.35, 0.8), 1.0),
    ]


def main() -> None:
    out = Path(__file__).resolve().parents[2] / "docs" / "images"
    p = enc.Params()
    render(child_assembly(p), out / "child.png", 24, -62, "Child unit")
    render(master_assembly(p), out / "master.png", 28, -58, "Master unit")
    render(lamp_section(p), out / "lamp_section.png", 12, 90, "Lamp section")
    render(child_inside(p), out / "child_inside.png", 62, -70, "Child unit - inside")
    render(master_inside(p), out / "master_inside.png", 62, -65, "Master unit - inside")


if __name__ == "__main__":
    main()
