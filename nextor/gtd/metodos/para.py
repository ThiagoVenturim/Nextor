"""Metodo P.A.R.A. (Projetos, Areas, Recursos, Arquivos - Tiago Forte)."""
from datetime import date
from typing import Any, Dict, List, Optional

from ..modelos import Item
from .base import Metodo


class MetodoPARA(Metodo):
    """Implementacao do metodo PARA (Building a Second Brain)."""

    nome = "P.A.R.A. (Tiago Forte)"
    slug = "para"
    descricao = "Organizacao centrada em acao: Projetos (curto prazo), Areas (padroes continuos), Recursos (interesses) e Arquivos (inativos)."

    def colunas(self) -> List[Dict[str, str]]:
        return [
            {"id": "inbox", "titulo": "Entrada", "descricao": "Itens pendentes de classificacao nos 4 baldes"},
            {"id": "projetos", "titulo": "Projetos", "descricao": "Resultados de curto prazo com prazos definidos"},
            {"id": "areas", "titulo": "Areas de Foco", "descricao": "Responsabilidades continuas (trabalho, faculdade, casa, saude)"},
            {"id": "recursos", "titulo": "Recursos", "descricao": "Temas de interesse, materiais de estudo e leituras uteis"},
            {"id": "arquivos", "titulo": "Arquivos", "descricao": "Itens concluidos ou inativos arquivados para historico"},
        ]

    def classificar(self, item: Item) -> str:
        if item.estado == "feito":
            return "arquivos"

        meta_balde = item.obter_meta("balde_para")
        if meta_balde in ("inbox", "projetos", "areas", "recursos", "arquivos"):
            return meta_balde

        if item.projeto_id:
            return "projetos"

        if item.contexto in ("@leitura",):
            return "recursos"

        if item.contexto in ("@faculdade", "@trabalho", "@casa", "@academia"):
            return "areas"

        if item.estado == "inbox":
            return "inbox"

        return "areas"

    def campos_extra(self) -> List[Dict[str, Any]]:
        return [
            {
                "campo": "balde_para",
                "tipo": "select",
                "opcoes": ["inbox", "projetos", "areas", "recursos", "arquivos"],
                "padrao": "areas",
                "rotulo": "Balde PARA",
            }
        ]

    def visao_dia(self, itens: List[Item], agenda: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        dados_base = super().visao_dia(itens, agenda)
        hoje = date.today().isoformat()

        # No PARA, o foco do dia sao os Projetos imediatos seguidos das Areas ativas
        projetos = dados_base["itens_por_coluna"].get("projetos", [])
        areas = dados_base["itens_por_coluna"].get("areas", [])

        urgentes = [i for i in (projetos + areas) if i.get("prazo") and i["prazo"] <= hoje]
        demais = [i for i in (projetos + areas) if not i.get("prazo") or i["prazo"] > hoje]

        dados_base["foco_hoje"] = urgentes + demais[:5]
        return dados_base
