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
        },
        "integracoes": {
            "notion": True,
            "github": True,
            "agenda": True,
            "artigos": True,
        },
        "agentes": {
            "organizar_inbox": True,
            "sugerir_ordem_dia": True,
            "revisao_semanal": True,
        },
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
    status_integracoes = {
        "notion": {
            "ativo": cfg.get("integracoes", {}).get("notion", True),
            "configurado": notion_cli.disponivel(),
            "descricao": "Sincronizacao bidirecional com bancos de dados do Notion",
        },
        "github": {
            "ativo": cfg.get("integracoes", {}).get("github", True),
            "configurado": bool(os.getenv("GITHUB_TOKEN", "") or getattr(config, "GITHUB_TOKEN", "")),
            "descricao": "Importacao de issues e PRs atribuidos como tarefas em @trabalho",
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
        "metodos": listar_metodos(),
        "canais": roteador_instancia.listar_status_canais(),
        "integracoes": status_integracoes,
        "agentes": agentes_catalogo,
        "mcp_ferramentas": mcp_ferramentas,
    }
