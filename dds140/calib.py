"""サンプルレートの実測校正。

実機では `cmd 148` のラベル（100M/10M/…）と、実際に届くデータの時間軸が
一致しない（2026-10-31 実測）。内蔵の 1 kHz 標準矩形波（BNC 間の小さな金属ピン）
を入力に繋いだ状態で測ると、各設定の「実効サンプルレート」を決められる。

    python3 -m dds140 calib-rate          # プローブを内蔵矩形波に当てて実行
    python3 -m dds140 calib-rate --show   # 保存済みの値を表示

保存先: ~/.dds140/rates.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import const as C
from .scope import Scope

REFERENCE_HZ = 1000.0          # 内蔵標準矩形波（仕様書 §4.2）
CONF_PATH = Path.home() / ".dds140" / "rates.json"


def _runs(codes: list[int], lo: int = 60, hi: int = 200) -> list[int]:
    """飽和（lo 以下 / hi 以上）の連続長を返す。矩形波の半周期の目安。"""
    out = []
    n = 1
    prev_high = codes[0] >= hi
    for v in codes[1:]:
        high = v >= hi
        if high == prev_high:
            n += 1
        else:
            if prev_high or n:      # 途中の値は無視して区間長だけ見る
                out.append(n)
            prev_high = high
            n = 1
    return out


def measure_period(frame) -> float | None:
    """矩形波の周期（サンプル数）を推定する。0/255 に振り切れている前提。"""
    codes = list(frame.ch1_codes)
    if not codes:
        return None
    lo = min(codes)
    hi = max(codes)
    if hi - lo < 150:              # 十分に振り切れていない
        return None
    mid = (lo + hi) / 2
    # 立ち上がりエッジ間隔の中央値（リンギングに強い）
    edges = [i for i in range(1, len(codes)) if codes[i - 1] < mid <= codes[i]]
    gaps = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
    gaps = [g for g in gaps if 4 <= g <= len(codes) // 2]
    if len(gaps) < 3:
        return None
    gaps.sort()
    return float(gaps[len(gaps) // 2])


def calibrate(scope: Scope, labels=None, reference_hz: float = REFERENCE_HZ,
              verbose: bool = True) -> dict:
    """各レート設定で矩形波の周期を測り、実効レートを求める。"""
    labels = labels or list(C.SAMPLE_RATES)
    result: dict[str, dict] = {}
    for label in labels:
        scope.configure(rate=label, ch1_range="50mV", ch2_range="2V")
        # 50mV/div で振り切らせる（振幅が小さいときは 200mV に落とす）
        period = None
        for rng in ("50mV", "100mV", "200mV"):
            scope.configure(rate=label, ch1_range=rng, ch2_range="2V")
            frame = scope.capture(total_bytes=262144, poll_timeout=25.0, skip=0)
            period = measure_period(frame)
            if period:
                break
        if not period:
            if verbose:
                print(f"  {label:5s}: 矩形波が見えない（プローブを内蔵 1kHz に当てる）")
            continue
        eff = period * reference_hz
        result[label] = {
            "period_samples": period,
            "rate_hz": eff,
            "label_hz": C.SAMPLE_RATES[label].hz,
            "ratio": C.SAMPLE_RATES[label].hz / eff,
        }
        if verbose:
            print(f"  {label:5s}: 周期 {period:7.1f} smp → 実効 "
                  f"{eff/1e3:8.2f} kS/s （ラベル {C.SAMPLE_RATES[label].hz/1e3:7.1f} kS/s, "
                  f"×{C.SAMPLE_RATES[label].hz/eff:5.1f}）")
    return result


def save(cal: dict, path: Path = CONF_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal, indent=2, ensure_ascii=False))
    return path


def load(path: Path = CONF_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def rate_for(label: str, label_hz: float, cal: dict | None = None) -> float:
    """校正値があれば実効レート、無ければラベルの値。"""
    if cal is None:
        cal = load()
    entry = cal.get(label)
    if entry and entry.get("rate_hz"):
        return float(entry["rate_hz"])
    return label_hz
