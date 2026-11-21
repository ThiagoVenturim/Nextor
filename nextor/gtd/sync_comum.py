"""Pecas comuns da sincronizacao do GTD com fontes externas (Issue #42).

Cada fonte (Notion, GitHub, anotacoes do Nextor) tem uma direcao configuravel:
- "importar": so traz mudancas da fonte para o GTD;
- "exportar": so leva mudancas do GTD para a fonte;
- "bidirecional": as duas coisas;
- "desligado": nada.

A deteccao de mudanca local usa uma impressao (hash) dos campos sincronizados, salva no
ultimo sincronismo. A deteccao de mudanca remota usa o carimbo da fonte (last_edited_time
do Notion, estado da issue no GitHub, marcacao [x] da anotacao). Quando os dois lados
mudaram, a politica "conflito" decide: "remoto" (padrao) ou "local".
"""
import hashlib
import json
from typing import Any, Dict, Optional

from .armazenamento import ArmazenamentoGTD


def pode_importar(direcao: str) -> bool:
    return direcao in ("importar", "bidirecional")


def pode_exportar(direcao: str) -> bool:
    return direcao in ("exportar", "bidirecional")


def impressao(campos: Dict[str, Any]) -> str:
    """Hash estavel dos campos sincronizados de um registro."""
    bruto = json.dumps(campos, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


def _tabela_impressao(tabela: str) -> str:
    return f"{tabela}#impressao"


def obter_impressao(banco: ArmazenamentoGTD, tabela: str, id_local: str) -> str:
    """Le a impressao salva no ultimo sincronismo.

    Reaproveita a tabela de mapeamento do Notion (presente nos backends SQLite e
    SQLAlchemy) com uma chave de tabela propria, sem exigir migracao de esquema.
    """
    reg = banco.obter_mapeamento_notion(_tabela_impressao(tabela), id_local)
    return (reg or {}).get("id_notion", "") or ""


def salvar_impressao(banco: ArmazenamentoGTD, tabela: str, id_local: str, valor: str) -> None:
    banco.salvar_mapeamento_notion(_tabela_impressao(tabela), id_local, valor, None)


def resolver_conflito(remoto_mudou: bool, local_mudou: bool, politica: str) -> Optional[str]:
    """Decide qual lado vence: 'remoto', 'local' ou None (nada mudou)."""
    if remoto_mudou and local_mudou:
        return "local" if politica == "local" else "remoto"
    if remoto_mudou:
        return "remoto"
    if local_mudou:
        return "local"
    return None
