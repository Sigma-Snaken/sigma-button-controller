import asyncio
import os
from pathlib import Path

import asyncssh


class OfflineDeployer:
    """Handles SSH connection, script upload, and execution on the Kachaka
    robot's Playground container (port 26500)."""

    SSH_PORT = 26500
    SSH_USER = "kachaka"
    REMOTE_SCRIPT_PATH = "/home/kachaka/route_executor.py"
    CONNECT_TIMEOUT = 10
    PGREP_ATTEMPTS = 10
    PGREP_INTERVAL = 0.2

    async def _connect(self, robot_ip: str) -> asyncssh.SSHClientConnection:
        """Create an SSH connection to the robot Playground container."""
        return await asyncssh.connect(
            robot_ip,
            port=self.SSH_PORT,
            username=self.SSH_USER,
            known_hosts=None,
            connect_timeout=self.CONNECT_TIMEOUT,
        )

    async def deploy(self, robot_ip: str, script_content: str, run_id: str) -> dict:
        """Upload and execute route_executor.py on the robot.

        Returns {"ok": True, "run_id": ..., "robot_ip": ...} on success or
        {"ok": False, "error": ...} on failure.
        """
        try:
            async with await self._connect(robot_ip) as conn:
                await conn.run("pkill -f route_executor.py || true")

                async with conn.start_sftp_client() as sftp:
                    async with sftp.open(self.REMOTE_SCRIPT_PATH, "w") as remote_file:
                        await remote_file.write(script_content)

                await conn.run(
                    f"nohup python3 -u {self.REMOTE_SCRIPT_PATH} "
                    f"> /tmp/route.log 2>&1 &"
                )

                if not await self._wait_for_process(conn, "route_executor.py"):
                    return {"ok": False, "error": "Process did not start after deploy"}

            return {"ok": True, "run_id": run_id, "robot_ip": robot_ip}

        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _wait_for_process(
        self, conn: asyncssh.SSHClientConnection, pattern: str,
    ) -> bool:
        for _ in range(self.PGREP_ATTEMPTS):
            result = await conn.run(f"pgrep -f {pattern}")
            if result.exit_status == 0:
                return True
            await asyncio.sleep(self.PGREP_INTERVAL)
        return False

    async def test_connection(self, robot_ip: str) -> dict:
        """Test SSH connectivity to the robot.

        Returns {"ok": True, "robot_ip": ...} on success or
        {"ok": False, "error": ...} on failure.
        """
        try:
            async with await self._connect(robot_ip) as conn:
                await conn.run("echo ok")
            return {"ok": True, "robot_ip": robot_ip}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_public_key(self, key_path: str | None = None) -> str | None:
        """Read and return the SSH public key.

        Reads ~/.ssh/id_rsa.pub by default, or the provided path.
        Returns the file contents or None if the file is not found.
        """
        if key_path is None:
            key_path = os.path.expanduser("~/.ssh/id_rsa.pub")
        try:
            return Path(key_path).read_text()
        except FileNotFoundError:
            return None
