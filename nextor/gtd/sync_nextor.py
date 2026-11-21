"""Sincronizacao do GTD com as anotacoes do proprio Nextor (Issue #42).

As anotacoes feitas por voz, Telegram ou API (anotacoes.md, lidas por nextor.pendencias)
viram proximas acoes no GTD. A conclusao anda nos dois sentidos:
- marcar [x] na anotacao conclui a tarefa no GTD (importar);
- concluir a tarefa no GTD marca [x] na anotacao, e reabrir desmarca (exportar).

A chave de cada anotacao e um hash do titulo, porque o numero da linha muda quando o
arquivo e editado. Tarefas criadas no painel nao sao copiadas para o arquivo de
anotacoes, para nao duplicar a captura.
"""
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

from .. import pendencias
from .armazenamento import ArmazenamentoGTD
from .modelos import Item
from .sync_comum import pode_exportar, pode_importar, resolver_conflito

log = logging.getLogger("nextor.gtd.sync_nextor")

PREFIXO_REF = "nextor:nota:"


def ref_anotacao(titulo: str) -> str:
    chave = " ".join(str(titulo or "").lower().split())
    return PREFIXO_REF + hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16]


def sincronizar_nextor(
    banco: ArmazenamentoGTD,
    direcao: str = "bidirecional",
    politica: str = "remoto",
    caminho_anotacoes: Optional[Path] = None,
) -> Dict[str, Any]:
    """Concilia tarefas do GTD com as anotacoes do Nextor."""
    res = {"novas": 0, "atualizadas_local": 0, "atualizadas_remoto": 0, "conflitos": 0, "erros": 0}
    if not (pode_importar(direcao) or pode_exportar(direcao)):
        return res

    notas: Dict[str, Dict[str, Any]] = {}
    for nota in pendencias.listar_anotacoes(caminho_anotacoes=caminho_anotacoes):
        notas.setdefault(ref_anotacao(nota["titulo"]), nota)

    # 1. Tarefas ja ligadas a uma anotacao.
    vinculadas = set()
    for item in banco.listar_itens():
        ref = item.ref_externa or ""
        if item.origem != "nextor" or not ref.startswith(PREFIXO_REF):
            continue
        vinculadas.add(ref)
        nota = notas.get(ref)
        if nota is None:
            continue  # anotacao removida do arquivo: a tarefa fica como esta
        ultimo = bool(item.obter_meta("nextor_feita", False))
        remoto_mudou = pode_importar(direcao) and nota["feita"] != ultimo
        local_feito = item.estado == "feito"
        local_mudou = pode_exportar(direcao) and local_feito != ultimo
        if remoto_mudou and local_mudou:
            res["conflitos"] += 1
        vencedor = resolver_conflito(remoto_mudou, local_mudou, politica)

        if vencedor == "remoto":
            if nota["feita"] and not local_feito:
                item.estado = "feito"
                item.concluido_em = datetime.now().isoformat(timespec="seconds")
            elif not nota["feita"] and local_feito:
                item.estado = "proxima"
                item.concluido_em = None
            item.definir_meta("nextor_feita", nota["feita"])
            banco.salvar_item(item)
            res["atualizadas_local"] += 1
        elif vencedor == "local":
            if local_feito:
                ok = pendencias.concluir_tarefa_anotacao(nota["linha_num"], caminho_anotacoes=caminho_anotacoes)
            else:
                ok = pendencias.reabrir_tarefa_anotacao(nota["linha_num"], caminho_anotacoes=caminho_anotacoes)
            if not ok:
                res["erros"] += 1
                continue
            item.definir_meta("nextor_feita", local_feito)
            banco.salvar_item(item)
            res["atualizadas_remoto"] += 1

    # 2. Anotacoes pendentes sem tarefa: viram proximas acoes.
    if pode_importar(direcao):
        for ref, nota in notas.items():
            if ref in vinculadas or nota["feita"] or banco.buscar_item_por_ref(ref):
                continue
            item = Item(
                id=str(uuid.uuid4()),
                titulo=nota["titulo"],
                nota="Anotacao do Nextor",
                contexto="@qualquer",
                estado="proxima",
                prazo=nota.get("prazo"),
                origem="nextor",
                ref_externa=ref,
            )
            item.definir_meta("nextor_feita", False)
            banco.salvar_item(item)
            res["novas"] += 1

    return res
