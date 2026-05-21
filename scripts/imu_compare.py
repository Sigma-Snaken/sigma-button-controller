#!/usr/bin/env python3
"""
Compare labeled IMU segment CSVs produced by imu_sample_test.py.

Usage:
    python scripts/imu_compare.py imu_baseline_*.csv imu_push_*.csv imu_shake_*.csv

For each CSV, prints peak/mean stats plus a candidate-rule evaluation:
  - accel deviation from baseline g
  - gyro magnitude
  - gz zero-crossing count (yaw oscillation — the only rotation axis available)
  - above-threshold sample counts (current 11.0 / 0.8 thresholds)
  - sliding-window mean gyro (proxy for "sustained rotation")
"""
import csv
import sys
from pathlib import Path


def load(path):
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def zero_crossings(values):
    n = 0
    prev = values[0]
    for v in values[1:]:
        if (prev >= 0) != (v >= 0):
            n += 1
        prev = v
    return n


def sliding_max_mean(values, window):
    if len(values) < window:
        return max(values) if values else 0.0
    return max(sum(values[i:i + window]) / window
               for i in range(len(values) - window + 1))


def stats(rows, g_baseline):
    accels = [r['accel_mag'] for r in rows]
    gyros = [r['gyro_mag'] for r in rows]
    gz = [r['gz'] for r in rows]

    return {
        "n": len(rows),
        "duration": rows[-1]['t'] if rows else 0.0,
        "accel_max": max(accels),
        "accel_dev_peak": max(abs(a - g_baseline) for a in accels),
        "accel_dev_mean": sum(abs(a - g_baseline) for a in accels) / len(accels),
        "gyro_max": max(gyros),
        "gyro_mean": sum(gyros) / len(gyros),
        "gz_zero_crossings": zero_crossings(gz),
        "above_a11": sum(1 for a in accels if a > 11.0),
        "above_g08": sum(1 for g in gyros if g > 0.8),
        "above_g05": sum(1 for g in gyros if g > 0.5),
        "above_g03": sum(1 for g in gyros if g > 0.3),
        "gyro_mean_1s": sliding_max_mean(gyros, 10),
        "gyro_mean_05s": sliding_max_mean(gyros, 5),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: imu_compare.py <csv1> [csv2 ...]", file=sys.stderr)
        sys.exit(1)

    paths = []
    for arg in sys.argv[1:]:
        paths.extend(sorted(Path(".").glob(arg)) if "*" in arg else [Path(arg)])

    datasets = []
    for p in paths:
        rows = load(p)
        if not rows:
            print(f"  (skip empty: {p})")
            continue
        label = p.stem.split("_")[1] if "_" in p.stem else p.stem
        datasets.append((label, p.name, rows))

    if not datasets:
        print("No data loaded", file=sys.stderr)
        sys.exit(1)

    baseline = next((d for d in datasets if d[0] == "baseline"), None)
    if baseline:
        g = sum(r['accel_mag'] for r in baseline[2]) / len(baseline[2])
        print(f"Baseline g (from '{baseline[0]}'): {g:.3f} m/s²\n")
    else:
        g = 9.75
        print(f"No 'baseline' label found — using assumed g = {g:.3f} m/s²\n")

    cols = [
        ("n", "n", "{:>4d}"),
        ("dur", "duration", "{:>5.1f}"),
        ("a_max", "accel_max", "{:>6.2f}"),
        ("a_dev_pk", "accel_dev_peak", "{:>8.2f}"),
        ("a_dev_avg", "accel_dev_mean", "{:>9.2f}"),
        ("g_max", "gyro_max", "{:>6.2f}"),
        ("g_avg", "gyro_mean", "{:>6.2f}"),
        ("g_avg_1s", "gyro_mean_1s", "{:>8.2f}"),
        ("g_avg_½s", "gyro_mean_05s", "{:>8.2f}"),
        ("gz_zc", "gz_zero_crossings", "{:>5d}"),
        ("a>11", "above_a11", "{:>4d}"),
        ("g>0.3", "above_g03", "{:>5d}"),
        ("g>0.5", "above_g05", "{:>5d}"),
        ("g>0.8", "above_g08", "{:>5d}"),
    ]

    header = " ".join(f"{name:>{len(name)}}" for name, _, _ in cols)
    print(f"{'label':<10} {header}")
    print("-" * (10 + 1 + len(header)))

    for label, fname, rows in datasets:
        s = stats(rows, g)
        row_str = " ".join(fmt.format(s[key]) for name, key, fmt in cols)
        print(f"{label:<10} {row_str}")
    print()

    # Candidate rules
    print("=== Candidate trigger rules (TRUE = would trigger) ===")
    rules = [
        ("R0 current   (peak a>11 OR peak g>0.8)",
         lambda s: s['above_a11'] > 0 or s['above_g08'] > 0),
        ("R1 sustained-gyro (mean g over 1s > 0.3)",
         lambda s: s['gyro_mean_1s'] > 0.3),
        ("R2 sustained-gyro (mean g over 0.5s > 0.4)",
         lambda s: s['gyro_mean_05s'] > 0.4),
        ("R3 gz oscillation (zero-crossings >= 4)",
         lambda s: s['gz_zero_crossings'] >= 4),
        ("R4 gyro-only peak (g > 0.5)",
         lambda s: s['above_g05'] > 0),
        ("R5 gyro AND low-accel-dev (mean g 0.5s > 0.4 AND a_dev_pk < 2.0)",
         lambda s: s['gyro_mean_05s'] > 0.4 and s['accel_dev_peak'] < 2.0),
    ]

    for name, fn in rules:
        results = []
        for label, _, rows in datasets:
            s = stats(rows, g)
            results.append(f"{label}={'Y' if fn(s) else '.'}")
        print(f"  {name:<55}  {'  '.join(results)}")


if __name__ == "__main__":
    main()
