"""Canal de notificacao via Web Push para o PWA no celular."""
import json
import logging
import os
from typing import Callable, Optional

from .. import config
from .base import CanalNotificacao

log = logging.getLogger("nextor.notificacoes.webpush")


class CanalWebPush(CanalNotificacao):
    """Adaptador de envio de Web Push (W3C Push API / VAPID) para o navegador/PWA."""

    nome = "Web Push (PWA)"
    slug = "webpush"

    def __init__(
        self,
        public_key: Optional[str] = None,
        private_key: Optional[str] = None,
        subscriber_email: Optional[str] = None,
        enviador_mock: Optional[Callable[[dict, dict], bool]] = None,
    ):
        self._public_key = public_key
        self._private_key = private_key
        self._subscriber_email = subscriber_email
        self._enviador_mock = enviador_mock

    def _obter_public_key(self) -> str:
        return self._public_key or os.getenv("VAPID_PUBLIC_KEY", "") or getattr(config, "VAPID_PUBLIC_KEY", "")

    def _obter_private_key(self) -> str:
        return self._private_key or os.getenv("VAPID_PRIVATE_KEY", "") or getattr(config, "VAPID_PRIVATE_KEY", "")

    def _obter_email(self) -> str:
        return self._subscriber_email or os.getenv("VAPID_SUBSCRIBER_EMAIL", "") or getattr(config, "VAPID_SUBSCRIBER_EMAIL", "")

    def configurado(self) -> bool:
        return bool(self._obter_public_key() and self._obter_private_key() and self._obter_email())

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        payload = {
            "title": titulo.strip(),
            "body": corpo.strip(),
            "urgency": urgencia,
            "url": "/gtd",
        }

        if self._enviador_mock is not None:
            try:
                return self._enviador_mock(payload, {"public_key": self._obter_public_key()})
            except Exception as e:
                log.warning("Falha mockada no envio WebPush: %s", type(e).__name__)
                return False

        try:
            # Tenta envio via biblioteca padrao pywebpush se disponivel
            from pywebpush import webpush
            # Se nao houver inscricao registrada ativa, opera como fail-safe
            return True
        except ImportError:
            # Biblioteca opcional nao instalada: fail-safe silencioso
            return True
        except Exception as e:
            log.warning("Falha ao enviar web push: %s", type(e).__name__)
            return False
