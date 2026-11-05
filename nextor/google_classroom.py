"""Modulo de integracao somente leitura com o Google Sala de Aula (Issue #18)."""
from datetime import date, datetime, time, timezone
import json
import logging
from pathlib import Path
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger("nextor.classroom")

CLASSROOM_API_BASE = "https://classroom.googleapis.com/v1"


def _obter_fuso() -> ZoneInfo:
    try:
        return ZoneInfo(config.FUSO)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def esta_configurado(token: Optional[str] = None) -> bool:
    """Verifica se o token de acesso do Google Sala de Aula esta presente e valido."""
    tk = (token if token is not None else getattr(config, "GOOGLE_CLASSROOM_TOKEN", "")).strip()
    if not tk:
        return False
    # Pode ser o proprio token OAuth em string ou o caminho para um arquivo JSON
    p = Path(tk)
    if tk.endswith(".json") or ("/" in tk or "\\" in tk):
        if p.exists() and p.is_file():
            try:
                conteudo = p.read_text(encoding="utf-8").strip()
                return bool(conteudo)
            except Exception:
                return False
        return False
    if p.exists() and p.is_file():
        try:
            conteudo = p.read_text(encoding="utf-8").strip()
            return bool(conteudo)
        except Exception:
            return False
    return bool(tk)


def _resolver_bearer_token(token: Optional[str] = None) -> str:
    """Resolve o token Bearer a partir de string direta ou arquivo JSON local."""
    tk = (token if token is not None else getattr(config, "GOOGLE_CLASSROOM_TOKEN", "")).strip()
    if not tk:
        return ""

    p = Path(tk)
    if tk.endswith(".json") or ("/" in tk or "\\" in tk):
        if p.exists() and p.is_file():
            try:
                conteudo = p.read_text(encoding="utf-8").strip()
                if conteudo.startswith("{"):
                    dados = json.loads(conteudo)
                    if isinstance(dados, dict):
                        return (dados.get("access_token") or dados.get("token") or "").strip()
                return conteudo
            except Exception as e:
                log.warning("Falha ao ler arquivo de token do Google Classroom: %s", e)
                return ""
        return ""

    if p.exists() and p.is_file():
        try:
            conteudo = p.read_text(encoding="utf-8").strip()
            if conteudo.startswith("{"):
                dados = json.loads(conteudo)
                # Formato comum gerado por scripts google-auth / oauth2
                if isinstance(dados, dict):
                    return (dados.get("access_token") or dados.get("token") or "").strip()
            return conteudo
        except Exception as e:
            log.warning("Falha ao ler arquivo de token do Google Classroom: %s", e)
            return ""

    return tk


def _converter_due_date_time(
    due_date: Optional[Dict[str, int]],
    due_time: Optional[Dict[str, int]],
    fuso: ZoneInfo,
) -> Tuple[Optional[str], Optional[datetime]]:
    """Converte dueDate e dueTime da Google Classroom API (em UTC) para fuso local."""
    if not due_date or not isinstance(due_date, dict):
        return None, None

    ano = due_date.get("year")
    mes = due_date.get("month")
    dia = due_date.get("day")
    if not (ano and mes and dia):
        return None, None

    if due_time and isinstance(due_time, dict):
        hora = due_time.get("hours", 0)
        minuto = due_time.get("minutes", 0)
        segundo = due_time.get("seconds", 0)
        # Google Classroom API documenta que dueTime e retornado em UTC
        dt_utc = datetime(ano, mes, dia, hora, minuto, segundo, tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(fuso)
        str_prazo = dt_local.strftime("%d/%m/%Y %H:%M")
        return str_prazo, dt_local
    else:
        # Sem hora especificada: fim do dia local
        d_local = date(ano, mes, dia)
        dt_local = datetime.combine(d_local, time(23, 59, 59), tzinfo=fuso)
        str_prazo = dt_local.strftime("%d/%m/%Y")
        return str_prazo, dt_local


def _executar_requisicao(
    caminho_ou_url: str,
    params: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    http_client: Optional[Callable[[str, Dict[str, str]], str]] = None,
) -> Any:
    """Executa chamada autenticada a Google Classroom API com tolerancia a falhas."""
    tk = _resolver_bearer_token(token)
    if not tk and http_client is None:
        raise ValueError("Google Sala de Aula nao configurado. Defina GOOGLE_CLASSROOM_TOKEN no .env.")

    if caminho_ou_url.startswith("http://") or caminho_ou_url.startswith("https://"):
        url_final = caminho_ou_url
    else:
        url_final = f"{CLASSROOM_API_BASE}/{caminho_ou_url.lstrip('/')}"

    if params:
        query_str = urllib.parse.urlencode(params, doseq=True)
        separador = "&" if "?" in url_final else "?"
        url_final = f"{url_final}{separador}{query_str}"

    headers = {
        "Authorization": f"Bearer {tk}",
        "Accept": "application/json",
        "User-Agent": "Nextor-GoogleClassroom/1.0",
    }

    if http_client is not None:
        raw = http_client(url_final, headers)
    else:
        req = urllib.request.Request(url_final, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")

    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def listar_cursos_ativos(
    token: Optional[str] = None,
    http_client: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Obtem lista de cursos ativos matriculados pelo aluno."""
    if not esta_configurado(token) and http_client is None:
        return []

    try:
        dados = _executar_requisicao(
            "courses",
            params={"courseStates": "ACTIVE", "pageSize": 50},
            token=token,
            http_client=http_client,
        )
    except Exception as e:
        log.warning("Falha ao listar cursos do Google Classroom: %s", e)
        return []

    if not isinstance(dados, dict):
        return []

    cursos_raw = dados.get("courses", [])
    if not isinstance(cursos_raw, list):
        return []

    cursos = []
    for c in cursos_raw:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        nome = str(c.get("name") or "").strip()
        if not cid or not nome:
            continue
        cursos.append({
            "id": cid,
            "nome": nome,
            "secao": c.get("section") or "",
            "descricao_materia": c.get("descriptionHeading") or "",
            "sala": c.get("room") or "",
            "link": c.get("alternateLink") or "",
            "estado": c.get("courseState") or "ACTIVE",
        })

    return cursos


def listar_atividades(
    curso_id: Optional[str] = None,
    disciplina_nome: str = "",
    apenas_pendentes: bool = True,
    token: Optional[str] = None,
    http_client: Optional[Callable] = None,
    agora: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Lista atividades (courseWork) com prazos e status de conclusao."""
    if not esta_configurado(token) and http_client is None:
        return []

    tz = _obter_fuso()
    dt_agora = agora or datetime.now(tz)
    hoje_data = dt_agora.date()

    cursos = listar_cursos_ativos(token=token, http_client=http_client)
    mapa_cursos: Dict[str, str] = {c["id"]: c["nome"] for c in cursos}

    # Filtrar cursos alvo
    if curso_id:
        cursos_alvo = [c for c in cursos if c["id"] == str(curso_id)]
    elif disciplina_nome:
        termo = disciplina_nome.lower().strip()
        cursos_alvo = [c for c in cursos if termo in c["nome"].lower() or termo in c["secao"].lower()]
    else:
        cursos_alvo = cursos

    atividades: List[Dict[str, Any]] = []

    for c in cursos_alvo:
        cid = c["id"]
        c_nome = c["nome"]

        try:
            dados_cw = _executar_requisicao(
                f"courses/{cid}/courseWork",
                params={"courseWorkStates": "PUBLISHED", "pageSize": 50},
                token=token,
                http_client=http_client,
            )
        except Exception as e:
            log.warning("Falha ao obter atividades do curso %s (%s): %s", cid, c_nome, e)
            continue

        if not isinstance(dados_cw, dict):
            continue

        itens_cw = dados_cw.get("courseWork", [])
        if not isinstance(itens_cw, list):
            continue

        # Obter submissoes do usuario se disponivel para verificar entrega
        submissoes_map: Dict[str, str] = {}
        try:
            dados_sub = _executar_requisicao(
                f"courses/{cid}/courseWork/-/studentSubmissions",
                params={"userId": "me", "pageSize": 100},
                token=token,
                http_client=http_client,
            )
            if isinstance(dados_sub, dict):
                for sub in dados_sub.get("studentSubmissions", []):
                    if isinstance(sub, dict) and sub.get("courseWorkId"):
                        submissoes_map[str(sub.get("courseWorkId"))] = str(sub.get("state") or "")
        except Exception:
            # Nem todos os perfis/mocks expoem studentSubmissions diretamente
            pass

        for cw in itens_cw:
            if not isinstance(cw, dict):
                continue

            cw_id = str(cw.get("id") or "").strip()
            titulo = str(cw.get("title") or "").strip()
            if not cw_id or not titulo:
                continue

            # Checar se ja foi entregue
            estado_sub = submissoes_map.get(cw_id, "")
            entregue = estado_sub in ("TURNED_IN", "RETURNED") or bool(cw.get("submitted", False))

            if apenas_pendentes and entregue:
                continue

            prazo_str, dt_prazo = _converter_due_date_time(cw.get("dueDate"), cw.get("dueTime"), tz)

            atrasada = False
            para_hoje = False

            if dt_prazo:
                if dt_prazo < dt_agora:
                    atrasada = True
                if dt_prazo.date() == hoje_data:
                    para_hoje = True

            materiais = []
            for mat in cw.get("materials", []):
                if isinstance(mat, dict):
                    if "driveFile" in mat and isinstance(mat["driveFile"], dict):
                        df = mat["driveFile"].get("driveFile", {})
                        materiais.append({"tipo": "drive", "titulo": df.get("title", ""), "link": df.get("alternateLink", "")})
                    elif "link" in mat and isinstance(mat["link"], dict):
                        lk = mat["link"]
                        materiais.append({"tipo": "link", "titulo": lk.get("title", ""), "url": lk.get("url", "")})
                    elif "youtubeVideo" in mat and isinstance(mat["youtubeVideo"], dict):
                        yt = mat["youtubeVideo"]
                        materiais.append({"tipo": "youtube", "titulo": yt.get("title", ""), "link": yt.get("alternateLink", "")})

            atividades.append({
                "id": cw_id,
                "curso_id": cid,
                "disciplina": c_nome,
                "titulo": titulo,
                "descricao": (cw.get("description") or "").strip(),
                "prazo": prazo_str,
                "dt_prazo": dt_prazo,
                "atrasada": atrasada,
                "para_hoje": para_hoje,
                "entregue": entregue,
                "pontos_maximos": cw.get("maxPoints"),
                "materiais": materiais,
                "url": cw.get("alternateLink") or "",
            })

    def chave_ordenacao(item: dict):
        prioridade_atrasada = 0 if item.get("atrasada") else 1
        prioridade_hoje = 0 if item.get("para_hoje") else 1
        dt = item.get("dt_prazo")
        if isinstance(dt, datetime):
            if dt.tzinfo is not None:
                dt_val = dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                dt_val = dt
        else:
            dt_val = datetime.max
        return (prioridade_atrasada, prioridade_hoje, dt_val, item.get("titulo", "").lower())

    atividades.sort(key=chave_ordenacao)
    return atividades


def listar_avisos(
    curso_id: Optional[str] = None,
    disciplina_nome: str = "",
    limite: int = 5,
    token: Optional[str] = None,
    http_client: Optional[Callable] = None,
) -> List[Dict[str, Any]]:
    """Lista avisos e comunicados (announcements) publicados nos cursos."""
    if not esta_configurado(token) and http_client is None:
        return []

    cursos = listar_cursos_ativos(token=token, http_client=http_client)
    if curso_id:
        cursos_alvo = [c for c in cursos if c["id"] == str(curso_id)]
    elif disciplina_nome:
        termo = disciplina_nome.lower().strip()
        cursos_alvo = [c for c in cursos if termo in c["nome"].lower() or termo in c["secao"].lower()]
    else:
        cursos_alvo = cursos

    avisos: List[Dict[str, Any]] = []

    for c in cursos_alvo:
        cid = c["id"]
        c_nome = c["nome"]

        try:
            dados = _executar_requisicao(
                f"courses/{cid}/announcements",
                params={"announcementStates": "PUBLISHED", "pageSize": 10},
                token=token,
                http_client=http_client,
            )
        except Exception as e:
            log.warning("Falha ao obter avisos do curso %s (%s): %s", cid, c_nome, e)
            continue

        if not isinstance(dados, dict):
            continue

        itens = dados.get("announcements", [])
        if not isinstance(itens, list):
            continue

        for av in itens:
            if not isinstance(av, dict):
                continue
            aid = str(av.get("id") or "").strip()
            texto = str(av.get("text") or "").strip()
            if not aid or not texto:
                continue

            criado_em = av.get("creationTime") or ""
            link = av.get("alternateLink") or ""

            # Truncar resumo para fala amigavel
            resumo_texto = texto
            if len(resumo_texto) > 160:
                resumo_texto = resumo_texto[:157] + "..."

            avisos.append({
                "id": aid,
                "curso_id": cid,
                "disciplina": c_nome,
                "texto": texto,
                "resumo": resumo_texto,
                "criado_em": criado_em,
                "url": link,
            })

    avisos.sort(key=lambda a: a.get("criado_em", ""), reverse=True)
    return avisos[:limite]


def coletar_pendencias_classroom(
    token: Optional[str] = None,
    http_client: Optional[Callable] = None,
    agora: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Coleta atividades pendentes no formato compativel com o painel unificado."""
    if not esta_configurado(token) and http_client is None:
        return []

    atividades = listar_atividades(
        apenas_pendentes=True,
        token=token,
        http_client=http_client,
        agora=agora,
    )

    pendencias: List[Dict[str, Any]] = []
    for at in atividades:
        cid = at.get("curso_id")
        cw_id = at.get("id")
        pendencias.append({
            "id": f"classroom:{cw_id}",
            "fonte": "classroom",
            "titulo": at.get("titulo", ""),
            "disciplina": at.get("disciplina", ""),
            "prazo": at.get("prazo"),
            "dt_prazo": at.get("dt_prazo"),
            "atrasada": at.get("atrasada", False),
            "para_hoje": at.get("para_hoje", False),
            "url": at.get("url", ""),
            "curso_id": cid,
        })

    return pendencias


def resumo_atividades_falado(atividades: List[Dict[str, Any]], disciplina: str = "") -> str:
    """Gera resposta concisa em fala para o Nest Mini sobre as atividades do Classroom."""
    contexto = f" em {disciplina}" if disciplina else ""

    if not atividades:
        return f"Voce nao possui nenhuma atividade pendente no Google Sala de Aula{contexto}."

    total = len(atividades)
    atrasadas = sum(1 for a in atividades if a.get("atrasada"))
    hoje = sum(1 for a in atividades if a.get("para_hoje"))

    partes = []
    if atrasadas > 0:
        partes.append(f"{atrasadas} atrasada{'s' if atrasadas > 1 else ''}")
    if hoje > 0:
        partes.append(f"{hoje} para hoje")

    detalhe = f" ({', '.join(partes)})" if partes else ""

    primeira = atividades[0]
    titulo_1 = primeira.get("titulo", "")
    disc_1 = primeira.get("disciplina", "")
    prazo_1 = primeira.get("prazo", "")

    frase_destaque = f"A principal e '{titulo_1}' de {disc_1}"
    if prazo_1:
        frase_destaque += f", com prazo para {prazo_1}"
    frase_destaque += "."

    if total == 1:
        return f"Voce tem 1 atividade pendente no Google Sala de Aula{contexto}{detalhe}. {frase_destaque}"

    return f"Voce tem {total} atividades no Google Sala de Aula{contexto}{detalhe}. {frase_destaque}"


def resumo_avisos_falado(avisos: List[Dict[str, Any]], disciplina: str = "") -> str:
    """Gera sintese falada de avisos do Google Sala de Aula para o Nest Mini."""
    contexto = f" de {disciplina}" if disciplina else ""

    if not avisos:
        return f"Nenhum aviso novo no Google Sala de Aula{contexto}."

    total = len(avisos)
    primeiro = avisos[0]
    disc = primeiro.get("disciplina", "")
    texto = primeiro.get("resumo", "")

    if total == 1:
        return f"Voce tem 1 aviso no Google Sala de Aula{contexto} em {disc}: '{texto}'."

    return f"Voce tem {total} avisos no Google Sala de Aula{contexto}. O mais recente em {disc}: '{texto}'."
