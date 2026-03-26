import asyncio
import json
from urllib.request import urlopen, Request
from urllib.error import URLError

from utils.logger import get_logger

logger = get_logger("notifier")


class TelegramNotifier:
    def __init__(self):
        self.bot_token: str = ""
        self.chat_ids: list[str] = []
        self.enabled: bool = False
        self.host_url: str = ""

    def configure(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_ids = [cid.strip() for cid in chat_id.split(",") if cid.strip()]
        self.enabled = bool(self.bot_token and self.chat_ids)
        logger.info(f"Telegram notifier {'enabled' if self.enabled else 'disabled'} ({len(self.chat_ids)} recipients)")

    @property
    def chat_id(self) -> str:
        """Return comma-separated string for API/UI compatibility."""
        return ", ".join(self.chat_ids)

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
        all_ok = True
        for chat_id in self.chat_ids:
            data = json.dumps({"chat_id": chat_id, "text": message, "parse_mode": "HTML"}).encode()
            req = Request(url, data=data, headers={"Content-Type": "application/json"})
            try:
                with urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        all_ok = False
            except URLError as e:
                logger.error(f"Telegram API error for {chat_id}: {e}")
                all_ok = False
        return all_ok
