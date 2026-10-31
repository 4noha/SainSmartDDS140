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
MIN_TRUSTED_PERIOD = 8.0       # これ未満の周期はエイリアスとみなして捨てる
CONF_PATH = Path.home() / ".dds140" / "rates.json"
RANGE_CONF = Path.home() / ".dds140" / "ranges.json"


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
        if period < MIN_TRUSTED_PERIOD:
            if verbose:
                print(f"  {label:5s}: 周期 {period:.1f} smp は短すぎる（エイリアス）→ 採用しない")
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
        # 周期が極端に短い測定はエイリアス（例: 240k で 4 サンプル）なので使わない
        period = float(entry.get("period_samples") or 0)
        if period >= MIN_TRUSTED_PERIOD:
            return float(entry["rate_hz"])
    return label_hz


# ---------------------------------------------------------------- 垂直（レンジ）
# 内蔵 1 kHz 矩形波の振幅を基準に、レンジごとの表示電圧を校正する。
# マニュアルの「約 1.5V」は不確かなので、既定では相対比較だけ行い、
# --reference-pp を指定したときだけ絶対値を合わせる。

RANGE_NAMES = ("2V", "1V", "500mV", "200mV", "100mV", "50mV")


def measure_pp(scope: Scope, rng: str, rate: str = "100M",
               samples: int = 16384):
    """CH1 の 1 レンジで矩形波の pp を測る。振り切れていたら None。"""
    scope.configure(rate=rate, ch1_range=rng, ch2_range="1V")
    frame = scope.capture(total_bytes=samples * 2, poll_timeout=25.0, skip=16)
    codes = list(frame.ch1_codes)
    lo, hi = min(codes), max(codes)
    v = frame.ch1_volts()
    vpp = max(v) - min(v)
    return {
        "range": rng,
        "code_lo": lo,
        "code_hi": hi,
        "pp_codes": hi - lo,
        "vpp": vpp,
        "v_per_lsb": (vpp / (hi - lo)) if hi > lo else None,
        "railed": hi >= 250 or lo <= 5,
        "gain_index": C.CH1_RANGES[rng].cal_scale,
        "nominal_div": C.CH1_RANGES[rng].div,
    }


def calibrate_ranges(scope: Scope, reference_pp: float | None = None,
                     verbose: bool = True) -> dict:
    rows = {}
    for rng in RANGE_NAMES:
        m = measure_pp(scope, rng)
        rows[rng] = m
        if verbose:
            if m["railed"]:
                print(f"  {rng:6s}: 振り切れ（{m['code_lo']}..{m['code_hi']}）"
                      f" → 小さい信号で測る必要あり。表示 {m['vpp']:.3f} V")
            else:
                print(f"  {rng:6s}: {m['pp_codes']:3d} LSB, 表示 {m['vpp']:.3f} V "
                      f"(V/LSB {m['v_per_lsb']:.5f})")

    usable = [r for r in rows.values() if not r["railed"] and r["pp_codes"] > 20]
    out = {"rows": rows, "reference_pp": reference_pp, "trims": {}}
    if not usable:
        return out

    # レンジ間の一貫性: 同じ 1 本の信号なので Vpp は同じはず
    vpps = [r["vpp"] for r in usable]
    mean_vpp = sum(vpps) / len(vpps)
    out["mean_vpp"] = mean_vpp
    out["spread_pct"] = (max(vpps) - min(vpps)) / mean_vpp * 100 if mean_vpp else 0.0
    if verbose:
        print(f"  → 使用可能 {len(usable)} レンジ, 平均 {mean_vpp:.3f} Vpp, "
              f"ばらつき {out['spread_pct']:.1f}%")

    if reference_pp:
        # ゲイン項目（cal_scale）ごとに補正係数をまとめる
        by_index: dict[int, list[float]] = {}
        for r in usable:
            by_index.setdefault(r["gain_index"], []).append(reference_pp / r["vpp"])
        trims = {}
        for idx, factors in by_index.items():
            f = sum(factors) / len(factors)
            trims[str(idx)] = round(f, 5)
            if verbose:
                print(f"     cal#{idx} の補正係数 ×{f:.4f} "
                      f"（{reference_pp} V を基準）")
        out["trims"] = trims
    return out


def save_ranges(data: dict, path: Path = RANGE_CONF) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


def load_ranges(path: Path = RANGE_CONF) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def apply_trims(cal, trims: dict) -> int:
    """補正係数を Calibration の生値に掛ける（表示電圧が変わる）。"""
    n = 0
    for key, factor in (trims or {}).items():
        try:
            idx = int(key)
        except ValueError:
            continue
        if idx in cal.raw and factor:
            cal.raw[idx] = cal.raw[idx] * float(factor)
            n += 1
    return n
