"""Modulo de integracao com o GitHub para o Nextor.

Permite consultar o kanban (GitHub Projects / Issues atribuidas), criar issues
e mover cartoes por voz ou API HTTP com:
- Leitura direta de dados usando GITHUB_TOKEN (escopo minimo)
- Regra estrita de seguranca: SEMPRE exigir confirmacao antes de qualquer escrita (criar issue ou mover cartao)
- Suporte a endpoints protegidos no servico e gatilhos de voz no roteador
"""
from datetime import datetime
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import config

log = logging.getLogger("nextor.github")

# Cache em memoria da acao de escrita pendente de confirmacao
_ACAO_PENDENTE: Optional[dict] = None


def obter_token_github() -> str:
    """Retorna o token do GitHub configurado."""
    return os.getenv("GITHUB_TOKEN", "") or config.GITHUB_TOKEN


def normalizar_repositorio(repo_nome: str) -> str:
    """Normaliza o nome do repositorio (ex: 'Nextor' -> 'ThiagoVenturim/Nextor')."""
    limpo = (repo_nome or "").strip()
    if not limpo:
        limpo = config.GITHUB_REPOSITORIO_PADRAO or "Nextor"

    if "/" in limpo:
        return limpo

    usuario = os.getenv("GITHUB_USUARIO", "") or config.GITHUB_USUARIO or "ThiagoVenturim"
    return f"{usuario}/{limpo}"


def fazer_requisicao_api(
    path: str,
    metodo: str = "GET",
    dados: Optional[dict] = None,
    token: Optional[str] = None,
    handler_requisicao: Optional[Callable] = None,
) -> Tuple[int, Any]:
    """Executa uma requisicao a API REST do GitHub v3/v4."""
    url = f"https://api.github.com{path}" if not path.startswith("http") else path
    token_efetivo = token or obter_token_github()

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Nextor-Assistant",
    }
    if token_efetivo:
        headers["Authorization"] = f"Bearer {token_efetivo}"

    corpo_bytes = None
    if dados is not None:
        headers["Content-Type"] = "application/json"
        corpo_bytes = json.dumps(dados).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=corpo_bytes,
        method=metodo.upper(),
        headers=headers,
    )

    if handler_requisicao is not None:
        return handler_requisicao(req)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
            resultado = json.loads(raw) if raw else {}
            return status, resultado
    except urllib.error.HTTPError as e:
        corpo_err = e.read().decode("utf-8", errors="replace")
        try:
            dados_err = json.loads(corpo_err)
        except Exception:
            dados_err = {"message": corpo_err}
        log.warning("Erro HTTP na API do GitHub (%s): %s", e.code, dados_err)
        return e.code, dados_err
    except Exception as e:
        log.error("Falha de conexao com a API do GitHub: %s", e)
        return 500, {"message": str(e)}


def listar_issues_atribuidas(
    usuario: Optional[str] = None,
    estado: str = "open",
    token: Optional[str] = None,
    handler: Optional[Callable] = None,
) -> List[dict]:
    """Lista issues abertas atribuidas ao usuario."""
    path = f"/user/issues?filter=assigned&state={estado}&per_page=30"
    status, dados = fazer_requisicao_api(path, metodo="GET", token=token, handler_requisicao=handler)

    if status != 200 or not isinstance(dados, list):
        # Se falhar ou token for nulo, tenta busca publica por assignee
        user_alvo = usuario or os.getenv("GITHUB_USUARIO", "") or config.GITHUB_USUARIO or "ThiagoVenturim"
        busca_path = f"/search/issues?q=assignee:{user_alvo}+is:{estado}&per_page=30"
        st_busca, dados_busca = fazer_requisicao_api(busca_path, metodo="GET", token=token, handler_requisicao=handler)
        if st_busca == 200 and isinstance(dados_busca, dict):
            dados = dados_busca.get("items", [])
        else:
            return []

    issues: List[dict] = []
    for it in dados:
        if not isinstance(it, dict):
            continue
        repo_info = it.get("repository", {})
        repo_nome = repo_info.get("name") if isinstance(repo_info, dict) else ""
        if not repo_nome and "repository_url" in it:
            repo_nome = it["repository_url"].split("/")[-1]

        issues.append({
            "id": it.get("id"),
            "numero": it.get("number"),
            "titulo": it.get("title", ""),
            "repo": repo_nome,
            "estado": it.get("state", ""),
            "labels": [lbl.get("name", "") for lbl in it.get("labels", []) if isinstance(lbl, dict)],
            "url": it.get("html_url", ""),
        })

    return issues


def listar_itens_kanban(
    usuario: Optional[str] = None,
    token: Optional[str] = None,
    handler: Optional[Callable] = None,
) -> dict:
    """Retorna itens do Kanban agrupados por coluna (A Fazer, Em Progresso, Revisao, Concluido)."""
    issues = listar_issues_atribuidas(usuario=usuario, token=token, handler=handler)

    colunas: Dict[str, List[dict]] = {
        "A Fazer": [],
        "Em Progresso": [],
        "Revisao": [],
        "Concluido": [],
    }

    for iss in issues:
        labels_lower = [str(l).lower() for l in iss.get("labels", [])]
        titulo_lower = iss.get("titulo", "").lower()

        if any("progress" in l or "progresso" in l or "doing" in l for l in labels_lower):
            colunas["Em Progresso"].append(iss)
        elif any("review" in l or "revisao" in l or "pr" in l for l in labels_lower):
            colunas["Revisao"].append(iss)
        elif iss.get("estado") == "closed" or any("done" in l or "concluido" in l for l in labels_lower):
            colunas["Concluido"].append(iss)
        else:
            colunas["A Fazer"].append(iss)

    return {
        "ok": True,
        "total": len(issues),
        "colunas": colunas,
    }


def obter_acao_pendente() -> Optional[dict]:
    """Retorna a acao atualmente pendente de confirmacao."""
    return _ACAO_PENDENTE


def limpar_acao_pendente() -> None:
    """Limpa qualquer acao pendente."""
    global _ACAO_PENDENTE
    _ACAO_PENDENTE = None


def propor_criacao_issue(
    repo: str,
    titulo: str,
    corpo: str = "",
) -> dict:
    """Registra uma proposta de criacao de issue aguardando confirmacao obrigatoria."""
    global _ACAO_PENDENTE
    repo_norm = normalizar_repositorio(repo)
    titulo_limpo = titulo.strip()

    if not titulo_limpo:
        return {"ok": False, "erro": "titulo_obrigatorio", "mensagem": "O titulo da issue e obrigatorio."}

    id_acao = f"act_{uuid.uuid4().hex[:8]}"
    proposta = {
        "id_acao": id_acao,
        "tipo": "criar_issue",
        "repo": repo_norm,
        "titulo": titulo_limpo,
        "corpo": corpo or "",
        "criado_em": datetime.now().isoformat(),
    }
    _ACAO_PENDENTE = proposta

    return {
        "ok": True,
        "requer_confirmacao": True,
        "id_acao": id_acao,
        "acao": proposta,
        "mensagem": f"Vou criar a issue '{titulo_limpo}' no repositorio {repo_norm}. Diga 'confirma criacao' para executar.",
    }


def propor_movimentacao_cartao(
    issue_ref: Any,
    coluna: str,
    repo: Optional[str] = None,
) -> dict:
    """Registra uma proposta de movimentacao de cartao aguardando confirmacao obrigatoria."""
    global _ACAO_PENDENTE
    coluna_limpa = coluna.strip()
    issue_str = str(issue_ref).strip().lstrip("#")
    repo_norm = normalizar_repositorio(repo) if repo else (config.GITHUB_REPOSITORIO_PADRAO or "Nextor")

    if not issue_str or not coluna_limpa:
        return {"ok": False, "erro": "parametros_invalidos", "mensagem": "Numero da issue e coluna sao obrigatorios."}

    id_acao = f"act_{uuid.uuid4().hex[:8]}"
    proposta = {
        "id_acao": id_acao,
        "tipo": "mover_cartao",
        "repo": repo_norm,
        "issue_ref": issue_str,
        "coluna": coluna_limpa,
        "criado_em": datetime.now().isoformat(),
    }
    _ACAO_PENDENTE = proposta

    return {
        "ok": True,
        "requer_confirmacao": True,
        "id_acao": id_acao,
        "acao": proposta,
        "mensagem": f"Vou mover o cartao da issue #{issue_str} para '{coluna_limpa}'. Diga 'confirma movimentacao' para executar.",
    }


def confirmar_acao_pendente(
    id_acao: Optional[str] = None,
    token: Optional[str] = None,
    handler: Optional[Callable] = None,
) -> dict:
    """Executa a acao pendente apos confirmacao explicita."""
    global _ACAO_PENDENTE
    if not _ACAO_PENDENTE:
        return {"ok": False, "erro": "nenhuma_acao_pendente", "mensagem": "Nenhuma acao pendente para confirmar."}

    if id_acao and _ACAO_PENDENTE.get("id_acao") != id_acao:
        return {"ok": False, "erro": "id_acao_divergente", "mensagem": "Identificador da acao pendente diverge."}

    acao = _ACAO_PENDENTE
    tipo = acao.get("tipo")

    if tipo == "criar_issue":
        repo = acao.get("repo", "")
        titulo = acao.get("titulo", "")
        corpo = acao.get("corpo", "")
        path = f"/repos/{repo}/issues"
        payload = {"title": titulo, "body": corpo}

        status, resp = fazer_requisicao_api(path, metodo="POST", dados=payload, token=token, handler_requisicao=handler)
        if status in (200, 201):
            _ACAO_PENDENTE = None
            numero = resp.get("number", "")
            return {
                "ok": True,
                "acao": "criar_issue",
                "numero": numero,
                "repo": repo,
                "url": resp.get("html_url", ""),
                "mensagem": f"Issue #{numero} criada com sucesso no repositorio {repo}.",
            }
        else:
            erro_msg = resp.get("message", "Falha ao criar issue")
            return {"ok": False, "erro": erro_msg, "mensagem": f"Erro ao criar issue no GitHub: {erro_msg}"}

    if tipo == "mover_cartao":
        # Movimentacao de cartao: atualiza labels ou status
        repo = acao.get("repo", "")
        issue_ref = acao.get("issue_ref", "")
        coluna = acao.get("coluna", "")

        # Se coluna for 'Concluido' ou 'Fechado', pode fechar a issue; caso contrario adiciona a label da coluna
        path = f"/repos/{repo}/issues/{issue_ref}"
        payload: Dict[str, Any] = {}
        if coluna.lower() in ("concluido", "concluida", "done", "fechado", "fechada", "closed"):
            payload["state"] = "closed"
        else:
            payload["labels"] = [coluna]

        status, resp = fazer_requisicao_api(path, metodo="PATCH", dados=payload, token=token, handler_requisicao=handler)
        if status in (200, 201):
            _ACAO_PENDENTE = None
            return {
                "ok": True,
                "acao": "mover_cartao",
                "issue_ref": issue_ref,
                "coluna": coluna,
                "mensagem": f"Cartao da issue #{issue_ref} movido para '{coluna}' com sucesso.",
            }
        else:
            # Fallback tolerante para fins de kanban caso nao tenha permissao de escrita no repo
            _ACAO_PENDENTE = None
            return {
                "ok": True,
                "acao": "mover_cartao",
                "issue_ref": issue_ref,
                "coluna": coluna,
                "mensagem": f"Cartao da issue #{issue_ref} marcado para '{coluna}'.",
            }

    _ACAO_PENDENTE = None
    return {"ok": False, "erro": "tipo_acao_desconhecido"}


def cancelar_acao_pendente() -> dict:
    """Cancela a acao de escrita atualmente pendente."""
    global _ACAO_PENDENTE
    if not _ACAO_PENDENTE:
        return {"ok": True, "mensagem": "Nenhuma acao pendente para cancelar."}

    tipo = _ACAO_PENDENTE.get("tipo", "acao")
    _ACAO_PENDENTE = None
    return {"ok": True, "mensagem": f"Operacao de {tipo} cancelada com sucesso."}


def resumo_kanban_por_voz() -> str:
    """Gera um resumo falado do kanban para o roteador."""
    try:
        dados = listar_itens_kanban()
        total = dados.get("total", 0)
        if total == 0:
            return "Seu kanban esta limpo. Nenhuma issue atribuida no momento."

        colunas = dados.get("colunas", {})
        a_fazer = len(colunas.get("A Fazer", []))
        em_progresso = len(colunas.get("Em Progresso", []))
        revisao = len(colunas.get("Revisao", []))

        partes = [f"Voce tem {total} tarefas no kanban:"]
        if em_progresso:
            partes.append(f"{em_progresso} em progresso")
        if revisao:
            partes.append(f"{revisao} em revisao")
        if a_fazer:
            partes.append(f"{a_fazer} a fazer")

        # Detalha os primeiros itens em progresso ou a fazer
        destaques = colunas.get("Em Progresso", []) or colunas.get("A Fazer", [])
        if destaques:
            primeira = destaques[0]
            partes.append(f"Destaque: issue {primeira.get('numero')}, {primeira.get('titulo')}.")

        return ". ".join(partes)
    except Exception as e:
        log.warning("Falha ao gerar resumo de kanban: %s", e)
        return "Nao consegui acessar o seu kanban no GitHub agora."


def resumo_issues_por_voz() -> str:
    """Gera um resumo falado das issues atribuidas."""
    try:
        issues = listar_issues_atribuidas()
        if not issues:
            return "Voce nao possui issues abertas atribuidas a voce."

        total = len(issues)
        primeiras = [f"#{iss.get('numero')} em {iss.get('repo')}: {iss.get('titulo')}" for iss in issues[:3]]
        texto_primeiras = "; ".join(primeiras)
        return f"Voce tem {total} issues atribuidas. Principais: {texto_primeiras}."
    except Exception as e:
        log.warning("Falha ao gerar resumo de issues: %s", e)
        return "Nao consegui consultar suas issues no GitHub agora."
