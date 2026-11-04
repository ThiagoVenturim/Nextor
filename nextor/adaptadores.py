"""Gerenciamento de adaptadores de assistentes (Siri, Alexa, Telegram, etc).

Controla tokens revogaveis por hash sha256 e comparacao hmac em tempo constante,
rate limiting por janela deslizante e registro seguro de requisicoes com sanitizacao de log.
"""
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any

from . import config

ARQUIVO = config.RAIZ / "adaptadores.json"
ARQUIVO_LOG = config.RAIZ / "assistentes.log"

_TRAVA = threading.Lock()
_HISTORICO_REQUISICOES: dict[str, list[float]] = {}


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gerar_token() -> str:
    return f"nxt_{secrets.token_urlsafe(24)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


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
        if item.get("id") == id_limpo:
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

    # Retorna o token completo apenas uma unica vez no ato da criacao
    retorno = dict(salvo)
    retorno["token"] = token_puro
    return retorno


def buscar_por_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    hash_candidato = _hash_token(token)
    lista = carregar()
    for item in lista:
        hash_salvo = item.get("token_hash", "")
        if hash_salvo and hmac.compare_digest(hash_salvo, hash_candidato):
            return item
    return None


def buscar_por_id(id_adaptador: str) -> dict[str, Any] | None:
    id_limpo = id_adaptador.strip().lower()
    lista = carregar()
    for item in lista:
        if item.get("id") == id_limpo:
            return item
    return None


def revogar(id_adaptador: str) -> bool:
    chave = id_adaptador.strip().lower()
    lista = carregar()
    alterado = False
    for item in lista:
        if item.get("id") == chave:
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
        if item.get("id") == chave:
            item["ativo"] = True
            item["reativado_em"] = _agora_iso()
            alterado = True
    if alterado:
        salvar(lista)
    return alterado


def remover(id_adaptador: str) -> bool:
    chave = id_adaptador.strip().lower()
    lista = carregar()
    nova_lista = [item for item in lista if item.get("id") != chave]
    if len(nova_lista) != len(lista):
        salvar(nova_lista)
        return True
    return False


def registrar_uso(id_adaptador: str) -> None:
    id_limpo = id_adaptador.strip().lower()
    lista = carregar()
    for item in lista:
        if item.get("id") == id_limpo:
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
        detalhe_escapado = detalhe.replace("\r\n", " ").replace("\r", " ").replace("\n", "\\n").replace("\t", "\\t").strip()
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


def resetar_estado_testes() -> None:
    with _TRAVA:
        _HISTORICO_REQUISICOES.clear()
