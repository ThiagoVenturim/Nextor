"""Cliente da API oficial do Notion para sincronizacao GTD (Issue #42).

Opera de forma segura e tolerante a falhas (fail-safe):
- Se NOTION_TOKEN nao estiver configurado, a integracao permanece desligada silenciosamente.
- Tratamento rigoroso de excecoes sem expor tokens ou credenciais em mensagens de erro ou logs.
- Suporta cliente HTTP injetavel para testes 100% offline.
"""
from datetime import datetime
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

from .. import config

log = logging.getLogger("nextor.gtd.notion")
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


def obter_token_notion() -> str:
    return os.getenv("NOTION_TOKEN", "") or getattr(config, "NOTION_TOKEN", "")


def obter_db_tarefas() -> str:
    return os.getenv("NOTION_DB_TAREFAS", "") or getattr(config, "NOTION_DB_TAREFAS", "")


def obter_db_leituras() -> str:
    return os.getenv("NOTION_DB_LEITURAS", "") or getattr(config, "NOTION_DB_LEITURAS", "")


class ClienteNotion:
    """Cliente HTTP minimo para as operacoes necessarias na API do Notion."""

    def __init__(
        self,
        token: Optional[str] = None,
        db_tarefas: Optional[str] = None,
        db_leituras: Optional[str] = None,
        http_client: Optional[Callable[[str, str, Optional[Dict[str, Any]], Dict[str, str]], Tuple[int, Dict[str, Any]]]] = None,
    ):
        self.token = (token if token is not None else obter_token_notion()).strip()
        self.db_tarefas = (db_tarefas if db_tarefas is not None else obter_db_tarefas()).strip()
        self.db_leituras = (db_leituras if db_leituras is not None else obter_db_leituras()).strip()
        self._http_client = http_client

    def disponivel(self) -> bool:
        """Indica se a integracao esta habilitada com token e pelo menos um banco configurado."""
        return bool(self.token and (self.db_tarefas or self.db_leituras))

    def _requisicao(
        self,
        caminho: str,
        metodo: str = "GET",
        dados: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        if not self.token:
            return 400, {"erro": "notion_desligado"}

        url = f"{NOTION_BASE_URL}{caminho}" if not caminho.startswith("http") else caminho
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "Nextor-GTD",
        }

        if self._http_client is not None:
            return self._http_client(url, metodo, dados, headers)

        payload = json.dumps(dados).encode("utf-8") if dados is not None else None
        req = urllib.request.Request(url, data=payload, headers=headers, method=metodo)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                corpo = json.loads(resp.read().decode("utf-8"))
                return resp.status, corpo
        except urllib.error.HTTPError as e:
            # Nunca inclui o token ou headers na mensagem de erro
            log.warning("Falha HTTP na API do Notion (codigo %s)", e.code)
            return e.code, {"erro": f"http_error_{e.code}"}
        except Exception as e:
            log.warning("Falha de conexao com a API do Notion: %s", type(e).__name__)
            return 503, {"erro": "falha_conexao"}

    def consultar_banco(
        self,
        database_id: str,
        filtro: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Consulta paginas de uma base de dados no Notion."""
        if not self.disponivel() or not database_id:
            return []

        payload: Dict[str, Any] = {}
        if filtro:
            payload["filter"] = filtro

        status, resp = self._requisicao(f"/databases/{database_id}/query", metodo="POST", dados=payload)
        if status == 200 and isinstance(resp, dict):
            return resp.get("results", [])
        return []

    def criar_pagina(self, database_id: str, propriedades: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Cria uma nova pagina em uma base de dados do Notion."""
        if not self.disponivel() or not database_id:
            return None

        payload = {
            "parent": {"database_id": database_id},
            "properties": propriedades,
        }
        status, resp = self._requisicao("/pages", metodo="POST", dados=payload)
        if status in (200, 201) and isinstance(resp, dict):
            return resp
        return None

    def atualizar_pagina(self, page_id: str, propriedades: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Atualiza propriedades de uma pagina existente no Notion."""
        if not self.disponivel() or not page_id:
            return None

        payload = {"properties": propriedades}
        status, resp = self._requisicao(f"/pages/{page_id}", metodo="PATCH", dados=payload)
        if status == 200 and isinstance(resp, dict):
            return resp
        return None


def extrair_texto_propriedade(prop: Dict[str, Any]) -> str:
    """Extrai texto legivel de uma propriedade de pagina do Notion."""
    if not isinstance(prop, dict):
        return ""
    tipo = prop.get("type", "")
    if tipo == "title":
        titulos = prop.get("title") or []
        return "".join(t.get("plain_text", "") for t in titulos)
    if tipo == "rich_text":
        textos = prop.get("rich_text") or []
        return "".join(t.get("plain_text", "") for t in textos)
    if tipo == "select":
        sel = prop.get("select") or {}
        return sel.get("name", "")
    if tipo == "status":
        st = prop.get("status") or {}
        return st.get("name", "")
    if tipo == "number":
        return str(prop.get("number", 0))
    if tipo == "url":
        return prop.get("url") or ""
    return ""


def montar_propriedade_titulo(texto: str) -> Dict[str, Any]:
    return {"title": [{"text": {"content": texto}}]}


def montar_propriedade_texto(texto: str) -> Dict[str, Any]:
    return {"rich_text": [{"text": {"content": texto}}]}


def montar_propriedade_select(nome: str) -> Dict[str, Any]:
    return {"select": {"name": nome}}


def montar_propriedade_numero(valor: int) -> Dict[str, Any]:
    return {"number": valor}
