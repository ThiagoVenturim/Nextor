"""Modulo de painel de tarefas e pendencias para o Nextor.

Agrega pendencias de multiplas fontes (anotacoes locais, agenda iCal, GitHub kanban),
com cada fonte sendo opcional e tolerante a falhas.
Oferece resposta em duas camadas:
1. Resumo curto falado para o Nest ('3 para hoje, 2 atrasadas')
2. Lista estruturada e ordenada por prazo para API HTTP e telas
Suporta marcar tarefas como feitas por voz e API, mantendo confirmacao previa
para mutacoes externas (GitHub).
"""
from datetime import date, datetime, timedelta
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger("nextor.pendencias")

# Acao pendente de conclusao externa que requer confirmacao
_CONCLUSAO_PENDENTE: Optional[dict] = None


def _obter_fuso() -> ZoneInfo:
    try:
        return ZoneInfo(config.FUSO)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def coletar_pendencias_anotacoes(
    caminho_anotacoes: Optional[Path] = None,
    agora: Optional[datetime] = None,
) -> List[dict]:
    """Coleta pendencias a partir do arquivo anotacoes.md."""
    arquivo = caminho_anotacoes or config.ANOTACOES
    if not arquivo.exists():
        return []

    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        log.warning("Falha ao ler anotacoes para pendencias: %s", e)
        return []

    tz = _obter_fuso()
    dt_agora = agora or datetime.now(tz)
    hoje_data = dt_agora.date()

    pendencias: List[dict] = []
    padrao_carimbo = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)\]\s*(.*)$")
    padrao_check = re.compile(r"^-\s*\[([ xX])\]\s*(.*)$")

    for idx, linha_bruta in enumerate(linhas, start=1):
        linha = linha_bruta.strip()
        if not linha or not linha.startswith("-"):
            continue

        # Ignora itens explicitamente marcados como concluidos [x]
        m_chk = padrao_check.match(linha)
        if m_chk and m_chk.group(1).lower() == "x":
            continue

        titulo = ""
        prazo_str = None
        dt_prazo = None

        m_carimbo = padrao_carimbo.match(linha)
        if m_carimbo:
            carimbo = m_carimbo.group(1).strip()
            titulo = m_carimbo.group(2).strip()
            prazo_str = carimbo
            try:
                if len(carimbo) == 10:
                    dt_prazo = datetime.strptime(carimbo, "%Y-%m-%d").replace(tzinfo=tz)
                else:
                    dt_prazo = datetime.strptime(carimbo, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            except Exception:
                pass
        elif m_chk:
            titulo = m_chk.group(2).strip()
        else:
            titulo = linha.lstrip("- ").strip()

        if not titulo:
            continue

        atrasada = False
        para_hoje = False

        if dt_prazo:
            data_prazo = dt_prazo.date()
            if data_prazo < hoje_data:
                atrasada = True
            elif data_prazo == hoje_data:
                para_hoje = True
                if dt_prazo < dt_agora and len(prazo_str) > 10:
                    atrasada = True

        pendencias.append({
            "id": f"nota:{idx}",
            "fonte": "anotacoes",
            "titulo": titulo,
            "prazo": prazo_str,
            "dt_prazo": dt_prazo,
            "atrasada": atrasada,
            "para_hoje": para_hoje,
            "linha_num": idx,
            "linha_original": linha_bruta,
        })

    return pendencias


def coletar_pendencias_agenda(
    agora: Optional[datetime] = None,
    dias: int = 7,
    mock_eventos: Optional[List[dict]] = None,
) -> List[dict]:
    """Coleta compromissos e tarefas da agenda iCal."""
    tz = _obter_fuso()
    dt_agora = agora or datetime.now(tz)
    hoje_data = dt_agora.date()

    eventos: List[dict] = []
    if mock_eventos is not None:
        eventos = mock_eventos
    else:
        try:
            from . import agenda
            eventos = agenda.eventos_entre(hoje_data, hoje_data + timedelta(days=dias))
        except Exception as e:
            log.warning("Falha ao coletar eventos da agenda para pendencias: %s", e)
            eventos = []

    pendencias: List[dict] = []
    for idx, ev in enumerate(eventos, start=1):
        titulo = ev.get("titulo") or ev.get("SUMMARY", "Compromisso")
        dt_inicio = ev.get("inicio") or ev.get("DTSTART")

        prazo_str = None
        atrasada = False
        para_hoje = False

        if isinstance(dt_inicio, datetime):
            if dt_inicio.tzinfo is None:
                dt_inicio = dt_inicio.replace(tzinfo=tz)
            prazo_str = dt_inicio.isoformat()
            if dt_inicio.date() == hoje_data:
                para_hoje = True
                if dt_inicio < dt_agora:
                    atrasada = True
            elif dt_inicio.date() < hoje_data:
                atrasada = True
        elif isinstance(dt_inicio, date):
            prazo_str = dt_inicio.isoformat()
            if dt_inicio == hoje_data:
                para_hoje = True
            elif dt_inicio < hoje_data:
                atrasada = True

        pendencias.append({
            "id": f"agenda:{idx}",
            "fonte": "agenda",
            "titulo": str(titulo),
            "prazo": prazo_str,
            "dt_prazo": dt_inicio if isinstance(dt_inicio, datetime) else None,
            "atrasada": atrasada,
            "para_hoje": para_hoje,
        })

    return pendencias


def coletar_pendencias_github(
    token: Optional[str] = None,
    usuario: Optional[str] = None,
    mock_issues: Optional[List[dict]] = None,
) -> List[dict]:
    """Coleta tarefas abertas do GitHub atribuídas ao usuário."""
    issues: List[dict] = []
    if mock_issues is not None:
        issues = mock_issues
    else:
        try:
            from . import github_integration
            issues = github_integration.listar_issues_atribuidas(token=token, usuario=usuario)
        except Exception as e:
            log.warning("Falha ao coletar issues do GitHub para pendencias: %s", e)
            issues = []

    pendencias: List[dict] = []
    for iss in issues:
        repo = iss.get("repo", "Nextor")
        num = iss.get("numero") or iss.get("number")
        titulo = iss.get("titulo") or iss.get("title", "")
        labels = [str(l).lower() for l in iss.get("labels", [])]

        para_hoje = any("hoje" in l or "today" in l or "urgente" in l or "doing" in l for l in labels)

        pendencias.append({
            "id": f"github:{repo}#{num}" if repo else f"github:{num}",
            "fonte": "github",
            "titulo": str(titulo),
            "repo": repo,
            "numero": num,
            "prazo": None,
            "dt_prazo": None,
            "atrasada": False,
            "para_hoje": para_hoje,
            "url": iss.get("url", ""),
        })

    return pendencias


def coletar_todas_pendencias(
    incluir_anotacoes: bool = True,
    incluir_agenda: bool = True,
    incluir_github: bool = True,
    agora: Optional[datetime] = None,
    caminho_anotacoes: Optional[Path] = None,
    mock_eventos: Optional[List[dict]] = None,
    mock_issues: Optional[List[dict]] = None,
    token_github: Optional[str] = None,
) -> List[dict]:
    """Agrega todas as pendencias das fontes ativas e ordena rigorosamente por prioridade e prazo."""
    lista: List[dict] = []

    if incluir_anotacoes:
        lista.extend(coletar_pendencias_anotacoes(caminho_anotacoes=caminho_anotacoes, agora=agora))

    if incluir_agenda:
        lista.extend(coletar_pendencias_agenda(agora=agora, mock_eventos=mock_eventos))

    if incluir_github:
        lista.extend(coletar_pendencias_github(token=token_github, mock_issues=mock_issues))

    def chave_ordenacao(item: dict):
        # 1. Atrasadas primeiro (0), depois outras (1)
        prioridade_atrasada = 0 if item.get("atrasada") else 1
        # 2. Para hoje (0), depois futuras ou sem prazo (1)
        prioridade_hoje = 0 if item.get("para_hoje") else 1

        dt = item.get("dt_prazo")
        # 3. Data de vencimento menor primeiro; sem data vai para o final
        dt_val = dt if isinstance(dt, datetime) else (datetime.max if not dt else datetime.combine(dt, datetime.min.time()))
        return (prioridade_atrasada, prioridade_hoje, dt_val, item.get("titulo", "").lower())

    lista.sort(key=chave_ordenacao)
    return lista


def gerar_resumo_falado(pendencias: List[dict], apenas_hoje: bool = False) -> str:
    """Gera resposta curta falada para o Nest ('3 para hoje, 2 atrasadas')."""
    if not pendencias:
        return "Voce nao tem tarefas pendentes para hoje." if apenas_hoje else "Voce nao possui nenhuma pendencia no momento."

    total = len(pendencias)
    atrasadas = sum(1 for p in pendencias if p.get("atrasada"))
    para_hoje = sum(1 for p in pendencias if p.get("para_hoje"))

    partes = []
    if apenas_hoje:
        partes.append(f"Voce tem {total} tarefas para hoje")
        if atrasadas:
            partes.append(f"sendo {atrasadas} em atraso")
    else:
        partes.append(f"Voce tem {total} pendencias")
        detalhes = []
        if para_hoje:
            detalhes.append(f"{para_hoje} para hoje")
        if atrasadas:
            detalhes.append(f"{atrasadas} atrasadas")
        if detalhes:
            partes.append(f"({', '.join(detalhes)})")

    # Destaque das primeiras tarefas
    destaques = [p["titulo"] for p in pendencias[:2]]
    texto_destaque = "; ".join(destaques)
    return f"{' '.join(partes)}. Principais: {texto_destaque}."


def concluir_tarefa_anotacao(linha_num: int, caminho_anotacoes: Optional[Path] = None) -> bool:
    """Marca uma linha do anotacoes.md como concluida [x]."""
    arquivo = caminho_anotacoes or config.ANOTACOES
    if not arquivo.exists():
        return False

    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        idx = linha_num - 1
        if 0 <= idx < len(linhas):
            original = linhas[idx]
            if re.match(r"^-\s*\[\s*\]", original):
                linhas[idx] = re.sub(r"^-\s*\[\s*\]", "- [x]", original)
            elif original.startswith("-"):
                linhas[idx] = f"- [x] {original.lstrip('- ').strip()}"
            else:
                linhas[idx] = f"- [x] {original}"
            arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            return True
        return False
    except Exception as e:
        log.error("Erro ao concluir anotacao: %s", e)
        return False


def obter_conclusao_pendente() -> Optional[dict]:
    """Retorna acao de conclusao pendente."""
    return _CONCLUSAO_PENDENTE


def limpar_conclusao_pendente() -> None:
    """Descarta acao de conclusao pendente."""
    global _CONCLUSAO_PENDENTE
    _CONCLUSAO_PENDENTE = None


def concluir_tarefa(
    id_tarefa: str,
    confirmar: bool = False,
    caminho_anotacoes: Optional[Path] = None,
    mock_github_handler: Optional[Callable] = None,
) -> dict:
    """Marca uma tarefa como feita de acordo com sua fonte e regras de confirmacao."""
    global _CONCLUSAO_PENDENTE
    id_limpo = id_tarefa.strip()

    if id_limpo.startswith("nota:"):
        try:
            num = int(id_limpo.split(":")[1])
            sucesso = concluir_tarefa_anotacao(num, caminho_anotacoes=caminho_anotacoes)
            if sucesso:
                return {
                    "ok": True,
                    "fonte": "anotacoes",
                    "id": id_limpo,
                    "mensagem": f"Tarefa {id_limpo} marcada como concluida nas anotacoes.",
                }
            return {"ok": False, "erro": "tarefa_nao_encontrada", "mensagem": "Nota nao encontrada para conclusao."}
        except Exception as e:
            return {"ok": False, "erro": str(e), "mensagem": "Falha ao concluir nota."}

    if id_limpo.startswith("github:"):
        ref = id_limpo.split(":", 1)[1]
        repo = None
        numero = ref
        if "#" in ref:
            repo, numero = ref.split("#", 1)

        if not confirmar:
            _CONCLUSAO_PENDENTE = {
                "tipo": "github",
                "id": id_limpo,
                "repo": repo,
                "numero": numero,
            }
            return {
                "ok": True,
                "requer_confirmacao": True,
                "id": id_limpo,
                "mensagem": f"Vou fechar a issue #{numero} no GitHub. Diga 'confirma conclusao' para executar.",
            }

        try:
            from . import github_integration
            proposta = github_integration.propor_movimentacao_cartao(issue_ref=numero, coluna="Concluido", repo=repo)
            resultado = github_integration.confirmar_acao_pendente(
                id_acao=proposta.get("id_acao"),
                handler=mock_github_handler,
            )
            _CONCLUSAO_PENDENTE = None
            if resultado.get("ok"):
                return {
                    "ok": True,
                    "fonte": "github",
                    "id": id_limpo,
                    "mensagem": f"Issue #{numero} concluida no GitHub com sucesso.",
                }
            return resultado
        except Exception as e:
            _CONCLUSAO_PENDENTE = None
            return {"ok": False, "erro": str(e), "mensagem": "Erro ao concluir issue no GitHub."}

    return {
        "ok": False,
        "erro": "fonte_nao_suportada",
        "mensagem": f"A fonte de '{id_limpo}' nao suporta conclusao direta por voz.",
    }


def confirmar_conclusao_pendente() -> str:
    """Confirma a conclusao pendente."""
    global _CONCLUSAO_PENDENTE
    if not _CONCLUSAO_PENDENTE:
        return "Nenhuma conclusao de tarefa pendente para confirmar."

    alvo = _CONCLUSAO_PENDENTE.get("id", "")
    res = concluir_tarefa(alvo, confirmar=True)
    _CONCLUSAO_PENDENTE = None
    return res.get("mensagem", "Tarefa concluida com sucesso.")


def cancelar_conclusao_pendente() -> str:
    """Cancela a conclusao pendente."""
    global _CONCLUSAO_PENDENTE
    if not _CONCLUSAO_PENDENTE:
        return "Nenhuma conclusao de tarefa para cancelar."
    _CONCLUSAO_PENDENTE = None
    return "Conclusao de tarefa cancelada com sucesso."


def resumo_falado_pendencias(apenas_hoje: bool = False) -> str:
    """Ponto de entrada falado para o roteador de intencoes."""
    try:
        lista = coletar_todas_pendencias()
        if apenas_hoje:
            lista = [p for p in lista if p.get("para_hoje") or p.get("atrasada")]
        return gerar_resumo_falado(lista, apenas_hoje=apenas_hoje)
    except Exception as e:
        log.warning("Falha ao gerar resumo falado de pendencias: %s", e)
        return "Nao consegui consolidar suas pendencias no momento."


def concluir_tarefa_por_voz(termo_ou_id: str) -> str:
    """Localiza e conclui tarefa a partir do termo ou ID falado."""
    limpo = termo_ou_id.strip()

    # Se ja for um ID explicito (ex: nota:1, github:12)
    if ":" in limpo:
        res = concluir_tarefa(limpo)
        return res.get("mensagem", "Operacao processada.")

    # Busca por correspondencia de titulo ou numero
    try:
        todas = coletar_todas_pendencias()
        # Se for apenas um numero, tenta casar com numero de issue ou id de nota
        if limpo.isdigit():
            for p in todas:
                if p["id"].endswith(f":{limpo}") or p["id"].endswith(f"#{limpo}"):
                    res = concluir_tarefa(p["id"])
                    return res.get("mensagem", "Operacao processada.")

        # Busca pelo titulo
        for p in todas:
            if limpo.lower() in p["titulo"].lower():
                res = concluir_tarefa(p["id"])
                return res.get("mensagem", "Operacao processada.")

        return f"Nao encontrei nenhuma tarefa pendente correspondente a '{limpo}'."
    except Exception as e:
        return f"Erro ao concluir tarefa: {e}"
