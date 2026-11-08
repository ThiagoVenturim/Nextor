"""Canal de notificacao via Discord Webhook."""
import json
import logging
import os
from typing import Callable, Optional
import urllib.request

from .. import config
from .base import CanalNotificacao

log = logging.getLogger("nextor.notificacoes.discord")


class CanalDiscord(CanalNotificacao):
    """Adaptador de envio de notificacoes para canais do Discord via Webhook."""

    nome = "Discord"
    slug = "discord"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        http_client: Optional[Callable[[str, dict], bool]] = None,
    ):
        self._webhook_url = webhook_url
        self._http_client = http_client

    def _obter_url(self) -> str:
        if self._webhook_url:
            return self._webhook_url
        return os.getenv("DISCORD_WEBHOOK_URL", "") or getattr(config, "DISCORD_WEBHOOK_URL", "")

    def configurado(self) -> bool:
        url = self._obter_url()
        return bool(url and url.startswith("http"))

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        url = self._obter_url()
        conteudo = f"**[{titulo.strip()}]**\n{corpo.strip()}"
        payload = {"content": conteudo}

        if self._http_client is not None:
            try:
                return self._http_client(url, payload)
            except Exception as e:
                log.warning("Falha mockada no envio Discord: %s", type(e).__name__)
                return False

        try:
            dados_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=dados_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Nextor-Notificacoes",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            # Nunca vaza a URL (que contem o token do webhook) no log
            log.warning("Falha ao despachar notificacao pelo Discord: %s", type(e).__name__)
            return False
