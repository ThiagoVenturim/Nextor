"""Modulo de integracao somente leitura com o Canvas LMS (Issue #17)."""
from datetime import date, datetime, timezone
import html
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger("nextor.canvas")


def _obter_fuso() -> ZoneInfo:
    try:
        return ZoneInfo(config.FUSO)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def esta_configurado(base_url: Optional[str] = None, token: Optional[str] = None) -> bool:
    """Verifica se as credenciais do Canvas LMS estao presentes."""
    url = (base_url or getattr(config, "CANVAS_BASE_URL", "")).strip()
    tk = (token or getattr(config, "CANVAS_TOKEN", "")).strip()
    return bool(url and tk)


def _executar_requisicao(
    caminho_ou_url: str,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    http_client: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> Any:
    """Executa chamada autenticada a API REST do Canvas LMS com tolerancia a falhas."""
    url_base = (base_url or getattr(config, "CANVAS_BASE_URL", "")).rstrip("/")
    tk = (token or getattr(config, "CANVAS_TOKEN", "")).strip()

    if not url_base or not tk:
        raise ValueError("Canvas LMS nao configurado. Defina CANVAS_BASE_URL e CANVAS_TOKEN no .env.")

    if caminho_ou_url.startswith("http://") or caminho_ou_url.startswith("https://"):
        url_final = caminho_ou_url
    else:
        url_final = f"{url_base}/{caminho_ou_url.lstrip('/')}"

    if params:
        query_str = urllib.parse.urlencode(params, doseq=True)
        separador = "&" if "?" in url_final else "?"
        url_final = f"{url_final}{separador}{query_str}"

    headers = {
        "Authorization": f"Bearer {tk}",
        "Accept": "application/json",
        "User-Agent": "Nextor-CanvasLMS/1.0",
    }

    if http_client is not None:
        raw = http_client(url_final, headers)
    else:
        req = urllib.request.Request(url_final, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")

    return json.loads(raw)


def listar_cursos_ativos(
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    http_client: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Obtem a lista de cursos ativos matriculados pelo estudante."""
    if not esta_configurado(base_url, token) and http_client is None:
        return []

    try:
        dados = _executar_requisicao(
            "/api/v1/courses",
            base_url=base_url,
            token=token,
            params={"enrollment_state": "active", "include[]": "term", "per_page": 50},
            http_client=http_client,
        )
    except Exception as e:
        log.warning("Falha ao listar cursos do Canvas: %s", e)
        return []

    if not isinstance(dados, list):
        return []

    cursos = []
    for c in dados:
        if not isinstance(c, dict):
            continue
        nome = c.get("name")
        if not nome or not nome.strip():
            continue
        termo_info = c.get("term") or {}
        cursos.append({
            "id": c.get("id"),
            "nome": nome.strip(),
            "codigo": c.get("course_code") or "",
            "termo": termo_info.get("name") or "",
        })

    return cursos


def _parse_data_iso(data_str: Optional[str], tz: ZoneInfo) -> Tuple[Optional[str], Optional[datetime]]:
    """Converte carimbo ISO 8601 UTC do Canvas para representacao no fuso do usuario."""
    if not data_str:
        return None, None
    try:
        # Ex: "2026-11-10T23:59:00Z" ou com offset
        limpo = data_str.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(limpo)
        dt_local = dt_utc.astimezone(tz)
        return dt_local.strftime("%Y-%m-%d %H:%M"), dt_local
    except Exception:
        return data_str[:16].replace("T", " "), None


def listar_tarefas(
    curso_id: Optional[int | str] = None,
    disciplina_nome: Optional[str] = None,
    apenas_pendentes: bool = True,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    agora: Optional[datetime] = None,
    http_client: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Lista tarefas e prazos do Canvas com indicacao de vencimento e atraso."""
    if not esta_configurado(base_url, token) and http_client is None:
        return []

    tz = _obter_fuso()
    dt_agora = agora or datetime.now(tz)
    hoje_data = dt_agora.date()

    cursos = listar_cursos_ativos(base_url=base_url, token=token, http_client=http_client)
    mapa_cursos = {c["id"]: c["nome"] for c in cursos}

    # Filtra por curso especifico se solicitado
    cursos_alvo = cursos
    if curso_id is not None:
        cursos_alvo = [c for c in cursos if str(c["id"]) == str(curso_id)]
    elif disciplina_nome:
        termo = disciplina_nome.strip().lower()
        cursos_alvo = [c for c in cursos if termo in c["nome"].lower() or termo in c["codigo"].lower()]

    tarefas_encontradas: List[Dict[str, Any]] = []

    for c in cursos_alvo:
        c_id = c["id"]
        c_nome = c["nome"]
        try:
            params = {"order_by": "due_at", "per_page": 50}
            if apenas_pendentes:
                params["bucket"] = "upcoming"

            dados = _executar_requisicao(
                f"/api/v1/courses/{c_id}/assignments",
                base_url=base_url,
                token=token,
                params=params,
                http_client=http_client,
            )
        except Exception as e:
            log.warning("Falha ao buscar tarefas do curso %s no Canvas: %s", c_id, e)
            continue

        if not isinstance(dados, list):
            continue

        for a in dados:
            if not isinstance(a, dict):
                continue

            # Se submetida, ignora se apenas pendentes
            has_submitted = a.get("has_submitted_submissions", False)
            if apenas_pendentes and has_submitted:
                continue

            prazo_raw = a.get("due_at")
            prazo_str, dt_prazo = _parse_data_iso(prazo_raw, tz)

            atrasada = False
            para_hoje = False

            if dt_prazo:
                data_prazo = dt_prazo.date()
                if data_prazo < hoje_data:
                    atrasada = True
                elif data_prazo == hoje_data:
                    para_hoje = True
                    if dt_prazo < dt_agora:
                        atrasada = True

            tarefas_encontradas.append({
                "id": a.get("id"),
                "titulo": (a.get("name") or "Tarefa sem nome").strip(),
                "curso_id": c_id,
                "curso_nome": c_nome,
                "prazo": prazo_str,
                "dt_prazo": dt_prazo,
                "atrasada": atrasada,
                "para_hoje": para_hoje,
                "pontos": a.get("points_possible"),
                "submetida": has_submitted,
                "url": a.get("html_url") or "",
            })

    # Ordena por prazo (vencimento mais proximo primeiro)
    def chave_ord(item):
        dt = item.get("dt_prazo")
        return dt if dt else datetime.max.replace(tzinfo=tz)

    tarefas_encontradas.sort(key=chave_ord)
    return tarefas_encontradas


def listar_avisos(
    curso_id: Optional[int | str] = None,
    disciplina_nome: Optional[str] = None,
    limite: int = 5,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    http_client: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Lista avisos e comunicados recentes dos cursos no Canvas."""
    if not esta_configurado(base_url, token) and http_client is None:
        return []

    tz = _obter_fuso()
    cursos = listar_cursos_ativos(base_url=base_url, token=token, http_client=http_client)
    if not cursos:
        return []

    cursos_alvo = cursos
    if curso_id is not None:
        cursos_alvo = [c for c in cursos if str(c["id"]) == str(curso_id)]
    elif disciplina_nome:
        termo = disciplina_nome.strip().lower()
        cursos_alvo = [c for c in cursos if termo in c["nome"].lower() or termo in c["codigo"].lower()]

    context_codes = [f"course_{c['id']}" for c in cursos_alvo]
    mapa_cursos = {f"course_{c['id']}": c["nome"] for c in cursos_alvo}

    try:
        dados = _executar_requisicao(
            "/api/v1/announcements",
            base_url=base_url,
            token=token,
            params={"context_codes[]": context_codes, "latest_only": "true", "per_page": limite},
            http_client=http_client,
        )
    except Exception as e:
        log.warning("Falha ao buscar avisos do Canvas: %s", e)
        return []

    if not isinstance(dados, list):
        return []

    avisos = []
    for item in dados[:limite]:
        if not isinstance(item, dict):
            continue
        msg_raw = item.get("message") or ""
        # Limpa tags html do corpo do aviso
        msg_limpa = re.sub(r"<[^>]+>", " ", msg_raw)
        msg_limpa = html.unescape(re.sub(r"\s+", " ", msg_limpa)).strip()
        resumo_msg = msg_limpa[:160] + "..." if len(msg_limpa) > 160 else msg_limpa

        data_post_str, dt_post = _parse_data_iso(item.get("posted_at"), tz)
        ctx = item.get("context_code") or ""
        nome_curso = mapa_cursos.get(ctx, "Curso")

        autor_info = item.get("author") or {}
        autor_nome = autor_info.get("display_name") or "Professor"

        avisos.append({
            "id": item.get("id"),
            "titulo": (item.get("title") or "Aviso sem titulo").strip(),
            "curso_nome": nome_curso,
            "autor": autor_nome,
            "mensagem": resumo_msg,
            "data": data_post_str,
            "url": item.get("html_url") or "",
        })

    return avisos


def coletar_pendencias_canvas(
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    agora: Optional[datetime] = None,
    http_client: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Gera itens de pendencias compativeis com o painel unificado de tarefas do Nextor."""
    if not esta_configurado(base_url, token) and http_client is None:
        return []

    tarefas = listar_tarefas(
        apenas_pendentes=True,
        base_url=base_url,
        token=token,
        agora=agora,
        http_client=http_client,
    )

    pendencias = []
    for t in tarefas:
        pendencias.append({
            "id": f"canvas:{t['curso_id']}#{t['id']}",
            "fonte": "canvas",
            "titulo": t["titulo"],
            "disciplina": t["curso_nome"],
            "prazo": t["prazo"],
            "dt_prazo": t["dt_prazo"],
            "atrasada": t["atrasada"],
            "para_hoje": t["para_hoje"],
            "url": t["url"],
        })

    return pendencias


def resumo_tarefas_falado(tarefas: List[Dict[str, Any]], disciplina: str = "") -> str:
    """Sintetiza as tarefas em texto conciso para fala no Google Nest Mini."""
    if not tarefas:
        alvo = f" em {disciplina}" if disciplina else ""
        return f"Voce nao tem tarefas pendentes no Canvas{alvo}."

    total = len(tarefas)
    atrasadas = sum(1 for t in tarefas if t.get("atrasada"))
    para_hoje = sum(1 for t in tarefas if t.get("para_hoje"))

    partes = [f"No Canvas, voce tem {total} tarefas pendentes"]
    detalhes = []
    if para_hoje:
        detalhes.append(f"{para_hoje} para hoje")
    if atrasadas:
        detalhes.append(f"{atrasadas} atrasadas")
    if detalhes:
        partes.append(f"({', '.join(detalhes)})")

    destaques = [f"{t['titulo']} ({t['curso_nome']})" for t in tarefas[:2]]
    partes.append(f"Principais: {'; '.join(destaques)}.")
    return " ".join(partes)


def resumo_avisos_falado(avisos: List[Dict[str, Any]], disciplina: str = "") -> str:
    """Sintetiza os avisos em texto conciso para fala no Google Nest Mini."""
    if not avisos:
        alvo = f" para {disciplina}" if disciplina else ""
        return f"Nenhum aviso novo no Canvas{alvo}."

    qtd = len(avisos)
    if qtd == 1:
        a = avisos[0]
        return f"No Canvas, voce tem 1 aviso de {a['curso_nome']}: '{a['titulo']}'."

    destaques = [f"'{a['titulo']}' em {a['curso_nome']}" for a in avisos[:2]]
    return f"No Canvas, ha {qtd} avisos recentes. Destaques: {'; '.join(destaques)}."
