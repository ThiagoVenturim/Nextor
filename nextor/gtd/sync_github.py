"""Sincronizacao do GTD com issues e PRs do GitHub (Issue #42).

Reusa nextor.github_integration (token so em GITHUB_TOKEN, nunca no repositorio).

- Importar: issues e PRs abertos atribuidos ao usuario (e dos repositorios configurados)
  viram proximas acoes em @trabalho, sem duplicar (chave: html_url). Issue ou PR fechado
  no GitHub marca a tarefa como feita; reaberto volta para proxima.
- Exportar: concluir no GTD fecha a issue; reabrir no GTD reabre. PRs nunca sao fechados
  pelo painel (fechar PR sem merge e decisao de revisao). Tarefas locais com
  metadados["github_repo"] viram issues novas nesse repositorio.

Escrever no GitHub so acontece com direcao "exportar" ou "bidirecional", escolhida pelo
usuario no painel; o padrao e "importar".
"""
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from .armazenamento import ArmazenamentoGTD
from .modelos import Item
from .sync_comum import pode_exportar, pode_importar, resolver_conflito

log = logging.getLogger("nextor.gtd.sync_github")

Requisicao = Callable[..., Tuple[int, Any]]

_PADRAO_URL = re.compile(r"^https://github\.com/([^/\s]+/[^/\s]+)/(issues|pull)/(\d+)$")
_PADRAO_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _requisicao_padrao() -> Requisicao:
    from .. import github_integration
    return github_integration.fazer_requisicao_api


def _normalizar_repo(repo: str) -> str:
    from .. import github_integration
    return github_integration.normalizar_repositorio(repo)


def info_da_url(url: str) -> Optional[Dict[str, Any]]:
    """Extrai repo, numero e tipo (issue/pr) de uma URL html do GitHub."""
    m = _PADRAO_URL.match((url or "").strip())
    if not m:
        return None
    return {"repo": m.group(1), "numero": int(m.group(3)), "tipo": "pr" if m.group(2) == "pull" else "issue"}


def _estado_remoto(elem: Dict[str, Any]) -> str:
    return "closed" if str(elem.get("state", "open")).lower() == "closed" else "open"


def _meta_github(item: Item) -> Dict[str, Any]:
    meta = item.obter_meta("github")
    if isinstance(meta, dict) and meta.get("repo") and meta.get("numero"):
        return meta
    info = info_da_url(item.ref_externa or "") or {}
    if not info:
        return {}
    # Itens criados antes desta versao: assume que estavam abertos ao serem importados.
    meta = dict(info, estado="open")
    item.definir_meta("github", meta)
    return meta


def _item_de_elemento(elem: Dict[str, Any], url: str) -> Item:
    info = info_da_url(url) or {}
    eh_pr = "pull_request" in elem or info.get("tipo") == "pr"
    numero = elem.get("number", info.get("numero", ""))
    titulo = (elem.get("title") or "Tarefa GitHub").strip()
    estado_remoto = _estado_remoto(elem)
    item = Item(
        id=str(uuid.uuid4()),
        titulo=titulo,
        nota=f"GitHub {'PR' if eh_pr else 'Issue'} #{numero}: {url}".strip(),
        contexto="@trabalho",
        estado="feito" if estado_remoto == "closed" else "proxima",
        origem="github",
        ref_externa=url,
    )
    if estado_remoto == "closed":
        item.concluido_em = _agora()
    if info:
        item.definir_meta("github", dict(info, estado=estado_remoto, tipo="pr" if eh_pr else "issue"))
    return item


def _aplicar_remoto(item: Item, estado_remoto: str, titulo: Optional[str]) -> None:
    if estado_remoto == "closed" and item.estado != "feito":
        item.estado = "feito"
        item.concluido_em = _agora()
    elif estado_remoto == "open" and item.estado == "feito":
        item.estado = "proxima"
        item.concluido_em = None
    if titulo:
        item.titulo = titulo.strip()


def reconciliar_item(
    item: Item,
    elem: Dict[str, Any],
    direcao: str,
    politica: str,
    requisicao: Requisicao,
) -> str:
    """Concilia uma tarefa com o estado atual da issue/PR. Retorna o que foi feito."""
    meta = _meta_github(item)
    if not meta:
        return "ignorado"
    estado_remoto = _estado_remoto(elem)
    titulo_remoto = (elem.get("title") or "").strip()
    ultimo = meta.get("estado", "open")

    remoto_mudou = pode_importar(direcao) and (
        estado_remoto != ultimo or (bool(titulo_remoto) and titulo_remoto != meta.get("titulo", titulo_remoto))
    )
    local_feito = item.estado == "feito"
    local_mudou = pode_exportar(direcao) and meta.get("tipo") == "issue" and local_feito != (ultimo == "closed")
    vencedor = resolver_conflito(remoto_mudou, local_mudou, politica)
    conflito = remoto_mudou and local_mudou

    if vencedor == "remoto":
        _aplicar_remoto(item, estado_remoto, titulo_remoto)
        item.definir_meta("github", dict(meta, estado=estado_remoto, titulo=titulo_remoto or meta.get("titulo", "")))
        return "conflito_remoto" if conflito else "atualizado_local"

    if vencedor == "local":
        novo_estado = "closed" if local_feito else "open"
        caminho = f"/repos/{meta['repo']}/issues/{meta['numero']}"
        status, _ = requisicao(caminho, metodo="PATCH", dados={"state": novo_estado})
        if status not in (200, 201):
            log.warning("GitHub recusou atualizar issue (codigo %s)", status)
            return "erro"
        item.definir_meta("github", dict(meta, estado=novo_estado))
        return "conflito_local" if conflito else "atualizado_remoto"

    if titulo_remoto and "titulo" not in meta:
        item.definir_meta("github", dict(meta, titulo=titulo_remoto))
    return "sem_mudanca"


def _buscar_abertas(repos: List[str], requisicao: Requisicao) -> List[Dict[str, Any]]:
    elementos: List[Dict[str, Any]] = []
    status, dados = requisicao("/issues?filter=assigned&state=open&per_page=100")
    if status == 200 and isinstance(dados, list):
        elementos.extend(e for e in dados if isinstance(e, dict))
    for r in repos or []:
        repo_norm = _normalizar_repo(r)
        if not _PADRAO_REPO.match(repo_norm):
            continue
        st, dados_r = requisicao(f"/repos/{repo_norm}/issues?state=open&per_page=100")
        if st == 200 and isinstance(dados_r, list):
            elementos.extend(e for e in dados_r if isinstance(e, dict))
    return elementos


def sincronizar_github(
    banco: ArmazenamentoGTD,
    direcao: str = "importar",
    politica: str = "remoto",
    repos: Optional[List[str]] = None,
    requisicao: Optional[Requisicao] = None,
) -> Dict[str, Any]:
    """Sincroniza tarefas do GTD com issues e PRs do GitHub conforme a direcao."""
    req = requisicao or _requisicao_padrao()
    res: Dict[str, Any] = {"novas": [], "atualizadas_local": 0, "atualizadas_remoto": 0,
                           "issues_criadas": 0, "conflitos": 0, "erros": 0}
    if not (pode_importar(direcao) or pode_exportar(direcao)):
        return res

    vistos: Dict[str, Dict[str, Any]] = {}
    if pode_importar(direcao):
        for elem in _buscar_abertas(repos or [], req):
            url = elem.get("html_url") or ""
            if not url or url in vistos:
                continue
            vistos[url] = elem

    # 1. Itens que ja existem localmente: concilia com o estado remoto.
    for item in banco.listar_itens():
        meta = _meta_github(item)
        if not meta:
            continue
        url = item.ref_externa or ""
        elem = vistos.pop(url, None)
        if elem is None:
            if item.estado == "feito" and meta.get("estado") == "closed":
                # Fechado dos dois lados. Se for reaberto e atribuido, volta na lista de abertos.
                continue
            # Nao esta entre os abertos (ou so exportamos): consulta o estado atual.
            st, dados = req(f"/repos/{meta['repo']}/issues/{meta['numero']}")
            if st != 200 or not isinstance(dados, dict):
                continue
            elem = dados
        resultado = reconciliar_item(item, elem, direcao, politica, req)
        if resultado in ("atualizado_local", "conflito_remoto"):
            res["atualizadas_local"] += 1
        elif resultado in ("atualizado_remoto", "conflito_local"):
            res["atualizadas_remoto"] += 1
        elif resultado == "erro":
            res["erros"] += 1
        if resultado.startswith("conflito"):
            res["conflitos"] += 1
        banco.salvar_item(item)

    # 2. Issues/PRs abertos ainda sem tarefa local.
    for url, elem in vistos.items():
        if banco.buscar_item_por_ref(url):
            continue
        item = _item_de_elemento(elem, url)
        banco.salvar_item(item)
        res["novas"].append(item)

    # 3. Tarefas locais marcadas para virar issue (metadados["github_repo"]).
    if pode_exportar(direcao):
        for item in banco.listar_itens():
            repo_alvo = str(item.obter_meta("github_repo") or "").strip()
            if not repo_alvo or item.ref_externa or item.estado == "feito":
                continue
            repo_norm = _normalizar_repo(repo_alvo)
            if not _PADRAO_REPO.match(repo_norm):
                res["erros"] += 1
                continue
            st, dados = req(f"/repos/{repo_norm}/issues", metodo="POST",
                            dados={"title": item.titulo, "body": item.nota or ""})
            if st not in (200, 201) or not isinstance(dados, dict) or not dados.get("html_url"):
                res["erros"] += 1
                continue
            item.ref_externa = dados["html_url"]
            info = info_da_url(item.ref_externa) or {"repo": repo_norm, "numero": dados.get("number"), "tipo": "issue"}
            item.definir_meta("github", dict(info, estado="open", titulo=item.titulo))
            banco.salvar_item(item)
            res["issues_criadas"] += 1

    return res


def aplicar_evento_webhook(
    banco: ArmazenamentoGTD,
    evento: str,
    payload: Dict[str, Any],
    direcao: str = "importar",
    usuario: str = "",
) -> Dict[str, Any]:
    """Aplica um evento de webhook (issues / pull_request) as tarefas locais.

    So traz mudancas do GitHub para o GTD; nunca escreve no GitHub.
    """
    if evento not in ("issues", "pull_request") or not pode_importar(direcao):
        return {"ok": True, "aplicado": False, "motivo": "evento_ignorado"}
    elem = payload.get("issue") if evento == "issues" else payload.get("pull_request")
    if not isinstance(elem, dict):
        return {"ok": False, "aplicado": False, "motivo": "payload_invalido"}
    url = str(elem.get("html_url") or "")
    if not info_da_url(url):
        return {"ok": False, "aplicado": False, "motivo": "url_invalida"}
    if evento == "pull_request":
        elem = dict(elem, pull_request={})

    item = banco.buscar_item_por_ref(url)
    if item is None:
        atribuidos = [str(a.get("login", "")).lower() for a in elem.get("assignees") or [] if isinstance(a, dict)]
        if payload.get("action") in ("opened", "assigned", "reopened") and usuario and usuario.lower() in atribuidos:
            novo = _item_de_elemento(elem, url)
            banco.salvar_item(novo)
            return {"ok": True, "aplicado": True, "acao": "criado", "item_id": novo.id}
        return {"ok": True, "aplicado": False, "motivo": "sem_tarefa_local"}

    def _sem_escrita(*_a, **_k):
        return 403, {}

    resultado = reconciliar_item(item, elem, "importar", "remoto", _sem_escrita)
    banco.salvar_item(item)
    return {"ok": True, "aplicado": resultado != "sem_mudanca", "acao": resultado, "item_id": item.id}
