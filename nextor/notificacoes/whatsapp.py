"""Canal de notificacao via WhatsApp Cloud API (Meta for Developers). Opcional.

Requisitos para uso (passo a passo em docs/NOTIFICACOES.md):
- Um app no Meta for Developers com o produto WhatsApp e uma conta WhatsApp Business
  (a Cloud API exige conta business; o numero de teste do painel serve para comecar).
- WHATSAPP_API_TOKEN: token de acesso (usuario do sistema ou token temporario do painel).
- WHATSAPP_PHONE_NUMBER_ID: ID do numero de envio gerado no painel (so letras e digitos).
- WHATSAPP_DESTINATARIO: numero de destino com DDI e DDD, so digitos (ex: 5511999999999).
- WHATSAPP_TEMPLATE (opcional): nome de um modelo aprovado com dois parametros no corpo
  ({{1}} = titulo, {{2}} = mensagem). Sem modelo, o envio e texto livre, que a Meta so
  entrega se o destinatario falou com o numero nas ultimas 24 horas.
- WHATSAPP_TEMPLATE_IDIOMA (opcional, padrao pt_BR) e WHATSAPP_API_VERSAO (padrao v19.0).

Sem essas variaveis o canal fica desligado e nada quebra.
"""
import json
import logging
import os
from typing import Callable, Optional
import urllib.request

from .. import config
from .base import CanalNotificacao, formatar_titulo

log = logging.getLogger("nextor.notificacoes.whatsapp")

# Limite do corpo de mensagem de texto da Cloud API.
LIMITE_TEXTO = 4096


def _ler(nome: str, padrao: str = "") -> str:
    return (os.getenv(nome, "") or getattr(config, nome, "") or padrao).strip()


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
        template: Optional[str] = None,
    ):
        self._token = token
        self._phone_id = phone_id
        self._destinatario = destinatario
        self._http_client = http_client
        self._template = template

    def _obter_token(self) -> str:
        return self._token or _ler("WHATSAPP_API_TOKEN")

    def _obter_phone_id(self) -> str:
        return self._phone_id or _ler("WHATSAPP_PHONE_NUMBER_ID")

    def _obter_destinatario(self) -> str:
        bruto = self._destinatario or _ler("WHATSAPP_DESTINATARIO")
        return "".join(ch for ch in str(bruto) if ch.isdigit())

    def _obter_template(self) -> str:
        return (self._template if self._template is not None else _ler("WHATSAPP_TEMPLATE")).strip()

    def configurado(self) -> bool:
        phone_id = self._obter_phone_id()
        # O ID entra no caminho da URL: so letras e digitos.
        return bool(self._obter_token() and phone_id.isalnum() and self._obter_destinatario())

    def montar_payload(self, titulo: str, corpo: str, urgencia: str = "normal") -> dict:
        titulo_fmt = formatar_titulo(titulo, urgencia)
        corpo_fmt = str(corpo or "").strip()
        destinatario = self._obter_destinatario()
        template = self._obter_template()
        if template:
            return {
                "messaging_product": "whatsapp",
                "to": destinatario,
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": _ler("WHATSAPP_TEMPLATE_IDIOMA", "pt_BR")},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": titulo_fmt[:200]},
                                {"type": "text", "text": corpo_fmt[:1000]},
                            ],
                        }
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destinatario,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": f"[{titulo_fmt}]\n{corpo_fmt}"[:LIMITE_TEXTO],
            },
        }

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        versao = _ler("WHATSAPP_API_VERSAO", "v19.0")
        url = f"https://graph.facebook.com/{versao}/{self._obter_phone_id()}/messages"
        payload = self.montar_payload(titulo, corpo, urgencia)
        headers = {
            "Authorization": f"Bearer {self._obter_token()}",
            "Content-Type": "application/json",
            "User-Agent": "Nextor-WhatsApp",
        }

        if self._http_client is not None:
            try:
                return bool(self._http_client(url, payload, headers))
            except Exception as e:
                log.warning("Falha no envio WhatsApp: %s", type(e).__name__)
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
            # Nunca vaza o token do WhatsApp no log.
            log.warning("Falha ao despachar notificacao pelo WhatsApp: %s", type(e).__name__)
            return False
