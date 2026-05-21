#!/usr/bin/env python3
"""
IMU sampling diagnostic — labeled segment recorder.

Each run records ONE action segment and writes a labeled CSV.
Run multiple times with different labels (baseline / push / shake / ...)
then use imu_compare.py to compare.

Usage:
    python scripts/imu_sample_test.py <robot_ip> <label> [duration_sec]

Examples:
    python scripts/imu_sample_test.py 192.168.125.103 baseline 5
    python scripts/imu_sample_test.py 192.168.125.103 push 10
    python scripts/imu_sample_test.py 192.168.125.103 shake 10

Output:
    imu_<label>_<timestamp>.csv
"""
import csv
import math
import sys
import time
from pathlib import Path

import kachaka_api
from kachaka_api import pb2


def main():
    if len(sys.argv) < 3:
        print("Usage: imu_sample_test.py <robot_ip> <label> [duration_sec]",
              file=sys.stderr)
        sys.exit(1)

    ip = sys.argv[1]
    label = sys.argv[2]
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    target = ip if ":" in ip else f"{ip}:26400"

    print(f"[{label}] Connecting to {target}, recording for {duration:.0f}s...")
    client = kachaka_api.KachakaApiClient(target)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"imu_{label}_{ts}.csv")

    cursor = 0
    samples = []
    start = time.monotonic()
    last_tick = start

    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "accel_mag", "gyro_mag",
                         "ax", "ay", "az", "gx", "gy", "gz"])

        print(f"[{label}] >>> START recording — do the action now")

        try:
            while time.monotonic() - start < duration:
                req = pb2.GetRequest(metadata=pb2.Metadata(cursor=cursor))
                resp = client.stub.GetRosImu(req)
                cursor = resp.metadata.cursor
                imu = resp.imu

                t = time.monotonic() - start
                ax = imu.linear_acceleration.x
                ay = imu.linear_acceleration.y
                az = imu.linear_acceleration.z
                gx = imu.angular_velocity.x
                gy = imu.angular_velocity.y
                gz = imu.angular_velocity.z
                accel_mag = math.sqrt(ax * ax + ay * ay + az * az)
                gyro_mag = math.sqrt(gx * gx + gy * gy + gz * gz)

                writer.writerow([f"{t:.4f}", f"{accel_mag:.3f}", f"{gyro_mag:.3f}",
                                 f"{ax:.3f}", f"{ay:.3f}", f"{az:.3f}",
                                 f"{gx:.3f}", f"{gy:.3f}", f"{gz:.3f}"])
                samples.append((t, accel_mag, gyro_mag))

                now = time.monotonic()
                if now - last_tick >= 1.0:
                    rate = len(samples) / (now - start)
                    remain = duration - (now - start)
                    print(f"  t={t:5.1f}s  n={len(samples):4d}  "
                          f"rate={rate:5.1f}Hz  remain={remain:4.1f}s  "
                          f"accel={accel_mag:5.2f}  gyro={gyro_mag:5.2f}",
                          flush=True)
                    last_tick = now
        except KeyboardInterrupt:
            print("\nInterrupted")

    elapsed = time.monotonic() - start
    accels = [s[1] for s in samples]
    gyros = [s[2] for s in samples]
    print(f"\n[{label}] DONE — {len(samples)} samples in {elapsed:.2f}s "
          f"({len(samples)/elapsed:.1f} Hz)")
    if accels:
        print(f"  accel: min={min(accels):.2f}  max={max(accels):.2f}  "
              f"peak_dev={max(abs(a-9.75) for a in accels):.2f}")
        print(f"  gyro:  min={min(gyros):.2f}  max={max(gyros):.2f}")
    print(f"  CSV:   {out_path.resolve()}")


if __name__ == "__main__":
    main()
