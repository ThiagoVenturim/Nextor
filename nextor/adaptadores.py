"""Gerenciamento unificado de adaptadores de assistentes (Siri, Alexa, Google, Telegram, MCP).

Controla tokens revogaveis por hash sha256 e comparacao hmac.compare_digest em tempo constante,
rate limiting por janela deslizante, despacho unificado sem efeito colateral de audio e
registro seguro de requisicoes com sanitizacao de log.
"""
from datetime import datetime
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("nextor.adaptadores")

ARQUIVO = config.RAIZ / "adaptadores.json"
ARQUIVO_LOG = config.RAIZ / "assistentes.log"

ADAPTADORES_CONHECIDOS: dict[str, dict[str, str]] = {
    "siri": {
        "nome": "Siri (Atalhos do iPhone)",
        "env_token": "SIRI_ADAPTADOR_TOKEN",
    },
    "alexa": {
        "nome": "Skill Alexa",
        "env_token": "ALEXA_ADAPTADOR_TOKEN",
    },
    "google": {
        "nome": "Google Assistant (Home Assistant)",
        "env_token": "GOOGLE_ADAPTADOR_TOKEN",
    },
    "telegram": {
        "nome": "Bot Telegram",
        "env_token": "TELEGRAM_ADAPTADOR_TOKEN",
    },
    "mcp": {
        "nome": "Cliente MCP (Claude, ChatGPT e outros)",
        "env_token": "MCP_ADAPTADOR_TOKEN",
    },
}

_TRAVA = threading.Lock()
_HISTORICO_REQUISICOES: dict[str, list[float]] = {}
_TOKENS_SESSAO: dict[str, str] = {}


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gerar_token() -> str:
    return f"nxt_{secrets.token_urlsafe(24)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _comparar_seguro(a: str, b: str) -> bool:
    """Compara duas strings em tempo constante usando hmac.compare_digest."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def comparar_tokens(recebido: str | None, esperado: str | None) -> bool:
    """Compara dois tokens em tempo constante (nunca usa operador de igualdade)."""
    rec = (recebido or "").strip()
    esp = (esperado or "").strip()
    if not rec or not esp:
        return False
    return _comparar_seguro(_hash_token(rec), _hash_token(esp))


def _prefixo_token(token: str) -> str:
    t = token.strip()
    if len(t) <= 8:
        return t[:4] + "..." if len(t) >= 4 else t + "..."
    return t[:8] + "..."


def carregar() -> list[dict[str, Any]]:
    with _TRAVA:
        if not ARQUIVO.exists():
            return []
        try:
            return json.loads(ARQUIVO.read_text(encoding="utf-8"))
        except Exception:
            return []


def salvar(lista: list[dict[str, Any]]) -> None:
    with _TRAVA:
        ARQUIVO.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def listar(apenas_ativos: bool = False, mascarar: bool = True) -> list[dict[str, Any]]:
    todos = carregar()
    resultado = []
    for item in todos:
        if apenas_ativos and not item.get("ativo", True):
            continue
        copia = dict(item)
        if mascarar:
            # Nunca expor o hash completo na listagem padrao
            copia.pop("token_hash", None)
        resultado.append(copia)
    return resultado


def cadastrar(
    id_adaptador: str,
    nome: str,
    token: str | None = None,
    limite_por_minuto: int = 60,
) -> dict[str, Any]:
    id_limpo = id_adaptador.strip().lower()
    if not id_limpo:
        raise ValueError("id do adaptador nao pode ser vazio")

    lista = carregar()
    for item in lista:
        if _comparar_seguro(str(item.get("id", "")), id_limpo):
            raise ValueError(f"adaptador '{id_limpo}' ja existe")

    token_puro = token.strip() if token else _gerar_token()
    token_hash = _hash_token(token_puro)
    prefixo = _prefixo_token(token_puro)

    salvo = {
        "id": id_limpo,
        "nome": nome.strip() or id_limpo,
        "prefixo": prefixo,
        "token_hash": token_hash,
        "limite_por_minuto": max(1, int(limite_por_minuto)),
        "ativo": True,
        "criado_em": _agora_iso(),
        "ultimo_uso": None,
        "total_requisicoes": 0,
    }
    lista.append(salvo)
    salvar(lista)

    with _TRAVA:
        _TOKENS_SESSAO[id_limpo] = token_puro

    # Retorna o token completo apenas uma unica vez no ato da criacao
    retorno = dict(salvo)
    retorno["token"] = token_puro
    return retorno


def _obter_token_ambiente(id_limpo: str, env_var: str = "") -> str:
    chave_env = env_var.strip()
    if not chave_env and id_limpo in ADAPTADORES_CONHECIDOS:
        chave_env = ADAPTADORES_CONHECIDOS[id_limpo]["env_token"]
    if not chave_env:
        return ""
    val_os = os.getenv(chave_env, "").strip()
    if val_os:
        return val_os
    return str(getattr(config, chave_env, "") or "").strip()


def _sincronizar_adaptador_com_token(id_limpo: str, nome: str, token_puro: str) -> dict[str, Any]:
    """Garante que o adaptador esteja salvo com o hash do token informado sem perder estado."""
    token_hash = _hash_token(token_puro)
    prefixo = _prefixo_token(token_puro)
    lista = carregar()
    for item in lista:
        if _comparar_seguro(str(item.get("id", "")), id_limpo):
            if not _comparar_seguro(str(item.get("token_hash", "")), token_hash):
                item["token_hash"] = token_hash
                item["prefixo"] = prefixo
                salvar(lista)
            with _TRAVA:
                _TOKENS_SESSAO[id_limpo] = token_puro
            return item

    info_padrao = ADAPTADORES_CONHECIDOS.get(id_limpo, {})
    nome_final = nome.strip() or info_padrao.get("nome", id_limpo)
    criado = cadastrar(id_limpo, nome_final, token=token_puro)
    copia = dict(criado)
    copia.pop("token", None)
    return copia


def obter_token_adaptador(
    id_adaptador: str,
    nome: str = "",
    env_var: str = "",
) -> str:
    """Obtem ou provisiona o token de um adaptador preservando seu estado (ativo, limites, uso)."""
    id_limpo = id_adaptador.strip().lower()
    if not id_limpo:
        raise ValueError("id do adaptador nao pode ser vazio")

    info_padrao = ADAPTADORES_CONHECIDOS.get(id_limpo, {})
    nome_final = nome.strip() or info_padrao.get("nome", id_limpo)

    token_env = _obter_token_ambiente(id_limpo, env_var=env_var)
    if token_env:
        _sincronizar_adaptador_com_token(id_limpo, nome_final, token_env)
        return token_env

    disp = buscar_por_id(id_limpo)
    if not disp:
        novo = cadastrar(id_limpo, nome_final)
        return novo.get("token", "")

    with _TRAVA:
        token_mem = _TOKENS_SESSAO.get(id_limpo, "")
    if token_mem and _comparar_seguro(str(disp.get("token_hash", "")), _hash_token(token_mem)):
        return token_mem

    if not disp.get("ativo", True):
        # Adaptador revogado: nao rotaciona nem reativa automaticamente
        return token_mem

    novo_token = _gerar_token()
    _sincronizar_adaptador_com_token(id_limpo, nome_final, novo_token)
    return novo_token


def buscar_por_token(token: str) -> dict[str, Any] | None:
    if not token or not token.strip():
        return None
    hash_candidato = _hash_token(token)
    lista = carregar()
    for item in lista:
        hash_salvo = str(item.get("token_hash", ""))
        if hash_salvo and hmac.compare_digest(hash_salvo, hash_candidato):
            return item

    # Verifica se corresponde a um token configurado via variavel de ambiente
    for id_conhecido, meta in ADAPTADORES_CONHECIDOS.items():
        tk_env = _obter_token_ambiente(id_conhecido, env_var=meta["env_token"])
        if tk_env and hmac.compare_digest(_hash_token(tk_env), hash_candidato):
            return _sincronizar_adaptador_com_token(id_conhecido, meta["nome"], tk_env)

    return None


def buscar_por_id(id_adaptador: str) -> dict[str, Any] | None:
    id_limpo = id_adaptador.strip().lower()
    if not id_limpo:
        return None
    lista = carregar()
    for item in lista:
        if _comparar_seguro(str(item.get("id", "")), id_limpo):
            return item
    return None


def revogar(id_adaptador: str) -> bool:
    chave = id_adaptador.strip().lower()
    lista = carregar()
    alterado = False
    for item in lista:
        if _comparar_seguro(str(item.get("id", "")), chave):
            item["ativo"] = False
            item["revogado_em"] = _agora_iso()
            alterado = True
    if alterado:
        salvar(lista)
    return alterado


def ativar(id_adaptador: str) -> bool:
    chave = id_adaptador.strip().lower()
    lista = carregar()
    alterado = False
    for item in lista:
        if _comparar_seguro(str(item.get("id", "")), chave):
            item["ativo"] = True
            item["reativado_em"] = _agora_iso()
            alterado = True
    if alterado:
        salvar(lista)
    return alterado


def remover(id_adaptador: str) -> bool:
    chave = id_adaptador.strip().lower()
    lista = carregar()
    nova_lista = [item for item in lista if not _comparar_seguro(str(item.get("id", "")), chave)]
    if len(nova_lista) < len(lista):
        salvar(nova_lista)
        with _TRAVA:
            _TOKENS_SESSAO.pop(chave, None)
        return True
    return False


def registrar_uso(id_adaptador: str) -> None:
    id_limpo = id_adaptador.strip().lower()
    lista = carregar()
    for item in lista:
        if _comparar_seguro(str(item.get("id", "")), id_limpo):
            item["ultimo_uso"] = _agora_iso()
            item["total_requisicoes"] = int(item.get("total_requisicoes", 0)) + 1
            salvar(lista)
            break


def verificar_limite(id_adaptador: str, limite_por_minuto: int = 60) -> tuple[bool, int, float]:
    agora = time.time()
    janela = 60.0
    id_limpo = id_adaptador.strip().lower()

    with _TRAVA:
        historico = _HISTORICO_REQUISICOES.setdefault(id_limpo, [])
        validos = [t for t in historico if agora - t < janela]
        _HISTORICO_REQUISICOES[id_limpo] = validos

        if len(validos) >= limite_por_minuto:
            tempo_reset = round(janela - (agora - validos[0]), 1)
            return False, 0, max(0.1, tempo_reset)

        validos.append(agora)
        restantes = limite_por_minuto - len(validos)
        return True, restantes, 0.0


def registrar_log(
    id_adaptador: str,
    texto: str,
    intencao: str = "",
    status_http: int = 200,
    detalhe: str = "",
) -> None:
    ativo_log = os.getenv("NEXTOR_LOG_ASSISTENTES", "1").strip().lower()
    if ativo_log in ("0", "false", "nao", "no"):
        return

    gravar_texto = os.getenv("NEXTOR_LOG_TEXTO", "sim").strip().lower() not in ("0", "false", "nao", "no")
    if gravar_texto and texto:
        texto_escapado = (
            texto.replace("\r\n", " ")
            .replace("\r", " ")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .strip()
        )
        texto_final = texto_escapado[:120]
    else:
        texto_final = ""

    carimbo = _agora_iso()
    linha = f"{carimbo}\t{id_adaptador}\t{status_http}\t{intencao}\t{texto_final}"
    if detalhe:
        detalhe_escapado = (
            detalhe.replace("\r\n", " ")
            .replace("\r", " ")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .strip()
        )
        linha += f"\t{detalhe_escapado}"
    linha += "\n"

    with _TRAVA:
        try:
            with ARQUIVO_LOG.open("a", encoding="utf-8") as f:
                f.write(linha)
        except Exception:
            pass


def ler_logs(limite: int = 50) -> list[dict[str, Any]]:
    with _TRAVA:
        if not ARQUIVO_LOG.exists():
            return []
        try:
            linhas = [l for l in ARQUIVO_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
            resultado = []
            for linha in reversed(linhas[-limite:]):
                partes = linha.split("\t")
                if len(partes) >= 4:
                    item = {
                        "quando": partes[0],
                        "adaptador": partes[1],
                        "status": int(partes[2]) if partes[2].isdigit() else 200,
                        "intencao": partes[3],
                        "texto": partes[4] if len(partes) > 4 else "",
                        "detalhe": partes[5] if len(partes) > 5 else "",
                    }
                    resultado.append(item)
            return resultado
        except Exception:
            return []


def extrair_token_requisicao(
    headers: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
) -> str:
    """Extrai o token do adaptador de query string, X-Nextor-Token, Telegram secret ou Bearer."""
    if args:
        tk_arg = args.get("token")
        if tk_arg and str(tk_arg).strip():
            return str(tk_arg).strip()

    if headers:
        mapa_lower = {str(k).lower(): str(v) for k, v in headers.items() if v is not None}
        for chave in ("x-nextor-token", "x-telegram-bot-api-secret-token"):
            if chave in mapa_lower and mapa_lower[chave].strip():
                return mapa_lower[chave].strip()
        auth = mapa_lower.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()

    return ""


def extrair_texto_payload(
    dados: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
) -> str:
    """Extrai e normaliza o texto de entrada de qualquer adaptador (Siri, Google/HA, etc)."""
    chaves_texto = ("texto", "pergunta", "comando", "frase", "mensagem", "query", "utterance", "input")

    if isinstance(dados, dict):
        for chave in chaves_texto:
            val = dados.get(chave)
            if isinstance(val, str) and val.strip():
                return val.strip()

        # Formato Google Assistant / Dialogflow / Home Assistant Conversation
        qr = dados.get("queryResult")
        if isinstance(qr, dict):
            qt = qr.get("queryText")
            if isinstance(qt, str) and qt.strip():
                return qt.strip()

        inputs = dados.get("inputs")
        if isinstance(inputs, list) and inputs:
            primeiro = inputs[0] if isinstance(inputs[0], dict) else {}
            raw_inputs = primeiro.get("rawInputs")
            if isinstance(raw_inputs, list) and raw_inputs:
                raw0 = raw_inputs[0] if isinstance(raw_inputs[0], dict) else {}
                q = raw0.get("query")
                if isinstance(q, str) and q.strip():
                    return q.strip()

    for fonte in (form, args):
        if fonte:
            for chave in chaves_texto:
                val = fonte.get(chave)
                if isinstance(val, str) and val.strip():
                    return val.strip()

    return ""


def autenticar_requisicao(
    token: str,
    id_esperado: str | None = None,
    consumir_limite: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int, dict[str, str]]:
    """Valida token do adaptador com hmac.compare_digest, checa revogacao e rate limit."""
    adaptador = buscar_por_token(token) if token else None
    if not adaptador:
        return None, {"ok": False, "erro": "token de adaptador invalido"}, 401, {}

    if id_esperado:
        id_esp_limpo = id_esperado.strip().lower()
        if id_esp_limpo and not _comparar_seguro(str(adaptador.get("id", "")), id_esp_limpo):
            return None, {"ok": False, "erro": "token nao pertence a este adaptador"}, 403, {}

    if not adaptador.get("ativo", True):
        registrar_log(adaptador["id"], "", intencao="", status_http=403, detalhe="adaptador revogado")
        return None, {"ok": False, "erro": "adaptador revogado"}, 403, {}

    if consumir_limite:
        permitido, _restantes, reset_em = verificar_limite(
            adaptador["id"], adaptador.get("limite_por_minuto", 60)
        )
        if not permitido:
            registrar_log(adaptador["id"], "", intencao="", status_http=429, detalhe="limite excedido")
            headers_erro = {"Retry-After": str(int(reset_em) + 1)}
            corpo_erro = {
                "ok": False,
                "erro": "limite de requisicoes excedido",
                "reset_em_segundos": reset_em,
            }
            return None, corpo_erro, 429, headers_erro

    return adaptador, None, 200, {}


def processar_texto_assistente(
    texto: str,
    token: str = "",
    id_dispositivo: str | None = None,
    fn_rotear: Callable[..., dict[str, Any]] | None = None,
    adaptador_autenticado: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int, dict[str, str]]:
    """Pipeline unificado do endpoint /v1/assistente (texto entra, texto sai, sem falar no Nest)."""
    if adaptador_autenticado is not None:
        adaptador = adaptador_autenticado
    else:
        adaptador, erro_dict, status_erro, headers_erro = autenticar_requisicao(token)
        if erro_dict is not None or adaptador is None:
            return erro_dict or {"ok": False, "erro": "nao autorizado"}, status_erro, headers_erro

    roteador_fn = fn_rotear
    if roteador_fn is None:
        try:
            from .roteador import rotear as roteador_padrao
            roteador_fn = roteador_padrao
        except Exception:
            roteador_fn = None

    if roteador_fn is None:
        registrar_log(adaptador["id"], "", intencao="", status_http=503, detalhe="roteador indisponivel")
        return {"ok": False, "erro": "roteador indisponivel"}, 503, {}

    texto_limpo = (texto or "").strip()
    if not texto_limpo:
        registrar_log(adaptador["id"], "", intencao="", status_http=400, detalhe="texto vazio")
        return {"ok": False, "erro": "texto vazio"}, 400, {}

    try:
        r = roteador_fn(texto_limpo, canal="remoto", id_dispositivo=id_dispositivo)
    except TypeError:
        r = roteador_fn(texto_limpo)

    if isinstance(r, str):
        r = {"resposta": r, "intencao": "conversa"}
    elif not isinstance(r, dict):
        r = {"resposta": str(r), "intencao": "conversa"}

    try:
        from .companheiro import companheiro
        companheiro.atualizar(ultima_mensagem=texto_limpo, ultima_resposta=r.get("resposta", ""))
    except Exception:
        pass

    registrar_uso(adaptador["id"])
    registrar_log(adaptador["id"], texto_limpo, intencao=r.get("intencao", ""), status_http=200)

    return (
        {
            "ok": True,
            "resposta": r.get("resposta", ""),
            "intencao": r.get("intencao", ""),
            "adaptador": adaptador["id"],
        },
        200,
        {},
    )


def chamar_assistente(
    texto: str,
    id_adaptador: str = "assistente",
    nome_adaptador: str = "Assistente",
    env_var: str = "",
    token_adaptador: str | None = None,
    base_url: str | None = None,
    urlopen_fn: Callable[..., Any] | None = None,
    tratar_erro_http: bool = False,
) -> str:
    """Despacha uma mensagem de um adaptador (Alexa, Telegram, etc) para /v1/assistente."""
    texto_limpo = (texto or "").strip()
    if not texto_limpo:
        return "Texto vazio."

    token = token_adaptador or obter_token_adaptador(id_adaptador, nome_adaptador, env_var=env_var)
    url = f"{base_url or f'http://localhost:{config.PORTA}'}/v1/assistente"
    payload = json.dumps({"texto": texto_limpo}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    abridor = urlopen_fn or urllib.request.urlopen
    try:
        with abridor(req, timeout=30) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
            if dados.get("ok", True):
                return dados.get("resposta", "") or dados.get("texto", "") or "Sem resposta."
            return dados.get("erro", "Erro no processamento da requisicao.")
    except urllib.error.HTTPError as e:
        if tratar_erro_http:
            corpo = e.read().decode("utf-8", errors="ignore")
            try:
                dados_erro = json.loads(corpo)
                msg_erro = dados_erro.get("erro", str(e))
            except Exception:
                msg_erro = str(e)
            return f"Erro ao consultar assistente ({e.code}): {msg_erro}"
        log.warning("Erro HTTP ao chamar /v1/assistente para %s: %s", id_adaptador, e)
    except Exception as e:
        log.debug("Servico HTTP /v1/assistente indisponivel via socket (%s); usando pipeline local.", e)

    # Fallback em processo pelo mesmo pipeline autenticado de /v1/assistente
    try:
        corpo_local, status_local, _ = processar_texto_assistente(texto_limpo, token=token)
        if status_local == 200 and corpo_local.get("ok"):
            return corpo_local.get("resposta", "Processado localmente.")
        return corpo_local.get("erro", "Nao foi possivel processar seu pedido no momento.")
    except Exception as e_local:
        log.error("Falha no pipeline local do assistente (%s): %s", id_adaptador, e_local)
        return "Nao foi possivel processar seu pedido no momento."


def resetar_estado_testes() -> None:
    with _TRAVA:
        _HISTORICO_REQUISICOES.clear()
        _TOKENS_SESSAO.clear()
