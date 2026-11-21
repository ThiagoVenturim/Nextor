"""Avisos prontos que alimentam o roteador de notificacoes (Issue #46).

Cada funcao monta o texto de um evento (agenda do dia, tarefas atrasadas, PRs para
revisar) e o entrega ao roteador, que decide os canais pela config do painel. Pode ser
chamada por uma tarefa agendada ou por POST /gtd/notificacoes/disparar.

Tarefas atrasadas e PRs ja avisados nao se repetem enquanto o processo estiver no ar
(atrasadas: uma vez por dia; PRs: uma vez por PR).
"""
import logging
import threading
from datetime import date
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("nextor.notificacoes.avisos")

Notificador = Callable[..., Dict[str, Any]]

_TRAVA = threading.Lock()
_ATRASADAS_AVISADAS: set = set()
_PRS_AVISADOS: set = set()
_LIMITE_ITENS_TEXTO = 5


def _notificador_padrao() -> Notificador:
    from .roteador_notificacoes import notificar
    return notificar


def _sem_envio(evento: str, motivo: str) -> Dict[str, Any]:
    return {"evento": evento, "enviado": False, "motivo": motivo, "despachados": [], "falhas": []}


def _resultado(evento: str, res: Dict[str, Any], itens: int) -> Dict[str, Any]:
    saida = {"evento": evento, "enviado": bool(res.get("despachados")), "itens": itens}
    saida.update({k: res.get(k) for k in ("silenciado", "despachados", "falhas", "ignorados") if k in res})
    return saida


def _listar(titulos: List[str]) -> str:
    linhas = [f"- {t}" for t in titulos[:_LIMITE_ITENS_TEXTO]]
    resto = len(titulos) - _LIMITE_ITENS_TEXTO
    if resto > 0:
        linhas.append(f"- e mais {resto}")
    return "\n".join(linhas)


def avisar_agenda_do_dia(db: Any = None, notificador: Optional[Notificador] = None) -> Dict[str, Any]:
    """Envia o resumo da agenda do dia (compromissos, acoes urgentes e leitura)."""
    from ..gtd.gtd import agenda_do_dia

    agenda = agenda_do_dia(db=db)
    corpo = agenda.get("resumo_falado") or "Nada marcado para hoje."
    notificar = notificador or _notificador_padrao()
    res = notificar(evento="agenda_do_dia", titulo="Agenda do dia", corpo=corpo)
    return _resultado("agenda_do_dia", res, len(agenda.get("eventos_agenda") or []))


def avisar_tarefas_atrasadas(
    db: Any = None,
    notificador: Optional[Notificador] = None,
    hoje: Optional[date] = None,
) -> Dict[str, Any]:
    """Avisa as proximas acoes com prazo vencido que ainda nao foram avisadas hoje."""
    from ..gtd.gtd import _obter_db

    dia = (hoje or date.today()).isoformat()
    banco = _obter_db(db)
    atrasadas = [i for i in banco.listar_itens(estado="proxima") if i.prazo and i.prazo < dia]
    with _TRAVA:
        novas = [i for i in atrasadas if (i.id, dia) not in _ATRASADAS_AVISADAS]
    if not novas:
        return _sem_envio("tarefa_atrasada", "nenhuma_nova")

    titulo = "Tarefa atrasada" if len(novas) == 1 else f"{len(novas)} tarefas atrasadas"
    corpo = _listar([f"{i.titulo} (prazo {i.prazo})" for i in novas])
    notificar = notificador or _notificador_padrao()
    res = notificar(evento="tarefa_atrasada", titulo=titulo, corpo=corpo, urgencia="normal")
    if res.get("despachados"):
        with _TRAVA:
            _ATRASADAS_AVISADAS.update((i.id, dia) for i in novas)
    return _resultado("tarefa_atrasada", res, len(novas))


def avisar_prs_para_revisar(
    prs: Optional[List[Dict[str, Any]]] = None,
    notificador: Optional[Notificador] = None,
    handler_github: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Avisa PRs que pediram sua revisao e ainda nao foram avisados."""
    if prs is None:
        from ..github_integration import listar_prs_para_revisar
        prs = listar_prs_para_revisar(handler=handler_github)
    with _TRAVA:
        novos = [p for p in prs if p.get("url") and p["url"] not in _PRS_AVISADOS]
    if not novos:
        return _sem_envio("pr_para_revisar", "nenhum_novo")

    titulo = "PR para revisar" if len(novos) == 1 else f"{len(novos)} PRs para revisar"
    corpo = _listar([f"{p.get('repo', '')}#{p.get('numero', '')} {p.get('titulo', '')}: {p['url']}" for p in novos])
    notificar = notificador or _notificador_padrao()
    res = notificar(evento="pr_para_revisar", titulo=titulo, corpo=corpo)
    if res.get("despachados"):
        with _TRAVA:
            _PRS_AVISADOS.update(p["url"] for p in novos)
    return _resultado("pr_para_revisar", res, len(novos))


AVISOS = {
    "agenda_do_dia": avisar_agenda_do_dia,
    "tarefa_atrasada": avisar_tarefas_atrasadas,
    "pr_para_revisar": avisar_prs_para_revisar,
}


def disparar_aviso(evento: str, notificador: Optional[Notificador] = None) -> Dict[str, Any]:
    """Executa o aviso pelo nome do evento. Levanta KeyError se o evento nao existir."""
    funcao = AVISOS[evento]
    return funcao(notificador=notificador)


def limpar_historico() -> None:
    """Esquece os avisos ja enviados (usado em testes)."""
    with _TRAVA:
        _ATRASADAS_AVISADAS.clear()
        _PRS_AVISADOS.clear()
