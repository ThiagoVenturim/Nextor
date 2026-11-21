"""Integracoes do GTD com Notion, GitHub e as anotacoes do proprio Nextor (Issue #42).

Ponto de entrada da sincronizacao usada pelo painel (/gtd/sincronizar), MCP e voz.
Cada fonte tem direcao configuravel no painel (importar, exportar, bidirecional ou
desligado) e uma politica unica de conflito ("remoto" ou "local"). Credenciais ficam
so no ambiente (.env): NOTION_TOKEN e GITHUB_TOKEN nunca vao para o repositorio nem
para os logs, que registram apenas o tipo da falha.
"""
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .armazenamento import ArmazenamentoGTD
from .configuracao import FONTES_SINCRONIZACAO, carregar_config, normalizar_sincronizacao
from .modelos import Item
from .notion import ClienteNotion
from .sync_github import aplicar_evento_webhook, sincronizar_github
from .sync_nextor import sincronizar_nextor
from .sync_notion import sincronizar_notion_completo

log = logging.getLogger("nextor.gtd.integracoes")

__all__ = [
    "tarefas_do_github",
    "sincronizar_notion",
    "sincronizar_tudo",
    "aplicar_evento_webhook",
]


def _obter_db(db: Optional[ArmazenamentoGTD]) -> ArmazenamentoGTD:
    return db if db is not None else ArmazenamentoGTD()


def tarefas_do_github(
    repos: Optional[List[str]] = None,
    db: Optional[ArmazenamentoGTD] = None,
    cliente_requisicao: Optional[Callable] = None,
    direcao: str = "importar",
    politica: str = "remoto",
) -> List[Item]:
    """Importa issues e PRs abertos do GitHub como tarefas em @trabalho, sem duplicar.

    Retorna apenas as tarefas novas. Com direcao "bidirecional" tambem propaga
    conclusoes locais para as issues.
    """
    res = sincronizar_github(_obter_db(db), direcao=direcao, politica=politica,
                             repos=repos, requisicao=cliente_requisicao)
    return res["novas"]


def sincronizar_notion(
    db: Optional[ArmazenamentoGTD] = None,
    cliente: Optional[ClienteNotion] = None,
    direcao: str = "bidirecional",
    politica: str = "remoto",
) -> Dict[str, Any]:
    """Sincroniza tarefas, projetos e leituras com o Notion.

    Sem token ou sem bases configuradas, devolve status "desligado" sem lancar excecao.
    """
    banco = _obter_db(db)
    notion = cliente if cliente is not None else ClienteNotion()
    if not notion.disponivel():
        return {"status": "desligado", "motivo": "token_ou_bases_notion_nao_configurados", "sincronizados": 0}

    detalhes = sincronizar_notion_completo(banco, notion, direcao=direcao, politica=politica)
    tarefas = detalhes.get("tarefas", {})
    leituras = detalhes.get("leituras", {})
    projetos = detalhes.get("projetos", {})

    def _soma(d: Dict[str, int]) -> int:
        return sum(d.get(k, 0) for k in ("puxadas", "atualizadas_local", "empurradas", "atualizadas_remoto"))

    return {
        "status": "ok",
        "direcao": direcao,
        "tarefas_puxadas": tarefas.get("puxadas", 0),
        "tarefas_empurradas": tarefas.get("empurradas", 0),
        "leituras_sincronizadas": _soma(leituras),
        "projetos_sincronizados": _soma(projetos),
        "conflitos": sum(d.get("conflitos", 0) for d in detalhes.values()),
        "erros": sum(d.get("erros", 0) for d in detalhes.values()),
        "detalhes": detalhes,
        "sincronizados": sum(_soma(d) for d in detalhes.values()),
    }


def _github_configurado() -> bool:
    from .. import github_integration
    return bool(github_integration.obter_token_github())


def sincronizar_tudo(
    repos: Optional[List[str]] = None,
    db: Optional[ArmazenamentoGTD] = None,
    fontes: Optional[Iterable[str]] = None,
    cfg: Optional[Dict[str, Any]] = None,
    cliente_notion: Optional[ClienteNotion] = None,
    requisicao_github: Optional[Callable] = None,
    caminho_anotacoes: Optional[Path] = None,
) -> Dict[str, Any]:
    """Sincroniza as fontes pedidas (padrao: todas) conforme a configuracao do painel."""
    banco = _obter_db(db)
    cfg = cfg if cfg is not None else carregar_config()
    sinc = normalizar_sincronizacao(None, cfg.get("sincronizacao"))
    ativas = cfg.get("integracoes") or {}
    politica = sinc.get("conflito", "remoto")
    pedidas = [f for f in (fontes or FONTES_SINCRONIZACAO) if f in FONTES_SINCRONIZACAO]

    resultado: Dict[str, Any] = {}
    for fonte in pedidas:
        direcao = sinc.get(fonte, "desligado")
        if not ativas.get(fonte, True) or direcao == "desligado":
            resultado[fonte] = {"status": "desligado", "motivo": "desativado_no_painel"}
            continue
        try:
            if fonte == "notion":
                resultado[fonte] = sincronizar_notion(db=banco, cliente=cliente_notion,
                                                      direcao=direcao, politica=politica)
            elif fonte == "github":
                if requisicao_github is None and not _github_configurado():
                    resultado[fonte] = {"status": "desligado", "motivo": "github_token_nao_configurado"}
                    continue
                res = sincronizar_github(banco, direcao=direcao, politica=politica,
                                         repos=list(repos or []) + list(sinc.get("github_repos") or []),
                                         requisicao=requisicao_github)
                novas = res.pop("novas")
                resultado[fonte] = dict(res, status="ok", direcao=direcao, novas_tarefas=len(novas))
            elif fonte == "nextor":
                res = sincronizar_nextor(banco, direcao=direcao, politica=politica,
                                         caminho_anotacoes=caminho_anotacoes)
                resultado[fonte] = dict(res, status="ok", direcao=direcao)
        except Exception as e:
            log.warning("Falha ao sincronizar %s: %s", fonte, type(e).__name__)
            resultado[fonte] = {"status": "erro", "motivo": type(e).__name__}

    # Chave mantida por compatibilidade com o painel anterior.
    resultado["github_novas_tarefas"] = (resultado.get("github") or {}).get("novas_tarefas", 0)
    return resultado
