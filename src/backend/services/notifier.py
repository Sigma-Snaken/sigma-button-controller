import asyncio
import json
from urllib.request import urlopen, Request
from urllib.error import URLError

from utils.logger import get_logger

logger = get_logger("notifier")


class TelegramNotifier:
    def __init__(self):
        self.bot_token: str = ""
        self.chat_id: str = ""
        self.enabled: bool = False

    def configure(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.enabled = bool(self.bot_token and self.chat_id)
        logger.info(f"Telegram notifier {'enabled' if self.enabled else 'disabled'}")

    async def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, message
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def _send_sync(self, message: str) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = json.dumps({"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except URLError as e:
            logger.error(f"Telegram API error: {e}")
            return False
