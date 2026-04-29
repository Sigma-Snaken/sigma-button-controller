import os
import sys
import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.offline_deployer import OfflineDeployer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_result(exit_status: int = 0, stdout: str = ""):
    result = MagicMock()
    result.exit_status = exit_status
    result.stdout = stdout
    return result


def _make_conn(run_results=None):
    """Build a mock SSH connection whose run() returns results in order."""
    conn = MagicMock()

    if run_results is None:
        run_results = [_make_run_result(0)]

    run_call_results = list(run_results)

    async def _run(cmd, **kwargs):
        if run_call_results:
            return run_call_results.pop(0)
        return _make_run_result(0)

    conn.run = _run

    # SFTP context manager
    remote_file = MagicMock()
    remote_file.write = AsyncMock()
    sftp = MagicMock()
    sftp.open = MagicMock(return_value=_async_ctx(remote_file))
    conn.start_sftp_client = MagicMock(return_value=_async_ctx(sftp))

    return conn


def _async_ctx(obj):
    """Wrap an object as an async context manager."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=obj)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOfflineDeployer:
    def setup_method(self):
        self.deployer = OfflineDeployer()

    # --- deploy ---

    @pytest.mark.asyncio
    async def test_deploy_success(self):
        conn = _make_conn(run_results=[
            _make_run_result(0),   # pkill
            _make_run_result(0),   # nohup launch
            _make_run_result(0),   # pgrep — process found
        ])

        with patch("services.offline_deployer.asyncssh") as mock_ssh, \
             patch("services.offline_deployer.asyncio.sleep", new=AsyncMock()):
            mock_ssh.connect = AsyncMock(return_value=_async_ctx(conn))

            result = await self.deployer.deploy("192.168.1.10", "print('hi')", "run-1")

        assert result["ok"] is True
        assert result["run_id"] == "run-1"
        assert result["robot_ip"] == "192.168.1.10"

    @pytest.mark.asyncio
    async def test_deploy_ssh_connection_failure(self):
        with patch("services.offline_deployer.asyncssh") as mock_ssh:
            mock_ssh.connect = AsyncMock(side_effect=OSError("Connection refused"))

            result = await self.deployer.deploy("192.168.1.10", "print('hi')", "run-2")

        assert result["ok"] is False
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_deploy_process_not_started(self):
        # pkill + nohup + PGREP_ATTEMPTS pgrep failures
        conn = _make_conn(run_results=[
            _make_run_result(0),
            _make_run_result(0),
            *[_make_run_result(1) for _ in range(OfflineDeployer.PGREP_ATTEMPTS)],
        ])

        with patch("services.offline_deployer.asyncssh") as mock_ssh, \
             patch("services.offline_deployer.asyncio.sleep", new=AsyncMock()):
            mock_ssh.connect = AsyncMock(return_value=_async_ctx(conn))

            result = await self.deployer.deploy("192.168.1.10", "print('hi')", "run-3")

        assert result["ok"] is False
        assert "did not start" in result["error"]

    # --- test_connection ---

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        conn = _make_conn(run_results=[_make_run_result(0, "ok")])

        with patch("services.offline_deployer.asyncssh") as mock_ssh:
            mock_ssh.connect = AsyncMock(return_value=_async_ctx(conn))

            result = await self.deployer.test_connection("192.168.1.10")

        assert result["ok"] is True
        assert result["robot_ip"] == "192.168.1.10"

    # --- get_public_key ---

    def test_get_public_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pub", delete=False) as f:
            f.write("ssh-rsa AAAAB3NzaC1 user@host")
            tmp_path = f.name

        try:
            key = self.deployer.get_public_key(tmp_path)
            assert key == "ssh-rsa AAAAB3NzaC1 user@host"
        finally:
            os.unlink(tmp_path)

    def test_get_public_key_not_found(self):
        result = self.deployer.get_public_key("/nonexistent/path/id_rsa.pub")
        assert result is None
