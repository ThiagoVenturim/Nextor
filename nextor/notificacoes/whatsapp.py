"""Canal de notificacao via WhatsApp Cloud API (Meta for Developers).

Requisitos para uso:
- Uma conta no Meta for Developers com app WhatsApp configurado.
- WHATSAPP_API_TOKEN: Token de acesso do usuario do sistema ou token temporario.
- WHATSAPP_PHONE_NUMBER_ID: ID do numero de telefone de envio gerado no painel.
- WHATSAPP_DESTINATARIO: Numero de telefone de destino com DDI e DDD (ex: 5511999999999).
"""
import json
import logging
import os
from typing import Callable, Optional
import urllib.request

from .. import config
from .base import CanalNotificacao

log = logging.getLogger("nextor.notificacoes.whatsapp")


class CanalWhatsApp(CanalNotificacao):
    """Adaptador de envio de notificacoes via WhatsApp Cloud API oficial."""

    nome = "WhatsApp"
    slug = "whatsapp"

    def __init__(
        self,
        token: Optional[str] = None,
        phone_id: Optional[str] = None,
        destinatario: Optional[str] = None,
        http_client: Optional[Callable[[str, dict, dict], bool]] = None,
    ):
        self._token = token
        self._phone_id = phone_id
        self._destinatario = destinatario
        self._http_client = http_client

    def _obter_token(self) -> str:
        return self._token or os.getenv("WHATSAPP_API_TOKEN", "") or getattr(config, "WHATSAPP_API_TOKEN", "")

    def _obter_phone_id(self) -> str:
        return self._phone_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "") or getattr(config, "WHATSAPP_PHONE_NUMBER_ID", "")

    def _obter_destinatario(self) -> str:
        return self._destinatario or os.getenv("WHATSAPP_DESTINATARIO", "") or getattr(config, "WHATSAPP_DESTINATARIO", "")

    def configurado(self) -> bool:
        return bool(self._obter_token() and self._obter_phone_id() and self._obter_destinatario())

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        phone_id = self._obter_phone_id()
        destinatario = self._obter_destinatario()
        token = self._obter_token()

        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destinatario,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": f"[{titulo.strip()}]\n{corpo.strip()}",
            },
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Nextor-WhatsApp",
        }

        if self._http_client is not None:
            try:
                return self._http_client(url, payload, headers)
            except Exception as e:
                log.warning("Falha mockada no envio WhatsApp: %s", type(e).__name__)
                return False

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.status in (200, 201)
        except Exception as e:
            # Nunca vaza o token do WhatsApp no log
            log.warning("Falha ao despachar notificacao pelo WhatsApp: %s", type(e).__name__)
            return False
