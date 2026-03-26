import httpx

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
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        all_ok = True
        async with httpx.AsyncClient(timeout=10) as client:
            for chat_id in self.chat_ids:
                try:
                    resp = await client.post(url, json={
                        "chat_id": chat_id, "text": message, "parse_mode": "HTML",
                    })
                    if resp.status_code != 200:
                        all_ok = False
                except Exception as e:
                    logger.error(f"Telegram API error for {chat_id}: {e}")
                    all_ok = False
        return all_ok
