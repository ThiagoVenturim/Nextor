"""Metodo GTD (Getting Things Done - A Arte de Fazer Acontecer)."""
from datetime import date
from typing import Any, Dict, List, Optional

from ..modelos import Item
from .base import Metodo


class MetodoGTD(Metodo):
    """Implementacao do metodo GTD de David Allen."""

    nome = "GTD (Getting Things Done)"
    slug = "gtd"
    descricao = "Fluxo classico de 5 passos: Capturar no Inbox, Esclarecer Proximas Acoes, Aguardando, Algum Dia e Feito."

    def colunas(self) -> List[Dict[str, str]]:
        return [
            {"id": "inbox", "titulo": "Caixa de Entrada", "descricao": "Itens capturados para esclarecer e processar"},
            {"id": "proxima", "titulo": "Proximas Acoes", "descricao": "Acoes imediatas prontas para execucao por contexto"},
            {"id": "aguardando", "titulo": "Aguardando", "descricao": "Tarefas delegadas ou pendentes de resposta externa"},
            {"id": "algum_dia", "titulo": "Algum Dia / Talvez", "descricao": "Ideias e projetos futuros sem compromisso imediato"},
            {"id": "feito", "titulo": "Concluido", "descricao": "Acoes e pendencias finalizadas"},
        ]

    def classificar(self, item: Item) -> str:
        if item.estado in ("inbox", "proxima", "aguardando", "algum_dia", "feito"):
            return item.estado
        return "inbox"

    def campos_extra(self) -> List[Dict[str, Any]]:
        return []

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        dados_base = super().visao_dia(itens, agenda)
        hoje = date.today().isoformat()

        proximas = dados_base["itens_por_coluna"].get("proxima", [])
        urgentes = [i for i in proximas if i.get("prazo") and i["prazo"] <= hoje]
        demais = [i for i in proximas if not i.get("prazo") or i["prazo"] > hoje]

        dados_base["foco_hoje"] = urgentes + demais[:5]
        return dados_base
