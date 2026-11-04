"""Gerenciamento de adaptadores de assistentes (Siri, Alexa, Telegram, etc).

Controla tokens revogaveis por adaptador, rate limiting em memoria e log de chamadas.
"""
from datetime import datetime
import json
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


def listar(apenas_ativos: bool = False, mascarar: bool = False) -> list[dict[str, Any]]:
    todos = carregar()
    resultado = []
    for item in todos:
        if apenas_ativos and not item.get("ativo", True):
            continue
        copia = dict(item)
        if mascarar:
            token = copia.get("token", "")
            if len(token) > 8:
                copia["token"] = token[:4] + "..." + token[-4:]
            else:
                copia["token"] = "***"
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

    token_gerado = token.strip() if token else secrets.token_urlsafe(24)
    novo = {
        "id": id_limpo,
        "nome": nome.strip() or id_limpo,
        "token": token_gerado,
        "limite_por_minuto": max(1, int(limite_por_minuto)),
        "ativo": True,
        "criado_em": _agora_iso(),
        "ultimo_uso": None,
        "total_requisicoes": 0,
    }
    lista.append(novo)
    salvar(lista)
    return novo


def buscar_por_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    token_limpo = token.strip()
    lista = carregar()
    for item in lista:
        if item.get("token") == token_limpo:
            return item
    return None


def buscar_por_id(id_adaptador: str) -> dict[str, Any] | None:
    id_limpo = id_adaptador.strip().lower()
    lista = carregar()
    for item in lista:
        if item.get("id") == id_limpo:
            return item
    return None


def revogar(id_ou_token: str) -> bool:
    chave = id_ou_token.strip()
    lista = carregar()
    alterado = False
    for item in lista:
        if item.get("id") == chave.lower() or item.get("token") == chave:
            item["ativo"] = False
            item["revogado_em"] = _agora_iso()
            alterado = True
    if alterado:
        salvar(lista)
    return alterado


def ativar(id_ou_token: str) -> bool:
    chave = id_ou_token.strip()
    lista = carregar()
    alterado = False
    for item in lista:
        if item.get("id") == chave.lower() or item.get("token") == chave:
            item["ativo"] = True
            item["reativado_em"] = _agora_iso()
            alterado = True
    if alterado:
        salvar(lista)
    return alterado


def remover(id_ou_token: str) -> bool:
    chave = id_ou_token.strip()
    lista = carregar()
    nova_lista = [
        item for item in lista
        if item.get("id") != chave.lower() and item.get("token") != chave
    ]
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
    carimbo = _agora_iso()
    linha = f"{carimbo}\t{id_adaptador}\t{status_http}\t{intencao}\t{texto}"
    if detalhe:
        linha += f"\t{detalhe}"
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
            linhas = ARQUIVO_LOG.read_text(encoding="utf-8").strip().splitlines()
            resultado = []
            for linha in reversed(linhas[-limite:]):
                partes = linha.split("\t")
                if len(partes) >= 5:
                    item = {
                        "quando": partes[0],
                        "adaptador": partes[1],
                        "status": int(partes[2]) if partes[2].isdigit() else 200,
                        "intencao": partes[3],
                        "texto": partes[4],
                        "detalhe": partes[5] if len(partes) > 5 else "",
                    }
                    resultado.append(item)
            return resultado
        except Exception:
            return []


def resetar_estado_testes() -> None:
    with _TRAVA:
        _HISTORICO_REQUISICOES.clear()
