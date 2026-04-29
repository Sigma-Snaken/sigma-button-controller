import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.offline_route_generator import OfflineRouteGenerator


def _make_generator():
    return OfflineRouteGenerator()


def _default_script(**overrides):
    kwargs = dict(
        run_id="run-abc-123",
        stops=[
            {"name": "stop_A"},
            {"name": "stop_B", "timeout_sec": 45},
        ],
        shelf_name="shelf_01",
        default_timeout=60,
        pi_url="http://192.168.1.100:8000",
    )
    kwargs.update(overrides)
    return _make_generator().generate(**kwargs)


def test_generate_contains_stops():
    script = _default_script()
    assert "stop_A" in script
    assert "stop_B" in script
    assert "run-abc-123" in script


def test_generate_contains_shelf():
    script = _default_script()
    assert "shelf_01" in script
    assert "move_shelf" in script
    assert "return_shelf" in script


def test_generate_contains_imu_thresholds():
    script = _default_script()
    assert "ACCEL_THRESHOLD = 11.0" in script
    assert "GYRO_THRESHOLD = 0.8" in script


def test_generate_contains_report_url():
    script = _default_script()
    assert "http://192.168.1.100:8000" in script
    assert "/api/routes/offline/report" in script


def test_generate_contains_grpc_internal():
    script = _default_script()
    assert "100.94.1.1:26400" in script


def test_generate_per_stop_timeout_override():
    script = _default_script()
    # stop_B has timeout_sec=45
    assert "45" in script


def test_generate_is_valid_python():
    script = _default_script()
    compile(script, "<test>", "exec")  # must not raise
