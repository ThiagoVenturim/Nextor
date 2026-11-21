"""Metodo GTD (Getting Things Done - A Arte de Fazer Acontecer)."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..modelos import ESTADOS_ITEM, Item
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
        if item.estado in ESTADOS_ITEM:
            return item.estado
        return "inbox"

    def campos_extra(self) -> List[Dict[str, Any]]:
        return []

    def mover(self, item: Item, coluna: str, itens: Optional[List[Item]] = None) -> Item:
        # No GTD a coluna e o proprio estado do item.
        c = self.validar_coluna(coluna)
        if c == "feito":
            if item.estado != "feito":
                item.concluido_em = datetime.now().isoformat(timespec="seconds")
        else:
            item.concluido_em = None
        item.estado = c
        return item

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        dados_base = super().visao_dia(itens, agenda)
        hoje = date.today().isoformat()

        proximas = dados_base["itens_por_coluna"].get("proxima", [])
        urgentes = [i for i in proximas if i.get("prazo") and i["prazo"] <= hoje]
        demais = [i for i in proximas if not i.get("prazo") or i["prazo"] > hoje]
        dados_base["foco_hoje"] = urgentes + demais[:5]

        # Contextos: proximas acoes abertas por contexto.
        contextos: Dict[str, int] = {}
        for i in proximas:
            ctx = i.get("contexto") or "@qualquer"
            contextos[ctx] = contextos.get(ctx, 0) + 1
        dados_base["contextos"] = contextos

        # Projetos: acoes abertas por projeto e quais estao sem proxima acao definida.
        projetos: Dict[str, Dict[str, int]] = {}
        for it in itens:
            if not it.projeto_id or it.estado == "feito":
                continue
            p = projetos.setdefault(it.projeto_id, {"abertas": 0, "proximas": 0})
            p["abertas"] += 1
            if it.estado == "proxima":
                p["proximas"] += 1
        dados_base["projetos"] = projetos

        # Revisao: o que precisa de atencao na revisao semanal.
        por_col = dados_base["itens_por_coluna"]
        dados_base["revisao"] = {
            "inbox_para_processar": len(por_col.get("inbox", [])),
            "aguardando": len(por_col.get("aguardando", [])),
            "algum_dia": len(por_col.get("algum_dia", [])),
            "projetos_sem_proxima_acao": sorted(pid for pid, p in projetos.items() if p["proximas"] == 0),
        }
        return dados_base
