"""Sincronizacao de mao dupla do GTD com bases do Notion (Issue #42).

Sincroniza tres bases opcionais, cada uma configurada por variavel de ambiente:
- NOTION_DB_TAREFAS  -> itens do GTD (titulo, estado, contexto, prazo, projeto);
- NOTION_DB_PROJETOS -> projetos (nome, estado, descricao);
- NOTION_DB_LEITURAS -> fila de leitura (titulo, estado, autor, tipo, paginas, url).

As propriedades sao reconhecidas pelo tipo e por nomes comuns em portugues e ingles
("Status"/"Estado", "Prazo"/"Due", ...), entao a base nao precisa de um esquema fixo.
Mudanca remota: last_edited_time diferente do salvo. Mudanca local: impressao dos campos
diferente da salva. Paginas arquivadas sao ignoradas; nada e apagado em nenhum lado.
"""
from datetime import datetime
import logging
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .armazenamento import ArmazenamentoGTD
from .modelos import Item, Leitura, Projeto, normalizar_contexto
from .notion import (
    ClienteNotion,
    extrair_relacoes,
    extrair_texto_propriedade,
    montar_propriedade_checkbox,
    montar_propriedade_data,
    montar_propriedade_numero,
    montar_propriedade_relacao,
    montar_propriedade_select,
    montar_propriedade_status,
    montar_propriedade_texto,
    montar_propriedade_titulo,
    montar_propriedade_url,
)
from .sync_comum import (
    impressao,
    obter_impressao,
    pode_exportar,
    pode_importar,
    resolver_conflito,
    salvar_impressao,
)

log = logging.getLogger("nextor.gtd.sync_notion")

Papeis = Dict[str, Tuple[Optional[Tuple[str, ...]], Tuple[str, ...]]]
Resolvidos = Dict[str, Tuple[str, Dict[str, Any]]]


def _norm(texto: Any) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("_", " ").split())


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# Sinonimos de estado aceitos vindos do Notion, ja normalizados por _norm.
SINONIMOS_ITEM = {
    "feito": ("feito", "feita", "concluido", "concluida", "done", "completo", "completed", "finalizado"),
    "aguardando": ("aguardando", "esperando", "waiting", "em espera", "bloqueado", "blocked"),
    "algum_dia": ("algum dia", "someday", "talvez", "maybe"),
    "inbox": ("inbox", "entrada", "caixa de entrada"),
    "proxima": ("proxima", "proximas", "a fazer", "to do", "todo", "not started", "nao iniciado",
                "em andamento", "in progress", "doing", "fazendo"),
}
ROTULOS_ITEM = {"inbox": "Inbox", "proxima": "Proxima", "aguardando": "Aguardando",
                "algum_dia": "Algum dia", "feito": "Feito"}

SINONIMOS_LEITURA = {
    "lido": ("lido", "lida", "read", "done", "concluido", "concluida", "feito"),
    "lendo": ("lendo", "reading", "em andamento", "in progress", "doing"),
    "quero_ler": ("quero ler", "to read", "fila", "nao iniciado", "not started", "a fazer", "to do"),
}
ROTULOS_LEITURA = {"quero_ler": "Quero ler", "lendo": "Lendo", "lido": "Lido"}

SINONIMOS_PROJETO = {
    "concluido": ("concluido", "concluida", "done", "feito", "completo", "completed"),
    "pausado": ("pausado", "paused", "on hold", "em espera", "parado"),
    "ativo": ("ativo", "active", "em andamento", "in progress", "doing", "not started", "a fazer"),
}
ROTULOS_PROJETO = {"ativo": "Ativo", "concluido": "Concluido", "pausado": "Pausado"}

NOMES_ESTADO = ("status", "estado", "state")


def _estado_de_texto(texto: str, sinonimos: Dict[str, Tuple[str, ...]]) -> str:
    alvo = _norm(texto)
    for estado, lista in sinonimos.items():
        if alvo in lista:
            return estado
    return ""


def _rotulo_estado(estado: str, defn: Dict[str, Any], sinonimos, rotulos) -> str:
    """Escolhe a opcao existente da propriedade que equivale ao estado local, se houver."""
    tipo = defn.get("type", "")
    opcoes = (defn.get(tipo) or {}).get("options") if isinstance(defn.get(tipo), dict) else None
    for op in opcoes or []:
        if isinstance(op, dict) and _estado_de_texto(op.get("name", ""), sinonimos) == estado:
            return op.get("name", "")
    return rotulos.get(estado, estado)


def resolver_papeis(props: Dict[str, Any], papeis: Papeis) -> Resolvidos:
    """Associa cada papel (titulo, estado, ...) a uma propriedade do Notion pelo tipo e nome."""
    resolvidos: Resolvidos = {}
    for papel, (nomes, tipos) in papeis.items():
        for tipo_preferido in tipos:
            for nome, defn in props.items():
                if not isinstance(defn, dict) or defn.get("type") != tipo_preferido:
                    continue
                if nomes is None or _norm(nome) in nomes:
                    resolvidos[papel] = (nome, defn)
                    break
            if papel in resolvidos:
                break
    return resolvidos


def _valor_propriedade(prop: Dict[str, Any]) -> Any:
    tipo = prop.get("type")
    if tipo == "number":
        return prop.get("number")
    if tipo == "checkbox":
        return bool(prop.get("checkbox"))
    if tipo == "date":
        inicio = (prop.get("date") or {}).get("start") or ""
        return inicio[:10] or None
    if tipo == "relation":
        return extrair_relacoes(prop)
    return extrair_texto_propriedade(prop)


def _montar_propriedade(tipo: str, valor: Any) -> Optional[Dict[str, Any]]:
    if tipo == "title":
        return montar_propriedade_titulo(str(valor or ""))
    if tipo == "rich_text":
        return montar_propriedade_texto(str(valor or ""))
    if tipo == "select":
        return montar_propriedade_select(str(valor)) if valor else {"select": None}
    if tipo == "status":
        return montar_propriedade_status(str(valor)) if valor else None
    if tipo == "number":
        return montar_propriedade_numero(valor) if valor is not None else {"number": None}
    if tipo == "date":
        return montar_propriedade_data(valor)
    if tipo == "checkbox":
        return montar_propriedade_checkbox(bool(valor))
    if tipo == "url":
        return montar_propriedade_url(str(valor or ""))
    if tipo == "relation":
        return montar_propriedade_relacao(list(valor or []))
    return None


class _Contexto:
    """Mapas entre projetos locais e paginas do Notion, usados pela relacao Projeto."""

    def __init__(self, banco: ArmazenamentoGTD):
        self.pagina_por_projeto: Dict[str, str] = {}
        self.projeto_por_pagina: Dict[str, str] = {}
        for p in banco.listar_projetos():
            m = banco.obter_mapeamento_notion("projetos", p.id)
            if m and m.get("id_notion"):
                self.pagina_por_projeto[p.id] = m["id_notion"]
                self.projeto_por_pagina[m["id_notion"]] = p.id


class _Entidade:
    tabela = ""
    papeis: Papeis = {}
    padrao_criacao: Resolvidos = {}

    def listar(self, banco: ArmazenamentoGTD) -> List[Any]:
        raise NotImplementedError

    def salvar(self, banco: ArmazenamentoGTD, obj: Any) -> None:
        raise NotImplementedError

    def campos_locais(self, obj: Any) -> Dict[str, Any]:
        raise NotImplementedError

    def de_remoto(self, valores: Dict[str, Any], resolvidos: Resolvidos, ctx: _Contexto) -> Dict[str, Any]:
        raise NotImplementedError

    def para_remoto(self, campos: Dict[str, Any], resolvidos: Resolvidos, ctx: _Contexto) -> Dict[str, Any]:
        raise NotImplementedError

    def aplicar(self, obj: Any, campos: Dict[str, Any]) -> None:
        raise NotImplementedError

    def novo(self, campos: Dict[str, Any], page_id: str) -> Any:
        raise NotImplementedError

    def exportar_novo(self, obj: Any) -> bool:
        return True

    def vincular_existente(self, banco: ArmazenamentoGTD, campos: Dict[str, Any]) -> Optional[Any]:
        return None


class _EntidadeItem(_Entidade):
    tabela = "itens"
    papeis: Papeis = {
        "titulo": (None, ("title",)),
        "estado": (NOMES_ESTADO + ("feito", "done", "concluido"), ("status", "select", "checkbox")),
        "contexto": (("contexto", "context", "lugar"), ("select",)),
        "prazo": (("prazo", "data", "due", "due date", "vencimento"), ("date",)),
        "projeto": (("projeto", "project"), ("relation",)),
    }
    # Sem esquema da base, cria so com o que a versao anterior ja enviava.
    padrao_criacao: Resolvidos = {
        "titulo": ("Nome", {"type": "title"}),
        "contexto": ("Contexto", {"type": "select"}),
    }

    def listar(self, banco):
        return banco.listar_itens()

    def salvar(self, banco, obj):
        banco.salvar_item(obj)

    def campos_locais(self, obj: Item) -> Dict[str, Any]:
        return {"titulo": obj.titulo, "estado": obj.estado, "contexto": obj.contexto,
                "prazo": obj.prazo, "projeto": obj.projeto_id}

    def de_remoto(self, valores, resolvidos, ctx):
        campos: Dict[str, Any] = {"titulo": str(valores.get("titulo") or "").strip()}
        if "estado" in valores:
            v = valores["estado"]
            if isinstance(v, bool):
                campos["estado"] = "feito" if v else ""
            else:
                campos["estado"] = _estado_de_texto(v, SINONIMOS_ITEM)
        if "contexto" in valores and valores["contexto"]:
            campos["contexto"] = normalizar_contexto(valores["contexto"])
        if "prazo" in valores:
            campos["prazo"] = valores["prazo"]
        if "projeto" in valores:
            ids = valores["projeto"] or []
            if not ids:
                campos["projeto"] = None
            elif ids[0] in ctx.projeto_por_pagina:
                campos["projeto"] = ctx.projeto_por_pagina[ids[0]]
        return campos

    def para_remoto(self, campos, resolvidos, ctx):
        valores: Dict[str, Any] = {"titulo": campos["titulo"], "contexto": campos["contexto"],
                                   "prazo": campos["prazo"]}
        if "estado" in resolvidos:
            defn = resolvidos["estado"][1]
            if defn.get("type") == "checkbox":
                valores["estado"] = campos["estado"] == "feito"
            else:
                valores["estado"] = _rotulo_estado(campos["estado"], defn, SINONIMOS_ITEM, ROTULOS_ITEM)
        if "projeto" in resolvidos:
            pagina = ctx.pagina_por_projeto.get(campos.get("projeto") or "")
            valores["projeto"] = [pagina] if pagina else []
        return valores

    def aplicar(self, obj: Item, campos):
        if campos.get("titulo"):
            obj.titulo = campos["titulo"]
        if "estado" in campos:
            novo = campos["estado"] or ("proxima" if obj.estado == "feito" else obj.estado)
            if novo == "feito" and obj.estado != "feito":
                obj.concluido_em = _agora()
            elif novo != "feito":
                obj.concluido_em = None
            obj.estado = novo
        if campos.get("contexto"):
            obj.contexto = campos["contexto"]
        if "prazo" in campos:
            obj.prazo = campos["prazo"]
        if "projeto" in campos:
            obj.projeto_id = campos["projeto"]

    def novo(self, campos, page_id):
        item = Item(
            id=str(uuid.uuid4()),
            titulo=campos["titulo"],
            nota=f"Sincronizado do Notion ({page_id})",
            contexto=campos.get("contexto") or "@qualquer",
            estado="proxima",
            origem="notion",
            ref_externa=f"notion:page:{page_id}",
        )
        self.aplicar(item, {k: v for k, v in campos.items() if k != "contexto"})
        return item

    def exportar_novo(self, obj: Item) -> bool:
        return obj.origem == "local"


class _EntidadeProjeto(_Entidade):
    tabela = "projetos"
    papeis: Papeis = {
        "titulo": (None, ("title",)),
        "estado": (NOMES_ESTADO, ("status", "select")),
        "descricao": (("descricao", "description", "notas", "notes"), ("rich_text",)),
    }
    padrao_criacao: Resolvidos = {"titulo": ("Nome", {"type": "title"})}

    def listar(self, banco):
        return banco.listar_projetos()

    def salvar(self, banco, obj):
        banco.salvar_projeto(obj)

    def campos_locais(self, obj: Projeto):
        return {"titulo": obj.nome, "estado": obj.estado, "descricao": obj.descricao}

    def de_remoto(self, valores, resolvidos, ctx):
        campos: Dict[str, Any] = {"titulo": str(valores.get("titulo") or "").strip()}
        if "estado" in valores:
            campos["estado"] = _estado_de_texto(valores["estado"], SINONIMOS_PROJETO)
        if "descricao" in valores:
            campos["descricao"] = str(valores["descricao"] or "")
        return campos

    def para_remoto(self, campos, resolvidos, ctx):
        valores = dict(campos)
        if "estado" in resolvidos:
            valores["estado"] = _rotulo_estado(campos["estado"], resolvidos["estado"][1],
                                               SINONIMOS_PROJETO, ROTULOS_PROJETO)
        return valores

    def aplicar(self, obj: Projeto, campos):
        if campos.get("titulo"):
            obj.nome = campos["titulo"]
        if campos.get("estado"):
            if campos["estado"] == "concluido" and obj.estado != "concluido":
                obj.concluido_em = _agora()
            elif campos["estado"] != "concluido":
                obj.concluido_em = None
            obj.estado = campos["estado"]
        if "descricao" in campos:
            obj.descricao = campos["descricao"]

    def novo(self, campos, page_id):
        proj = Projeto(id=str(uuid.uuid4()), nome=campos["titulo"])
        self.aplicar(proj, campos)
        return proj


class _EntidadeLeitura(_Entidade):
    tabela = "leituras"
    papeis: Papeis = {
        "titulo": (None, ("title",)),
        "estado": (NOMES_ESTADO + ("lido", "read"), ("status", "select", "checkbox")),
        "autor": (("autor", "autora", "author"), ("rich_text",)),
        "tipo": (("tipo", "type"), ("select",)),
        "paginas_total": (("paginas", "paginas total", "total de paginas", "pages"), ("number",)),
        "paginas_lidas": (("lidas", "paginas lidas", "pages read"), ("number",)),
        "fonte_url": (("url", "link", "fonte"), ("url",)),
    }
    padrao_criacao: Resolvidos = {"titulo": ("Nome", {"type": "title"})}

    def listar(self, banco):
        return banco.listar_leituras()

    def salvar(self, banco, obj):
        banco.salvar_leitura(obj)

    def campos_locais(self, obj: Leitura):
        return {"titulo": obj.titulo, "estado": obj.estado, "autor": obj.autor, "tipo": obj.tipo,
                "paginas_total": obj.paginas_total, "paginas_lidas": obj.paginas_lidas,
                "fonte_url": obj.fonte_url}

    def de_remoto(self, valores, resolvidos, ctx):
        campos: Dict[str, Any] = {"titulo": str(valores.get("titulo") or "").strip()}
        if "estado" in valores:
            v = valores["estado"]
            campos["estado"] = ("lido" if v else "") if isinstance(v, bool) else _estado_de_texto(v, SINONIMOS_LEITURA)
        if "autor" in valores:
            campos["autor"] = str(valores["autor"] or "")
        if valores.get("tipo"):
            t = _norm(valores["tipo"])
            campos["tipo"] = "artigo" if t in ("artigo", "article", "paper") else "livro"
        for k in ("paginas_total", "paginas_lidas"):
            if k in valores and valores[k] is not None:
                try:
                    campos[k] = max(0, int(valores[k]))
                except (TypeError, ValueError):
                    pass
        if "fonte_url" in valores:
            campos["fonte_url"] = str(valores["fonte_url"] or "")
        return campos

    def para_remoto(self, campos, resolvidos, ctx):
        valores = dict(campos)
        if "estado" in resolvidos:
            defn = resolvidos["estado"][1]
            if defn.get("type") == "checkbox":
                valores["estado"] = campos["estado"] == "lido"
            else:
                valores["estado"] = _rotulo_estado(campos["estado"], defn, SINONIMOS_LEITURA, ROTULOS_LEITURA)
        if "tipo" in resolvidos:
            valores["tipo"] = "Artigo" if campos["tipo"] == "artigo" else "Livro"
        return valores

    def aplicar(self, obj: Leitura, campos):
        if campos.get("titulo"):
            obj.titulo = campos["titulo"]
        if "estado" in campos:
            novo = campos["estado"] or ("quero_ler" if obj.estado == "lido" else obj.estado)
            if novo == "lido" and obj.estado != "lido":
                obj.concluido_em = _agora()
            elif novo != "lido":
                obj.concluido_em = None
            obj.estado = novo
        for k in ("autor", "tipo", "paginas_total", "paginas_lidas", "fonte_url"):
            if k in campos:
                setattr(obj, k, campos[k])

    def novo(self, campos, page_id):
        leitura = Leitura(id=str(uuid.uuid4()), titulo=campos["titulo"], tipo="livro", estado="quero_ler")
        self.aplicar(leitura, campos)
        return leitura

    def vincular_existente(self, banco, campos):
        existente = banco.buscar_leitura_por_titulo(campos["titulo"])
        if existente and not banco.obter_mapeamento_notion(self.tabela, existente.id):
            return existente
        return None


ITENS = _EntidadeItem()
PROJETOS = _EntidadeProjeto()
LEITURAS = _EntidadeLeitura()


def _novo_contador() -> Dict[str, int]:
    return {"puxadas": 0, "atualizadas_local": 0, "empurradas": 0,
            "atualizadas_remoto": 0, "conflitos": 0, "erros": 0}


def _montar_propriedades(ent: _Entidade, obj: Any, resolvidos: Resolvidos, ctx: _Contexto) -> Dict[str, Any]:
    valores = ent.para_remoto(ent.campos_locais(obj), resolvidos, ctx)
    props: Dict[str, Any] = {}
    for papel, (nome, defn) in resolvidos.items():
        if papel not in valores:
            continue
        prop = _montar_propriedade(defn.get("type", ""), valores[papel])
        if prop is not None:
            props[nome] = prop
    return props


def sincronizar_entidade(
    ent: _Entidade,
    banco: ArmazenamentoGTD,
    notion: ClienteNotion,
    database_id: str,
    direcao: str,
    politica: str = "remoto",
) -> Dict[str, int]:
    """Sincroniza uma base do Notion com a tabela local correspondente."""
    cont = _novo_contador()
    if not database_id or not (pode_importar(direcao) or pode_exportar(direcao)):
        return cont

    ctx = _Contexto(banco)
    locais = ent.listar(banco)
    esquema_cache: List[Dict[str, Any]] = []

    def esquema() -> Dict[str, Any]:
        # A pagina traz o tipo das propriedades, mas so o esquema traz as opcoes de select/status.
        if not esquema_cache:
            esquema_cache.append(notion.obter_esquema(database_id) or {})
        return esquema_cache[0]
    por_pagina: Dict[str, Tuple[Any, Dict[str, Any]]] = {}
    for obj in locais:
        m = banco.obter_mapeamento_notion(ent.tabela, obj.id)
        if m and m.get("id_notion"):
            por_pagina[m["id_notion"]] = (obj, m)

    for pag in notion.consultar_banco(database_id):
        if pag.get("archived") or pag.get("in_trash"):
            continue
        page_id = pag.get("id") or ""
        props = pag.get("properties") or {}
        resolvidos = resolver_papeis(props, ent.papeis)
        if not page_id or "titulo" not in resolvidos:
            continue
        valores = {papel: _valor_propriedade(props[nome]) for papel, (nome, _) in resolvidos.items()}
        campos = ent.de_remoto(valores, resolvidos, ctx)
        if not campos.get("titulo"):
            continue
        editado = pag.get("last_edited_time", "") or ""

        par = por_pagina.get(page_id)
        if par is None:
            if not pode_importar(direcao):
                continue
            obj = ent.vincular_existente(banco, campos)
            if obj is None:
                obj = ent.novo(campos, page_id)
            else:
                ent.aplicar(obj, campos)
            ent.salvar(banco, obj)
            banco.salvar_mapeamento_notion(ent.tabela, obj.id, page_id, editado)
            salvar_impressao(banco, ent.tabela, obj.id, impressao(ent.campos_locais(obj)))
            por_pagina[page_id] = (obj, {"id_notion": page_id, "last_edited_time": editado})
            cont["puxadas"] += 1
            continue

        obj, mapa = par
        remoto_mudou = pode_importar(direcao) and editado != (mapa.get("last_edited_time") or "")
        local_mudou = pode_exportar(direcao) and (
            impressao(ent.campos_locais(obj)) != obter_impressao(banco, ent.tabela, obj.id)
        )
        if remoto_mudou and local_mudou:
            cont["conflitos"] += 1
        vencedor = resolver_conflito(remoto_mudou, local_mudou, politica)

        if vencedor == "remoto":
            ent.aplicar(obj, campos)
            ent.salvar(banco, obj)
            banco.salvar_mapeamento_notion(ent.tabela, obj.id, page_id, editado)
            salvar_impressao(banco, ent.tabela, obj.id, impressao(ent.campos_locais(obj)))
            cont["atualizadas_local"] += 1
        elif vencedor == "local":
            resolvidos_envio = resolver_papeis(esquema(), ent.papeis)
            if "titulo" not in resolvidos_envio:
                resolvidos_envio = resolvidos
            props_envio = _montar_propriedades(ent, obj, resolvidos_envio, ctx)
            resp = notion.atualizar_pagina(page_id, props_envio) if props_envio else {}
            if resp is None:
                cont["erros"] += 1
                continue
            novo_editado = resp.get("last_edited_time") or editado
            banco.salvar_mapeamento_notion(ent.tabela, obj.id, page_id, novo_editado)
            salvar_impressao(banco, ent.tabela, obj.id, impressao(ent.campos_locais(obj)))
            cont["atualizadas_remoto"] += 1

    if pode_exportar(direcao):
        resolvidos_criacao: Optional[Resolvidos] = None
        for obj in locais:
            if banco.obter_mapeamento_notion(ent.tabela, obj.id) or not ent.exportar_novo(obj):
                continue
            if resolvidos_criacao is None:
                resolvidos_criacao = resolver_papeis(esquema(), ent.papeis)
                if "titulo" not in resolvidos_criacao:
                    resolvidos_criacao = dict(ent.padrao_criacao)
            props_criacao = _montar_propriedades(ent, obj, resolvidos_criacao, ctx)
            nova = notion.criar_pagina(database_id, props_criacao)
            if nova and nova.get("id"):
                banco.salvar_mapeamento_notion(ent.tabela, obj.id, nova["id"], nova.get("last_edited_time", ""))
                salvar_impressao(banco, ent.tabela, obj.id, impressao(ent.campos_locais(obj)))
                cont["empurradas"] += 1
            else:
                cont["erros"] += 1

    return cont


def sincronizar_notion_completo(
    banco: ArmazenamentoGTD,
    notion: ClienteNotion,
    direcao: str = "bidirecional",
    politica: str = "remoto",
) -> Dict[str, Any]:
    """Sincroniza projetos, tarefas e leituras (nessa ordem, para resolver a relacao Projeto)."""
    resultado: Dict[str, Any] = {}
    for nome, ent, db_id in (
        ("projetos", PROJETOS, notion.db_projetos),
        ("tarefas", ITENS, notion.db_tarefas),
        ("leituras", LEITURAS, notion.db_leituras),
    ):
        if not db_id:
            continue
        try:
            resultado[nome] = sincronizar_entidade(ent, banco, notion, db_id, direcao, politica)
        except Exception as e:
            log.warning("Falha ao sincronizar %s com o Notion: %s", nome, type(e).__name__)
            resultado[nome] = dict(_novo_contador(), erros=1)
    return resultado
