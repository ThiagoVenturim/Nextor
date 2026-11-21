"""Gestao da configuracao do framework de produtividade pessoal (Issue #47).

Persiste preferencias do usuario em arquivo JSON local (~/.nextor/config.json).
Centraliza metodo ativo, canais de notificacao, temas, paletas e integracoes.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .. import config

log = logging.getLogger("nextor.gtd.configuracao")

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
        "rotina": [],
        "kanban_wip_limite": 3,
        "pomodoro_duracao_min": 25,
        "wizard_concluido": False,
    }


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
        if isinstance(dados.get("integracoes"), dict):
            for k, v in padrao["integracoes"].items():
                dados["integracoes"].setdefault(k, v)
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
        if t in ("escuro", "claro"):
            atual["tema"] = t

    if "paleta" in novos_dados:
        p = str(novos_dados["paleta"]).strip().lower()
        if p in ("azul", "esmeralda", "violeta", "ambar"):
            atual["paleta"] = p

    if "horario_silencio" in novos_dados and isinstance(novos_dados["horario_silencio"], dict):
        hs = novos_dados["horario_silencio"]
        atual["horario_silencio"] = {
            "ativo": bool(hs.get("ativo", True)),
            "inicio": str(hs.get("inicio", "22:00")).strip(),
            "fim": str(hs.get("fim", "07:00")).strip(),
        }

    if "canais_ativos" in novos_dados and isinstance(novos_dados["canais_ativos"], list):
        atual["canais_ativos"] = [str(c).strip().lower() for c in novos_dados["canais_ativos"]]

    if "eventos_notificacao" in novos_dados and isinstance(novos_dados["eventos_notificacao"], dict):
        atual["eventos_notificacao"].update(novos_dados["eventos_notificacao"])

    if "integracoes" in novos_dados and isinstance(novos_dados["integracoes"], dict):
        atual["integracoes"].update({k: bool(v) for k, v in novos_dados["integracoes"].items()})

    if "sincronizacao" in novos_dados:
        atual["sincronizacao"] = normalizar_sincronizacao(novos_dados["sincronizacao"], atual.get("sincronizacao"))

    if "agentes" in novos_dados and isinstance(novos_dados["agentes"], dict):
        atual["agentes"].update({k: bool(v) for k, v in novos_dados["agentes"].items()})

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
            canais_aviso = [str(c).strip().lower() for c in canais_aviso]
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

    # Ferramentas MCP disponiveis
    mcp_ferramentas = [
        {"nome": "gtd_capturar", "descricao": "Captura rapida para a caixa de entrada"},
        {"nome": "gtd_dia", "descricao": "Consulta a agenda e proximas acoes do dia"},
        {"nome": "gtd_trocar_metodo", "descricao": "Troca o metodo de organizacao ativo"},
        {"nome": "pomodoro_iniciar", "descricao": "Inicia uma sessao de foco pomodoro"},
        {"nome": "pomodoro_parar", "descricao": "Interrompe a sessao pomodoro ativa"},
        {"nome": "leitura_progresso", "descricao": "Registra paginas lidas na meta diaria"},
        {"nome": "notificacao_teste", "descricao": "Dispara notificacao de teste pelos canais ativos"},
        {"nome": "agenda_dia", "descricao": "Consulta a agenda do dia com reunioes e blocos livres"},
        {"nome": "proxima_reuniao", "descricao": "Consulta a proxima reuniao agendada e link de video"},
        {"nome": "blocos_livres", "descricao": "Calcula os blocos de horario livre e sugere timeboxing"},
        {"nome": "gtd_sincronizar", "descricao": "Sincroniza tarefas com Notion, GitHub e anotacoes do Nextor"},
    ]

    # Agentes especializados disponiveis
    agentes_catalogo = [
        {
            "id": "organizar_inbox",
            "nome": "Organizador de Inbox",
            "descricao": "Sugere contexto, prazo e nivel de energia para itens da caixa de entrada",
            "ativo": cfg.get("agentes", {}).get("organizar_inbox", True),
        },
        {
            "id": "sugerir_ordem_dia",
            "nome": "Planejador do Dia",
            "descricao": "Calcula a melhor sequencia de tarefas intercalando estudos, trabalho e pausas",
            "ativo": cfg.get("agentes", {}).get("sugerir_ordem_dia", True),
        },
        {
            "id": "revisao_semanal",
            "nome": "Condutor de Revisao Semanal",
            "descricao": "Identifica gargalos, projetos parados e cobra definicao de proximas acoes",
            "ativo": cfg.get("agentes", {}).get("revisao_semanal", True),
        },
    ]

    return {
        "config": cfg,
        "direcoes_sincronizacao": list(DIRECOES_SINCRONIZACAO),
        "metodos": listar_metodos(),
        "canais": roteador_instancia.listar_status_canais(),
        "integracoes": status_integracoes,
        "agentes": agentes_catalogo,
        "mcp_ferramentas": mcp_ferramentas,
    }
