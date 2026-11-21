"""Sugestao da ordem do dia a partir da agenda, da rotina e dos contextos GTD (Issue #43).

A rotina e uma lista de blocos de horario ligados a um contexto, por exemplo
"08:00-12:00 @faculdade; 13:00-18:00 @trabalho; 18:30-19:30 @academia". Ela vem, nesta
ordem de prioridade, do argumento ``rotina``, da chave ``rotina`` do config.json do painel,
da variavel NEXTOR_GTD_ROTINA do .env e, por fim, de ROTINA_PADRAO.

Para cada bloco o planejador desconta os compromissos da agenda que caem dentro dele e
encaixa as proximas acoes do contexto: atrasadas primeiro, depois as de hoje, as com prazo
e as sem prazo. Acoes de @qualquer preenchem os blocos que ainda tem espaco. Tudo e local,
sem rede e sem modelo de linguagem.
"""
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .. import config
from .armazenamento import ArmazenamentoGTD
from .modelos import CONTEXTOS_PERMITIDOS, Item

# Rotina generica: faculdade, trabalho, academia, estudo em casa e leitura todos os dias.
# Os horarios reais do dono ficam no .env (NEXTOR_GTD_ROTINA) ou no painel, nunca no repo.
ROTINA_PADRAO = (
    "08:00-12:00 @faculdade; 13:00-18:00 @trabalho; 18:30-19:30 @academia; "
    "20:00-21:00 @estudo; 21:00-21:30 @leitura; 21:30-22:00 @casa"
)

MAX_BLOCOS_ROTINA = 24
MINUTOS_MINIMOS_LIVRES = 15
ACOES_POR_BLOCO_PADRAO = 3

_PESO_ENERGIA_MANHA = {"alta": 0, "media": 1, "baixa": 2}
_PESO_ENERGIA_NOITE = {"baixa": 0, "media": 1, "alta": 2}


def _hora_para_minutos(texto: str) -> Optional[int]:
    try:
        h_str, m_str = str(texto).strip().split(":", 1)
        h, m = int(h_str), int(m_str)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def _minutos_para_hora(minutos: int) -> str:
    minutos = max(0, min(minutos, 24 * 60 - 1))
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _normalizar_bloco(inicio: Any, fim: Any, contexto: Any) -> Optional[Dict[str, str]]:
    ini_min = _hora_para_minutos(inicio)
    fim_min = _hora_para_minutos(fim)
    if ini_min is None or fim_min is None or fim_min <= ini_min:
        return None
    ctx = str(contexto or "").strip().lower()
    if ctx and not ctx.startswith("@"):
        ctx = f"@{ctx}"
    if ctx not in CONTEXTOS_PERMITIDOS:
        return None
    return {"inicio": _minutos_para_hora(ini_min), "fim": _minutos_para_hora(fim_min), "contexto": ctx}


def parsear_rotina(rotina: Any) -> List[Dict[str, str]]:
    """Converte a rotina em blocos validos, ordenados pelo horario de inicio.

    Aceita texto ("HH:MM-HH:MM @contexto" separados por ponto e virgula, virgula ou quebra
    de linha) ou lista de dicionarios com inicio, fim e contexto. Entradas invalidas, com
    horario impossivel ou contexto desconhecido, sao descartadas.
    """
    blocos: List[Dict[str, str]] = []
    if isinstance(rotina, str):
        trechos = rotina.replace("\n", ";").replace(",", ";").split(";")
        for trecho in trechos:
            partes = trecho.split()
            if len(partes) != 2 or "-" not in partes[0]:
                continue
            inicio, _, fim = partes[0].partition("-")
            bloco = _normalizar_bloco(inicio, fim, partes[1])
            if bloco:
                blocos.append(bloco)
    elif isinstance(rotina, (list, tuple)):
        for entrada in rotina:
            if isinstance(entrada, dict):
                bloco = _normalizar_bloco(entrada.get("inicio"), entrada.get("fim"), entrada.get("contexto"))
                if bloco:
                    blocos.append(bloco)
    blocos.sort(key=lambda b: b["inicio"])
    return blocos[:MAX_BLOCOS_ROTINA]


def rotina_para_texto(blocos: Iterable[Dict[str, str]]) -> str:
    return "; ".join(f"{b['inicio']}-{b['fim']} {b['contexto']}" for b in blocos)


def obter_rotina(rotina: Any = None, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """Resolve a rotina ativa: argumento, config.json, NEXTOR_GTD_ROTINA ou ROTINA_PADRAO."""
    candidatos: List[Any] = [rotina]
    if cfg is None:
        try:
            from .configuracao import carregar_config
            cfg = carregar_config()
        except Exception:
            cfg = {}
    candidatos.append((cfg or {}).get("rotina"))
    candidatos.append(getattr(config, "GTD_ROTINA", ""))
    for candidato in candidatos:
        if candidato:
            blocos = parsear_rotina(candidato)
            if blocos:
                return blocos
    return parsear_rotina(ROTINA_PADRAO)


def _fuso() -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(getattr(config, "FUSO", "") or "America/Sao_Paulo")
    except Exception:
        return None


def _minutos_do_dia(valor: Any, dia: date) -> Optional[int]:
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is not None:
        fuso = _fuso()
        if fuso is not None:
            valor = valor.astimezone(fuso)
    if valor.date() < dia:
        return 0
    if valor.date() > dia:
        return 24 * 60
    return valor.hour * 60 + valor.minute


def _intervalos_eventos(eventos: Iterable[Dict[str, Any]], dia: date) -> List[Dict[str, Any]]:
    """Extrai os compromissos com horario (em minutos do dia). Eventos de dia todo ficam de fora."""
    intervalos = []
    for e in eventos or []:
        if e.get("dia_inteiro"):
            continue
        ini = _minutos_do_dia(e.get("inicio"), dia)
        fim = _minutos_do_dia(e.get("fim"), dia)
        if ini is None:
            ini = _hora_para_minutos(e.get("horario", ""))
        if ini is None:
            continue
        if fim is None or fim <= ini:
            duracao = int(e.get("duracao_minutos") or 30)
            fim = ini + max(duracao, 1)
        intervalos.append({
            "inicio": ini,
            "fim": min(fim, 24 * 60),
            "titulo": str(e.get("titulo") or "Compromisso"),
            "eh_reuniao": bool(e.get("eh_reuniao")),
            "link_video": e.get("link_video"),
        })
    intervalos.sort(key=lambda i: i["inicio"])
    return intervalos


def _minutos_ocupados(ini: int, fim: int, intervalos: List[Dict[str, Any]]) -> int:
    trechos = sorted((max(ini, i["inicio"]), min(fim, i["fim"])) for i in intervalos)
    total, cursor = 0, ini
    for a, b in trechos:
        if b <= a:
            continue
        a = max(a, cursor)
        if b > a:
            total += b - a
            cursor = b
    return total


def _chave_acao(item: Item, hoje_iso: str, manha: bool) -> Tuple[int, str, int, str]:
    if item.prazo and item.prazo < hoje_iso:
        urgencia = 0
    elif item.prazo == hoje_iso:
        urgencia = 1
    elif item.prazo:
        urgencia = 2
    else:
        urgencia = 3
    pesos = _PESO_ENERGIA_MANHA if manha else _PESO_ENERGIA_NOITE
    return (urgencia, item.prazo or "9999-99-99", pesos.get(item.energia, 1), item.criado_em or "")


def _resumo_acao(item: Item, hoje_iso: str) -> Dict[str, Any]:
    return {
        "id": item.id,
        "titulo": item.titulo,
        "contexto": item.contexto,
        "prazo": item.prazo,
        "energia": item.energia,
        "atrasada": bool(item.prazo and item.prazo < hoje_iso),
        "para_hoje": item.prazo == hoje_iso,
    }


def _buscar_eventos_hoje() -> List[Dict[str, Any]]:
    try:
        from .. import agenda
        return agenda.eventos_hoje() or []
    except Exception:
        return []


def sugerir_ordem_do_dia(
    db: Optional[ArmazenamentoGTD] = None,
    eventos: Optional[List[Dict[str, Any]]] = None,
    rotina: Any = None,
    agora: Optional[datetime] = None,
    acoes_por_bloco: int = ACOES_POR_BLOCO_PADRAO,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Monta a linha do tempo sugerida do dia: compromissos da agenda e blocos de contexto.

    ``eventos`` segue o formato de nextor.agenda (inicio e fim como datetime). Se for None,
    os eventos de hoje sao lidos da agenda configurada; falhas viram lista vazia.
    """
    banco = db if db is not None else ArmazenamentoGTD()
    agora = agora or datetime.now()
    dia = agora.date()
    hoje_iso = dia.isoformat()
    agora_min = agora.hour * 60 + agora.minute
    acoes_por_bloco = max(1, int(acoes_por_bloco or ACOES_POR_BLOCO_PADRAO))

    blocos_rotina = obter_rotina(rotina, cfg=cfg)
    if eventos is None:
        eventos = _buscar_eventos_hoje()
    intervalos = _intervalos_eventos(eventos, dia)

    proximas = banco.listar_itens(estado="proxima")
    por_contexto: Dict[str, List[Item]] = {}
    for item in proximas:
        por_contexto.setdefault(item.contexto, []).append(item)

    leitura_faltam = None
    try:
        meta = int(getattr(config, "LEITURA_META_DIARIA", 20))
        leitura_faltam = max(0, meta - banco.paginas_lidas_na_data(hoje_iso))
    except Exception:
        leitura_faltam = None

    linha: List[Dict[str, Any]] = []
    contextos_com_bloco = set()
    blocos_contexto: List[Dict[str, Any]] = []
    for b in blocos_rotina:
        ini = _hora_para_minutos(b["inicio"]) or 0
        fim = _hora_para_minutos(b["fim"]) or ini
        ocupado = _minutos_ocupados(ini, fim, intervalos)
        livres = (fim - ini) - ocupado
        manha = ini < 14 * 60
        ctx = b["contexto"]
        contextos_com_bloco.add(ctx)
        entrada: Dict[str, Any] = {
            "tipo": "contexto",
            "inicio": b["inicio"],
            "fim": b["fim"],
            "contexto": ctx,
            "titulo": ctx,
            "minutos_livres": livres,
            "ocupado_pela_agenda": livres < MINUTOS_MINIMOS_LIVRES,
            "passado": fim <= agora_min,
            "acoes": [],
        }
        if not entrada["ocupado_pela_agenda"]:
            candidatas = sorted(por_contexto.get(ctx, []), key=lambda i: _chave_acao(i, hoje_iso, manha))
            entrada["acoes"] = [_resumo_acao(i, hoje_iso) for i in candidatas[:acoes_por_bloco]]
            for i in candidatas[:acoes_por_bloco]:
                por_contexto[ctx].remove(i)
        if ctx == "@leitura" and leitura_faltam is not None:
            entrada["leitura_faltam_paginas"] = leitura_faltam
        blocos_contexto.append(entrada)
        linha.append(entrada)

    # Acoes de @qualquer completam os blocos livres que ainda tem espaco, na ordem do dia.
    soltas = sorted(por_contexto.get("@qualquer", []), key=lambda i: _chave_acao(i, hoje_iso, True))
    for entrada in blocos_contexto:
        if not soltas:
            break
        if entrada["ocupado_pela_agenda"] or entrada["passado"] or entrada["contexto"] == "@qualquer":
            continue
        while soltas and len(entrada["acoes"]) < acoes_por_bloco:
            entrada["acoes"].append(_resumo_acao(soltas.pop(0), hoje_iso))
    por_contexto["@qualquer"] = soltas

    for i in intervalos:
        linha.append({
            "tipo": "evento",
            "inicio": _minutos_para_hora(i["inicio"]),
            "fim": _minutos_para_hora(i["fim"]),
            "titulo": i["titulo"],
            "eh_reuniao": i["eh_reuniao"],
            "link_video": i["link_video"],
            "passado": i["fim"] <= agora_min,
        })

    # Eventos antes de blocos no mesmo horario: o compromisso fixo vem primeiro.
    linha.sort(key=lambda e: (e["inicio"], 0 if e["tipo"] == "evento" else 1))

    # Sobras: tudo de contextos sem bloco na rotina e, dos demais, so o que vence hoje ou atrasou.
    sem_bloco: List[Dict[str, Any]] = []
    for ctx, itens in por_contexto.items():
        for item in sorted(itens, key=lambda i: _chave_acao(i, hoje_iso, True)):
            urgente = bool(item.prazo and item.prazo <= hoje_iso)
            if urgente or ctx not in contextos_com_bloco:
                sem_bloco.append(_resumo_acao(item, hoje_iso))

    proximo_passo = None
    for entrada in linha:
        if entrada["passado"]:
            continue
        if entrada["tipo"] == "evento":
            proximo_passo = {"tipo": "evento", "inicio": entrada["inicio"], "titulo": entrada["titulo"]}
            break
        if entrada["acoes"]:
            primeira = entrada["acoes"][0]
            proximo_passo = {
                "tipo": "acao",
                "inicio": entrada["inicio"],
                "contexto": entrada["contexto"],
                "titulo": primeira["titulo"],
                "id": primeira["id"],
            }
            break

    return {
        "data": hoje_iso,
        "rotina": blocos_rotina,
        "linha_do_tempo": linha,
        "sem_bloco": sem_bloco,
        "proximo_passo": proximo_passo,
        "resumo": _montar_resumo(linha, sem_bloco, proximo_passo),
    }


def _montar_resumo(linha: List[Dict[str, Any]], sem_bloco: List[Dict[str, Any]],
                   proximo_passo: Optional[Dict[str, Any]]) -> str:
    partes = []
    futuros = [e for e in linha if not e["passado"]]
    if not futuros:
        partes.append("A rotina de hoje ja terminou.")
    else:
        trechos = []
        for e in futuros[:6]:
            if e["tipo"] == "evento":
                trechos.append(f"{e['inicio']} {e['titulo']}")
            elif e["ocupado_pela_agenda"]:
                trechos.append(f"{e['inicio']} {e['contexto']} (ocupado pela agenda)")
            elif e["acoes"]:
                trechos.append(f"{e['inicio']} {e['contexto']} ({len(e['acoes'])} acao(oes))")
            else:
                trechos.append(f"{e['inicio']} {e['contexto']}")
        partes.append("Ordem sugerida: " + ", ".join(trechos) + ".")
    if proximo_passo:
        partes.append(f"Proximo passo: {proximo_passo['titulo']} as {proximo_passo['inicio']}.")
    if sem_bloco:
        partes.append(f"{len(sem_bloco)} acao(oes) urgentes ou sem bloco na rotina.")
    return " ".join(partes)
