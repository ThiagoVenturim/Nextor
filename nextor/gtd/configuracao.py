"""Gestao da configuracao do framework de produtividade pessoal (Issue #47).

Persiste preferencias do usuario em arquivo JSON local (~/.nextor/config.json).
Centraliza metodo ativo, canais de notificacao, temas, paletas e integracoes.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config

log = logging.getLogger("nextor.gtd.configuracao")

TEMAS = ("escuro", "claro")
PALETAS = ("azul", "esmeralda", "violeta", "ambar")
CANAIS_NOTIFICACAO = ("telegram", "discord", "whatsapp", "webpush", "voz")
INTEGRACOES = ("notion", "github", "agenda", "artigos", "nextor")
_RE_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_RE_NOME_FERRAMENTA = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Skills agrupam as ferramentas MCP por area. Desligar uma skill tira do servidor MCP
# todas as ferramentas dela e desativa os agentes que dependem dela.
SKILLS_CATALOGO: List[Dict[str, str]] = [
    {"id": "gtd", "nome": "Tarefas (GTD)", "descricao": "Capturar, processar e sincronizar tarefas, trocar metodo e registrar leitura"},
    {"id": "agenda", "nome": "Agenda", "descricao": "Consultar compromissos, proxima reuniao e blocos livres do dia"},
    {"id": "pomodoro", "nome": "Pomodoro", "descricao": "Iniciar, parar e consultar sessoes de foco"},
    {"id": "notas", "nome": "Anotacoes", "descricao": "Salvar e ler anotacoes rapidas"},
    {"id": "notificacoes", "nome": "Notificacoes", "descricao": "Disparar avisos de teste pelos canais ativos"},
    {"id": "noticias", "nome": "Noticias", "descricao": "Resumir noticias recentes de um assunto"},
    {"id": "voz", "nome": "Voz no Nest", "descricao": "Falar um texto em voz alta no alto-falante da casa"},
    {"id": "coach", "nome": "Coach de estudos", "descricao": "Acao de estudo do dia, progresso, XP e trilhas"},
    {"id": "nexread", "nome": "NexRead", "descricao": "Traduzir, marcar e estudar artigos abertos pela pessoa"},
    {"id": "nexvoice", "nome": "NexVoice", "descricao": "Traducao de audio ao vivo com consentimento e legendas"},
]
SKILLS_IDS = tuple(s["id"] for s in SKILLS_CATALOGO)

# Agentes que a pessoa pode anexar. Cada um so roda se as skills que ele usa estao ligadas.
AGENTES_CATALOGO: List[Dict[str, Any]] = [
    {
        "id": "organizar_inbox",
        "nome": "Organizador de Inbox",
        "descricao": "Sugere contexto, prazo e nivel de energia para itens da caixa de entrada",
        "skills": ["gtd"],
    },
    {
        "id": "sugerir_ordem_dia",
        "nome": "Planejador do Dia",
        "descricao": "Calcula a melhor sequencia de tarefas intercalando estudos, trabalho e pausas",
        "skills": ["gtd", "agenda"],
    },
    {
        "id": "revisao_semanal",
        "nome": "Condutor de Revisao Semanal",
        "descricao": "Identifica gargalos, projetos parados e cobra definicao de proximas acoes",
        "skills": ["gtd"],
    },
]
AGENTES_IDS = tuple(a["id"] for a in AGENTES_CATALOGO)

# Direcoes de sincronizacao aceitas por fonte externa (Issue #42).
DIRECOES_SINCRONIZACAO = ("desligado", "importar", "exportar", "bidirecional")
POLITICAS_CONFLITO = ("remoto", "local")
FONTES_SINCRONIZACAO = ("notion", "github", "nextor")


def obter_sincronizacao_padrao() -> Dict[str, Any]:
    # GitHub comeca so importando: escrever no GitHub (fechar/abrir issues) exige que o
    # usuario escolha "bidirecional" ou "exportar" no painel, o que vale como confirmacao.
    return {
        "notion": "bidirecional",
        "github": "importar",
        "nextor": "bidirecional",
        "conflito": "remoto",
        "github_repos": [],
    }


def normalizar_sincronizacao(dados: Any, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Mescla e valida a secao 'sincronizacao', descartando valores invalidos."""
    resultado = dict(base) if isinstance(base, dict) else obter_sincronizacao_padrao()
    for k, v in obter_sincronizacao_padrao().items():
        resultado.setdefault(k, v)
    if not isinstance(dados, dict):
        return resultado
    for fonte in FONTES_SINCRONIZACAO:
        if fonte in dados:
            d = str(dados[fonte]).strip().lower()
            if d in DIRECOES_SINCRONIZACAO:
                resultado[fonte] = d
    if "conflito" in dados:
        p = str(dados["conflito"]).strip().lower()
        if p in POLITICAS_CONFLITO:
            resultado["conflito"] = p
    if "github_repos" in dados and isinstance(dados["github_repos"], list):
        repos = []
        for r in dados["github_repos"]:
            r = str(r).strip()
            # Aceita apenas "repo" ou "dono/repo" com caracteres validos do GitHub.
            if r and len(r) <= 140 and all(ch.isalnum() or ch in "-_./" for ch in r) and r.count("/") <= 1 and ".." not in r:
                repos.append(r)
        resultado["github_repos"] = repos[:20]
    return resultado


def obter_caminho_config() -> Path:
    env_caminho = os.getenv("NEXTOR_GTD_CONFIG_JSON", "")
    if env_caminho:
        return Path(env_caminho).resolve()
    pasta = Path(getattr(config, "GTD_DIR", Path.home() / ".nextor")).resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / "config.json"


def obter_config_padrao() -> Dict[str, Any]:
    return {
        "metodo_ativo": "gtd",
        "tema": "escuro",
        "paleta": "azul",
        "horario_silencio": {
            "ativo": True,
            "inicio": "22:00",
            "fim": "07:00",
        },
        "canais_ativos": ["telegram"],
        "eventos_notificacao": {
            "lembrete": ["telegram"],
            "agenda_do_dia": ["telegram"],
            "tarefa_atrasada": ["telegram"],
            "pr_para_revisar": ["telegram"],
            "pomodoro_fim": ["voz", "telegram"],
            "reuniao_lembrete": ["telegram"],
            "reuniao_inicio": ["telegram"],
        },
        "agenda": {
            "lembrete_minutos_antes": 10,
            "abrir_link_automatico": True,
            "canais_aviso": ["telegram"],
            "expediente_inicio": "08:00",
            "expediente_fim": "18:00",
            "limite_horas_dia_cheio": 6.0,
        },
        "integracoes": {
            "notion": True,
            "github": True,
            "agenda": True,
            "artigos": True,
            "nextor": True,
        },
        "sincronizacao": obter_sincronizacao_padrao(),
        "agentes": {
            "organizar_inbox": True,
            "sugerir_ordem_dia": True,
            "revisao_semanal": True,
        },
        # Skills e ferramentas MCP: ausente conta como ligado, para ferramentas novas
        # aparecerem sem migracao. So o que a pessoa desliga fica gravado como False.
        "skills": {s: True for s in SKILLS_IDS},
        "mcp_ferramentas": {},
        "rotina": [],
        "kanban_wip_limite": 3,
        "pomodoro_duracao_min": 25,
        "wizard_concluido": False,
    }


def _hora_valida(valor: Any, padrao: str) -> str:
    texto = str(valor if valor is not None else "").strip()
    return texto if _RE_HORA.match(texto) else padrao


def _filtrar_canais(canais: List[Any]) -> List[str]:
    """Mantem so canais conhecidos, sem repetir e na ordem recebida."""
    resultado: List[str] = []
    for c in canais:
        slug = str(c).strip().lower()
        if slug in CANAIS_NOTIFICACAO and slug not in resultado:
            resultado.append(slug)
    return resultado


def _eventos_conhecidos() -> List[str]:
    from ..notificacoes.roteador_notificacoes import EVENTOS_PERMITIDOS
    eventos = list(obter_config_padrao()["eventos_notificacao"].keys())
    return eventos + [e for e in EVENTOS_PERMITIDOS if e not in eventos]


def _nomes_ferramentas_mcp() -> set:
    try:
        from ..mcp_server import FERRAMENTAS
    except Exception as e:  # pragma: no cover - mcp_server sempre importa com o fallback
        log.warning("Catalogo MCP indisponivel: %s", type(e).__name__)
        return set()
    return set(FERRAMENTAS)


def skill_ativa(cfg: Dict[str, Any], skill_id: str) -> bool:
    return bool((cfg.get("skills") or {}).get(skill_id, True))


def ferramenta_mcp_ativa(cfg: Dict[str, Any], nome: str, skill_id: str) -> bool:
    """Uma ferramenta MCP so e exposta se ela e a skill dela estiverem ligadas."""
    return skill_ativa(cfg, skill_id) and bool((cfg.get("mcp_ferramentas") or {}).get(nome, True))


def agente_ativo(cfg: Dict[str, Any], agente_id: str) -> bool:
    """O agente roda se foi anexado e todas as skills que ele usa estao ligadas."""
    if not (cfg.get("agentes") or {}).get(agente_id, True):
        return False
    for agente in AGENTES_CATALOGO:
        if agente["id"] == agente_id:
            return all(skill_ativa(cfg, s) for s in agente["skills"])
    return False


def carregar_config(caminho_customizado: Optional[Path] = None) -> Dict[str, Any]:
    """Le o arquivo de configuracao persistido ou devolve a configuracao padrao."""
    caminho = caminho_customizado or obter_caminho_config()
    padrao = obter_config_padrao()

    if not caminho.exists():
        return padrao

    try:
        conteudo = caminho.read_text(encoding="utf-8")
        dados = json.loads(conteudo)
        # Mescla com os padroes para garantir chaves ausentes
        for k, v in padrao.items():
            if k not in dados:
                dados[k] = v
        for secao in ("integracoes", "agentes", "skills", "eventos_notificacao"):
            if not isinstance(dados.get(secao), dict):
                dados[secao] = padrao[secao]
            for k, v in padrao[secao].items():
                dados[secao].setdefault(k, v)
        if not isinstance(dados.get("mcp_ferramentas"), dict):
            dados["mcp_ferramentas"] = {}
        dados["sincronizacao"] = normalizar_sincronizacao(None, dados.get("sincronizacao"))
        return dados
    except Exception as e:
        log.warning("Falha ao ler config.json, usando padrao: %s", type(e).__name__)
        return padrao


def salvar_config(novos_dados: Dict[str, Any], caminho_customizado: Optional[Path] = None) -> Dict[str, Any]:
    """Valida e persiste as novas configuracoes do usuario."""
    atual = carregar_config(caminho_customizado=caminho_customizado)

    if "metodo_ativo" in novos_dados:
        from .metodos.registro import REGISTRO_METODOS
        m = str(novos_dados["metodo_ativo"]).strip().lower()
        if m in REGISTRO_METODOS:
            atual["metodo_ativo"] = m

    if "tema" in novos_dados:
        t = str(novos_dados["tema"]).strip().lower()
        if t in TEMAS:
            atual["tema"] = t

    if "paleta" in novos_dados:
        p = str(novos_dados["paleta"]).strip().lower()
        if p in PALETAS:
            atual["paleta"] = p

    if "horario_silencio" in novos_dados and isinstance(novos_dados["horario_silencio"], dict):
        hs = novos_dados["horario_silencio"]
        sil_atual = atual.get("horario_silencio") or {}
        atual["horario_silencio"] = {
            "ativo": bool(hs.get("ativo", sil_atual.get("ativo", True))),
            "inicio": _hora_valida(hs.get("inicio"), sil_atual.get("inicio", "22:00")),
            "fim": _hora_valida(hs.get("fim"), sil_atual.get("fim", "07:00")),
        }

    if "canais_ativos" in novos_dados and isinstance(novos_dados["canais_ativos"], list):
        atual["canais_ativos"] = _filtrar_canais(novos_dados["canais_ativos"])

    if "eventos_notificacao" in novos_dados and isinstance(novos_dados["eventos_notificacao"], dict):
        eventos_validos = _eventos_conhecidos()
        for evento, canais in novos_dados["eventos_notificacao"].items():
            evento = str(evento).strip().lower()
            if evento in eventos_validos and isinstance(canais, list):
                atual["eventos_notificacao"][evento] = _filtrar_canais(canais)

    if "integracoes" in novos_dados and isinstance(novos_dados["integracoes"], dict):
        atual["integracoes"].update({k: bool(v) for k, v in novos_dados["integracoes"].items() if k in INTEGRACOES})

    if "sincronizacao" in novos_dados:
        atual["sincronizacao"] = normalizar_sincronizacao(novos_dados["sincronizacao"], atual.get("sincronizacao"))

    if "agentes" in novos_dados and isinstance(novos_dados["agentes"], dict):
        atual["agentes"].update({k: bool(v) for k, v in novos_dados["agentes"].items() if k in AGENTES_IDS})

    if "skills" in novos_dados and isinstance(novos_dados["skills"], dict):
        atual["skills"].update({k: bool(v) for k, v in novos_dados["skills"].items() if k in SKILLS_IDS})

    if "mcp_ferramentas" in novos_dados and isinstance(novos_dados["mcp_ferramentas"], dict):
        conhecidas = _nomes_ferramentas_mcp()
        for nome, ligado in novos_dados["mcp_ferramentas"].items():
            nome = str(nome).strip()
            if _RE_NOME_FERRAMENTA.match(nome) and nome in conhecidas:
                atual["mcp_ferramentas"][nome] = bool(ligado)

    if "kanban_wip_limite" in novos_dados:
        try:
            atual["kanban_wip_limite"] = max(1, int(novos_dados["kanban_wip_limite"]))
        except (ValueError, TypeError):
            pass

    if "pomodoro_duracao_min" in novos_dados:
        try:
            atual["pomodoro_duracao_min"] = max(1, int(novos_dados["pomodoro_duracao_min"]))
        except (ValueError, TypeError):
            pass

    if "agenda" in novos_dados and isinstance(novos_dados["agenda"], dict):
        ag = novos_dados["agenda"]
        ag_atual = atual.get("agenda") or {}
        try:
            lembrete_min = max(1, int(ag.get("lembrete_minutos_antes", ag_atual.get("lembrete_minutos_antes", 10))))
        except (ValueError, TypeError):
            lembrete_min = 10

        try:
            limite_cheio = max(1.0, float(ag.get("limite_horas_dia_cheio", ag_atual.get("limite_horas_dia_cheio", 6.0))))
        except (ValueError, TypeError):
            limite_cheio = 6.0

        canais_aviso = ag.get("canais_aviso", ag_atual.get("canais_aviso", ["telegram"]))
        if isinstance(canais_aviso, list):
            canais_aviso = _filtrar_canais(canais_aviso)
        else:
            canais_aviso = ["telegram"]

        atual["agenda"] = {
            "lembrete_minutos_antes": lembrete_min,
            "abrir_link_automatico": bool(ag.get("abrir_link_automatico", ag_atual.get("abrir_link_automatico", True))),
            "canais_aviso": canais_aviso,
            "expediente_inicio": str(ag.get("expediente_inicio", ag_atual.get("expediente_inicio", "08:00"))).strip(),
            "expediente_fim": str(ag.get("expediente_fim", ag_atual.get("expediente_fim", "18:00"))).strip(),
            "limite_horas_dia_cheio": limite_cheio,
        }

    if "rotina" in novos_dados:
        # Rotina do dia (Issue #43): texto ou lista; so blocos validos sao guardados.
        # Vazio volta a usar NEXTOR_GTD_ROTINA ou a rotina generica.
        from .ordem_dia import parsear_rotina
        bruto = novos_dados["rotina"]
        atual["rotina"] = parsear_rotina(bruto) if bruto else []

    if "wizard_concluido" in novos_dados:
        atual["wizard_concluido"] = bool(novos_dados["wizard_concluido"])

    caminho = caminho_customizado or obter_caminho_config()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(atual, indent=2, ensure_ascii=False), encoding="utf-8")
    return atual


def obter_config_completa(caminho_customizado: Optional[Path] = None) -> Dict[str, Any]:
    """Retorna configuracao atual acompanhada do catalogo de metodos, canais e integracoes."""
    cfg = carregar_config(caminho_customizado=caminho_customizado)
    from .metodos.registro import listar_metodos
    from ..notificacoes.roteador_notificacoes import roteador_instancia

    # Status de integracoes no .env
    from .notion import ClienteNotion
    notion_cli = ClienteNotion()
    sinc = cfg.get("sincronizacao") or obter_sincronizacao_padrao()
    status_integracoes = {
        "notion": {
            "ativo": cfg.get("integracoes", {}).get("notion", True),
            "configurado": notion_cli.disponivel(),
            "direcao": sinc.get("notion", "bidirecional"),
            "descricao": "Tarefas, projetos e leituras sincronizados com bases do Notion",
        },
        "github": {
            "ativo": cfg.get("integracoes", {}).get("github", True),
            "configurado": bool(os.getenv("GITHUB_TOKEN", "") or getattr(config, "GITHUB_TOKEN", "")),
            "direcao": sinc.get("github", "importar"),
            "descricao": "Issues e PRs atribuidos viram tarefas em @trabalho; concluir fecha a issue",
        },
        "nextor": {
            "ativo": cfg.get("integracoes", {}).get("nextor", True),
            "configurado": True,
            "direcao": sinc.get("nextor", "bidirecional"),
            "descricao": "Anotacoes do Nextor (voz, Telegram) viram tarefas; concluir marca a anotacao",
        },
        "agenda": {
            "ativo": cfg.get("integracoes", {}).get("agenda", True),
            "configurado": bool(getattr(config, "AGENDA_ICAL", "")),
            "descricao": "Compromissos e reunioes sincronizados via iCal da Google Agenda",
        },
        "artigos": {
            "ativo": cfg.get("integracoes", {}).get("artigos", True),
            "configurado": True,
            "descricao": "Busca e inclusao de artigos cientificos (OpenAlex e arXiv) na fila de leitura",
        },
    }

    # Ferramentas MCP: o catalogo vem do proprio nextor/mcp_server.py, entao nao fica defasado.
    from ..mcp_server import listar_ferramentas
    flags_mcp = cfg.get("mcp_ferramentas") or {}
    mcp_ferramentas = [
        {
            **f,
            "ativo": bool(flags_mcp.get(f["nome"], True)),
            "exposta": ferramenta_mcp_ativa(cfg, f["nome"], f["skill"]),
        }
        for f in listar_ferramentas()
    ]

    skills_catalogo = [
        {
            **s,
            "ativo": skill_ativa(cfg, s["id"]),
            "ferramentas": [f["nome"] for f in mcp_ferramentas if f["skill"] == s["id"]],
        }
        for s in SKILLS_CATALOGO
    ]

    agentes_catalogo = [
        {
            **a,
            "skills": list(a["skills"]),
            "ativo": bool((cfg.get("agentes") or {}).get(a["id"], True)),
            "efetivo": agente_ativo(cfg, a["id"]),
        }
        for a in AGENTES_CATALOGO
    ]

    return {
        "config": cfg,
        "direcoes_sincronizacao": list(DIRECOES_SINCRONIZACAO),
        "metodos": listar_metodos(),
        "canais": roteador_instancia.listar_status_canais(),
        "eventos": _eventos_conhecidos(),
        "temas": list(TEMAS),
        "paletas": list(PALETAS),
        "integracoes": status_integracoes,
        "agentes": agentes_catalogo,
        "skills": skills_catalogo,
        "mcp_ferramentas": mcp_ferramentas,
    }
