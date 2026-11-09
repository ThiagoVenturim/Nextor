"""Integracao entre o Coach de Estudos e o painel GTD do Nextor (Issue #57).

Cada acao do dia vira uma tarefa no GTD com contexto @estudo e prazo.
Concluir a tarefa no painel GTD reflete no progresso do coach, e vice-versa.
"""
import logging
from typing import Any, List, Optional
import uuid

from ..gtd.armazenamento import ArmazenamentoGTD
from ..gtd.modelos import Item
from .armazenamento import ArmazenamentoCoach
from .modelos import Plano, ProgressoAcao, Recurso

log = logging.getLogger("nextor.coach.gtd")


def _obter_db_coach(db: Optional[ArmazenamentoCoach]) -> ArmazenamentoCoach:
    return db if db is not None else ArmazenamentoCoach()


def _obter_db_gtd(db: Optional[ArmazenamentoGTD]) -> ArmazenamentoGTD:
    return db if db is not None else ArmazenamentoGTD()


def criar_tarefa_gtd_para_acao(
    acao: ProgressoAcao,
    recurso: Optional[Recurso] = None,
    db_coach: Optional[ArmazenamentoCoach] = None,
    db_gtd: Optional[ArmazenamentoGTD] = None,
) -> Item:
    """Cria uma tarefa no painel GTD correspondente a uma acao de estudo."""
    b_coach = _obter_db_coach(db_coach)
    b_gtd = _obter_db_gtd(db_gtd)

    rec = recurso or b_coach.obter_recurso(acao.recurso_id)
    titulo_rec = rec.titulo if rec else "Acao de estudo"
    tipo_rec = rec.tipo if rec else "aula"
    duracao = rec.duracao_min if rec else 15
    nota = f"Trilha de estudos Nextor. Tipo: {tipo_rec} ({duracao} min)."
    if rec and rec.url:
        nota += f" Link: {rec.url}"

    ref = f"coach:{acao.plano_id}:{acao.recurso_id}"

    # Se ja existir item com essa ref_externa, reaproveita
    existente = b_gtd.buscar_item_por_ref(ref)
    if existente:
        if acao.gtd_item_id != existente.id:
            acao.gtd_item_id = existente.id
            b_coach.salvar_acao(acao)
        return existente

    item = Item(
        id=str(uuid.uuid4()),
        titulo=f"[Estudo] {titulo_rec}",
        nota=nota,
        contexto="@estudo",
        estado="proxima",
        prazo=acao.data,
        energia="media",
        origem="coach",
        ref_externa=ref,
        metadados={
            "plano_id": acao.plano_id,
            "recurso_id": acao.recurso_id,
            "acao_id": acao.id,
            "tipo_estudo": tipo_rec,
        },
    )
    b_gtd.salvar_item(item)

    acao.gtd_item_id = item.id
    b_coach.salvar_acao(acao)
    return item


def criar_tarefas_gtd_plano(
    plano: Plano,
    acoes: List[ProgressoAcao],
    db_coach: Optional[ArmazenamentoCoach] = None,
    db_gtd: Optional[ArmazenamentoGTD] = None,
) -> List[Item]:
    """Cria as tarefas GTD para todas as acoes pendentes de um plano."""
    itens: List[Item] = []
    b_coach = _obter_db_coach(db_coach)
    b_gtd = _obter_db_gtd(db_gtd)
    for acao in acoes:
        if acao.estado == "pendente":
            it = criar_tarefa_gtd_para_acao(acao, db_coach=b_coach, db_gtd=b_gtd)
            itens.append(it)
    return itens


def concluir_tarefa_gtd_vinculada(
    gtd_item_id: str,
    db_gtd: Optional[ArmazenamentoGTD] = None,
) -> Optional[Item]:
    """Conclui a tarefa no painel GTD quando a acao de estudo e finalizada pelo coach."""
    b_gtd = _obter_db_gtd(db_gtd)
    item = b_gtd.obter_item(gtd_item_id)
    if not item:
        return None
    if item.estado != "feito":
        from datetime import datetime
        item.estado = "feito"
        item.concluido_em = datetime.now().isoformat(timespec="seconds")
        return b_gtd.salvar_item(item)
    return item


def sincronizar_conclusao_gtd(
    item_id: str,
    db_coach: Optional[ArmazenamentoCoach] = None,
    db_gtd: Optional[ArmazenamentoGTD] = None,
) -> Optional[dict]:
    """Quando uma tarefa GTD oriunda do coach e concluida, sincroniza com o coach."""
    b_gtd = _obter_db_gtd(db_gtd)
    item = b_gtd.obter_item(item_id)
    if not item or item.origem != "coach" or not item.ref_externa:
        return None

    if not item.ref_externa.startswith("coach:"):
        return None

    partes = item.ref_externa.split(":")
    if len(partes) < 3:
        return None

    plano_id = partes[1]
    recurso_id = partes[2]

    from .coach import concluir
    return concluir(plano_id, recurso_id, data=item.prazo, db=db_coach, db_gtd=b_gtd, sincronizar_gtd=False)
