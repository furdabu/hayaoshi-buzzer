#!/usr/bin/env python3
"""配線マニュアル (docs/soldering-guide.md) 用の図を作る。

    python hardware/wiring/make_diagrams.py

- 標準ライブラリだけで動く。出力は docs/images/wiring/*.svg
- docs/soldering-guide.md と docs/hub-stripboard.md の <!-- AUTO:名前 --> 〜 <!-- /AUTO --> の間の表も、
  同じデータから書き直す
- 配線の内容は下の「データ」に 1 か所だけ書いてあり、図はすべてそこから描く
- 描く前に「中継基板 + 線」をたどった接続が、期待する回路 (EXPECTED_*) と同じかを照合する。
  食い違っていたら図を作らずにエラーで止まる
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "images" / "wiring"
GUIDE = Path(__file__).resolve().parents[2] / "docs" / "soldering-guide.md"
STRIP_GUIDE = Path(__file__).resolve().parents[2] / "docs" / "hub-stripboard.md"
FONT = "'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans JP','Yu Gothic',Meiryo,sans-serif"

# 線の色 (図の色, 手順書に書く色の例)
NET = {
    "bat": ("#e03131", "赤"),
    "gnd": ("#212529", "黒"),
    "5v": ("#f08c00", "橙"),
    "led5": ("#d9480f", "橙"),
    "12v": ("#c2255c", "桃"),
    "data": ("#2f9e44", "緑"),
    "btn": ("#1971c2", "青"),
    "btn2": ("#1098ad", "水色"),
    "ctl": ("#e6b400", "黄"),
    "ledk": ("#7048e8", "紫"),
    "sense": ("#868e96", "灰"),
    "ser": ("#0b7285", "水色"),
    "ser2": ("#5c940d", "黄緑"),
    "spk": ("#8d6e63", "茶"),
    "3v3": ("#e8590c", "橙"),
    "clk": ("#3b5bdb", "青"),
    "dio": ("#ae3ec9", "紫"),
}
INK = "#212529"
MUTED = "#868e96"

# ============================================================================
#  データ 1: 中継基板
#  行 (1, 2, 3...) は裏の銅はくで横 1 列がつながっている。列は a〜n
# ============================================================================
COLS = "abcdefghijklmn"

# 行番号: (呼び名, 色)
ROW_INFO = {
    1: ("ベース (線なし)", None),
    2: ("ボタン LED −", "ledk"),
    3: ("GND", "gnd"),
    4: ("GND", "gnd"),
    5: ("ボタン LED 信号", "ctl"),
    6: ("LED 電源", "led5"),
    7: ("電池測定", "sense"),
    8: ("データ 入口", "data"),
    9: ("5V", "5v"),
    10: ("電池 +", "bat"),
    11: ("データ 出口", "data"),
    12: ("GND", "gnd"),
    13: ("音 送信 入口", "ser"),
    14: ("音 受信 入口", "ser2"),
    15: ("(使わない)", None),
    16: ("音 送信 出口", "ser"),
    17: ("音 受信 出口", "ser2"),
}
ROWS_CHILD = 11
ROWS_MASTER = 17


@dataclass
class Part:
    key: str
    kind: str  # res / diode / ecap / ccap / npn / jumper
    label: str
    pins: list  # [(ピン名, 列, 行)]
    master_only: bool = False


PARTS = [
    Part("R1k", "res", "1kΩ", [("1", "c", 5), ("2", "c", 1)]),
    Part("R10k", "res", "10kΩ", [("1", "d", 1), ("2", "d", 4)]),
    Part("J1", "jumper", "", [("1", "e", 3), ("2", "e", 4)]),
    Part("Q", "npn", "2SC1815", [("B", "f", 1), ("C", "f", 2), ("E", "f", 3)]),
    Part("Rb", "res", "100kΩ", [("1", "g", 7), ("2", "g", 4)]),
    Part("Cc", "ccap", "0.1µF", [("1", "h", 7), ("2", "h", 4)]),
    Part("Ce", "ecap", "1000µF", [("+", "k", 6), ("-", "k", 4)]),
    Part("Di", "diode", "1N4001", [("K", "i", 6), ("A", "i", 9)]),
    Part("Rt", "res", "100kΩ", [("1", "d", 10), ("2", "d", 7)]),
    Part("R330", "res", "330Ω", [("1", "e", 8), ("2", "e", 11)]),
    Part("Cdf", "ecap", "1000µF", [("+", "h", 10), ("-", "h", 12)], True),
    Part("J2", "jumper", "", [("1", "n", 4), ("2", "n", 12)], True),
    Part("Rtx", "res", "1kΩ", [("1", "c", 13), ("2", "c", 16)], True),
    Part("Rrx", "res", "1kΩ", [("1", "e", 14), ("2", "e", 17)], True),
]
ECAP_R = 1.97  # 電解コンデンサの胴体の半径 (穴の間隔を 1 として。直径 10mm)
# 注文した基板 (プリント基板) に印刷する部品の名前。hardware/pcb/make_pcb.py が使う
PCB_LABEL = {"1kΩ": "1k", "10kΩ": "10k", "100kΩ": "100k", "330Ω": "330", "1N4001": "4001", "0.1µF": "104",
             "1000µF": "1000u", "2SC1815": "C1815"}


# ============================================================================
#  データ 2: 線。番号は手順書の表と同じ
# ============================================================================
@dataclass
class Wire:
    num: int
    net: str
    a: tuple
    b: tuple


def H(row: int, side: str) -> tuple:
    """中継基板の行。side は図でどちら側に描くか ("L" / "R")"""
    return ("hub", row, side)


CHILD_WIRES = [
    Wire(1, "bat", ("bat", "+"), ("tp", "B+")),
    Wire(2, "gnd", ("bat", "-"), ("tp", "B-")),
    Wire(3, "bat", ("tp", "OUT+"), ("psw", "SW1")),
    Wire(4, "bat", ("psw", "SW2"), H(10, "L")),
    Wire(5, "gnd", ("tp", "OUT-"), H(3, "L")),
    Wire(6, "bat", H(10, "L"), ("mt5", "VIN+")),
    Wire(7, "gnd", H(3, "L"), ("mt5", "VIN-")),
    Wire(8, "bat", H(10, "R"), ("mt12", "VIN+")),
    Wire(9, "gnd", H(4, "R"), ("mt12", "VIN-")),
    Wire(10, "5v", ("mt5", "VOUT+"), H(9, "L")),
    Wire(11, "gnd", ("mt5", "VOUT-"), H(4, "L")),
    Wire(12, "5v", H(9, "R"), ("esp", "5V")),
    Wire(13, "gnd", H(3, "R"), ("esp", "GND")),
    Wire(14, "sense", ("esp", "D0"), H(7, "R")),
    Wire(15, "data", ("esp", "D2"), H(8, "R")),
    Wire(16, "ctl", ("esp", "D3"), H(5, "R")),
    Wire(17, "data", H(11, "R"), ("led", "IN")),
    Wire(18, "led5", H(6, "R"), ("led", "PWR")),
    Wire(19, "gnd", H(3, "R"), ("led", "GND")),
    Wire(20, "btn", ("esp", "D1"), ("btn", "NO")),
    Wire(21, "gnd", H(4, "R"), ("btn", "COM")),
    Wire(22, "12v", ("mt12", "VOUT+"), ("btn", "LED+")),
    Wire(23, "ledk", H(2, "R"), ("btn", "LED-")),
    Wire(24, "5v", H(9, "L"), ("psw", "LED+")),
    Wire(25, "gnd", H(4, "L"), ("psw", "LED-")),
]
# ステップ 2 (線 10・11) は MT3608 の電圧を合わせてからつなぐので、ステップ 1 と分けてある
CHILD_STEPS = [
    ("電源の入口", range(1, 10)),
    ("5V をつなぐ (電圧を合わせてから)", range(10, 12)),
    ("マイコン", range(12, 17)),
    ("ランプ", range(17, 20)),
    ("ボタン", range(20, 24)),
    ("電源ボタンの LED", range(24, 26)),
]

MASTER_WIRES = [
    Wire(1, "bat", ("bat", "+"), ("tp", "B+")),
    Wire(2, "gnd", ("bat", "-"), ("tp", "B-")),
    Wire(3, "bat", ("tp", "OUT+"), ("psw", "C")),
    Wire(4, "bat", ("psw", "NO"), H(10, "L")),
    Wire(5, "gnd", ("tp", "OUT-"), H(3, "L")),
    Wire(6, "bat", H(10, "L"), ("mt5", "VIN+")),
    Wire(7, "gnd", H(3, "L"), ("mt5", "VIN-")),
    Wire(8, "bat", H(10, "R"), ("mt12", "VIN+")),
    Wire(9, "gnd", H(12, "R"), ("mt12", "VIN-")),
    Wire(10, "5v", ("mt5", "VOUT+"), H(9, "L")),
    Wire(11, "gnd", ("mt5", "VOUT-"), H(4, "L")),
    Wire(12, "5v", H(9, "R"), ("esp", "5V")),
    Wire(13, "gnd", H(3, "R"), ("esp", "GND_A")),
    Wire(14, "sense", ("esp", "35"), H(7, "R")),
    Wire(15, "data", ("esp", "27"), H(8, "R")),
    Wire(16, "ctl", ("esp", "26"), H(5, "R")),
    Wire(17, "data", H(11, "R"), ("led", "IN")),
    Wire(18, "led5", H(6, "R"), ("led", "PWR")),
    Wire(19, "gnd", H(3, "R"), ("led", "GND")),
    Wire(20, "btn", ("esp", "32"), ("ok", "NO")),
    Wire(21, "btn2", ("esp", "33"), ("ng", "NO")),
    Wire(22, "gnd", H(4, "R"), ("ok", "COM")),
    Wire(23, "gnd", ("ok", "COM#2"), ("ng", "COM")),
    Wire(24, "12v", ("mt12", "VOUT+"), ("ok", "LED+")),
    Wire(25, "12v", ("ok", "LED+#2"), ("ng", "LED+")),
    Wire(26, "ledk", H(2, "R"), ("ok", "LED-")),
    Wire(27, "ledk", ("ok", "LED-#2"), ("ng", "LED-")),
    Wire(28, "5v", H(9, "L"), ("psw", "LED+")),
    Wire(29, "gnd", H(4, "L"), ("psw", "LED-")),
    Wire(30, "bat", H(10, "L"), ("df", "VCC")),
    Wire(31, "gnd", H(12, "L"), ("df", "GND")),
    Wire(32, "ser", ("esp", "17"), H(13, "R")),
    Wire(33, "ser", H(16, "L"), ("df", "RX")),
    Wire(34, "ser2", ("df", "TX"), H(14, "L")),
    Wire(35, "ser2", H(17, "R"), ("esp", "16")),
    Wire(36, "spk", ("df", "SPK_1"), ("spk", "1")),
    Wire(37, "spk", ("df", "SPK_2"), ("spk", "2")),
    Wire(38, "3v3", ("esp", "3V3"), ("tm", "VCC")),
    Wire(39, "gnd", ("esp", "GND_B"), ("tm", "GND")),
    Wire(40, "clk", ("esp", "18"), ("tm", "CLK")),
    Wire(41, "dio", ("esp", "19"), ("tm", "DIO")),
]
MASTER_STEPS = [
    ("電源の入口", range(1, 10)),
    ("5V をつなぐ (電圧を合わせてから)", range(10, 12)),
    ("マイコン", range(12, 17)),
    ("ランプ", range(17, 20)),
    ("正解・不正解ボタン", range(20, 28)),
    ("電源ボタンの LED", range(28, 30)),
    ("音 (DFPlayer とスピーカー)", range(30, 38)),
    ("4 桁表示", range(38, 42)),
]

# ============================================================================
#  データ 3: 期待する回路 (docs/wiring.md と同じ内容を、図とは別に書いたもの)
# ============================================================================
EXPECTED_CHILD = [
    {"bat.+", "tp.B+"},
    {"bat.-", "tp.B-"},
    {"tp.OUT+", "psw.SW1"},
    {"psw.SW2", "mt5.VIN+", "mt12.VIN+", "Rt.1"},
    {"tp.OUT-", "mt5.VIN-", "mt5.VOUT-", "mt12.VIN-", "esp.GND", "led.GND", "btn.COM", "psw.LED-",
     "Ce.-", "Q.E", "R10k.2", "Rb.2", "Cc.2", "J1.1", "J1.2"},
    {"mt5.VOUT+", "esp.5V", "psw.LED+", "Di.A"},
    {"Di.K", "Ce.+", "led.PWR"},
    {"esp.D2", "R330.1"},
    {"R330.2", "led.IN"},
    {"esp.D1", "btn.NO"},
    {"Rt.2", "Rb.1", "Cc.1", "esp.D0"},
    {"esp.D3", "R1k.1"},
    {"R1k.2", "R10k.1", "Q.B"},
    {"Q.C", "btn.LED-"},
    {"mt12.VOUT+", "btn.LED+"},
]
EXPECTED_MASTER = [
    {"bat.+", "tp.B+"},
    {"bat.-", "tp.B-"},
    {"tp.OUT+", "psw.C"},
    {"psw.NO", "mt5.VIN+", "mt12.VIN+", "Rt.1", "df.VCC", "Cdf.+"},
    {"tp.OUT-", "mt5.VIN-", "mt5.VOUT-", "mt12.VIN-", "esp.GND_A", "esp.GND_B", "led.GND", "ok.COM", "ng.COM",
     "psw.LED-", "df.GND", "tm.GND", "Ce.-", "Cdf.-", "Q.E", "R10k.2", "Rb.2", "Cc.2",
     "J1.1", "J1.2", "J2.1", "J2.2"},
    {"mt5.VOUT+", "esp.5V", "psw.LED+", "Di.A"},
    {"Di.K", "Ce.+", "led.PWR"},
    {"esp.27", "R330.1"},
    {"R330.2", "led.IN"},
    {"esp.32", "ok.NO"},
    {"esp.33", "ng.NO"},
    {"Rt.2", "Rb.1", "Cc.1", "esp.35"},
    {"esp.26", "R1k.1"},
    {"R1k.2", "R10k.1", "Q.B"},
    {"Q.C", "ok.LED-", "ng.LED-"},
    {"mt12.VOUT+", "ok.LED+", "ng.LED+"},
    {"esp.17", "Rtx.1"},
    {"Rtx.2", "df.RX"},
    {"df.TX", "Rrx.1"},
    {"Rrx.2", "esp.16"},
    {"df.SPK_1", "spk.1"},
    {"df.SPK_2", "spk.2"},
    {"esp.3V3", "tm.VCC"},
    {"esp.18", "tm.CLK"},
    {"esp.19", "tm.DIO"},
]
# 部品の中でつながっている端子 (親機の ESP32 には GND ピンが複数ある)
INTERNAL_MASTER = [("esp.GND_A", "esp.GND_B")]


def parts_for(master: bool) -> list:
    return [p for p in PARTS if master or not p.master_only]


def verify(name: str, wires: list, master: bool, expected: list, internal=()) -> None:
    """中継基板と線をたどって、つながっている端子の組が expected と同じか調べる"""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    def term(end):
        if end[0] == "hub":
            return ("row", end[1])
        return f"{end[0]}.{end[1].split('#')[0]}"

    rows = ROWS_MASTER if master else ROWS_CHILD
    for p in parts_for(master):
        for pin, _col, row in p.pins:
            assert 1 <= row <= rows, f"{name}: {p.key} が基板の外"
            union(f"{p.key}.{pin}", ("row", row))
        if p.kind == "jumper":  # ジャンパーは両端がつながっている
            union(f"{p.key}.1", f"{p.key}.2")
    for w in wires:
        for end in (w.a, w.b):
            if end[0] == "hub":
                assert 1 <= end[1] <= rows, f"{name}: 線 {w.num} が基板の外"
        union(term(w.a), term(w.b))
    for x, y in internal:
        union(x, y)

    groups: dict = {}
    for x in list(parent):
        if isinstance(x, str):
            groups.setdefault(find(x), set()).add(x)
    actual = {frozenset(g) for g in groups.values() if len(g) > 1}
    want = {frozenset(g) for g in expected}
    if actual != want:
        lines = [f"{name}: 図の接続が期待する回路と違います"]
        for g in sorted(want - actual, key=sorted):
            lines.append("  足りない / 違う: " + ", ".join(sorted(g)))
        for g in sorted(actual - want, key=sorted):
            lines.append("  図ではこうなっている: " + ", ".join(sorted(g)))
        raise SystemExit("\n".join(lines))
    singles = [x for x, g in ((x, groups[find(x)]) for x in parent if isinstance(x, str)) if len(g) == 1]
    assert not singles, f"{name}: どこにもつながっていない端子 {singles}"
    print(f"  {name}: 接続 OK ({len(want)} 組, 線 {len(wires)} 本)")


# ============================================================================
#  SVG の部品
# ============================================================================
class Svg:
    def __init__(self, w: float, h: float, title: str):
        self.w, self.h = w, h
        self.items = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'font-family="{FONT}" role="img">',
            f"<title>{escape(title)}</title>",
            f'<rect width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>',
        ]

    def add(self, s: str) -> None:
        self.items.append(s)

    def rect(self, x, y, w, h, fill, stroke="none", sw=1.0, rx=0.0, extra=""):
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}" {extra}/>')

    def circle(self, x, y, r, fill, stroke="none", sw=1.0, extra=""):
        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>')

    def line(self, x1, y1, x2, y2, stroke, sw=1.0, extra=""):
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
                 f'stroke-width="{sw}" stroke-linecap="round" {extra}/>')

    def path(self, d, stroke, sw=1.0, fill="none", extra=""):
        self.add(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round" '
                 f'stroke-linejoin="round" {extra}/>')

    def text(self, x, y, s, size=15, fill=INK, anchor="start", weight="normal", extra=""):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
                 f'font-weight="{weight}" dominant-baseline="central" {extra}>{escape(str(s))}</text>')

    def badge(self, x, y, num, color, r=11):
        """線の番号 (丸)"""
        dark = color in ("#e6b400",)
        self.circle(x, y, r, color, "#ffffff", 1.6)
        self.text(x, y + 0.5, num, 12.5 if num < 10 else 11.5, INK if dark else "#ffffff", "middle", "bold")

    def rownum(self, x, y, num, fill="#ffffff", size=20):
        """中継基板の行番号 (四角)"""
        self.rect(x - size / 2, y - size / 2, size, size, fill, INK, 1.3, 3)
        self.text(x, y + 0.5, num, 12.5, INK, "middle", "bold")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.items + ["</svg>"]) + "\n", encoding="utf-8")


def tint(color: str, amount: float = 0.86) -> str:
    """色を白に近づける"""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(c + (255 - c) * amount) for c in (r, g, b))


def rounded(pts: list, r: float = 7.0) -> str:
    """折れ線の角を丸めた path"""
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr
        bx, by = x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr
        d += f" L{ax:.1f},{ay:.1f} Q{x1:.1f},{y1:.1f} {bx:.1f},{by:.1f}"
    return d + f" L{pts[-1][0]:.1f},{pts[-1][1]:.1f}"


# ============================================================================
#  全体の配線図 (部品を箱、線を番号つきの色線で描く)
# ============================================================================
GAP = 28  # 端子の間隔
HEAD = 52  # 箱の見出しの高さ


class Mod:
    """部品 1 個。pins は [(キー, 表示名)]。キーが None の行は小見出し"""

    def __init__(self, key, title, sub, pins, side, tone="#495057"):
        self.key, self.title, self.sub, self.pins, self.side, self.tone = key, title, sub, pins, side, tone
        self.x = self.y = 0.0
        self.w = 200.0

    @property
    def h(self) -> float:
        return HEAD + len(self.pins) * GAP + 8

    def pin(self, key: str) -> tuple:
        for i, (k, _label) in enumerate(self.pins):
            if k == key:
                x = self.x + self.w if self.side == "R" else self.x
                return x, self.y + HEAD + (i + 0.5) * GAP
        raise KeyError(f"{self.key}.{key}")

    def draw(self, s: Svg, used: set, dim: bool) -> None:
        tone = "#adb5bd" if dim else self.tone
        ink = MUTED if dim else INK
        s.rect(self.x, self.y, self.w, self.h, "#f8f9fa", tone, 1.6, 8)
        s.path(f"M{self.x:.1f},{self.y + HEAD - 8:.1f} v-{HEAD - 16} a8,8 0 0 1 8,-8 h{self.w - 16:.1f} a8,8 0 0 1 8,8 "
               f"v{HEAD - 16} z", "none", 0, tone)
        s.text(self.x + self.w / 2, self.y + 17, self.title, 15.5, "#ffffff", "middle", "bold")
        s.text(self.x + self.w / 2, self.y + 35, self.sub, 12, "#f1f3f5", "middle")
        for i, (k, label) in enumerate(self.pins):
            y = self.y + HEAD + (i + 0.5) * GAP
            if k is None:
                s.text(self.x + self.w / 2, y + 2, label, 11.5, MUTED, "middle")
                continue
            px = self.x + self.w if self.side == "R" else self.x
            on = k in used
            s.rect(px - 6, y - 6, 12, 12, "#ffd43b" if on else "#dee2e6", "#495057" if on else "#adb5bd", 1.2, 2)
            if self.side == "R":
                s.text(px - 14, y + 0.5, label, 14.5, ink if on else MUTED, "end", "bold" if on else "normal")
            else:
                s.text(px + 14, y + 0.5, label, 14.5, ink if on else MUTED, "start", "bold" if on else "normal")


class Hub:
    """中継基板。行ごとに、左右につながる線の数だけ端子を並べる"""

    def __init__(self, rows: int, wires: list):
        self.rows, self.x, self.y, self.w = rows, 0.0, 0.0, 230.0
        self.ends: dict = {}  # (行, 側) -> [線番号]
        for w in wires:
            for end in (w.a, w.b):
                if end[0] == "hub":
                    self.ends.setdefault((end[1], end[2]), []).append(w.num)
        self.row_h = {r: max(1, len(self.ends.get((r, "L"), [])), len(self.ends.get((r, "R"), []))) * GAP
                      for r in range(1, rows + 1)}

    @property
    def h(self) -> float:
        return HEAD + sum(self.row_h.values()) + 8

    def row_top(self, row: int) -> float:
        return self.y + HEAD + sum(self.row_h[r] for r in range(1, row))

    def pin(self, row: int, side: str, num: int) -> tuple:
        nums = self.ends[(row, side)]
        top = self.row_top(row) + (self.row_h[row] - len(nums) * GAP) / 2
        return (self.x if side == "L" else self.x + self.w), top + (nums.index(num) + 0.5) * GAP

    def draw(self, s: Svg, active_rows: set, hi: set) -> None:
        tone = "#0b7285"
        s.rect(self.x, self.y, self.w, self.h, "#f8f9fa", tone, 2, 8)
        s.path(f"M{self.x:.1f},{self.y + HEAD - 8:.1f} v-{HEAD - 16} a8,8 0 0 1 8,-8 h{self.w - 16:.1f} a8,8 0 0 1 8,8 "
               f"v{HEAD - 16} z", "none", 0, tone)
        s.text(self.x + self.w / 2, self.y + 17, "中継基板", 15.5, "#ffffff", "middle", "bold")
        s.text(self.x + self.w / 2, self.y + 35, "□ の数字 = 行の番号", 12, "#e3fafc", "middle")
        for r in range(1, self.rows + 1):
            top, h = self.row_top(r), self.row_h[r]
            name, net = ROW_INFO[r]
            on = r in active_rows
            fill = tint(NET[net][0]) if (net and on) else "#f1f3f5"
            s.rect(self.x + 8, top + 2, self.w - 16, h - 4, fill, "#ced4da", 1, 5)
            s.rownum(self.x + 30, top + h / 2, r)
            s.text(self.x + 50, top + h / 2 + 0.5, name, 14, INK if on else MUTED, "start", "bold" if on else "normal")
            for side in "LR":
                for n in self.ends.get((r, side), []):
                    px, py = self.pin(r, side, n)
                    lit = n in hi
                    s.rect(px - 6, py - 6, 12, 12, "#ffd43b" if lit else "#dee2e6", "#495057" if lit else "#adb5bd", 1.2, 2)


def stack(mods: list, x: float, y: float, gap: float = 22) -> float:
    for m in mods:
        m.x, m.y = x, y
        y += m.h + gap
    return y - gap


def route_channel(items: list, x0: float, x1: float, seed: int) -> dict:
    """縦の通路に線を 1 本ずつ割り当てる。交差と重なりが少ない並びを探す"""
    n = len(items)
    if n == 0:
        return {}
    pitch = min(14.0, (x1 - x0) / max(1, n - 1))
    start = (x0 + x1) / 2 - pitch * (n - 1) / 2
    xs = [start + i * pitch for i in range(n)]

    def cost(order: list) -> float:
        seg = []
        for slot, idx in enumerate(order):
            _num, (xa, ya), (xb, yb) = items[idx]
            xt = xs[slot]
            seg.append(((min(xa, xt), max(xa, xt), ya), (min(xb, xt), max(xb, xt), yb), (xt, min(ya, yb), max(ya, yb))))
        c = 0.0
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                xt, y0, y1 = seg[j][2]
                for hx0, hx1, hy in seg[i][:2]:
                    if hx0 < xt < hx1 and y0 < hy < y1:
                        c += 1
                if i < j:
                    for a in seg[i][:2]:
                        for b in seg[j][:2]:
                            if abs(a[2] - b[2]) < 9 and min(a[1], b[1]) - max(a[0], b[0]) > 0.5:
                                c += 1000
            c += (seg[i][0][1] - seg[i][0][0] + seg[i][1][1] - seg[i][1][0]) * 0.0004
        return c

    rng = random.Random(seed)
    best, best_c = None, float("inf")
    for _ in range(40):
        order = list(range(n))
        rng.shuffle(order)
        cur = cost(order)
        improved = True
        while improved:
            improved = False
            for i in range(n):
                for j in range(i + 1, n):
                    order[i], order[j] = order[j], order[i]
                    c = cost(order)
                    if c < cur - 1e-9:
                        cur, improved = c, True
                    else:
                        order[i], order[j] = order[j], order[i]
        if cur < best_c:
            best, best_c = order[:], cur
    if best_c >= 1000:
        print(f"    注意: 線の重なりが残っています (cost={best_c:.0f})")
    return {items[idx][0]: xs[slot] for slot, idx in enumerate(best)}


class Pictorial:
    def __init__(self, title: str, left: list, right: list, wires: list, rows: int):
        self.title, self.left, self.right, self.wires = title, left, right, wires
        self.mods = {m.key: m for m in left + right}
        self.hub = Hub(rows, wires)
        n_l = sum(1 for w in wires if self.chan(w) == "L")
        n_r = len(wires) - n_l
        chan_l, chan_r = 76 + 14 * (n_l - 1), 76 + 14 * (n_r - 1)
        top = 64
        lx = 24
        for m in left:
            m.w = 196
        for m in right:
            m.w = 214
        self.hub.x = lx + 196 + chan_l
        rx = self.hub.x + self.hub.w + chan_r
        lh = sum(m.h for m in left) + 22 * (len(left) - 1)
        rh = sum(m.h for m in right) + 22 * (len(right) - 1)
        body = max(lh, rh, self.hub.h)
        stack(left, lx, top + (body - lh) / 2)
        stack(right, rx, top + (body - rh) / 2)
        self.hub.y = top + (body - self.hub.h) / 2
        self.W, self.Ht = rx + 214 + 24, top + body + 58
        self.trunk = {}
        for name, x0, x1, seed in (("L", lx + 196 + 38, self.hub.x - 38, 3), ("R", self.hub.x + self.hub.w + 38, rx - 38, 5)):
            items = [(w.num, self.xy(w, w.a), self.xy(w, w.b)) for w in wires if self.chan(w) == name]
            self.trunk.update(route_channel(items, x0, x1, seed))

    def chan(self, w: Wire) -> str:
        for end in (w.a, w.b):
            if end[0] != "hub":
                return self.mods[end[0]].side_of_hub
        raise ValueError(w)

    def xy(self, w: Wire, end: tuple) -> tuple:
        if end[0] == "hub":
            return self.hub.pin(end[1], end[2], w.num)
        return self.mods[end[0]].pin(end[1])

    def draw(self, path: Path, highlight=None, subtitle: str = "") -> None:
        hi = set(w.num for w in self.wires) if highlight is None else set(highlight)
        s = Svg(self.W, self.Ht, self.title + " " + subtitle)
        s.text(24, 26, self.title, 21, INK, "start", "bold")
        if subtitle:
            s.text(24, 50, subtitle, 14.5, "#495057")
        used, rows_on = set(), set()
        for w in self.wires:
            if w.num in hi:
                for end in (w.a, w.b):
                    if end[0] == "hub":
                        rows_on.add(end[1])
                    else:
                        used.add((end[0], end[1]))
        for w in self.wires:  # 今回つながない線はうすく
            if w.num not in hi:
                s.path(rounded(self.points(w)), "#dee2e6", 2.2)
        for m in self.left + self.right:
            mine = {k for (mk, k) in used if mk == m.key}
            m.draw(s, mine, not mine)
        self.hub.draw(s, rows_on, hi)
        for w in self.wires:
            if w.num in hi:
                d = rounded(self.points(w))
                s.path(d, "#ffffff", 6.5)
                s.path(d, NET[w.net][0], 3.6)
        for w in self.wires:
            if w.num in hi:
                (xa, ya), (xb, yb) = self.xy(w, w.a), self.xy(w, w.b)
                xt = self.trunk[w.num]
                for x, y in ((xa, ya), (xb, yb)):
                    s.badge(x + (20 if xt > x else -20), y, w.num, NET[w.net][0])
        y = self.Ht - 26
        s.badge(36, y, 1, "#495057")
        s.text(54, y, "= 線の番号 (手順書の表と同じ)", 13.5, "#495057")
        s.rownum(310, y, 3)
        s.text(328, y, "= 中継基板の行", 13.5, "#495057")
        s.rect(452, y - 6, 12, 12, "#ffd43b", "#495057", 1.2, 2)
        s.text(472, y, "= はんだ付けする端子", 13.5, "#495057")
        s.save(path)

    def points(self, w: Wire) -> list:
        (xa, ya), (xb, yb) = self.xy(w, w.a), self.xy(w, w.b)
        xt = self.trunk[w.num]
        return [(xa, ya), (xt, ya), (xt, yb), (xb, yb)]


def child_pictorial() -> Pictorial:
    left = [
        Mod("bat", "電池ボックス", "18650 を 1 本", [("+", "＋ (赤い線)"), ("-", "− (黒い線)")], "R", "#1864ab"),
        Mod("tp", "TP4056", "充電モジュール", [("B+", "B+"), ("B-", "B−"), ("OUT+", "OUT+"), ("OUT-", "OUT−")], "R", "#2b8a3e"),
        Mod("psw", "電源ボタン", "Pten 16mm",
            [("SW1", "スイッチ端子"), ("SW2", "スイッチ端子"), ("LED+", "LED ＋"), ("LED-", "LED −")], "R", "#5f3dc4"),
        Mod("mt5", "MT3608 (5V 用)", "先に 5.1V に調整",
            [("VIN+", "VIN+"), ("VIN-", "VIN−"), ("VOUT+", "VOUT+"), ("VOUT-", "VOUT−")], "R", "#d9480f"),
    ]
    right = [
        Mod("esp", "XIAO ESP32C6", "マイコン",
            [(None, "── 右の列 (上から) ──"), ("5V", "5V"), ("GND", "GND"),
             (None, "── 左の列 (上から) ──"), ("D0", "D0"), ("D1", "D1"), ("D2", "D2"), ("D3", "D3")], "L", "#2b8a3e"),
        Mod("led", "LED 基板", "WS2812B 7 連 (ランプ)", [("IN", "IN"), ("PWR", "PWR"), ("GND", "GND")], "L", "#1864ab"),
        Mod("btn", "アーケードボタン", "60mm",
            [("NO", "スイッチ NO"), ("COM", "スイッチ COM"), ("LED+", "LED ＋"), ("LED-", "LED −")], "L", "#c92a2a"),
        Mod("mt12", "MT3608 (12V 用)", "先に 12V に調整",
            [("VIN+", "VIN+"), ("VIN-", "VIN−"), ("VOUT+", "VOUT+")], "L", "#d9480f"),
    ]
    for m in left:
        m.side_of_hub = "L"
    for m in right:
        m.side_of_hub = "R"
    return Pictorial("子機の配線", left, right, CHILD_WIRES, ROWS_CHILD)


def master_pictorial() -> Pictorial:
    left = [
        Mod("bat", "電池ボックス", "18650 を 3 本 (並列)", [("+", "＋ (赤い線)"), ("-", "− (黒い線)")], "R", "#1864ab"),
        Mod("tp", "TP4056", "充電モジュール", [("B+", "B+"), ("B-", "B−"), ("OUT+", "OUT+"), ("OUT-", "OUT−")], "R", "#2b8a3e"),
        Mod("psw", "電源ボタン", "LA16-11D (5A)",
            [("C", "スイッチ C"), ("NO", "スイッチ NO"), ("LED+", "LED ＋"), ("LED-", "LED −")], "R", "#5f3dc4"),
        Mod("mt5", "MT3608 (5V 用)", "先に 5.1V に調整",
            [("VIN+", "VIN+"), ("VIN-", "VIN−"), ("VOUT+", "VOUT+"), ("VOUT-", "VOUT−")], "R", "#d9480f"),
        Mod("df", "DFPlayer Mini", "音を鳴らす",
            [("VCC", "VCC"), ("RX", "RX"), ("TX", "TX"), ("SPK_1", "SPK_1"), ("GND", "GND"), ("SPK_2", "SPK_2")], "R", "#2b8a3e"),
        Mod("spk", "スピーカー", "8Ω", [("1", "端子"), ("2", "端子")], "R", "#495057"),
    ]
    right = [
        Mod("esp", "ESP32-DevKitC-32E", "マイコン (38 ピン)",
            [(None, "── 3V3・5V がある列 ──"), ("3V3", "3V3"), ("35", "35"), ("32", "32"), ("33", "33"), ("26", "26"),
             ("27", "27"), ("GND_A", "GND"), ("5V", "5V"),
             (None, "── 反対の列 ──"), ("GND_B", "GND"), ("19", "19"), ("18", "18"), ("17", "17"), ("16", "16")],
            "L", "#2b8a3e"),
        Mod("tm", "TM1637", "4 桁表示", [("CLK", "CLK"), ("DIO", "DIO"), ("VCC", "VCC"), ("GND", "GND")], "L", "#1864ab"),
        Mod("led", "LED 基板", "WS2812B 7 連 (ランプ)", [("IN", "IN"), ("PWR", "PWR"), ("GND", "GND")], "L", "#1864ab"),
        Mod("ok", "正解ボタン (赤)", "司会者から見て右",
            [("NO", "スイッチ NO"), ("COM", "スイッチ COM"), ("COM#2", "　〃 (2 本目)"), ("LED+", "LED ＋"),
             ("LED+#2", "　〃 (2 本目)"), ("LED-", "LED −"), ("LED-#2", "　〃 (2 本目)")], "L", "#c92a2a"),
        Mod("ng", "不正解ボタン (青)", "司会者から見て左",
            [("NO", "スイッチ NO"), ("COM", "スイッチ COM"), ("LED+", "LED ＋"), ("LED-", "LED −")], "L", "#1864ab"),
        Mod("mt12", "MT3608 (12V 用)", "先に 12V に調整",
            [("VIN+", "VIN+"), ("VIN-", "VIN−"), ("VOUT+", "VOUT+")], "L", "#d9480f"),
    ]
    for m in left:
        m.side_of_hub = "L"
    for m in right:
        m.side_of_hub = "R"
    return Pictorial("親機の配線", left, right, MASTER_WIRES, ROWS_MASTER)


# ============================================================================
#  中継基板の部品配置図 (部品をのせる面から見た図)
# ============================================================================
P = 36.0  # 穴の間隔 (図の上での px)


def blocked_holes(master: bool) -> set:
    """部品の足や胴体でふさがる穴"""
    out = set()
    rows = ROWS_MASTER if master else ROWS_CHILD
    for p in parts_for(master):
        if p.kind == "jumper" and p.key == "J2":
            out.update((c, r) for _n, c, r in p.pins)
            continue
        cs = [COLS.index(c) for _n, c, _r in p.pins]
        rs = [r for _n, _c, r in p.pins]
        if p.kind == "ecap":
            cx, cy = cs[0], sum(rs) / 2
            for ci in range(len(COLS)):
                for r in range(1, rows + 1):
                    if math.hypot(ci - cx, r - cy) < ECAP_R:
                        out.add((COLS[ci], r))
        for r in range(min(rs), max(rs) + 1):
            out.add((COLS[cs[0]], r))
    return out


def wire_holes(wires: list, master: bool) -> dict:
    """線をはんだ付けする穴を、行の左右の端から順に割り当てる"""
    blocked = blocked_holes(master)
    taken: dict = {}
    for w in wires:
        for end in (w.a, w.b):
            if end[0] != "hub":
                continue
            row, side = end[1], end[2]
            for col in ("abc" if side == "L" else "nml"):
                if (col, row) not in blocked and (col, row) not in taken:
                    taken[(col, row)] = w
                    break
            else:
                raise SystemExit(f"線 {w.num}: 行 {row} の {side} 側に空いた穴がありません")
    return taken


def draw_board(path: Path, title: str, wires: list, master: bool) -> dict:
    rows = ROWS_MASTER if master else ROWS_CHILD
    ox, oy = 96.0, 118.0
    W = ox + (len(COLS) - 1) * P + 250
    Ht = oy + (rows - 1) * P + 122
    s = Svg(W, Ht, title)
    s.text(24, 26, title, 21, INK, "start", "bold")
    s.text(24, 50, "部品をのせる面から見た図。横 1 列 (同じ行) は裏の銅はくでつながっています", 14.5, "#495057")

    def xy(col: str, row: float) -> tuple:
        return ox + COLS.index(col) * P, oy + (row - 1) * P

    s.rect(ox - P * 0.75, oy - P * 0.75, (len(COLS) - 1) * P + P * 1.5, (rows - 1) * P + P * 1.5, "#e9dcc3", "#a68a5b", 1.6, 6)
    for ci, c in enumerate(COLS):
        s.text(ox + ci * P, oy - P * 1.08, c, 14, "#495057", "middle", "bold")
    for r in range(1, rows + 1):
        y = oy + (r - 1) * P
        name, net = ROW_INFO[r]
        s.rect(ox - P * 0.45, y - 8, (len(COLS) - 1) * P + P * 0.9, 16, "#d9a45b" if net or r == 1 else "#d8ccb4", "none", 0, 8,
               'opacity="0.55"')
        s.rownum(ox - P * 1.35, y, r, tint(NET[net][0], 0.7) if net else "#ffffff", 22)
        s.text(ox + (len(COLS) - 1) * P + P * 1.05, y + 0.5, name, 14, INK if net else MUTED, "start", "bold" if net else "normal")
        for ci in range(len(COLS)):
            s.circle(ox + ci * P, y, 4.2, "#ffffff", "#8c6d3f", 1.1)

    holes = wire_holes(wires, master)
    lead = "#6c757d"
    parts = parts_for(master)
    for p in parts:  # 電解コンデンサは大きいので先に (うすく) 描く
        if p.kind != "ecap":
            continue
        (xa, ya), (xb, yb) = xy(p.pins[0][1], p.pins[0][2]), xy(p.pins[1][1], p.pins[1][2])
        cx, cy = (xa + xb) / 2, (ya + yb) / 2
        s.circle(cx, cy, ECAP_R * P * 0.97, "#1c7ed6", "#1864ab", 1.6, 'fill-opacity="0.16" stroke-dasharray="6 4"')
    for p in parts:
        pts = [xy(c, r) for _n, c, r in p.pins]
        (xa, ya), (xb, yb) = pts[0], pts[-1]
        cx, cy = (xa + xb) / 2, (ya + yb) / 2
        if p.kind == "jumper":
            long = abs(yb - ya) > P * 1.5
            if long:
                s.path(f"M{xa:.1f},{ya:.1f} h19 V{yb:.1f} h-19", "#ffffff", 7)
                s.path(f"M{xa:.1f},{ya:.1f} h19 V{yb:.1f} h-19", "#212529", 3.6)
            else:
                s.line(xa, ya, xb, yb, "#212529", 4)
            for x, y in pts:
                s.circle(x, y, 5.2, "#212529")
        elif p.kind in ("res", "diode"):
            s.line(xa, ya, xb, yb, lead, 2.6)
            half = P * 0.92 if p.kind == "res" else P * 0.78
            fill, stroke, ink = ("#f3d9a4", "#a67c2e", INK) if p.kind == "res" else ("#343a40", "#212529", "#ffffff")
            s.rect(cx - 9.5, cy - half, 19, half * 2, fill, stroke, 1.3, 7)
            if p.kind == "diode":  # 帯 = カソード (K) 側
                k = [xy(c, r) for n, c, r in p.pins if n == "K"][0]
                by = cy - half + 5 if k[1] < cy else cy + half - 12
                s.rect(cx - 9.5, by, 19, 7, "#dee2e6")
            ty = cy
            if p.kind == "diode":
                ty = cy + (4 if k[1] < cy else -4)
            s.text(cx, ty, p.label, 10.5 if p.kind == "res" else 9, ink, "middle", "bold",
                   f'transform="rotate(-90 {cx:.1f} {ty:.1f})"')
            for x, y in pts:
                s.circle(x, y, 4.6, lead)
        elif p.kind == "ccap":
            s.line(xa, ya, xb, yb, lead, 2.6)
            s.add(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="9" ry="{P * 0.62:.1f}" fill="#f59f00" stroke="#b76e00" stroke-width="1.3"/>')
            s.text(cx, cy, "104", 10.5, INK, "middle", "bold", f'transform="rotate(-90 {cx:.1f} {cy:.1f})"')
            for x, y in pts:
                s.circle(x, y, 4.6, lead)
        elif p.kind == "ecap":
            for n, c, r in p.pins:
                x, y = xy(c, r)
                s.circle(x, y, 9.5, "#1864ab" if n == "+" else "#ffffff", "#1864ab", 2)
                s.text(x, y + 0.5, "＋" if n == "+" else "−", 13, "#ffffff" if n == "+" else "#1864ab", "middle", "bold")
            s.text(cx + 15, cy, p.label, 11.5, "#1864ab", "start", "bold")
        elif p.kind == "npn":
            x, y = pts[1]
            # 平らな面が右 (n 列側)。左がふくらんだ D 形
            s.path(f"M{x + 9:.1f},{y - 24:.1f} L{x + 9:.1f},{y + 24:.1f} L{x - 2:.1f},{y + 24:.1f} "
                   f"A24,24 0 0 1 {x - 2:.1f},{y - 24:.1f} Z", "#000000", 1.4, "#343a40", 'fill-opacity="0.88"')
            for (n, _c, _r), (px, py) in zip(p.pins, pts):
                s.circle(px, py, 4.6, "#dee2e6")
                s.text(px + 20, py + 0.5, n, 12.5, "#c92a2a", "middle", "bold")
            s.line(x + 9, y - 21, x + 9, y + 21, "#ffd43b", 4.5)  # 平らな面 (印字のある面)
    for (col, row), w in holes.items():
        x, y = xy(col, row)
        s.badge(x, y, w.num, NET[w.net][0], 12.5)

    y = oy + (rows - 1) * P + 62
    s.badge(36, y, 1, "#495057")
    s.text(54, y, "= その番号の線をはんだ付けする穴 (同じ行ならどの穴でも同じ)", 13.5, "#495057")
    s.rect(486, y - 6, 26, 12, "#343a40")
    s.rect(505, y - 6, 7, 12, "#dee2e6")
    s.text(522, y, "= ダイオードの帯", 13.5, "#495057")
    s.rect(24, y + 21, 5, 14, "#ffd43b", "#495057", 0.8)
    s.text(38, y + 28, "= トランジスタの平らな面 (印字のある面)。右 (n 列側) に向けます。＋ − はコンデンサの向きです", 13.5, "#495057")
    s.save(path)
    return holes


# ============================================================================
#  向きのある部品の図
# ============================================================================
def draw_parts(path: Path) -> None:
    W, Ht = 1040, 330
    s = Svg(W, Ht, "向きのある部品の見分け方")
    s.text(24, 26, "向きのある部品の見分け方", 21, INK, "start", "bold")
    pw = 240

    def panel(i: int, title: str) -> float:
        x = 24 + i * (pw + 12)
        s.rect(x, 50, pw, 262, "#f8f9fa", "#ced4da", 1.2, 8)
        s.text(x + pw / 2, 72, title, 15, INK, "middle", "bold")
        return x

    # トランジスタ
    x = panel(0, "トランジスタ 2SC1815")
    cx = x + pw / 2
    s.path(f"M{cx - 34},{178} v-52 a10,10 0 0 1 10,-10 h48 a10,10 0 0 1 10,10 v52 z", "#000", 1.4, "#343a40")
    s.text(cx, 140, "C1815", 15, "#ffffff", "middle", "bold")
    for dx, n in ((-24, "E"), (0, "C"), (24, "B")):
        s.line(cx + dx, 178, cx + dx, 232, "#868e96", 4)
        s.text(cx + dx, 250, n, 17, "#c92a2a", "middle", "bold")
    s.text(cx, 98, "印字のある平らな面を手前に", 12.5, "#495057", "middle")
    s.text(cx, 280, "左から E ・ C ・ B", 14, INK, "middle", "bold")
    s.text(cx, 299, "足を 2.54mm 間隔に広げて挿す", 12, "#495057", "middle")

    # ダイオード
    x = panel(1, "ダイオード 1N4001")
    cx = x + pw / 2
    s.line(cx - 92, 150, cx + 92, 150, "#868e96", 4)
    s.rect(cx - 44, 132, 88, 36, "#343a40", "#000", 1.4, 6)
    s.rect(cx + 20, 132, 14, 36, "#dee2e6")
    s.text(cx - 76, 128, "A", 16, "#c92a2a", "middle", "bold")
    s.text(cx + 76, 128, "K", 16, "#c92a2a", "middle", "bold")
    s.path(f"M{cx - 60},{200} H{cx + 52} m-10,-7 l10,7 l-10,7", "#1971c2", 2.6)
    s.text(cx, 224, "電気は帯のない側 → 帯のある側", 12.5, "#1971c2", "middle")
    s.text(cx, 98, "帯 (銀色の線) のある側が K", 12.5, "#495057", "middle")
    s.text(cx, 270, "帯を 6 行 (LED 電源) に", 14, INK, "middle", "bold")
    s.text(cx, 291, "反対側を 9 行 (5V) に", 14, INK, "middle", "bold")

    # 電解コンデンサ
    x = panel(2, "電解コンデンサ 1000µF")
    cx = x + pw / 2
    s.rect(cx - 30, 104, 60, 84, "#1c4f8a", "#0b3566", 1.4, 6)
    s.rect(cx + 12, 104, 18, 84, "#dee2e6", "none", 0, 3)
    for dy in (124, 146, 168):
        s.text(cx + 21, dy, "−", 15, "#1c4f8a", "middle", "bold")
    s.line(cx - 12, 188, cx - 12, 246, "#868e96", 4)
    s.line(cx + 12, 188, cx + 12, 232, "#868e96", 4)
    s.text(cx - 44, 236, "長い足", 12.5, "#495057", "end")
    s.text(cx - 44, 254, "＋", 17, "#c92a2a", "end", "bold")
    s.text(cx + 44, 222, "短い足", 12.5, "#495057", "start")
    s.text(cx + 44, 240, "− (帯の側)", 14, "#c92a2a", "start", "bold")
    s.text(cx, 284, "逆に付けると破裂します", 13.5, "#c92a2a", "middle", "bold")
    s.text(cx, 301, "＋ と − を必ず確認", 12, "#495057", "middle")

    # 抵抗の色
    x = panel(3, "抵抗の色の帯 (5 本帯)")
    col = {"橙": "#f76707", "黒": "#212529", "茶": "#8d5524", "赤": "#e03131"}
    for i, (val, bands) in enumerate((("330Ω", "橙橙黒黒茶"), ("1kΩ", "茶黒黒茶茶"), ("10kΩ", "茶黒黒赤茶"), ("100kΩ", "茶黒黒橙茶"))):
        y = 108 + i * 44
        s.text(x + 16, y, val, 15, INK, "start", "bold")
        bx = x + 88
        s.line(bx - 10, y, bx + 138, y, "#868e96", 3)
        s.rect(bx, y - 11, 128, 22, "#a5d8ff", "#4dabf7", 1.2, 9)
        for j, ch in enumerate(bands):
            s.rect(bx + 14 + j * 19 + (10 if j == 4 else 0), y - 11, 9, 22, col[ch])
        s.text(bx + 64, y + 21, " ".join(bands), 11.5, "#495057", "middle")
    s.text(x + pw / 2, 289, "迷ったらテスターで測る", 13.5, INK, "middle", "bold")
    s.text(x + pw / 2, 304, "抵抗に向きはありません", 12, "#495057", "middle")
    s.save(path)


# ============================================================================
#  マイコンなどのピンの位置
# ============================================================================
def pin_column(s: Svg, x: float, y: float, names: list, used: dict, side: str, gap: float = 25.0) -> None:
    """ピンの列。名前は基板の内側、線と番号は外側に描く"""
    d = -1 if side == "L" else 1
    for i, n in enumerate(names):
        py = y + i * gap
        key = n.strip()
        on = n in used
        s.circle(x, py, 7.5, "#ffd43b" if on else "#dee2e6", "#495057" if on else "#adb5bd", 1.3)
        s.text(x - d * 13, py + 0.5, key, 13.5, "#ffffff" if on else "#d8f5dd", "start" if side == "L" else "end",
               "bold" if on else "normal", "" if on else 'opacity="0.75"')
        if on:
            num, net, note = used[n]
            s.line(x + d * 9, py, x + d * 52, py, NET[net][0], 3)
            s.badge(x + d * 62, py, num, NET[net][0])
            s.text(x + d * 80, py + 0.5, note, 13, INK, "end" if side == "L" else "start")


def draw_pins_child(path: Path) -> None:
    W, Ht = 760, 372
    s = Svg(W, Ht, "XIAO ESP32C6 のピン")
    s.text(24, 26, "XIAO ESP32C6: はんだ付けするピン", 21, INK, "start", "bold")
    s.text(24, 50, "部品のある面を上、USB を上にして見た図。ピンの名前は基板の裏に印刷されています", 14, "#495057")
    bx, by, bw, bh = 272, 84, 216, 222
    cx = bx + bw / 2
    s.rect(bx, by, bw, bh, "#2b8a3e", "#1b5e2b", 1.6, 8)
    s.rect(cx - 26, by - 12, 52, 34, "#ced4da", "#868e96", 1.3, 5)
    s.text(cx, by + 5, "USB", 11.5, "#495057", "middle", "bold")
    # 基板上の LED (USB の右)
    s.rect(cx + 36, by + 8, 9, 6, "#ffa94d", "#d9480f", 0.8, 1.5)
    s.text(cx + 40.5, by + 25, "LED", 9.5, "#d3f9d8", "middle")
    # 金属カバー (技適の番号が印字されている)
    s.rect(cx - 40, by + 42, 80, 96, "#dee2e6", "#868e96", 1.2, 4)
    s.text(cx, by + 80, "金属カバー", 11.5, "#343a40", "middle", "bold")
    s.text(cx, by + 98, "技適の番号が", 9.8, "#495057", "middle")
    s.text(cx, by + 111, "印字されている", 9.8, "#495057", "middle")
    # 下の端: 外付けアンテナ用の端子 (使わない) と、基板上のアンテナ
    s.circle(cx - 24, by + bh - 24, 6.5, "#e9c46a", "#8d6e1f", 1.1)
    s.rect(cx + 2, by + bh - 29, 36, 10, "#c9b458", "#8d6e1f", 1, 2)
    s.text(cx + 20, by + bh - 36, "アンテナ", 10.5, "#d3f9d8", "middle")
    used = {"5V": (12, "5v", "5V"), "GND": (13, "gnd", "GND"), "D0": (14, "sense", "電池測定"),
            "D1": (20, "btn", "ボタン NO"), "D2": (15, "data", "LED データ"), "D3": (16, "ctl", "ボタン LED 信号")}
    pin_column(s, bx + 15, by + 34, ["D0", "D1", "D2", "D3", "D4", "D5", "D6"], used, "L")
    pin_column(s, bx + bw - 15, by + 34, ["5V", "GND", "3V3", "D10", "D9", "D8", "D7"], used, "R")
    s.text(24, Ht - 22, "黄色の 6 か所だけ使います。丸の数字は線の番号です。下の端の丸い金色の端子 (外付けアンテナ用) は使いません", 13.5,
           "#495057")
    s.save(path)


def draw_pins_master(path: Path) -> None:
    W, Ht = 1180, 640
    s = Svg(W, Ht, "親機の基板のピン")
    s.text(24, 26, "親機: はんだ付けするピン", 21, INK, "start", "bold")
    s.text(24, 50, "部品のある面を上にして見た図。ピンの名前は基板に印刷されているので、はんだ付けの前に印字と見くらべてください", 14, "#495057")
    # ESP32-DevKitC-32E
    bx, by, bw, bh = 250, 96, 200, 500
    s.text(bx + bw / 2, by - 16, "ESP32-DevKitC-32E (38 ピン)", 15, INK, "middle", "bold")
    s.rect(bx, by, bw, bh, "#2b8a3e", "#1b5e2b", 1.6, 8)
    s.rect(bx + 64, by + 8, bw - 128, 124, "#adb5bd", "#868e96", 1.2, 4)
    s.text(bx + bw / 2, by + 60, "ESP32", 12.5, "#343a40", "middle", "bold")
    s.text(bx + bw / 2, by + 78, "アンテナ側", 10.5, "#343a40", "middle")
    s.rect(bx + bw / 2 - 24, by + bh - 26, 48, 36, "#ced4da", "#868e96", 1.3, 5)
    s.text(bx + bw / 2, by + bh - 9, "USB", 11.5, "#495057", "middle", "bold")
    left = ["3V3", "EN", "VP", "VN", "34", "35", "32", "33", "25", "26", "27", "14", "12", "GND", "13", "D2", "D3", "CMD", "5V"]
    right = ["GND", "23", "22", "TX", "RX", "21", "GND ", "19", "18", "5", "17", "16", "4", "0", "2", "15", "D1", "D0", "CLK"]
    used_l = {"3V3": (38, "3v3", "表示 VCC"), "35": (14, "sense", "電池測定"), "32": (20, "btn", "正解ボタン NO"),
              "33": (21, "btn2", "不正解ボタン NO"), "26": (16, "ctl", "ボタン LED 信号"), "27": (15, "data", "LED データ"),
              "GND": (13, "gnd", "GND"), "5V": (12, "5v", "5V")}
    used_r = {"GND": (39, "gnd", "表示 GND"), "19": (41, "dio", "表示 DIO"), "18": (40, "clk", "表示 CLK"),
              "17": (32, "ser", "音 送信"), "16": (35, "ser2", "音 受信")}
    pin_column(s, bx + 15, by + 22, left, used_l, "L", 25.3)
    pin_column(s, bx + bw - 15, by + 22, right, used_r, "R", 25.3)
    # DFPlayer
    dx, dy, dw, dh = 810, 116, 200, 250
    s.text(dx + dw / 2, dy - 30, "DFPlayer Mini", 15, INK, "middle", "bold")
    s.rect(dx, dy, dw, dh, "#1864ab", "#0b3d6e", 1.6, 8)
    s.rect(dx + dw / 2 - 14, dy - 5, 28, 12, "#ffffff", "#0b3d6e", 1.2, 3)
    s.text(dx + dw / 2, dy + 20, "切り欠き", 10.5, "#d0ebff", "middle")
    s.rect(dx + dw / 2 - 34, dy + dh - 30, 68, 36, "#ced4da", "#868e96", 1.2, 4)
    s.text(dx + dw / 2, dy + dh - 12, "microSD", 11, "#495057", "middle", "bold")
    used_d = {"VCC": (30, "bat", "電池 +"), "RX": (33, "ser", "音 送信"), "TX": (34, "ser2", "音 受信"),
              "SPK_1": (36, "spk", "スピーカー"), "GND": (31, "gnd", "GND"), "SPK_2": (37, "spk", "スピーカー")}
    pin_column(s, dx + 15, dy + 34, ["VCC", "RX", "TX", "DAC_R", "DAC_L", "SPK_1", "GND", "SPK_2"], used_d, "L")
    pin_column(s, dx + dw - 15, dy + 34, ["BUSY", "USB−", "USB+", "ADKEY2", "ADKEY1", "IO_2", "GND ", "IO_1"], {}, "R")
    # TM1637
    tx, ty, tw, th = 810, 450, 200, 140
    s.text(tx + tw / 2, ty - 22, "TM1637 4 桁表示", 15, INK, "middle", "bold")
    s.rect(tx, ty, tw, th, "#1864ab", "#0b3d6e", 1.6, 8)
    s.rect(tx + 74, ty + 26, tw - 92, th - 52, "#212529", "#000", 1, 4)
    s.text(tx + 74 + (tw - 92) / 2, ty + th / 2, "88:88", 20, "#e03131", "middle", "bold")
    used_t = {"CLK": (40, "clk", "ESP32 の 18 へ"), "DIO": (41, "dio", "ESP32 の 19 へ"),
              "VCC": (38, "3v3", "ESP32 の 3V3 へ"), "GND": (39, "gnd", "ESP32 の GND へ")}
    pin_column(s, tx + 15, ty + 32, ["CLK", "DIO", "VCC", "GND"], used_t, "L")
    s.text(24, Ht - 20, "黄色のピンだけ使います。丸の数字は線の番号です", 13.5, "#495057")
    s.save(path)


# ============================================================================
#  手順書の表 (図と同じデータから作る)
# ============================================================================
SHORT_NAME = {"esp": {"XIAO ESP32C6": "XIAO", "ESP32-DevKitC-32E": "ESP32"}}
TOP_PLATE = {"led", "btn", "ok", "ng"}  # 天板に付く部品。天板を開けられるように線を長くする


def end_text(pic: Pictorial, w: Wire, end: tuple, holes: dict) -> str:
    if end[0] == "hub":
        row = end[1]
        return f"中継基板の **{w.num} 番の穴** ({row} 行: {ROW_INFO[row][0]})"
    m = pic.mods[end[0]]
    key = end[1].split("#")[0]
    label = next(lb for k, lb in m.pins if k == key).replace("＋", "+")
    name = SHORT_NAME.get(m.key, {}).get(m.title, m.title)
    extra = " (2 本目)" if "#" in end[1] else ""
    sep = " " if name[-1].isascii() else ""
    return f"{name}{sep}の **{label}**{extra}"


def wire_length(w: Wire) -> str:
    mods = {e[0] for e in (w.a, w.b)}
    if "bat" in mods:
        return "電池ボックスの線"
    top = len(mods & TOP_PLATE)
    if top == 2:
        return "15cm"
    return "20cm" if top == 1 else "12cm"


def step_table(pic: Pictorial, nums, holes: dict) -> str:
    rows = ["| 線 | 色の例 | ここから | ここへ | 長さの目安 |", "| :---: | :---: | --- | --- | --- |"]
    by_num = {w.num: w for w in pic.wires}
    for n in nums:
        w = by_num[n]
        rows.append(f"| **{n}** | {NET[w.net][1]} | {end_text(pic, w, w.a, holes)} | {end_text(pic, w, w.b, holes)} | {wire_length(w)} |")
    return "\n".join(rows)


PART_ORDER = ["R1k", "R10k", "Rb", "Rt", "R330", "Rtx", "Rrx", "J1", "J2", "Di", "Cc", "Q", "Ce", "Cdf"]
# 部品: (名前, 注文した基板での注意, ストリップ基板での注意)
PART_TEXT = {
    "J1": ("ジャンパー (切り落とした抵抗の足で作る)", "", "コの字に曲げて挿す"),
    "R1k": ("抵抗 1kΩ", "", ""), "R10k": ("抵抗 10kΩ", "", ""), "Rb": ("抵抗 100kΩ", "", ""), "Rt": ("抵抗 100kΩ", "", ""),
    "R330": ("抵抗 330Ω", "", ""),
    "Di": ("ダイオード 1N4001", "**帯のある側を、3 本線が印刷されている側へ**", "**帯のある側を 6 行へ**"),
    "Cc": ("セラミックコンデンサ 0.1µF (印字 104)", "向きなし。足を少し広げて挿す", "向きなし。足を少し広げて挿す"),
    "Q": ("トランジスタ 2SC1815", "**印字のある平らな面を、二重線が印刷されている側へ**。足を広げて 3 つの穴に",
          "**印字のある平らな面を右 (n 列側) へ**。足を広げて 3 つの穴に"),
    "Ce": ("電解コンデンサ 1000µF", "**長い足を `+` の印の穴へ**", "**長い足 (＋) を 6 行、帯のある側 (−) を 4 行へ**"),
    "J2": ("ジャンパー線 (被覆つきの電線 約 4cm)", "", "ほかの線のじゃまにならないよう基板の端を通す"),
    "Rtx": ("抵抗 1kΩ", "", ""), "Rrx": ("抵抗 1kΩ", "", ""),
    "Cdf": ("電解コンデンサ 1000µF", "**長い足を `+` の印の穴へ**", "**長い足 (＋) を 10 行、帯のある側 (−) を 12 行へ**"),
}


def parts_table() -> str:
    """注文した基板 (プリント基板) に付ける部品。ジャンパーは基板の中の配線になっているので入らない"""
    rows = ["| 順 | 部品 | 基板の印刷 | 向き・注意 | 使う機種 |", "| :---: | --- | :---: | --- | :---: |"]
    by_key = {p.key: p for p in PARTS}
    i = 0
    for key in PART_ORDER:
        p = by_key[key]
        if p.kind == "jumper":
            continue
        i += 1
        name, note, _strip = PART_TEXT[key]
        rows.append(f"| {i} | {name} | `{PCB_LABEL[p.label]}` | {note or '向きなし'} | {'親機だけ' if p.master_only else '両方'} |")
    return "\n".join(rows)


def strip_parts_table() -> str:
    """ストリップ基板で作るときの部品と穴の場所"""
    rows = ["| 順 | 部品 | 足を挿す穴 | 向き・注意 | 使う機種 |", "| :---: | --- | --- | --- | :---: |"]
    by_key = {p.key: p for p in PARTS}
    for i, key in enumerate(PART_ORDER, 1):
        p = by_key[key]
        name, _pcb, note = PART_TEXT[key]
        if p.kind == "npn":
            holes = " ・ ".join(f"`{c}{r}` ({n})" for n, c, r in p.pins)
        else:
            holes = " と ".join(f"`{c}{r}`" for _n, c, r in sorted(p.pins, key=lambda x: x[2]))
        rows.append(f"| {i} | {name} | {holes} | {note or '向きなし'} | {'親機だけ' if p.master_only else '両方'} |")
    return "\n".join(rows)


def update_doc(path: Path, blocks: dict) -> None:
    """資料の <!-- AUTO:名前 --> 〜 <!-- /AUTO --> の間を書き直す"""
    if not path.exists():
        print(f"  {path.name} がないので表は書き出しません")
        return
    text = path.read_text(encoding="utf-8")
    for name, body in blocks.items():
        pat = re.compile(rf"(<!-- AUTO:{re.escape(name)} -->\n).*?(<!-- /AUTO -->)", re.S)
        if not pat.search(text):
            raise SystemExit(f"{path.name} に <!-- AUTO:{name} --> がありません")
        text = pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text)
    path.write_text(text, encoding="utf-8")
    print(f"  {path.name} の表を {len(blocks)} か所更新しました")


def main() -> None:
    print("接続を照合:")
    verify("子機", CHILD_WIRES, False, EXPECTED_CHILD)
    verify("親機", MASTER_WIRES, True, EXPECTED_MASTER, INTERNAL_MASTER)
    print("図を作成:")
    holes = {
        "child": draw_board(OUT / "board_child.svg", "中継基板 (子機用)", CHILD_WIRES, False),
        "master": draw_board(OUT / "board_master.svg", "中継基板 (親機用)", MASTER_WIRES, True),
    }
    blocks = {"board-parts": parts_table()}
    for name, pic, steps in (("child", child_pictorial(), CHILD_STEPS), ("master", master_pictorial(), MASTER_STEPS)):
        pic.draw(OUT / f"{name}_all.svg", None, "全体 (すべての線)")
        for i, (label, nums) in enumerate(steps, 1):
            nums = list(nums)
            pic.draw(OUT / f"{name}_step{i}.svg", nums, f"ステップ {i}: {label} (線 {nums[0]}〜{nums[-1]})")
            blocks[f"{name}-step{i}"] = step_table(pic, nums, holes[name])
    draw_parts(OUT / "parts.svg")
    draw_pins_child(OUT / "pins_child.svg")
    draw_pins_master(OUT / "pins_master.svg")
    print(f"  {len(list(OUT.glob('*.svg')))} 個の SVG を docs/images/wiring/ に書き出しました")
    update_doc(GUIDE, blocks)
    update_doc(STRIP_GUIDE, {"strip-parts": strip_parts_table()})


if __name__ == "__main__":
    main()
