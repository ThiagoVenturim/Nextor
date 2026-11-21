"""Inscricoes de Web Push dos navegadores/PWA (Issue #46).

Cada aparelho que ativa as notificacoes no PWA manda sua PushSubscription
(endpoint + chaves p256dh e auth). Elas ficam em um JSON local, fora do repositorio:
NEXTOR_PUSH_INSCRICOES ou <NEXTOR_GTD_DIR>/push_inscricoes.json.
"""
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .. import config

log = logging.getLogger("nextor.notificacoes.inscricoes_push")

LIMITE_INSCRICOES = 20
_TAMANHO_MAX_ENDPOINT = 1024
_TAMANHO_MAX_CHAVE = 256


def caminho_padrao() -> Path:
    env = os.getenv("NEXTOR_PUSH_INSCRICOES", "").strip()
    if env:
        return Path(env).resolve()
    pasta = Path(getattr(config, "GTD_DIR", Path.home() / ".nextor")).resolve()
    return pasta / "push_inscricoes.json"


def validar_inscricao(dados: Any) -> Optional[Dict[str, Any]]:
    """Valida uma PushSubscription (formato de PushSubscription.toJSON()).

    Retorna a inscricao normalizada ou None se for invalida.
    """
    if not isinstance(dados, dict):
        return None
    endpoint = str(dados.get("endpoint") or "").strip()
    chaves = dados.get("keys")
    if not endpoint or len(endpoint) > _TAMANHO_MAX_ENDPOINT or not isinstance(chaves, dict):
        return None
    url = urlparse(endpoint)
    if url.scheme != "https" or not url.hostname:
        return None
    p256dh = str(chaves.get("p256dh") or "").strip()
    auth = str(chaves.get("auth") or "").strip()
    permitidos = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=+/")
    for chave in (p256dh, auth):
        if not chave or len(chave) > _TAMANHO_MAX_CHAVE or not set(chave) <= permitidos:
            return None
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


class InscricoesPush:
    """Armazena as inscricoes de Web Push em um arquivo JSON local."""

    def __init__(self, caminho: Optional[Path] = None):
        self._caminho = Path(caminho) if caminho else None
        self._trava = threading.Lock()

    @property
    def caminho(self) -> Path:
        return self._caminho or caminho_padrao()

    def _ler(self) -> List[Dict[str, Any]]:
        caminho = self.caminho
        if not caminho.exists():
            return []
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Falha ao ler inscricoes de push: %s", type(e).__name__)
            return []
        if not isinstance(dados, list):
            return []
        return [i for i in (validar_inscricao(d) for d in dados) if i]

    def _gravar(self, inscricoes: List[Dict[str, Any]]) -> None:
        caminho = self.caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(inscricoes, indent=2), encoding="utf-8")

    def listar(self) -> List[Dict[str, Any]]:
        with self._trava:
            return self._ler()

    def quantidade(self) -> int:
        return len(self.listar())

    def adicionar(self, dados: Any) -> bool:
        """Adiciona ou atualiza uma inscricao. Retorna False se ela for invalida."""
        nova = validar_inscricao(dados)
        if not nova:
            return False
        with self._trava:
            atuais = [i for i in self._ler() if i["endpoint"] != nova["endpoint"]]
            atuais.append(nova)
            # Mantem as mais recentes quando passa do limite.
            self._gravar(atuais[-LIMITE_INSCRICOES:])
        return True

    def remover(self, endpoint: str) -> bool:
        endpoint = str(endpoint or "").strip()
        with self._trava:
            atuais = self._ler()
            restantes = [i for i in atuais if i["endpoint"] != endpoint]
            if len(restantes) == len(atuais):
                return False
            self._gravar(restantes)
        return True
