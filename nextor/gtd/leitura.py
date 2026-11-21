"""Modulo de gestao de leituras e meta diaria (Issue #44).

Organiza livros e artigos, acompanha o progresso diario de leitura
e integra artigos cientificos buscados via OpenAlex e arXiv.
"""
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional
import uuid

from .. import config
from .armazenamento import ArmazenamentoGTD
from .modelos import ESTADOS_LEITURA, Leitura

# Estimativa padrao de paginas para artigo academico importado sem essa informacao.
PAGINAS_PADRAO_ARTIGO = 10
LIMITE_MAX_IMPORTACAO = 20


def _obter_db(db: Optional[ArmazenamentoGTD]) -> ArmazenamentoGTD:
    return db if db is not None else ArmazenamentoGTD()


def _meta_configurada() -> int:
    try:
        return max(1, int(getattr(config, "LEITURA_META_DIARIA", 20)))
    except (TypeError, ValueError):
        return 20


def criar_leitura(
    titulo: str,
    autor: str = "",
    tipo: str = "livro",
    estado: str = "quero_ler",
    paginas_total: int = 0,
    paginas_lidas: int = 0,
    fonte_url: str = "",
    db: Optional[ArmazenamentoGTD] = None,
) -> Leitura:
    """Cadastra um novo livro ou artigo na fila de leitura."""
    t = (titulo or "").strip()
    if not t:
        raise ValueError("O titulo da leitura nao pode ser vazio.")

    leitura = Leitura(
        id=str(uuid.uuid4()),
        titulo=t,
        autor=(autor or "").strip(),
        tipo=tipo if tipo in ("livro", "artigo") else "livro",
        estado=estado if estado in ESTADOS_LEITURA else "quero_ler",
        paginas_total=max(0, int(paginas_total or 0)),
        paginas_lidas=max(0, int(paginas_lidas or 0)),
        fonte_url=(fonte_url or "").strip(),
    )
    if leitura.estado == "lido" and not leitura.concluido_em:
        leitura.concluido_em = datetime.now().isoformat(timespec="seconds")
    banco = _obter_db(db)
    return banco.salvar_leitura(leitura)


def obter_leitura(leitura_id: str, db: Optional[ArmazenamentoGTD] = None) -> Optional[Leitura]:
    banco = _obter_db(db)
    return banco.obter_leitura(leitura_id)


def listar_leituras(
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    db: Optional[ArmazenamentoGTD] = None,
) -> List[Leitura]:
    banco = _obter_db(db)
    return banco.listar_leituras(estado=estado, tipo=tipo)


def definir_estado_leitura(
    leitura_id: str,
    estado: str,
    db: Optional[ArmazenamentoGTD] = None,
) -> Leitura:
    """Muda o estado de uma leitura (quero_ler, lendo, lido).

    Marcar como lido registra a data de conclusao e completa as paginas do item,
    sem somar nada ao historico diario: a meta conta so paginas registradas.
    Voltar de lido para outro estado limpa a data de conclusao.
    """
    estado_norm = (estado or "").strip().lower()
    if estado_norm not in ESTADOS_LEITURA:
        raise ValueError(f"Estado invalido '{estado}'. Use: {', '.join(ESTADOS_LEITURA)}.")

    banco = _obter_db(db)
    leitura = banco.obter_leitura(leitura_id)
    if not leitura:
        raise ValueError(f"Leitura com id '{leitura_id}' nao encontrada.")

    leitura.estado = estado_norm
    if estado_norm == "lido":
        if not leitura.concluido_em:
            leitura.concluido_em = datetime.now().isoformat(timespec="seconds")
        if leitura.paginas_total > 0:
            leitura.paginas_lidas = max(leitura.paginas_lidas, leitura.paginas_total)
    else:
        leitura.concluido_em = None
    return banco.salvar_leitura(leitura)


def remover_leitura(leitura_id: str, db: Optional[ArmazenamentoGTD] = None) -> bool:
    """Remove uma leitura da lista. Retorna False se o id nao existir."""
    banco = _obter_db(db)
    return banco.remover_leitura(leitura_id)


def atualizar_progresso(
    leitura_id: str,
    paginas: int,
    db: Optional[ArmazenamentoGTD] = None,
) -> Dict[str, Any]:
    """Registra paginas lidas em uma leitura e no historico diario."""
    if paginas <= 0:
        raise ValueError("O numero de paginas lidas deve ser maior que zero.")

    banco = _obter_db(db)
    leitura = banco.obter_leitura(leitura_id)
    if not leitura:
        raise ValueError(f"Leitura com id '{leitura_id}' nao encontrada.")

    leitura.paginas_lidas += paginas
    if leitura.estado == "quero_ler":
        leitura.estado = "lendo"

    if leitura.paginas_total > 0 and leitura.paginas_lidas >= leitura.paginas_total:
        leitura.estado = "lido"
        leitura.concluido_em = datetime.now().isoformat(timespec="seconds")

    banco.salvar_leitura(leitura)
    total_hoje = banco.registrar_progresso_leitura(leitura.id, paginas)

    meta_diaria = _meta_configurada()
    meta_atingida = total_hoje >= meta_diaria

    return {
        "leitura": leitura.to_dict(),
        "paginas_adicionadas": paginas,
        "paginas_lidas_hoje": total_hoje,
        "meta_diaria": meta_diaria,
        "meta_atingida": meta_atingida,
        "faltam_paginas": max(0, meta_diaria - total_hoje),
    }


def meta_diaria_progresso(db: Optional[ArmazenamentoGTD] = None) -> Dict[str, Any]:
    """Retorna o status da meta de leitura no dia de hoje."""
    banco = _obter_db(db)
    hoje_iso = date.today().isoformat()
    paginas_hoje = banco.paginas_lidas_na_data(hoje_iso)
    meta = _meta_configurada()
    return {
        "data": hoje_iso,
        "paginas_lidas_hoje": paginas_hoje,
        "meta_diaria": meta,
        "meta_atingida": paginas_hoje >= meta,
        "faltam_paginas": max(0, meta - paginas_hoje),
        "percentual": min(100, round(paginas_hoje * 100 / meta)),
    }


def resumo_leituras(db: Optional[ArmazenamentoGTD] = None, limite_fila: int = 3) -> Dict[str, Any]:
    """Resumo da lista de leitura para o painel do dia.

    Traz a meta de hoje, a contagem por estado, o que esta sendo lido e os
    proximos itens da fila 'quero_ler'.
    """
    banco = _obter_db(db)
    todas = banco.listar_leituras()
    contagem = {estado: 0 for estado in ESTADOS_LEITURA}
    for leitura in todas:
        contagem[leitura.estado] = contagem.get(leitura.estado, 0) + 1

    lendo = [leitura.to_dict() for leitura in todas if leitura.estado == "lendo"]
    fila = [leitura.to_dict() for leitura in todas if leitura.estado == "quero_ler"][: max(0, limite_fila)]
    return {
        "meta": meta_diaria_progresso(db=banco),
        "contagem": contagem,
        "lendo": lendo,
        "fila_quero_ler": fila,
    }


def _autores_curto(autores_raw: Any) -> str:
    if isinstance(autores_raw, list):
        nomes = [str(a).strip() for a in autores_raw if str(a).strip()]
        texto = ", ".join(nomes[:3])
        if len(nomes) > 3:
            texto += " et al."
        return texto
    return str(autores_raw or "").strip()


def importar_artigos(
    termo: str = "",
    fonte: str = "todos",
    limite: int = 5,
    db: Optional[ArmazenamentoGTD] = None,
    buscador: Optional[Callable] = None,
    artigos: Optional[Iterable[Dict[str, Any]]] = None,
) -> List[Leitura]:
    """Adiciona artigos cientificos a fila 'quero_ler' sem duplicar.

    Usa os artigos ja buscados por ``nextor.artigos_cientificos`` quando
    ``artigos`` e informado (por exemplo, o resultado de /estudos/artigos/buscar).
    Sem ``artigos``, faz a busca pelo ``termo`` com o mesmo modulo (ou com o
    ``buscador`` injetado nos testes). Verifica duplicidade por URL da fonte ou
    titulo exato.
    """
    banco = _obter_db(db)
    try:
        limite = max(1, min(LIMITE_MAX_IMPORTACAO, int(limite)))
    except (TypeError, ValueError):
        limite = 5

    if artigos is not None:
        candidatos = [a for a in artigos if isinstance(a, dict)][:limite]
    elif buscador is not None:
        candidatos = buscador(termo, fonte=fonte, limite=limite)
    else:
        if not (termo or "").strip():
            return []
        try:
            from .. import artigos_cientificos
            candidatos = artigos_cientificos.buscar_artigos(termo, fonte=fonte, limite=limite)
        except Exception:
            candidatos = []

    importados: List[Leitura] = []
    for art in candidatos:
        url = str(art.get("url") or art.get("pdf_url") or "").strip()
        titulo = str(art.get("titulo") or "").strip()
        if not titulo:
            continue

        # Evita duplicatas por URL ou por titulo
        if url and banco.buscar_leitura_por_url(url):
            continue
        if banco.buscar_leitura_por_titulo(titulo):
            continue

        nova = Leitura(
            id=str(uuid.uuid4()),
            titulo=titulo,
            autor=_autores_curto(art.get("autores")),
            tipo="artigo",
            estado="quero_ler",
            paginas_total=PAGINAS_PADRAO_ARTIGO,
            paginas_lidas=0,
            fonte_url=url,
        )
        banco.salvar_leitura(nova)
        importados.append(nova)

    return importados
