"""DFPlayer 用の効果音を合成して sd/mp3/ に書き出す (Python 標準ライブラリ + ffmpeg)

    python generate_sounds.py

    0001.mp3  正解     ピンポーン
    0002.mp3  不正解   ブッブー
    0003.mp3  回答権   ピコーン
    0004.mp3  起動音   ドミソ

このスクリプトで作った音はこのリポジトリのライセンスで自由に使えます。
好きな音に差し替えたい場合は、同じファイル名の mp3 を microSD の /mp3 フォルダに置いてください。
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

RATE = 44100


def silence(sec: float) -> list[float]:
    return [0.0] * int(RATE * sec)


def bell(freq: float, sec: float, decay: float, gain: float = 1.0) -> list[float]:
    """チャイムのような減衰音 (倍音を少し混ぜる)"""
    out = []
    for i in range(int(RATE * sec)):
        t = i / RATE
        env = math.exp(-t * decay) * min(1.0, t / 0.004)
        s = (
            math.sin(2 * math.pi * freq * t)
            + 0.35 * math.sin(2 * math.pi * freq * 2 * t)
            + 0.12 * math.sin(2 * math.pi * freq * 3.01 * t)
        )
        out.append(gain * env * s / 1.47)
    return out


def buzz(freq: float, sec: float, gain: float = 1.0) -> list[float]:
    """ブザー音 (少しずらした 2 つの矩形波を重ねる)"""
    out = []
    n = int(RATE * sec)
    for i in range(n):
        t = i / RATE
        env = min(1.0, t / 0.005) * min(1.0, (sec - t) / 0.02)
        s = 0.0
        for f in (freq, freq * 1.012):
            s += 1.0 if math.sin(2 * math.pi * f * t) >= 0 else -1.0
        out.append(gain * env * s / 2)
    return out


def sweep_then_ring(f0: float, f1: float, sweep_sec: float, ring_sec: float) -> list[float]:
    out = []
    phase = 0.0
    n = int(RATE * sweep_sec)
    for i in range(n):
        f = f0 + (f1 - f0) * i / n
        phase += 2 * math.pi * f / RATE
        out.append(0.8 * math.sin(phase) * min(1.0, i / 100))
    for i in range(int(RATE * ring_sec)):
        t = i / RATE
        phase += 2 * math.pi * f1 / RATE
        out.append(0.8 * math.sin(phase) * math.exp(-t * 6))
    return out


def mix(*tracks: tuple[float, list[float]]) -> list[float]:
    """(開始秒, 波形) を重ねる"""
    length = max(int(start * RATE) + len(w) for start, w in tracks)
    out = [0.0] * length
    for start, w in tracks:
        o = int(start * RATE)
        for i, s in enumerate(w):
            out[o + i] += s
    return out


def normalize(w: list[float], peak: float = 0.89) -> list[float]:
    m = max(abs(s) for s in w) or 1.0
    return [s * peak / m for s in w]


def write_wav(path: Path, w: list[float]) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in w))


def sounds() -> dict[str, list[float]]:
    correct = mix((0.0, bell(988, 0.5, 6)), (0.28, bell(784, 1.6, 2.6)))
    incorrect = buzz(150, 0.20) + silence(0.07) + buzz(150, 0.75)
    buzz_in = sweep_then_ring(1200, 2349, 0.06, 0.6)
    startup = mix(
        (0.00, bell(1047, 0.3, 9, 0.8)),
        (0.12, bell(1319, 0.3, 9, 0.8)),
        (0.24, bell(1568, 0.8, 4, 0.8)),
    )
    return {
        "0001": normalize(correct),
        "0002": normalize(incorrect, 0.7),  # 矩形波は耳につくので少し小さめ
        "0003": normalize(buzz_in),
        "0004": normalize(startup, 0.7),
    }


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "sd" / "mp3"
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    with tempfile.TemporaryDirectory() as tmp:
        for name, w in sounds().items():
            if ffmpeg is None:
                dst = out_dir / f"{name}.wav"
                write_wav(dst, w)
                print("wrote", dst, "(ffmpeg が無いので WAV で出力)")
                continue
            wav = Path(tmp) / f"{name}.wav"
            write_wav(wav, w)
            dst = out_dir / f"{name}.mp3"
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame",
                 "-b:a", "128k", "-ar", "44100", "-ac", "1", "-map_metadata", "-1", str(dst)],
                check=True,
            )
            print("wrote", dst)


if __name__ == "__main__":
    main()
