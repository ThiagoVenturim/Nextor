"""Gerenciamento de dispositivos do usuario (celular, tablet, notebook, PC, TV).

Controla cadastro e pareamento por token/QR code, permissoes por tipo de aparelho,
registro de presenca, determinacao do aparelho ativo e navegacao/hand-off de respostas.
Tokens sao armazenados exclusivamente como hash SHA-256 e comparados em tempo constante.
"""
from datetime import datetime
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
import time
from typing import Any

from . import config

ARQUIVO = config.RAIZ / "dispositivos.json"
TIPOS_PERMITIDOS = ("celular", "tablet", "notebook", "pc", "tv")

# Faixas de VPN privada aceitas alem das redes locais (RFC 1918, loopback, link-local, ULA):
# 100.64.0.0/10 e o espaco CGNAT usado pelo Tailscale; fd7a:115c:a1e0::/48 e a faixa IPv6 dele.
REDES_VPN_PADRAO = ("100.64.0.0/10", "fd7a:115c:a1e0::/48")

_PADRAO_SEGREDO = re.compile(r"((?:token|secret|senha|password)=)[^&\s#\"']+", re.IGNORECASE)

PERMISSOES_PADRAO: dict[str, list[str]] = {
    "tv": ["visualizar"],
    "pc": ["visualizar", "executar", "interagir"],
    "notebook": ["visualizar", "executar", "interagir"],
    "celular": ["visualizar", "interagir"],
    "tablet": ["visualizar", "interagir"],
}

_TRAVA = threading.Lock()
_MENSAGENS_PENDENTES: dict[str, list[dict[str, Any]]] = {}
_DISPOSITIVO_ATIVO_EXPLICITO: str | None = None


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gerar_token() -> str:
    return f"nxt_dev_{secrets.token_urlsafe(24)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _prefixo_token(token: str) -> str:
    t = token.strip()
    if len(t) <= 12:
        return t[:6] + "..." if len(t) >= 6 else t + "..."
    return t[:10] + "..."


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


def cadastrar(
    id_dispositivo: str,
    nome: str,
    tipo: str,
    permissoes: list[str] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    id_limpo = id_dispositivo.strip().lower()
    tipo_limpo = tipo.strip().lower()
    if not id_limpo:
        raise ValueError("id do dispositivo nao pode ser vazio")
    if tipo_limpo not in TIPOS_PERMITIDOS:
        raise ValueError(f"tipo invalido; use um de: {', '.join(TIPOS_PERMITIDOS)}")

    lista = carregar()
    for item in lista:
        if item.get("id") == id_limpo:
            raise ValueError(f"dispositivo '{id_limpo}' ja existe")

    perms = permissoes if permissoes is not None else PERMISSOES_PADRAO.get(tipo_limpo, ["visualizar"])
    token_puro = token.strip() if token else _gerar_token()
    token_hash = _hash_token(token_puro)
    prefixo = _prefixo_token(token_puro)

    salvo = {
        "id": id_limpo,
        "nome": nome.strip() or id_limpo,
        "tipo": tipo_limpo,
        "prefixo": prefixo,
        "token_hash": token_hash,
        "permissoes": sorted(list(set(perms))),
        "ativo": True,
        "criado_em": _agora_iso(),
        "ultimo_visto": None,
        "presenca": {
            "online": False,
            "ip": None,
            "user_agent": None,
            "atualizado_em": None,
        },
    }
    lista.append(salvo)
    salvar(lista)

    # Retorna o token completo apenas uma unica vez no ato do cadastro
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


def buscar_por_id(id_dispositivo: str) -> dict[str, Any] | None:
    if not id_dispositivo:
        return None
    id_limpo = id_dispositivo.strip().lower()
    for item in carregar():
        if item.get("id") == id_limpo:
            return item
    return None


def buscar_por_tipo_ou_nome(termo: str) -> dict[str, Any] | None:
    t = termo.strip().lower()
    if not t:
        return None
    todos = carregar()
    # Match exato de id ou nome (permite encontrar desativados para checagem)
    for d in todos:
        if d["id"] == t or d["nome"].lower() == t:
            return d
    # Match por tipo (prioriza ativos)
    por_tipo = [d for d in todos if d["tipo"] == t]
    if por_tipo:
        ativos = [d for d in por_tipo if d.get("ativo", True)]
        return ativos[0] if ativos else por_tipo[0]
    # Match parcial de nome
    for d in todos:
        if t in d["nome"].lower():
            return d
    return None


def revogar(id_dispositivo: str) -> bool:
    chave = id_dispositivo.strip().lower()
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


def ativar(id_dispositivo: str) -> bool:
    chave = id_dispositivo.strip().lower()
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


def remover(id_dispositivo: str) -> bool:
    chave = id_dispositivo.strip().lower()
    lista = carregar()
    nova_lista = [item for item in lista if item.get("id") != chave]
    if len(nova_lista) != len(lista):
        salvar(nova_lista)
        return True
    return False


def listar(apenas_ativos: bool = False, mascarar: bool = True) -> list[dict[str, Any]]:
    todos = carregar()
    resultado = []
    for item in todos:
        if apenas_ativos and not item.get("ativo", True):
            continue
        copia = dict(item)
        if mascarar:
            copia.pop("token_hash", None)
        resultado.append(copia)
    return resultado


def registrar_presenca(
    id_dispositivo: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any] | None:
    id_limpo = id_dispositivo.strip().lower()
    lista = carregar()
    dispositivo = None
    for item in lista:
        if item.get("id") == id_limpo:
            agora = _agora_iso()
            item["ultimo_visto"] = agora
            item["presenca"] = {
                "online": True,
                "ip": ip,
                "user_agent": user_agent,
                "atualizado_em": agora,
            }
            dispositivo = item
            break
    if dispositivo:
        salvar(lista)
    return dispositivo


def definir_ativo(id_dispositivo: str) -> bool:
    global _DISPOSITIVO_ATIVO_EXPLICITO
    disp = buscar_por_id(id_dispositivo)
    if disp and disp.get("ativo", True):
        _DISPOSITIVO_ATIVO_EXPLICITO = disp["id"]
        return True
    return False


def dispositivo_ativo() -> dict[str, Any] | None:
    global _DISPOSITIVO_ATIVO_EXPLICITO
    if _DISPOSITIVO_ATIVO_EXPLICITO:
        disp = buscar_por_id(_DISPOSITIVO_ATIVO_EXPLICITO)
        if disp and disp.get("ativo", True):
            return disp

    ativos = [d for d in carregar() if d.get("ativo", True) and d.get("ultimo_visto")]
    if not ativos:
        todos_ativos = [d for d in carregar() if d.get("ativo", True)]
        return todos_ativos[0] if todos_ativos else None

    ativos.sort(key=lambda d: d.get("ultimo_visto") or "", reverse=True)
    return ativos[0]


def tem_permissao(id_dispositivo: str, permissao: str) -> bool:
    disp = buscar_por_id(id_dispositivo)
    if not disp or not disp.get("ativo", True):
        return False
    return permissao in disp.get("permissoes", [])


def enviar_resposta_dispositivo(
    id_dispositivo: str,
    texto: str,
    titulo: str = "Nextor",
    intencao: str = "",
) -> dict[str, Any]:
    disp = buscar_por_id(id_dispositivo)
    if not disp:
        raise ValueError(f"dispositivo '{id_dispositivo}' nao encontrado")
    if not disp.get("ativo", True):
        raise ValueError(f"dispositivo '{disp['nome']}' esta desativado ou revogado")

    msg = {
        "id": f"msg-{int(time.time() * 1000)}",
        "quando": _agora_iso(),
        "dispositivo_alvo": disp["id"],
        "tipo_dispositivo": disp["tipo"],
        "titulo": titulo,
        "texto": texto,
        "intencao": intencao,
    }

    with _TRAVA:
        fila = _MENSAGENS_PENDENTES.setdefault(disp["id"], [])
        fila.append(msg)
        if len(fila) > 50:
            fila.pop(0)

    definir_ativo(disp["id"])
    return msg


def obter_mensagens_pendentes(
    id_dispositivo: str,
    limpar: bool = False,
) -> list[dict[str, Any]]:
    disp = buscar_por_id(id_dispositivo)
    if not disp:
        return []
    with _TRAVA:
        fila = _MENSAGENS_PENDENTES.get(disp["id"], [])
        resultado = list(fila)
        if limpar:
            _MENSAGENS_PENDENTES[disp["id"]] = []
        return resultado


def gerar_url_pareamento(
    id_dispositivo: str,
    token_puro: str,
    host: str = "localhost",
    porta: int = 5005,
) -> str:
    disp = buscar_por_id(id_dispositivo)
    if not disp:
        raise ValueError("dispositivo nao encontrado")
    return f"http://{host}:{porta}/dispositivo/conectar?id={disp['id']}#token={token_puro}"


def resetar_estado_testes() -> None:
    global _DISPOSITIVO_ATIVO_EXPLICITO
    with _TRAVA:
        _MENSAGENS_PENDENTES.clear()
        _DISPOSITIVO_ATIVO_EXPLICITO = None


def _redes_configuradas(redes_extras: str | list[str] | tuple[str, ...] | None) -> list:
    if redes_extras is None:
        redes_extras = getattr(config, "REDES_PERMITIDAS", "")
    if isinstance(redes_extras, str):
        itens = [r.strip() for r in redes_extras.replace(";", ",").split(",")]
    else:
        itens = [str(r).strip() for r in redes_extras]
    redes = []
    for bruto in list(REDES_VPN_PADRAO) + [i for i in itens if i]:
        try:
            redes.append(ipaddress.ip_network(bruto, strict=False))
        except ValueError:
            continue
    return redes


def endereco_permitido(
    ip: str | None,
    redes_extras: str | list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Diz se o endereco de origem esta na rede local ou numa VPN privada.

    Aceita loopback, redes privadas (RFC 1918 e IPv6 ULA), link-local, a faixa do Tailscale
    e as redes extras de NEXTOR_REDES_PERMITIDAS (CIDRs separados por virgula). Recusa
    qualquer endereco publico da internet e valores invalidos.
    """
    if not ip:
        return False
    try:
        endereco = ipaddress.ip_address(str(ip).strip().split("%")[0])
    except ValueError:
        return False
    if isinstance(endereco, ipaddress.IPv6Address) and endereco.ipv4_mapped:
        endereco = endereco.ipv4_mapped
    if endereco.is_unspecified or endereco.is_multicast:
        return False
    if endereco.is_loopback or endereco.is_link_local:
        return True
    for rede in _redes_configuradas(redes_extras):
        if endereco.version == rede.version and endereco in rede:
            return True
    return bool(endereco.is_private and not endereco.is_reserved)


def mascarar_segredos(texto: str) -> str:
    """Troca valores de token/senha em query strings por *** (usado nos logs HTTP)."""
    if not texto:
        return texto
    return _PADRAO_SEGREDO.sub(r"\1***", texto)


def gerar_qr_svg(conteudo: str) -> str | None:
    """Gera o QR code de pareamento em SVG, sem rede. Retorna None sem a biblioteca segno."""
    try:
        import segno
    except ImportError:
        return None
    import io

    qr = segno.make(conteudo, error="m")
    saida = io.BytesIO()
    qr.save(saida, kind="svg", scale=4, border=2, xmldecl=False, svgns=True)
    return saida.getvalue().decode("utf-8")
