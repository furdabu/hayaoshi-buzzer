#!/usr/bin/env python3
"""中継基板のプリント基板 (発注用のガーバーデータ) を作る。

    pip install gerbonara
    python hardware/pcb/make_pcb.py

- 部品の位置と線の番号は hardware/wiring/make_diagrams.py のデータをそのまま使う。
  ストリップ基板で作る中継基板と、部品の並び・線の番号・行の番号が同じになる
- 出力:
    hardware/pcb/hub_child/ , hub_master/      ガーバーデータ (1 層ずつのファイル)
    hardware/pcb/hayaoshi-hub-child-r1.zip など  基板メーカーにそのままアップロードする zip
    docs/images/pcb/*.svg                       表と裏の見た目
- 書き出したファイルを読み直して、銅はくのつながり・すき間・穴・印刷の重なりを調べる。
  問題があればエラーで止まる
"""
from __future__ import annotations

import math
import re
import sys
import warnings
import zipfile
from pathlib import Path

warnings.simplefilter("ignore")

from gerbonara import ExcellonFile, GerberFile  # noqa: E402
from gerbonara.apertures import CircleAperture  # noqa: E402
from gerbonara.cad.primitives import Board, Graphics, Line, Newstroke, Pad, THTPad  # noqa: E402
from gerbonara.utils import MM  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "wiring"))
import make_diagrams as wd  # noqa: E402

REV = "r1"
IMG = HERE.parents[1] / "docs" / "images" / "pcb"

P = 2.54  # 穴の間隔
EDGE = 0.8  # 基板の端から文字までの余白
PAD_R = 1.0  # 余白の計算に使うパッドの半径
HOLE_PART, PAD_PART = 1.0, 1.9  # 部品の足: 穴の直径, パッドの直径
HOLE_DIODE, PAD_DIODE = 1.1, 2.0  # ダイオードは足が太い
HOLE_WIRE, PAD_WIRE = 1.2, 2.0  # 線をはんだ付けする穴
TRACE_POWER, TRACE_SIGNAL = 1.2, 0.6  # 配線の幅
POWER_NETS = {"gnd", "5v", "bat", "led5"}
SILK_W = 0.16  # 印刷の線の太さ (0.15mm より細いと印刷されないことがある)
F_WIRE, F_ROW, F_PART = 1.2, 1.0, 1.0  # 文字の高さ: 線の番号 / 行の番号 / 部品の値 (1mm 以上が読みやすい)
MIN_GAP = 0.3  # 別の配線どうしのすき間の下限
MIN_EDGE = 0.5  # 銅はくと基板の端のすき間の下限
MIN_RING = 0.35  # 穴のまわりの銅はくの幅の下限

NAMING = {
    "top copper": "{board_name}.GTL", "bottom copper": "{board_name}.GBL",
    "top mask": "{board_name}.GTS", "bottom mask": "{board_name}.GBS",
    "top silk": "{board_name}.GTO", "bottom silk": "{board_name}.GBO",
    "top paste": "{board_name}.GTP", "bottom paste": "{board_name}.GBP",
    "inner copper": "{board_name}.G{layer_number}", "mechanical outline": "{board_name}.GKO",
    "drill unknown": "{board_name}.DRL", "drill plated": "{board_name}-PTH.DRL",
    "drill nonplated": "{board_name}-NPTH.DRL", "other comments": "{board_name}.GM2",
}
_font = Newstroke()


def text_width(s: str, size: float) -> float:
    xs = [x for stroke in _font.render(s, size=size) for x, _y in stroke]
    return max(xs) if xs else 0.0


class Design:
    """1 枚の基板。座標は左上が原点・下向きが +y (図と同じ向き)。書き出すときに上下を反転する"""

    def __init__(self, kind: str):
        self.kind = kind
        self.master = kind == "master"
        self.name = f"hayaoshi-hub-{kind}-{REV}"
        self.rows = wd.ROWS_MASTER if self.master else wd.ROWS_CHILD
        wires = wd.MASTER_WIRES if self.master else wd.CHILD_WIRES
        self.holes = wd.wire_holes(wires, self.master)  # {(列, 行): 線}
        self.parts = wd.parts_for(self.master)
        self.jumpers = [p for p in self.parts if p.kind == "jumper"]

        # 行の左右に印刷する線の番号 (左から右の順)
        self.left = {r: [w.num for (c, rr), w in sorted(self.holes.items()) if rr == r and c in "abc"]
                     for r in range(1, self.rows + 1)}
        self.right = {r: [w.num for (c, rr), w in sorted(self.holes.items()) if rr == r and c in "lmn"]
                      for r in range(1, self.rows + 1)}
        wl = max(text_width(" ".join(map(str, v)), F_WIRE) for v in self.left.values())
        wr = max(text_width(" ".join(map(str, v)), F_WIRE) for v in self.right.values())
        self.row_w = max(text_width("17", F_ROW), text_width("ROW", F_ROW))
        self.sep_x = EDGE + self.row_w + 0.55
        self.x0 = self.sep_x + 0.55 + wl + 0.6 + PAD_R
        self.y0 = EDGE + F_ROW + 0.7 + PAD_R
        self.detour_x = self.x(len(wd.COLS) - 1) + 2.3  # 親機の長いジャンパーが通る位置
        self.W = round(max(self.x(len(wd.COLS) - 1) + PAD_R + 0.6 + wr + EDGE, self.detour_x + 1.6), 1)
        self.H = round(self.y(self.rows) + PAD_R + 0.8 + F_ROW + EDGE, 1)

        # パッド: {(x, y): (穴, パッド, 端子の名前)}
        self.pads: dict = {}
        for p in self.parts:
            if p.kind == "jumper":
                continue
            hole, pad = (HOLE_DIODE, PAD_DIODE) if p.kind == "diode" else (HOLE_PART, PAD_PART)
            for pin, c, r in p.pins:
                self.pads[self.xy(c, r)] = (hole, pad, f"{p.key}.{pin}")
        for (c, r), w in self.holes.items():
            assert self.xy(c, r) not in self.pads, f"穴が重なっています: {c}{r}"
            self.pads[self.xy(c, r)] = (HOLE_WIRE, PAD_WIRE, f"W{w.num}")

        # 裏面の配線: [(x1, y1, x2, y2, 幅)]
        self.traces: list = []
        for r in range(1, self.rows + 1):
            xs = [x for (x, y) in self.pads if abs(y - self.y(r)) < 1e-6]
            xs += [self.x(wd.COLS.index(c)) for j in self.jumpers for _n, c, rr in j.pins if rr == r]
            if len(set(xs)) >= 2:
                net = wd.ROW_INFO[r][1]
                width = TRACE_POWER if net in POWER_NETS else TRACE_SIGNAL
                self.traces.append((min(xs), self.y(r), max(xs), self.y(r), width))
        for j in self.jumpers:
            (xa, ya), (xb, yb) = (self.xy(c, r) for _n, c, r in j.pins)
            between = [1 for (x, y) in self.pads if abs(x - xa) < 1e-6 and min(ya, yb) < y < max(ya, yb)]
            if abs(xa - xb) < 1e-6 and not between:
                self.traces.append((xa, ya, xb, yb, TRACE_POWER))
            else:  # 間に別の穴があるので、基板の右の外側を回る
                d = self.detour_x
                self.traces += [(xa, ya, d, ya, 1.0), (d, ya, d, yb, 1.0), (d, yb, xb, yb, 1.0)]

    def x(self, ci: int) -> float:
        return self.x0 + ci * P

    def y(self, row: float) -> float:
        return self.y0 + (row - 1) * P

    def xy(self, col: str, row: float) -> tuple:
        return (round(self.x(wd.COLS.index(col)), 4), round(self.y(row), 4))

    # ---- 期待するつながり (行とジャンパーから求める) ----
    def expected_nets(self) -> set:
        parent: dict = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for (x, y), (_h, _d, name) in self.pads.items():
            row = round((y - self.y0) / P) + 1
            parent[find(name)] = find(("row", row))
        for j in self.jumpers:
            (_n1, _c1, r1), (_n2, _c2, r2) = j.pins
            parent[find(("row", r1))] = find(("row", r2))
        groups: dict = {}
        for a in list(parent):
            if isinstance(a, str):
                groups.setdefault(find(a), set()).add(a)
        return {frozenset(g) for g in groups.values()}

    # ---- 基板を組み立てる ----
    def build(self) -> Board:
        b = Board(self.W, self.H, corner_radius=1.5)
        fy = lambda y: self.H - y  # noqa: E731  ガーバーは上向きが +y
        silk = CircleAperture(SILK_W, unit=MM)
        top_silk: list = []
        bottom_silk: list = []

        def line(x1, y1, x2, y2):
            top_silk.append(Line(x1, fy(y1), x2, fy(y2), aperture=silk, unit=MM))

        def poly(pts, close=False):
            pts = list(pts) + ([pts[0]] if close else [])
            for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                line(x1, y1, x2, y2)

        def text(x, y, s, size, h="center", rot=0.0, flip=False):
            """文字を線で描く。(x, y) は文字の上下の中央。rot は反時計回り (ラジアン)、flip は裏面用 (左右反転)。
            ライブラリの Text は文字が上下逆さになるので使わない"""
            w = text_width(s, size)
            ox = {"left": 0.0, "center": -w / 2, "right": -w}[h]
            cos, sin = math.cos(rot), math.sin(rot)
            for stroke in _font.render(s, size=size):
                pts = []
                for gx, gy in stroke:  # フォントは下向きが +y で、文字は y = -size 〜 0 にある
                    lx, ly = gx + ox, -(gy + 0.55 * size)
                    if flip:
                        lx = -lx
                    pts.append((x + lx * cos - ly * sin, fy(y) + lx * sin + ly * cos))
                for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                    (bottom_silk if flip else top_silk).append(Line(x1, y1, x2, y2, aperture=silk, unit=MM))

        stacks: dict = {}
        for (x, y), (hole, dia, _name) in self.pads.items():
            stack = stacks.setdefault((hole, dia), THTPad.circle(hole, dia, paste=False))
            b.add(Pad(x, fy(y), stack))
        copper = [Line(x1, fy(y1), x2, fy(y2), aperture=CircleAperture(w, unit=MM), unit=MM) for x1, y1, x2, y2, w in self.traces]
        b.add(Graphics(0, 0, bottom_copper=copper))

        # 行の番号と線の番号
        text(EDGE + self.row_w / 2, EDGE + F_ROW / 2, "ROW", F_ROW)
        line(self.sep_x, self.y(1) - 1.0, self.sep_x, self.y(self.rows) + 1.0)
        text(self.x(0) - PAD_R - 0.6, EDGE + F_ROW / 2, "WIRE", F_ROW, "right")
        text(self.x(len(wd.COLS) - 1) + PAD_R + 0.6, EDGE + F_ROW / 2, "WIRE", F_ROW, "left")
        for r in range(1, self.rows + 1):
            text(EDGE + self.row_w / 2, self.y(r), str(r), F_ROW)
            if self.left[r]:
                text(self.x(0) - PAD_R - 0.6, self.y(r), " ".join(map(str, self.left[r])), F_WIRE, "right")
            if self.right[r]:
                text(self.x(len(wd.COLS) - 1) + PAD_R + 0.6, self.y(r), " ".join(map(str, self.right[r])), F_WIRE, "left")

        # 部品の形と値
        for p in self.parts:
            if p.kind == "jumper":
                continue
            pts = [self.xy(c, r) for _n, c, r in p.pins]
            (xa, ya), (xb, yb) = pts[0], pts[-1]
            x, top, bot = xa, min(ya, yb), max(ya, yb)
            cy = (top + bot) / 2
            label = wd.PCB_LABEL[p.label]
            if p.kind in ("res", "diode", "ccap"):
                half = (bot - top) / 2 - 1.3 if p.kind != "ccap" else 1.75
                poly([(x - 0.9, cy - half), (x + 0.9, cy - half), (x + 0.9, cy + half), (x - 0.9, cy + half)], close=True)
                if p.kind == "ccap":  # 足の線
                    line(x, top + 1.3, x, cy - half)
                    line(x, cy + half, x, bot - 1.3)
                ty = cy
                if p.kind == "diode":  # 帯 = カソード (K) 側
                    ky = [yy for (n, _c, _r), (_xx, yy) in zip(p.pins, pts) if n == "K"][0]
                    sgn = -1 if ky < cy else 1
                    for d in (0.25, 0.45, 0.65):
                        line(x - 0.9, cy + sgn * (half - d), x + 0.9, cy + sgn * (half - d))
                    ty = cy - sgn * 0.4
                text(x, ty, label, F_PART, rot=math.pi / 2)
            elif p.kind == "ecap":
                r, n = 5.0, 90  # 直径 10mm の円。ほかの穴にかかる所は描かない
                ring = [(x + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                for q1, q2 in zip(ring[:-1], ring[1:]):
                    if all(math.hypot((q1[0] + q2[0]) / 2 - px, (q1[1] + q2[1]) / 2 - py) > dia / 2 + 0.45
                           for (px, py), (_h, dia, _n) in self.pads.items()):
                        line(*q1, *q2)
                for (n, _c, _r), (px, py) in zip(p.pins, pts):
                    text(px - 2.0, py, "+" if n == "+" else "-", 1.6)
                text(x + 2.9, cy, label, F_PART, rot=math.pi / 2)
            elif p.kind == "npn":
                # 3 つの穴を囲む枠。右の二重線が「印字のある平らな面」
                poly([(x - 0.6, top - 1.4), (x + 1.5, top - 1.4), (x + 1.5, bot + 1.4), (x - 0.6, bot + 1.4),
                      (x - 1.6, bot + 0.4), (x - 1.6, top - 0.4)], close=True)
                line(x + 1.8, top - 1.4, x + 1.8, bot + 1.4)
                for (n, _c, _r), (px, py) in zip(p.pins, pts):
                    text(px + 2.7, py, n, F_ROW)
                text(x + 4.3, cy, label, F_PART, rot=math.pi / 2)

        title = f"HAYAOSHI MK.1 HUB {'MASTER' if self.master else 'CHILD'} {REV}"
        text(self.W / 2, self.H - EDGE - F_ROW / 2, title, F_ROW)
        text(self.W / 2, self.H - EDGE - F_ROW / 2, "github.com/furdabu/hayaoshi-buzzer", F_ROW, flip=True)
        b.add(Graphics(0, 0, top_silk=top_silk, bottom_silk=bottom_silk))
        return b


# ============================================================================
#  書き出したファイルを読み直して調べる
# ============================================================================
def seg_dist(a, b) -> float:
    """線分 a=(x1,y1,x2,y2) と b の中心線どうしの最短距離"""
    def pt_seg(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])

    a, b = a[:4], b[:4]
    a1, a2, b1, b2 = a[:2], a[2:4], b[:2], b[2:4]
    d1, d2, d3, d4 = cross(b1, b2, a1), cross(b1, b2, a2), cross(a1, a2, b1), cross(a1, a2, b2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 * d2 != 0 and d3 * d4 != 0:
        return 0.0
    return min(pt_seg(*a1, *b), pt_seg(*a2, *b), pt_seg(*b1, *a), pt_seg(*b2, *a))


def shapes_of(path: Path) -> list:
    """ガーバーの図形を (x1, y1, x2, y2, 太さ) の線分にする (丸いパッドは長さ 0 の線分)"""
    out = []
    for o in GerberFile.open(path).objects:
        d = getattr(o.aperture, "diameter", None)
        assert d is not None, f"{path.name}: 丸以外の形があります"
        name = type(o).__name__
        if name == "Flash":
            out.append((o.x, o.y, o.x, o.y, d))
        elif name == "Line":
            out.append((o.x1, o.y1, o.x2, o.y2, d))
        elif name == "Arc":
            n = 48
            cx, cy = o.x1 + o.cx, o.y1 + o.cy
            r = math.hypot(o.cx, o.cy)
            a0, a1 = math.atan2(o.y1 - cy, o.x1 - cx), math.atan2(o.y2 - cy, o.x2 - cx)
            sweep = (a0 - a1) % (2 * math.pi) if o.clockwise else (a1 - a0) % (2 * math.pi)
            sweep = sweep or 2 * math.pi
            sign = -1 if o.clockwise else 1
            pts = [(cx + r * math.cos(a0 + sign * sweep * i / n), cy + r * math.sin(a0 + sign * sweep * i / n)) for i in range(n + 1)]
            out += [(*p, *q, d) for p, q in zip(pts[:-1], pts[1:])]
        else:
            raise AssertionError(f"{path.name}: 知らない図形 {name}")
    return out


def check(d: Design, out_dir: Path) -> list:
    fy = lambda y: d.H - y  # noqa: E731
    msgs = []
    bottom = shapes_of(out_dir / f"{d.name}.GBL")
    top = shapes_of(out_dir / f"{d.name}.GTL")
    drills = [(o.x, o.y, o.tool.diameter) for o in ExcellonFile.open(out_dir / f"{d.name}-PTH.DRL").objects]

    # 1. つながり: 重なっている図形をまとめる
    parent = list(range(len(bottom)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(bottom)):
        for j in range(i + 1, len(bottom)):
            if seg_dist(bottom[i], bottom[j]) < (bottom[i][4] + bottom[j][4]) / 2 - 1e-6:
                parent[find(i)] = find(j)
    nets: dict = {}
    for (x, y), (_hole, _dia, name) in d.pads.items():
        hit = [i for i, s in enumerate(bottom) if s[0] == s[2] and s[1] == s[3] and math.hypot(s[0] - x, s[1] - fy(y)) < 1e-3]
        assert len(hit) == 1, f"{name}: 裏面にパッドがありません"
        nets.setdefault(find(hit[0]), set()).add(name)
    actual, want = {frozenset(g) for g in nets.values()}, d.expected_nets()
    if actual != want:
        for g in sorted(want - actual, key=sorted):
            msgs.append("つながっていない / 違う: " + ", ".join(sorted(g)))
        for g in sorted(actual - want, key=sorted):
            msgs.append("基板ではこうなっている: " + ", ".join(sorted(g)))

    # 2. 別の配線どうしのすき間
    gap = min((seg_dist(bottom[i], bottom[j]) - (bottom[i][4] + bottom[j][4]) / 2, i, j)
              for i in range(len(bottom)) for j in range(i + 1, len(bottom)) if find(i) != find(j))
    if gap[0] < MIN_GAP:
        msgs.append(f"配線のすき間が {gap[0]:.2f}mm しかありません ({bottom[gap[1]][:4]} と {bottom[gap[2]][:4]})")

    # 3. 穴とパッド
    assert len(drills) == len(d.pads) == len(top), "穴・パッドの数が合いません"
    ring = 9.9
    for x, y, dia in drills:
        for layer in (top, bottom):
            pad = [s[4] for s in layer if s[0] == s[2] and math.hypot(s[0] - x, s[1] - y) < 1e-3]
            assert pad, f"穴 ({x:.2f}, {y:.2f}) にパッドがありません"
            ring = min(ring, (pad[0] - dia) / 2)
    if ring < MIN_RING:
        msgs.append(f"穴のまわりの銅はくが {ring:.2f}mm しかありません")

    # 4. 基板の端までのすき間
    edge = min(min(s[0], s[2], d.W - s[0], d.W - s[2], s[1], s[3], d.H - s[1], d.H - s[3]) - s[4] / 2 for s in bottom + top)
    if edge < MIN_EDGE:
        msgs.append(f"銅はくが基板の端から {edge:.2f}mm しか離れていません")

    # 5. 印刷がパッド (はんだ付けする所) に重なっていないか、基板からはみ出していないか
    silk = shapes_of(out_dir / f"{d.name}.GTO")
    over = 9.9
    names = {(round(x, 3), round(fy(y), 3)): n for (x, y), (_h, _d, n) in d.pads.items()}
    near: dict = {}
    for s in silk:
        for t in top:
            g = seg_dist(s, t) - (s[4] + t[4]) / 2
            over = min(over, g)
            if g < 0.1:
                key = names[(round(t[0], 3), round(t[1], 3))]
                near[key] = min(near.get(key, 9.9), g)
    if over < 0.1:
        msgs.append("印刷がパッドに近すぎます: " + ", ".join(f"{k} ({v:.2f}mm)" for k, v in sorted(near.items())))
    out = min(min(s[0], s[2], d.W - s[0], d.W - s[2], s[1], s[3], d.H - s[1], d.H - s[3]) - s[4] / 2
              for s in silk + shapes_of(out_dir / f"{d.name}.GBO"))
    if out < 0.3:
        msgs.append(f"印刷が基板の端に近すぎます ({out:.2f}mm)")

    tools = sorted({t for _x, _y, t in drills})
    print(f"  {d.name}: {d.W:.1f} x {d.H:.1f}mm, 穴 {len(drills)} 個 (直径 {', '.join(f'{t:.1f}' for t in tools)}mm), "
          f"つながり {len(want)} 組, 配線のすき間 最小 {gap[0]:.2f}mm, 端まで {edge:.2f}mm, 印刷とパッド {over:.2f}mm")
    return msgs


def fix_gerber_syntax(path: Path) -> None:
    """gerbonara 1.6 は G75 の行末の * を書かない。きびしい読み取りソフトでも読めるように補い、
    すべての行が * か *% で終わっていることを確かめる"""
    lines = path.read_text().splitlines()
    lines = ["G75*" if ln.strip() == "G75" else ln for ln in lines]
    bad = [ln for ln in lines if ln.strip() and not ln.rstrip().endswith(("*", "*%"))]
    assert not bad, f"{path.name}: ガーバーの文法に合わない行があります {bad[:3]}"
    path.write_text("\n".join(lines) + "\n")


def export(d: Design) -> None:
    board = d.build()
    out_dir = HERE / f"hub_{d.kind}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():
        old.unlink()
    board.layer_stack().save_to_directory(out_dir, naming_scheme=NAMING, board_name=d.name)
    for f in list(out_dir.iterdir()):  # 使わない層 (はんだペースト・めっきなしの穴) は入れない
        if f.suffix in (".GTP", ".GBP") or f.name.endswith("-NPTH.DRL"):
            f.unlink()
        elif f.suffix != ".DRL":
            fix_gerber_syntax(f)
    IMG.mkdir(parents=True, exist_ok=True)
    for side in ("top", "bottom"):
        svg = str(board.pretty_svg(side=side))
        svg = re.sub(r'<svg width="[^"]+" height="[^"]+"', f'<svg width="{d.W * 14:.0f}" height="{d.H * 14:.0f}"', svg, count=1)
        (IMG / f"hub_{d.kind}_{side}.svg").write_text(svg, encoding="utf-8")
    problems = check(d, out_dir)
    if problems:
        raise SystemExit(f"{d.name}: 基板データに問題があります\n  " + "\n  ".join(problems))
    with zipfile.ZipFile(HERE / f"{d.name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out_dir.iterdir()):
            info = zipfile.ZipInfo(f.name, date_time=(2026, 1, 1, 0, 0, 0))  # 中身が同じなら zip も同じになるように
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())


def main() -> None:
    print("中継基板のプリント基板を作成:")
    for kind in ("child", "master"):
        export(Design(kind))
    print(f"  zip は {HERE.name}/ に、見た目の図は docs/images/pcb/ に書き出しました")


if __name__ == "__main__":
    main()
