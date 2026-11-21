"""Operacoes do painel sobre o metodo ativo, compartilhadas por HTTP e MCP (Issue #45)."""
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..armazenamento import ArmazenamentoGTD
from ..modelos import Item
from .base import Metodo
from .registro import obter_metodo


class ItemNaoEncontrado(LookupError):
    """O item pedido nao existe no armazenamento."""


def metodo_ativo(cfg: Optional[Mapping[str, Any]] = None, slug: Optional[str] = None) -> Metodo:
    """Metodo pedido explicitamente ou o ``metodo_ativo`` da configuracao, ja configurado."""
    if cfg is None:
        from ..configuracao import carregar_config
        cfg = carregar_config()
    return obter_metodo(slug or cfg.get("metodo_ativo"), cfg)


def montar_visao(
    db: Optional[ArmazenamentoGTD] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    slug: Optional[str] = None,
    agenda: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    banco = db if db is not None else ArmazenamentoGTD()
    metodo = metodo_ativo(cfg, slug)
    return metodo.visao_dia(banco.listar_itens(), agenda)


def mover_item(
    item_id: str,
    coluna: str,
    db: Optional[ArmazenamentoGTD] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    slug: Optional[str] = None,
) -> Tuple[Item, Metodo]:
    """Move um item para uma coluna do metodo e persiste.

    Levanta ``ItemNaoEncontrado``, ``ColunaInvalida`` ou ``LimiteWIPExcedido``.
    Campos de outros metodos ficam intactos, entao a troca de metodo nao perde nada.
    """
    banco = db if db is not None else ArmazenamentoGTD()
    item = banco.obter_item(str(item_id or "").strip())
    if item is None:
        raise ItemNaoEncontrado(f"item nao encontrado: {item_id}")
    metodo = metodo_ativo(cfg, slug)
    metodo.mover(item, coluna, banco.listar_itens())
    banco.salvar_item(item)
    return item, metodo
