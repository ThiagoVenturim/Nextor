"""Canal de notificacao via Web Push para o PWA no celular (W3C Push API com VAPID).

Configuracao (detalhes em docs/NOTIFICACOES.md):
- VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY e VAPID_SUBSCRIBER_EMAIL no .env.
- Biblioteca opcional pywebpush: pip install -e ".[push]".
- Cada aparelho ativa as notificacoes no painel /gtd, que registra a inscricao no servidor.
"""
import json
import logging
import os
from typing import Any, Callable, Dict, Optional

from .. import config
from .base import CanalNotificacao, formatar_titulo, normalizar_urgencia
from .inscricoes_push import InscricoesPush

log = logging.getLogger("nextor.notificacoes.webpush")

# Cabecalho Urgency do protocolo Web Push (RFC 8030).
URGENCIA_HTTP = {"baixa": "low", "normal": "normal", "alta": "high", "critica": "high"}
# Tempo que o servico de push guarda a mensagem se o aparelho estiver offline.
TTL_SEGUNDOS = 12 * 3600
# Status de resposta que indicam inscricao expirada ou cancelada.
STATUS_INSCRICAO_EXPIRADA = (404, 410)

# (inscricao, dados_json, chave_privada, claims, urgencia_http) -> status HTTP
EnviadorPush = Callable[[Dict[str, Any], str, str, Dict[str, str], str], int]


def _enviar_com_pywebpush(
    inscricao: Dict[str, Any],
    dados: str,
    chave_privada: str,
    claims: Dict[str, str],
    urgencia_http: str,
) -> int:
    """Envia uma mensagem com pywebpush. Levanta ImportError se a biblioteca faltar."""
    from pywebpush import WebPushException, webpush

    try:
        resp = webpush(
            subscription_info=inscricao,
            data=dados,
            vapid_private_key=chave_privada,
            vapid_claims=dict(claims),
            ttl=TTL_SEGUNDOS,
            headers={"Urgency": urgencia_http},
            timeout=10,
        )
        return int(getattr(resp, "status_code", 201) or 201)
    except WebPushException as e:
        resposta = getattr(e, "response", None)
        status = getattr(resposta, "status_code", None)
        if status is None:
            raise
        return int(status)


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
        inscricoes: Optional[InscricoesPush] = None,
        enviar_push: Optional[EnviadorPush] = None,
    ):
        """enviador_mock substitui o envio inteiro (testes antigos); enviar_push substitui
        so a chamada HTTP por inscricao, mantendo a logica de inscricoes e expiracao."""
        self._public_key = public_key
        self._private_key = private_key
        self._subscriber_email = subscriber_email
        self._enviador_mock = enviador_mock
        self.inscricoes = inscricoes or InscricoesPush()
        self._enviar_push = enviar_push or _enviar_com_pywebpush

    def _obter_public_key(self) -> str:
        return (self._public_key or os.getenv("VAPID_PUBLIC_KEY", "") or getattr(config, "VAPID_PUBLIC_KEY", "")).strip()

    def _obter_private_key(self) -> str:
        return (self._private_key or os.getenv("VAPID_PRIVATE_KEY", "") or getattr(config, "VAPID_PRIVATE_KEY", "")).strip()

    def _obter_email(self) -> str:
        return (self._subscriber_email or os.getenv("VAPID_SUBSCRIBER_EMAIL", "") or getattr(config, "VAPID_SUBSCRIBER_EMAIL", "")).strip()

    def chave_publica(self) -> str:
        """Chave publica VAPID que o navegador usa em pushManager.subscribe (nao e segredo)."""
        return self._obter_public_key()

    def _claims(self) -> Dict[str, str]:
        contato = self._obter_email()
        if not contato.startswith(("mailto:", "https://")):
            contato = f"mailto:{contato}"
        return {"sub": contato}

    def configurado(self) -> bool:
        return bool(self._obter_public_key() and self._obter_private_key() and self._obter_email())

    def montar_payload(self, titulo: str, corpo: str, urgencia: str = "normal") -> Dict[str, Any]:
        return {
            "title": formatar_titulo(titulo, urgencia)[:120],
            "body": str(corpo or "").strip()[:1000],
            "urgency": normalizar_urgencia(urgencia),
            "url": "/gtd",
        }

    def enviar(self, titulo: str, corpo: str, urgencia: str = "normal") -> bool:
        if not self.configurado():
            return False

        payload = self.montar_payload(titulo, corpo, urgencia)

        if self._enviador_mock is not None:
            try:
                return bool(self._enviador_mock(payload, {"public_key": self._obter_public_key()}))
            except Exception as e:
                log.warning("Falha no envio WebPush: %s", type(e).__name__)
                return False

        inscricoes = self.inscricoes.listar()
        if not inscricoes:
            log.info("Web Push sem aparelhos inscritos; ative as notificacoes no painel /gtd.")
            return False

        dados = json.dumps(payload, ensure_ascii=False)
        urgencia_http = URGENCIA_HTTP.get(normalizar_urgencia(urgencia), "normal")
        entregues = 0
        for inscricao in inscricoes:
            try:
                status = self._enviar_push(inscricao, dados, self._obter_private_key(), self._claims(), urgencia_http)
            except ImportError:
                log.warning("Biblioteca pywebpush nao instalada; instale com pip install -e \".[push]\".")
                return False
            except Exception as e:
                # Nunca loga o endpoint (identifica o aparelho) nem a chave privada.
                log.warning("Falha ao enviar web push: %s", type(e).__name__)
                continue
            if 200 <= status < 300:
                entregues += 1
            elif status in STATUS_INSCRICAO_EXPIRADA:
                self.inscricoes.remover(inscricao["endpoint"])
                log.info("Inscricao de web push expirada removida.")
            else:
                log.warning("Servico de push respondeu com status %s.", status)
        return entregues > 0
