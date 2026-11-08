"""Canal de notificacao via Telegram (reutilizando bot do Nextor)."""
import logging
import os
from typing import Optional

from .. import config
from .base import CanalNotificacao

log = logging.getLogger("nextor.notificacoes.telegram")


class CanalTelegram(CanalNotificacao):
    """Adaptador de envio de notificacoes para o Telegram do usuario."""

    nome = "Telegram"
    slug = "telegram"

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self._bot_token = bot_token
        self._chat_id = chat_id

    def _obter_token(self) -> str:
        if self._bot_token:
            return self._bot_token
        return os.getenv("TELEGRAM_BOT_TOKEN", "") or getattr(config, "TELEGRAM_BOT_TOKEN", "")

    def _obter_chat_id(self) -> str:
        if self._chat_id:
            return str(self._chat_id)
        dono = os.getenv("TELEGRAM_DONO_CHAT_ID", "") or getattr(config, "TELEGRAM_DONO_CHAT_ID", "")
        if dono:
            return str(dono).strip()
        autorizados = os.getenv("TELEGRAM_USUARIOS_AUTORIZADOS", "") or getattr(config, "TELEGRAM_USUARIOS_AUTORIZADOS", "")
        if autorizados:
            primeiro = autorizados.replace(";", ",").replace(" ", ",").split(",")[0].strip()
            return primeiro
        return ""

    def configurado(self) -> bool:
        return bool(self._obter_token() and self._obter_chat_id())

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        texto = f"[{titulo.strip()}]\n{corpo.strip()}"
        token = self._obter_token()
        chat = self._obter_chat_id()

        try:
            from .. import telegram_bot
            res = telegram_bot.enviar_mensagem_telegram(chat_id=chat, texto=texto, bot_token=token)
            return bool(res and res.get("ok"))
        except Exception as e:
            log.warning("Falha ao despachar notificacao pelo Telegram: %s", type(e).__name__)
            return False
