"""Modulo de gestao de leituras e meta diaria (Issue #44).

Organiza livros e artigos, acompanha o progresso diário de leitura
e integra artigos cientificos buscados via OpenAlex e arXiv.
"""
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional
import uuid

from .. import config
from .armazenamento import ArmazenamentoGTD
from .modelos import Leitura


def _obter_db(db: Optional[ArmazenamentoGTD]) -> ArmazenamentoGTD:
    return db if db is not None else ArmazenamentoGTD()


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
        estado=estado if estado in ("quero_ler", "lendo", "lido") else "quero_ler",
        paginas_total=max(0, int(paginas_total or 0)),
        paginas_lidas=max(0, int(paginas_lidas or 0)),
        fonte_url=(fonte_url or "").strip(),
    )
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

    meta_diaria = getattr(config, "LEITURA_META_DIARIA", 20)
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
    meta = getattr(config, "LEITURA_META_DIARIA", 20)
    return {
        "data": hoje_iso,
        "paginas_lidas_hoje": paginas_hoje,
        "meta_diaria": meta,
        "meta_atingida": paginas_hoje >= meta,
        "faltam_paginas": max(0, meta - paginas_hoje),
    }


def importar_artigos(
    termo: str = "",
    fonte: str = "todos",
    limite: int = 5,
    db: Optional[ArmazenamentoGTD] = None,
    buscador: Optional[Callable] = None,
) -> List[Leitura]:
    """Busca artigos cientificos e adiciona a fila 'quero_ler' sem duplicar.

    Verifica duplicidade por URL da fonte ou titulo exato.
    """
    banco = _obter_db(db)
    if buscador is not None:
        artigos = buscador(termo, fonte=fonte, limite=limite)
    else:
        try:
            from .. import artigos_cientificos
            artigos = artigos_cientificos.buscar_artigos(termo, fonte=fonte, limite=limite)
        except Exception:
            artigos = []

    importados: List[Leitura] = []
    for art in artigos:
        url = (art.get("url") or art.get("pdf_url") or "").strip()
        titulo = (art.get("titulo") or "").strip()
        if not titulo:
            continue

        # Evita duplicatas por URL ou por titulo
        if url and banco.buscar_leitura_por_url(url):
            continue
        if banco.buscar_leitura_por_titulo(titulo):
            continue

        autores_raw = art.get("autores") or []
        if isinstance(autores_raw, list):
            autor_str = ", ".join(autores_raw[:3])
            if len(autores_raw) > 3:
                autor_str += " et al."
        else:
            autor_str = str(autores_raw)

        nova = Leitura(
            id=str(uuid.uuid4()),
            titulo=titulo,
            autor=autor_str,
            tipo="artigo",
            estado="quero_ler",
            paginas_total=10,  # Estimativa padrao para artigo academico
            paginas_lidas=0,
            fonte_url=url,
        )
        banco.salvar_leitura(nova)
        importados.append(nova)

    return importados
