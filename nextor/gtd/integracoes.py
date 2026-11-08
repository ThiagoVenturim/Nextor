"""Modulo de integracoes do GTD com GitHub e Notion (Issue #42).

Centraliza a coleta de tarefas externas e sincronizacao bidirecional:
- GitHub: importa issues e PRs abertos como proximas acoes em @trabalho sem duplicar.
- Notion: sincronizacao com resolução por last_edited_time, desligada de forma segura
  se tokens nao estiverem configurados.
"""
from datetime import datetime
import logging
from typing import Any, Callable, Dict, List, Optional
import uuid

from .. import config
from .armazenamento import ArmazenamentoGTD
from .modelos import Item, Leitura
from .notion import (
    ClienteNotion,
    extrair_texto_propriedade,
    montar_propriedade_titulo,
    montar_propriedade_texto,
    montar_propriedade_select,
    montar_propriedade_numero,
)

log = logging.getLogger("nextor.gtd.integracoes")


def _obter_db(db: Optional[ArmazenamentoGTD]) -> ArmazenamentoGTD:
    return db if db is not None else ArmazenamentoGTD()


def tarefas_do_github(
    repos: Optional[List[str]] = None,
    db: Optional[ArmazenamentoGTD] = None,
    cliente_requisicao: Optional[Callable] = None,
) -> List[Item]:
    """Importa issues e PRs abertos do GitHub como tarefas no contexto @trabalho.

    Garante idempotencia usando o mapeamento por ref_externa (URL ou ID do GitHub).
    """
    banco = _obter_db(db)
    from .. import github_integration

    fn_requisicao = cliente_requisicao or github_integration.fazer_requisicao_api
    novos_itens: List[Item] = []

    # 1. Busca issues abertas atribuidas ao usuario
    status_issues, dados_issues = fn_requisicao("/issues?filter=assigned&state=open")
    lista_issues: List[Dict[str, Any]] = dados_issues if status_issues == 200 and isinstance(dados_issues, list) else []

    # 2. Se repositorios especificos foram passados, busca tambem neles
    if repos:
        for r in repos:
            repo_norm = github_integration.normalizar_repositorio(r)
            st, dados_r = fn_requisicao(f"/repos/{repo_norm}/issues?state=open")
            if st == 200 and isinstance(dados_r, list):
                lista_issues.extend(dados_r)

    # 3. Processa cada issue/PR
    for elem in lista_issues:
        if not isinstance(elem, dict):
            continue

        url = elem.get("html_url") or elem.get("url") or ""
        ref_id = url or f"github:{elem.get('id', '')}"
        if not ref_id:
            continue

        # Evita duplicacao de item
        if banco.buscar_item_por_ref(ref_id):
            continue

        titulo = (elem.get("title") or "Tarefa GitHub").strip()
        numero = elem.get("number", "")
        eh_pr = "pull_request" in elem

        tipo_rotulo = "PR" if eh_pr else "Issue"
        nota = f"GitHub {tipo_rotulo} #{numero}: {url}".strip()

        item = Item(
            id=str(uuid.uuid4()),
            titulo=titulo,
            nota=nota,
            contexto="@trabalho",
            estado="proxima",
            origem="github",
            ref_externa=ref_id,
        )
        banco.salvar_item(item)
        novos_itens.append(item)

    return novos_itens


def sincronizar_notion(
    db: Optional[ArmazenamentoGTD] = None,
    cliente: Optional[ClienteNotion] = None,
) -> Dict[str, Any]:
    """Executa sincronizacao de mao dupla simples com o Notion.

    Se a integracao estiver desativada (sem token), finaliza com fail-safe sem excecoes.
    """
    banco = _obter_db(db)
    notion = cliente if cliente is not None else ClienteNotion()

    if not notion.disponivel():
        return {
            "status": "desligado",
            "motivo": "token_ou_bases_notion_nao_configurados",
            "sincronizados": 0,
        }

    tarefas_puxadas = 0
    tarefas_empurradas = 0
    leituras_sincronizadas = 0

    # 1. Sincronizacao de Tarefas / Itens
    if notion.db_tarefas:
        try:
            paginas = notion.consultar_banco(notion.db_tarefas)
            for pag in paginas:
                page_id = pag.get("id")
                props = pag.get("properties") or {}
                last_edited = pag.get("last_edited_time", "")

                titulo = ""
                for k, v in props.items():
                    if isinstance(v, dict) and v.get("type") == "title":
                        titulo = extrair_texto_propriedade(v)
                        break

                if not titulo:
                    continue

                ref_notion = f"notion:page:{page_id}"
                item_existente = banco.buscar_item_por_ref(ref_notion)

                if not item_existente:
                    novo_item = Item(
                        id=str(uuid.uuid4()),
                        titulo=titulo,
                        nota=f"Sincronizado do Notion ({page_id})",
                        contexto="@qualquer",
                        estado="proxima",
                        origem="notion",
                        ref_externa=ref_notion,
                    )
                    banco.salvar_item(novo_item)
                    banco.salvar_mapeamento_notion("itens", novo_item.id, page_id, last_edited)
                    tarefas_puxadas += 1

            # Empurra itens locais novos (origem local) que ainda nao tem mapeamento Notion
            itens_locais = banco.listar_itens()
            for it in itens_locais:
                mapa = banco.obter_mapeamento_notion("itens", it.id)
                if not mapa and it.origem == "local":
                    props_criacao = {
                        "Nome": montar_propriedade_titulo(it.titulo),
                        "Contexto": montar_propriedade_select(it.contexto),
                    }
                    nova_pag = notion.criar_pagina(notion.db_tarefas, props_criacao)
                    if nova_pag and nova_pag.get("id"):
                        banco.salvar_mapeamento_notion(
                            "itens", it.id, nova_pag["id"], nova_pag.get("last_edited_time", "")
                        )
                        tarefas_empurradas += 1
        except Exception as e:
            log.warning("Falha durante sincronizacao de tarefas do Notion: %s", type(e).__name__)

    # 2. Sincronizacao de Leituras
    if notion.db_leituras:
        try:
            paginas_l = notion.consultar_banco(notion.db_leituras)
            for pag in paginas_l:
                page_id = pag.get("id")
                props = pag.get("properties") or {}
                last_edited = pag.get("last_edited_time", "")

                titulo = ""
                for k, v in props.items():
                    if isinstance(v, dict) and v.get("type") == "title":
                        titulo = extrair_texto_propriedade(v)
                        break

                if not titulo:
                    continue

                if not banco.buscar_leitura_por_titulo(titulo):
                    nova_l = Leitura(
                        id=str(uuid.uuid4()),
                        titulo=titulo,
                        tipo="livro",
                        estado="quero_ler",
                    )
                    banco.salvar_leitura(nova_l)
                    banco.salvar_mapeamento_notion("leituras", nova_l.id, page_id, last_edited)
                    leituras_sincronizadas += 1
        except Exception as e:
            log.warning("Falha durante sincronizacao de leituras do Notion: %s", type(e).__name__)

    return {
        "status": "ok",
        "tarefas_puxadas": tarefas_puxadas,
        "tarefas_empurradas": tarefas_empurradas,
        "leituras_sincronizadas": leituras_sincronizadas,
        "sincronizados": tarefas_puxadas + tarefas_empurradas + leituras_sincronizadas,
    }


def sincronizar_tudo(
    repos: Optional[List[str]] = None,
    db: Optional[ArmazenamentoGTD] = None,
) -> Dict[str, Any]:
    """Executa a sincronizacao conjunta de todas as fontes externas."""
    res_github = tarefas_do_github(repos=repos, db=db)
    res_notion = sincronizar_notion(db=db)
    return {
        "github_novas_tarefas": len(res_github),
        "notion": res_notion,
    }
