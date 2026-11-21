"""Canal de notificacao via Discord: webhook de canal ou bot.

Modos (o webhook tem prioridade quando os dois estao configurados):
- Webhook: DISCORD_WEBHOOK_URL (Configuracoes do canal > Integracoes > Webhooks).
- Bot: DISCORD_BOT_TOKEN e DISCORD_CANAL_ID (o bot precisa estar no servidor com
  permissao de enviar mensagens nesse canal).
"""
import json
import logging
import os
from typing import Callable, Optional
import urllib.request

from .. import config
from .base import CanalNotificacao, formatar_titulo

log = logging.getLogger("nextor.notificacoes.discord")

API_DISCORD = "https://discord.com/api/v10"
# Limite de caracteres de uma mensagem do Discord.
LIMITE_CONTEUDO = 2000


def _ler(nome: str) -> str:
    return (os.getenv(nome, "") or getattr(config, nome, "") or "").strip()


class CanalDiscord(CanalNotificacao):
    """Adaptador de envio de notificacoes para o Discord (webhook ou bot)."""

    nome = "Discord"
    slug = "discord"

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        http_client: Optional[Callable[..., bool]] = None,
        bot_token: Optional[str] = None,
        canal_id: Optional[str] = None,
    ):
        """http_client (para testes) recebe (url, payload) no modo webhook e
        (url, payload, headers) no modo bot."""
        self._webhook_url = webhook_url
        self._http_client = http_client
        self._bot_token = bot_token
        self._canal_id = canal_id

    def _obter_url(self) -> str:
        return (self._webhook_url or _ler("DISCORD_WEBHOOK_URL")).strip()

    def _obter_bot_token(self) -> str:
        return (self._bot_token or _ler("DISCORD_BOT_TOKEN")).strip()

    def _obter_canal_id(self) -> str:
        return str(self._canal_id or _ler("DISCORD_CANAL_ID")).strip()

    def _webhook_valido(self) -> bool:
        return self._obter_url().startswith("https://")

    def _bot_valido(self) -> bool:
        canal = self._obter_canal_id()
        return bool(self._obter_bot_token() and canal.isdigit())

    def modo(self) -> str:
        """Retorna "webhook", "bot" ou "" (nao configurado)."""
        if self._webhook_valido():
            return "webhook"
        if self._bot_valido():
            return "bot"
        return ""

    def configurado(self) -> bool:
        return bool(self.modo())

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        modo = self.modo()
        if not modo:
            return False

        conteudo = f"**[{formatar_titulo(titulo, urgencia)}]**\n{str(corpo or '').strip()}"
        payload = {
            "content": conteudo[:LIMITE_CONTEUDO],
            # Nunca mencionar @everyone/@here a partir do texto de uma notificacao.
            "allowed_mentions": {"parse": []},
        }
        headers = {"Content-Type": "application/json", "User-Agent": "Nextor-Notificacoes"}

        if modo == "webhook":
            url = self._obter_url()
        else:
            url = f"{API_DISCORD}/channels/{self._obter_canal_id()}/messages"
            headers["Authorization"] = f"Bot {self._obter_bot_token()}"

        if self._http_client is not None:
            try:
                if modo == "webhook":
                    return bool(self._http_client(url, payload))
                return bool(self._http_client(url, payload, headers))
            except Exception as e:
                log.warning("Falha no envio Discord (%s): %s", modo, type(e).__name__)
                return False

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            # Nunca vaza a URL do webhook nem o token do bot no log.
            log.warning("Falha ao despachar notificacao pelo Discord (%s): %s", modo, type(e).__name__)
            return False
