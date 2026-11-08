"""Agenda do Nextor: le a Google Agenda por um endereco privado iCal (sem Google Cloud).

Inclui deteccao de reunioes (Zoom, Meet, Teams ou participantes), calculo de conflitos,
blocos livres, sugestoes de timeboxing (estudos, academia, leitura) e disparos de lembretes.
"""
from datetime import date, datetime, time, timedelta
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import urllib.request
from zoneinfo import ZoneInfo

from . import config

try:
    from icalendar import Calendar
    import recurring_ical_events
except ImportError:
    Calendar = None
    recurring_ical_events = None

log = logging.getLogger("nextor.agenda")

TZ = ZoneInfo(config.FUSO)
DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]

# Padrao para deteccao de links de videoconferencia (Zoom, Google Meet, Microsoft Teams, etc.)
PADRAO_LINK_VIDEO = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)?(?:"
    r"meet\.google\.com/[a-z0-9-]+|"
    r"zoom\.(?:us|com)/[^\s>\"']+|"
    r"teams\.(?:microsoft|live)\.com/[^\s>\"']+|"
    r"teams\.web\.office\.com/[^\s>\"']+|"
    r"webex\.com/[^\s>\"']+|"
    r"meet\.jit\.si/[^\s>\"']+"
    r")",
    re.IGNORECASE,
)

# Registro em memoria de alertas ja disparados (evita notificacoes duplicadas)
_ALERTAS_DISPARADOS: Set[Tuple[str, str]] = set()


def limpar_alertas_reuniao() -> None:
    """Limpa o registro de alertas ja enviados (util para isolamento de testes)."""
    _ALERTAS_DISPARADOS.clear()


def extrair_link_video(texto: Optional[str]) -> Optional[str]:
    """Identifica e extrai link de videoconferencia de um texto ou URL."""
    if not texto:
        return None
    match = PADRAO_LINK_VIDEO.search(str(texto))
    if not match:
        return None
    link = match.group(0).rstrip(".,;)>\"'")
    return link


def extrair_participantes(ev: Any) -> List[str]:
    """Extrai lista de emails ou identificadores de participantes de um evento."""
    participantes: List[str] = []
    if ev is None:
        return participantes

    # Se for dicionario sintetico
    if isinstance(ev, dict):
        parts = ev.get("participantes") or ev.get("attendees") or []
        if isinstance(parts, list):
            return [str(p).strip() for p in parts if str(p).strip()]
        if isinstance(parts, str) and parts.strip():
            return [parts.strip()]
        return participantes

    # Se for componente icalendar
    try:
        attendees = ev.get("ATTENDEE")
        if attendees is None:
            return participantes
        if not isinstance(attendees, list):
            attendees = [attendees]
        for att in attendees:
            valor = str(att)
            if valor.lower().startswith("mailto:"):
                valor = valor[7:]
            valor = valor.strip()
            if valor:
                participantes.append(valor)
    except Exception:
        pass

    return participantes


def _parsear_ics_simples(conteudo: str) -> List[Dict[str, Any]]:
    """Parser leve de eventos VEVENT em formato ICS (sem dependencia externa)."""
    linhas = []
    # Desdobra linhas de continuacao (RFC 5545)
    for linha in conteudo.splitlines():
        if linha.startswith(" ") or linha.startswith("\t"):
            if linhas:
                linhas[-1] += linha[1:]
        else:
            linhas.append(linha)

    eventos: List[Dict[str, Any]] = []
    evento_atual: Optional[Dict[str, Any]] = None

    for raw_linha in linhas:
        linha = raw_linha.strip()
        if not linha:
            continue
        if linha == "BEGIN:VEVENT":
            evento_atual = {
                "summary": "(sem titulo)",
                "dtstart": None,
                "dtend": None,
                "duration": None,
                "description": "",
                "location": "",
                "url": "",
                "uid": "",
                "attendees": [],
            }
            continue
        if linha == "END:VEVENT":
            if evento_atual and evento_atual.get("dtstart"):
                eventos.append(evento_atual)
            evento_atual = None
            continue

        if evento_atual is None:
            continue

        # Separa chave e valor
        if ":" in linha:
            prop_meta, valor = linha.split(":", 1)
            prop = prop_meta.split(";")[0].upper()

            if prop == "SUMMARY":
                evento_atual["summary"] = valor.replace(r"\,", ",").replace(r"\;", ";")
            elif prop == "DESCRIPTION":
                evento_atual["description"] = valor.replace(r"\n", "\n").replace(r"\,", ",").replace(r"\;", ";")
            elif prop == "LOCATION":
                evento_atual["location"] = valor.replace(r"\,", ",").replace(r"\;", ";")
            elif prop == "URL":
                evento_atual["url"] = valor.strip()
            elif prop == "UID":
                evento_atual["uid"] = valor.strip()
            elif prop == "ATTENDEE":
                email = valor.replace("mailto:", "").replace("MAILTO:", "").strip()
                evento_atual["attendees"].append(email)
            elif prop == "DTSTART":
                evento_atual["dtstart"] = _converter_data_ics(valor)
            elif prop == "DTEND":
                evento_atual["dtend"] = _converter_data_ics(valor)

    return eventos


def _converter_data_ics(valor_str: str) -> datetime | date:
    """Converte valor de DTSTART/DTEND do iCalendar para datetime ou date no fuso local."""
    s = valor_str.strip().rstrip("Z")
    eh_utc = valor_str.strip().endswith("Z")

    if len(s) == 8 and s.isdigit():
        # Formato YYYYMMDD (dia inteiro)
        ano, mes, dia = int(s[0:4]), int(s[4:6]), int(s[6:8])
        return date(ano, mes, dia)

    # Formato YYYYMMDDTHHMMSS
    if "T" in s:
        partes = s.split("T")
        data_p, hora_p = partes[0], partes[1]
        ano, mes, dia = int(data_p[0:4]), int(data_p[4:6]), int(data_p[6:8])
        h = int(hora_p[0:2]) if len(hora_p) >= 2 else 0
        m = int(hora_p[2:4]) if len(hora_p) >= 4 else 0
        sec = int(hora_p[4:6]) if len(hora_p) >= 6 else 0
        if eh_utc:
            dt_utc = datetime(ano, mes, dia, h, m, sec, tzinfo=ZoneInfo("UTC"))
            return dt_utc.astimezone(TZ)
        return datetime(ano, mes, dia, h, m, sec, tzinfo=TZ)

    try:
        return datetime.fromisoformat(valor_str).astimezone(TZ)
    except Exception:
        return datetime.now(TZ)


def _baixar_ics(url: str) -> bytes:
    url = url.replace("webcal://", "https://")
    req = urllib.request.Request(url, headers={"User-Agent": "Nextor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _normaliza(ev: Any) -> dict:
    """Normaliza um evento (seja de icalendar, do parser simples ou de dict sintetico)."""
    # 1. Caso seja um dicionario ja sintetizado
    if isinstance(ev, dict) and "titulo" in ev and "inicio" in ev:
        inicio = ev["inicio"]
        dia_inteiro = ev.get("dia_inteiro", not isinstance(inicio, datetime))
        fim = ev.get("fim")
        if fim is None:
            if isinstance(inicio, datetime):
                fim = inicio + timedelta(hours=1)
            else:
                fim = inicio + timedelta(days=1)
        descricao = str(ev.get("descricao", ""))
        local = str(ev.get("local", ""))
        url_ev = str(ev.get("url", ""))
        parts = extrair_participantes(ev)
        link = ev.get("link_video") or extrair_link_video(url_ev) or extrair_link_video(descricao) or extrair_link_video(local)
        eh_reuniao = bool(ev.get("eh_reuniao", False) or link or parts)
        duracao = int((fim - inicio).total_seconds() // 60) if isinstance(inicio, datetime) and isinstance(fim, datetime) else 1440

        return {
            "uid": str(ev.get("uid") or f"ev-{ev['titulo']}-{inicio}"),
            "titulo": str(ev.get("titulo", "(sem titulo)")),
            "inicio": inicio,
            "fim": fim,
            "dia_inteiro": dia_inteiro,
            "duracao_minutos": max(0, duracao),
            "descricao": descricao,
            "local": local,
            "url": url_ev,
            "participantes": parts,
            "link_video": link,
            "eh_reuniao": eh_reuniao,
        }

    # 2. Caso seja gerado pelo parser leve _parsear_ics_simples
    if isinstance(ev, dict) and "dtstart" in ev:
        inicio = ev["dtstart"]
        dia_inteiro = not isinstance(inicio, datetime)
        fim = ev.get("dtend")
        if fim is None:
            fim = inicio + (timedelta(days=1) if dia_inteiro else timedelta(hours=1))
        descricao = ev.get("description", "")
        local = ev.get("location", "")
        url_ev = ev.get("url", "")
        parts = ev.get("attendees", [])
        link = extrair_link_video(url_ev) or extrair_link_video(descricao) or extrair_link_video(local)
        duracao = int((fim - inicio).total_seconds() // 60) if isinstance(inicio, datetime) and isinstance(fim, datetime) else 1440

        return {
            "uid": ev.get("uid") or f"ev-{ev.get('summary')}-{inicio}",
            "titulo": str(ev.get("summary", "(sem titulo)")),
            "inicio": inicio,
            "fim": fim,
            "dia_inteiro": dia_inteiro,
            "duracao_minutos": max(0, duracao),
            "descricao": descricao,
            "local": local,
            "url": url_ev,
            "participantes": parts,
            "link_video": link,
            "eh_reuniao": bool(link or parts),
        }

    # 3. Caso seja objeto icalendar.Event
    dtstart = ev.get("DTSTART")
    inicio = dtstart.dt if dtstart else datetime.now(TZ)
    dia_inteiro = not isinstance(inicio, datetime)
    if isinstance(inicio, datetime) and inicio.tzinfo is not None:
        inicio = inicio.astimezone(TZ)

    dtend = ev.get("DTEND")
    if dtend:
        fim = dtend.dt
        if isinstance(fim, datetime) and fim.tzinfo is not None:
            fim = fim.astimezone(TZ)
    else:
        fim = inicio + (timedelta(days=1) if dia_inteiro else timedelta(hours=1))

    descricao = str(ev.get("DESCRIPTION", "") or "")
    local = str(ev.get("LOCATION", "") or "")
    url_ev = str(ev.get("URL", "") or "")
    parts = extrair_participantes(ev)
    link = extrair_link_video(url_ev) or extrair_link_video(descricao) or extrair_link_video(local)
    duracao = int((fim - inicio).total_seconds() // 60) if isinstance(inicio, datetime) and isinstance(fim, datetime) else 1440

    return {
        "uid": str(ev.get("UID", "") or f"ev-{ev.get('SUMMARY')}-{inicio}"),
        "titulo": str(ev.get("SUMMARY", "(sem titulo)")),
        "inicio": inicio,
        "fim": fim,
        "dia_inteiro": dia_inteiro,
        "duracao_minutos": max(0, duracao),
        "descricao": descricao,
        "local": local,
        "url": url_ev,
        "participantes": parts,
        "link_video": link,
        "eh_reuniao": bool(link or parts),
    }


def parsear_ics(conteudo: str | bytes) -> List[dict]:
    """Converte uma string ou bytes no formato iCalendar em lista de eventos normalizados."""
    texto = conteudo.decode("utf-8", errors="ignore") if isinstance(conteudo, bytes) else str(conteudo)
    if Calendar is not None:
        try:
            cal = Calendar.from_ical(texto.encode("utf-8"))
            eventos = []
            for componente in cal.walk():
                if componente.name == "VEVENT":
                    eventos.append(_normaliza(componente))
            return eventos
        except Exception as e:
            log.warning("Falha no parser icalendar, tentando parser leve: %s", type(e).__name__)

    # Fallback para parser leve embutido
    brutos = _parsear_ics_simples(texto)
    return [_normaliza(e) for e in brutos]


def eventos_entre(
    inicio: date,
    fim: date,
    url: str = "",
    ics_conteudo: Optional[bytes | str] = None,
) -> list:
    """Busca e normaliza eventos contidos no intervalo de datas.

    Permite injetar conteudo ics direto para testes offline sem rede.
    """
    if ics_conteudo is not None:
        todos = parsear_ics(ics_conteudo)
    else:
        url = url or getattr(config, "AGENDA_ICAL", "")
        if not url:
            return []
        try:
            conteudo_baixado = _baixar_ics(url)
        except Exception as e:
            log.warning("Nao foi possivel baixar o calendario iCal: %s", type(e).__name__)
            return []

        if Calendar is not None and recurring_ical_events is not None:
            try:
                cal = Calendar.from_ical(conteudo_baixado)
                brutos = recurring_ical_events.of(cal).between(inicio, fim)
                eventos = [_normaliza(e) for e in brutos]
                eventos.sort(key=lambda e: (
                    e["inicio"] if isinstance(e["inicio"], datetime)
                    else datetime(e["inicio"].year, e["inicio"].month, e["inicio"].day, tzinfo=TZ)
                ))
                return eventos
            except Exception as e:
                log.warning("Falha ao expandir eventos recorrentes: %s", type(e).__name__)

        todos = parsear_ics(conteudo_baixado)

    # Filtra pelo intervalo de datas
    filtrados = []
    for ev in todos:
        ini_ev = ev["inicio"]
        d_ev = ini_ev.date() if isinstance(ini_ev, datetime) else ini_ev
        if inicio <= d_ev <= fim:
            filtrados.append(ev)

    filtrados.sort(key=lambda e: (
        e["inicio"] if isinstance(e["inicio"], datetime)
        else datetime(e["inicio"].year, e["inicio"].month, e["inicio"].day, tzinfo=TZ)
    ))
    return filtrados


def eventos_dia(
    data_ref: Optional[date | datetime] = None,
    url: str = "",
    ics_conteudo: Optional[bytes | str] = None,
) -> list:
    """Lista eventos do dia de referencia (padrao: hoje)."""
    if data_ref is None:
        hoje = datetime.now(TZ).date()
    elif isinstance(data_ref, datetime):
        hoje = data_ref.date()
    else:
        hoje = data_ref
    return eventos_entre(hoje, hoje, url=url, ics_conteudo=ics_conteudo)


def eventos_hoje(url: str = "", ics_conteudo: Optional[bytes | str] = None) -> list:
    """Mantem retrocompatibilidade com chamadas existentes."""
    return eventos_dia(url=url, ics_conteudo=ics_conteudo)


def eventos_semana(
    data_ref: Optional[date | datetime] = None,
    url: str = "",
    ics_conteudo: Optional[bytes | str] = None,
) -> list:
    """Lista eventos para os proximos 7 dias a partir da data de referencia."""
    if data_ref is None:
        hoje = datetime.now(TZ).date()
    elif isinstance(data_ref, datetime):
        hoje = data_ref.date()
    else:
        hoje = data_ref
    return eventos_entre(hoje, hoje + timedelta(days=7), url=url, ics_conteudo=ics_conteudo)


def eventos_proximos(
    dias: int = 7,
    url: str = "",
    ics_conteudo: Optional[bytes | str] = None,
) -> list:
    """Lista eventos nos proximos N dias."""
    hoje = datetime.now(TZ).date()
    return eventos_entre(hoje, hoje + timedelta(days=dias), url=url, ics_conteudo=ics_conteudo)


def proxima_reuniao(
    agora: Optional[datetime] = None,
    eventos: Optional[List[dict]] = None,
    url: str = "",
    ics_conteudo: Optional[bytes | str] = None,
) -> Optional[dict]:
    """Retorna o proximo evento classificado como reuniao."""
    momento = agora or datetime.now(TZ)
    if eventos is None:
        evs = eventos_proximos(dias=7, url=url, ics_conteudo=ics_conteudo)
    else:
        evs = eventos

    reunioes_futuras = []
    for e in evs:
        if not e.get("eh_reuniao"):
            continue
        inicio = e["inicio"]
        fim = e.get("fim")
        if isinstance(inicio, datetime):
            # Se a reuniao ainda nao terminou
            if fim and isinstance(fim, datetime):
                if fim >= momento:
                    reunioes_futuras.append(e)
            elif inicio >= momento - timedelta(minutes=15):
                reunioes_futuras.append(e)

    if not reunioes_futuras:
        return None

    reunioes_futuras.sort(key=lambda e: e["inicio"])
    return reunioes_futuras[0]


def detectar_conflitos(eventos: List[dict]) -> List[dict]:
    """Identifica eventos que possuem sobreposicao de horario no calendario."""
    conflitos = []
    # Considera apenas eventos com horario definido (nao dia inteiro)
    com_horario = [e for e in eventos if not e.get("dia_inteiro") and isinstance(e.get("inicio"), datetime)]
    com_horario.sort(key=lambda e: e["inicio"])

    for i in range(len(com_horario)):
        for j in range(i + 1, len(com_horario)):
            ev1 = com_horario[i]
            ev2 = com_horario[j]

            ini1, fim1 = ev1["inicio"], ev1["fim"]
            ini2, fim2 = ev2["inicio"], ev2["fim"]

            # Ha sobreposicao se o maximo dos inicios for menor que o minimo dos fins
            sobreposicao_inicio = max(ini1, ini2)
            sobreposicao_fim = min(fim1, fim2)

            if sobreposicao_inicio < sobreposicao_fim:
                duracao_min = int((sobreposicao_fim - sobreposicao_inicio).total_seconds() // 60)
                conflitos.append({
                    "evento1": ev1["titulo"],
                    "evento2": ev2["titulo"],
                    "inicio_conflito": sobreposicao_inicio,
                    "fim_conflito": sobreposicao_fim,
                    "duracao_minutos": duracao_min,
                    "detalhes": [ev1, ev2],
                })

    return conflitos


def calcular_blocos_livres(
    eventos: List[dict],
    data_ref: Optional[date] = None,
    inicio_dia: str = "08:00",
    fim_dia: str = "18:00",
    duracao_minima: int = 15,
) -> List[dict]:
    """Calcula os espacos livres entre compromissos na janela produtiva do dia."""
    d = data_ref or datetime.now(TZ).date()
    h_ini, m_ini = map(int, inicio_dia.strip().split(":"))
    h_fim, m_fim = map(int, fim_dia.strip().split(":"))

    limite_inicio = datetime(d.year, d.month, d.day, h_ini, m_ini, tzinfo=TZ)
    limite_fim = datetime(d.year, d.month, d.day, h_fim, m_fim, tzinfo=TZ)

    # Extrai intervalos ocupados que tocam este dia
    ocupados: List[Tuple[datetime, datetime]] = []
    for e in eventos:
        if e.get("dia_inteiro"):
            continue
        ini = e.get("inicio")
        fim = e.get("fim")
        if not isinstance(ini, datetime) or not isinstance(fim, datetime):
            continue
        # Limita a janela do expediente
        ini_clip = max(limite_inicio, ini)
        fim_clip = min(limite_fim, fim)
        if ini_clip < fim_clip:
            ocupados.append((ini_clip, fim_clip))

    # Mescla intervalos ocupados sobrepostos
    ocupados.sort(key=lambda x: x[0])
    mesclados: List[Tuple[datetime, datetime]] = []
    for intervalo in ocupados:
        if not mesclados:
            mesclados.append(intervalo)
        else:
            ult_ini, ult_fim = mesclados[-1]
            if intervalo[0] <= ult_fim:
                mesclados[-1] = (ult_ini, max(ult_fim, intervalo[1]))
            else:
                mesclados.append(intervalo)

    # Extrai os blocos livres
    blocos_livres = []
    ponteiro = limite_inicio

    for ocup_ini, ocup_fim in mesclados:
        if ocup_ini > ponteiro:
            minutos = int((ocup_ini - ponteiro).total_seconds() // 60)
            if minutos >= duracao_minima:
                blocos_livres.append({
                    "inicio": ponteiro,
                    "fim": ocup_ini,
                    "duracao_minutos": minutos,
                    "inicio_str": ponteiro.strftime("%H:%M"),
                    "fim_str": ocup_ini.strftime("%H:%M"),
                })
        ponteiro = max(ponteiro, ocup_fim)

    if ponteiro < limite_fim:
        minutos = int((limite_fim - ponteiro).total_seconds() // 60)
        if minutos >= duracao_minima:
            blocos_livres.append({
                "inicio": ponteiro,
                "fim": limite_fim,
                "duracao_minutos": minutos,
                "inicio_str": ponteiro.strftime("%H:%M"),
                "fim_str": limite_fim.strftime("%H:%M"),
            })

    return blocos_livres


def sugerir_timeboxing(
    blocos_livres: List[dict],
    contextos_gtd: Optional[List[str]] = None,
) -> List[dict]:
    """Sugere alocacao de foco para estudo, academia e leitura nos espacos livres do dia."""
    sugestoes = []
    sugestoes_rotativas = [
        {"contexto": "@faculdade", "titulo": "Bloco de Estudo / Revisao", "min_duracao": 45},
        {"contexto": "@academia", "titulo": "Treino / Atividade Fisica", "min_duracao": 50},
        {"contexto": "@leitura", "titulo": "Meta de Leitura Diaria", "min_duracao": 25},
        {"contexto": "@trabalho", "titulo": "Bloco de Foco Profundo", "min_duracao": 30},
    ]

    indice = 0
    for bloco in blocos_livres:
        dur = bloco["duracao_minutos"]
        if dur < 20:
            continue

        candidato = None
        # Procura um tipo que caiba no bloco
        for offset in range(len(sugestoes_rotativas)):
            cand = sugestoes_rotativas[(indice + offset) % len(sugestoes_rotativas)]
            if dur >= cand["min_duracao"]:
                candidato = cand
                indice = (indice + offset + 1) % len(sugestoes_rotativas)
                break

        if not candidato:
            candidato = {"contexto": "@leitura", "titulo": "Leitura rapida ou pausa de foco", "min_duracao": 15}

        sugestoes.append({
            "contexto": candidato["contexto"],
            "titulo": candidato["titulo"],
            "inicio": bloco["inicio"],
            "fim": bloco["fim"],
            "inicio_str": bloco["inicio_str"],
            "fim_str": bloco["fim_str"],
            "duracao_minutos": dur,
        })

    return sugestoes


def analisar_dia(
    eventos: List[dict],
    data_ref: Optional[date] = None,
    inicio_dia: str = "08:00",
    fim_dia: str = "18:00",
    limite_horas_cheio: float = 6.0,
) -> dict:
    """Realiza analise abrangente da agenda do dia com timeboxing e deteccao de dia cheio."""
    d = data_ref or datetime.now(TZ).date()
    conflitos = detectar_conflitos(eventos)
    blocos_livres = calcular_blocos_livres(eventos, data_ref=d, inicio_dia=inicio_dia, fim_dia=fim_dia)
    timeboxing = sugerir_timeboxing(blocos_livres)

    reunioes = [e for e in eventos if e.get("eh_reuniao")]

    # Calcula tempo total ocupado em horas no expediente
    minutos_ocupados = sum(
        e.get("duracao_minutos", 0) for e in eventos
        if not e.get("dia_inteiro") and isinstance(e.get("inicio"), datetime)
    )
    horas_ocupadas = round(minutos_ocupados / 60.0, 1)

    minutos_livres = sum(b.get("duracao_minutos", 0) for b in blocos_livres)
    horas_livres = round(minutos_livres / 60.0, 1)

    # Criterio para dia cheio: compromissos >= limite OU muitos eventos sem folga
    motivos_cheio = []
    if horas_ocupadas >= limite_horas_cheio:
        motivos_cheio.append(f"Mais de {horas_ocupadas}h de compromissos marcados")
    if len(eventos) >= 6:
        motivos_cheio.append(f"Alto volume de eventos ({len(eventos)} no dia)")
    if horas_livres <= 1.0 and len(eventos) > 2:
        motivos_cheio.append("Menos de 1 hora livre no expediente")

    dia_cheio = len(motivos_cheio) > 0
    aviso_dia_cheio = "; ".join(motivos_cheio) if dia_cheio else ""

    return {
        "data": d.isoformat(),
        "total_eventos": len(eventos),
        "total_reunioes": len(reunioes),
        "horas_ocupadas": horas_ocupadas,
        "horas_livres": horas_livres,
        "dia_cheio": dia_cheio,
        "motivo_dia_cheio": aviso_dia_cheio,
        "conflitos": conflitos,
        "blocos_livres": blocos_livres,
        "sugestoes_timeboxing": timeboxing,
        "reunioes": reunioes,
    }


def lembrar_e_abrir_reunioes(
    eventos: List[dict],
    agora: Optional[datetime] = None,
    config_usuario: Optional[dict] = None,
    despachante_notificacao: Optional[Callable] = None,
    abridor_url: Optional[Callable] = None,
    abrir_link_automatico: bool = True,
) -> Dict[str, Any]:
    """Varre reunioes e despacha lembretes antecipados e comando de abertura no horario.

    - Lembrete antecipado: enviado quando faltar <= minutos_antes (padrao: 10 min).
    - No horario: abre link de video no desktop/PWA ou despacha mensagem no canal.
    """
    momento = agora or datetime.now(TZ)
    cfg = config_usuario or {}
    agenda_cfg = cfg.get("agenda") or {}
    minutos_antes = int(agenda_cfg.get("lembrete_minutos_antes", 10))
    canais_aviso = agenda_cfg.get("canais_aviso") or cfg.get("canais_ativos") or ["telegram"]

    lembretes_enviados = []
    aberturas_realizadas = []

    for ev in eventos:
        if not ev.get("eh_reuniao"):
            continue

        inicio = ev.get("inicio")
        if not isinstance(inicio, datetime):
            continue

        uid = ev.get("uid") or f"{ev['titulo']}-{inicio.isoformat()}"
        link = ev.get("link_video") or ""

        # 1. Checagem de lembrete antecipado
        janela_lembrete_inicio = inicio - timedelta(minutes=minutos_antes)
        if janela_lembrete_inicio <= momento < inicio:
            chave_alerta = (uid, "lembrete")
            if chave_alerta not in _ALERTAS_DISPARADOS:
                _ALERTAS_DISPARADOS.add(chave_alerta)
                min_restantes = max(1, int((inicio - momento).total_seconds() // 60))
                titulo_notif = "Lembrete de Reuniao"
                corpo_notif = f"Sua reuniao '{ev['titulo']}' comeca em {min_restantes} minuto(s) ({inicio.strftime('%H:%M')})."
                if link:
                    corpo_notif += f" Link: {link}"

                if despachante_notificacao:
                    despachante_notificacao(
                        evento="lembrete",
                        titulo=titulo_notif,
                        corpo=corpo_notif,
                        canais_especificos=canais_aviso,
                    )
                else:
                    try:
                        from .notificacoes import notificar
                        notificar(
                            evento="lembrete",
                            titulo=titulo_notif,
                            corpo=corpo_notif,
                            canais_especificos=canais_aviso,
                            config_usuario=cfg,
                        )
                    except Exception as e:
                        log.warning("Falha ao despachar lembrete de reuniao: %s", type(e).__name__)

                lembretes_enviados.append({"uid": uid, "titulo": ev["titulo"], "minutos_restantes": min_restantes})

        # 2. Checagem do momento da reuniao (abertura de link)
        # Janela de abertura: entre inicio e inicio + 5 minutos
        if inicio <= momento <= inicio + timedelta(minutes=5):
            chave_abrir = (uid, "abrir")
            if chave_abrir not in _ALERTAS_DISPARADOS:
                _ALERTAS_DISPARADOS.add(chave_abrir)
                aberto = False

                if link and abrir_link_automatico:
                    if abridor_url:
                        try:
                            abridor_url(link)
                            aberto = True
                        except Exception as e:
                            log.warning("Falha no abridor customizado: %s", type(e).__name__)
                    else:
                        try:
                            import webbrowser
                            webbrowser.open(link)
                            aberto = True
                        except Exception as e:
                            log.warning("Falha ao abrir navegador: %s", type(e).__name__)

                # Se nao abriu ou se precisa mandar canal:
                titulo_inicio = "Reuniao Iniciada"
                corpo_inicio = f"A reuniao '{ev['titulo']}' esta comecando agora."
                if link:
                    corpo_inicio += f" Acesse aqui: {link}"

                if despachante_notificacao:
                    despachante_notificacao(
                        evento="lembrete",
                        titulo=titulo_inicio,
                        corpo=corpo_inicio,
                        canais_especificos=canais_aviso,
                    )
                else:
                    try:
                        from .notificacoes import notificar
                        notificar(
                            evento="lembrete",
                            titulo=titulo_inicio,
                            corpo=corpo_inicio,
                            canais_especificos=canais_aviso,
                            config_usuario=cfg,
                        )
                    except Exception as e:
                        log.warning("Falha ao notificar inicio de reuniao: %s", type(e).__name__)

                aberturas_realizadas.append({
                    "uid": uid,
                    "titulo": ev["titulo"],
                    "link": link,
                    "navegador_aberto": aberto,
                })

    return {
        "lembretes_enviados": lembretes_enviados,
        "aberturas_realizadas": aberturas_realizadas,
    }


def _hora_falada(dt: Any) -> str:
    return f"as {dt.hour} horas" if dt.minute == 0 else f"as {dt.hour} e {dt.minute:02d}"


def resumo_falado(eventos: list, prefixo_dia: bool = False) -> str:
    if not eventos:
        return "Voce nao tem compromissos marcados."
    partes = []
    hoje = datetime.now(TZ).date()
    for e in eventos:
        inicio = e["inicio"]
        if e["dia_inteiro"]:
            quando, dia = "", inicio
        else:
            quando, dia = _hora_falada(inicio), inicio.date()
        if prefixo_dia and dia != hoje:
            quando = f"{DIAS_SEMANA[dia.weekday()]} dia {dia.day} {quando}".strip()
        partes.append(f"{quando}, {e['titulo']}".strip(", ").strip())
    if len(partes) == 1:
        return f"Voce tem um compromisso: {partes[0]}."
    return f"Voce tem {len(partes)} compromissos. " + "; ".join(partes) + "."


if __name__ == "__main__":
    print(resumo_falado(eventos_proximos(7), prefixo_dia=True))
