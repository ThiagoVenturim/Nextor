"""Camada de banco de dados plugavel baseada em SQLAlchemy Core (Issue #66).

Permite utilizar SQLite local (padrao zero config) ou bancos externos (PostgreSQL,
MySQL, SQL Server via ODBC) informando uma DB_URL no ambiente ou .env.
Todas as operacoes utilizam consultas parametrizadas com SQLAlchemy Core.
"""
from datetime import date, datetime
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from . import config
from .coach.modelos import Plano, Pontuacao, ProgressoAcao, Recurso, Trilha
from .gtd.modelos import Item, Leitura, Projeto

log = logging.getLogger("nextor.db")

try:
    import sqlalchemy as sa
    from sqlalchemy import (
        Column,
        Index,
        Integer,
        MetaData,
        String,
        Table,
        Text,
        case,
        create_engine,
        delete,
        func,
        insert,
        select,
        update,
    )
    from sqlalchemy.pool import StaticPool
    TEM_SQLALCHEMY = True
except ImportError:
    sa = None
    StaticPool = None
    TEM_SQLALCHEMY = False


if TEM_SQLALCHEMY:
    metadata = MetaData()

    # Tabelas GTD
    tabela_itens = Table(
        "itens",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("titulo", Text, nullable=False),
        Column("nota", Text, default=""),
        Column("contexto", String(64), default="@qualquer"),
        Column("estado", String(32), default="inbox"),
        Column("projeto_id", String(64), nullable=True),
        Column("prazo", String(32), nullable=True),
        Column("energia", String(32), default="media"),
        Column("criado_em", String(64), nullable=False),
        Column("concluido_em", String(64), nullable=True),
        Column("origem", String(64), default="local"),
        Column("ref_externa", String(255), nullable=True),
        Column("metadados", Text, default="{}"),
        Index("idx_itens_estado", "estado"),
        Index("idx_itens_contexto", "contexto"),
        Index("idx_itens_projeto", "projeto_id"),
        Index("idx_itens_ref", "ref_externa"),
    )

    tabela_projetos = Table(
        "projetos",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("nome", Text, nullable=False),
        Column("descricao", Text, default=""),
        Column("estado", String(32), default="ativo"),
        Column("criado_em", String(64), nullable=False),
        Column("concluido_em", String(64), nullable=True),
    )

    tabela_leituras = Table(
        "leituras",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("titulo", Text, nullable=False),
        Column("autor", Text, default=""),
        Column("tipo", String(32), default="livro"),
        Column("estado", String(32), default="quero_ler"),
        Column("paginas_total", Integer, default=0),
        Column("paginas_lidas", Integer, default=0),
        Column("fonte_url", Text, default=""),
        Column("criado_em", String(64), nullable=False),
        Column("concluido_em", String(64), nullable=True),
        Index("idx_leituras_estado", "estado"),
    )

    tabela_historico_leitura = Table(
        "historico_leitura",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("leitura_id", String(64), nullable=False),
        Column("paginas", Integer, nullable=False),
        Column("data_registro", String(32), nullable=False),
        Column("criado_em", String(64), nullable=False),
        Index("idx_hist_data", "data_registro"),
    )

    tabela_sincronizacao_notion = Table(
        "sincronizacao_notion",
        metadata,
        Column("tabela", String(64), primary_key=True),
        Column("id_local", String(64), primary_key=True),
        Column("id_notion", String(128), nullable=False),
        Column("last_edited_time", String(64), nullable=True),
    )

    # Tabelas Coach
    tabela_trilhas = Table(
        "trilhas",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("titulo", Text, nullable=False),
        Column("habilidade", String(128), nullable=False),
        Column("nivel", String(64), default="iniciante"),
        Column("descricao", Text, default=""),
        Column("criado_em", String(64), nullable=False),
        Column("atualizado_em", String(64), nullable=True),
        Column("autor", String(128), default="Nextor"),
    )

    tabela_recursos = Table(
        "recursos",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("trilha_id", String(64), nullable=False),
        Column("tipo", String(64), nullable=False),
        Column("titulo", Text, nullable=False),
        Column("ordem", Integer, default=1),
        Column("duracao_min", Integer, default=15),
        Column("dominio_publico", Integer, default=0),
        Column("url", Text, nullable=True),
        Column("descricao", Text, default=""),
        Index("idx_recursos_trilha", "trilha_id", "ordem"),
    )

    tabela_planos = Table(
        "planos",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("trilha_id", String(64), nullable=False),
        Column("criado_em", String(64), nullable=False),
        Column("dias_semana", Integer, default=5),
        Column("minutos_dia", Integer, default=30),
        Column("ativo", Integer, default=1),
        Column("data_inicio", String(64), nullable=False),
    )

    tabela_progresso_acoes = Table(
        "progresso_acoes",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("plano_id", String(64), nullable=False),
        Column("recurso_id", String(64), nullable=False),
        Column("data", String(32), nullable=False),
        Column("estado", String(32), default="pendente"),
        Column("pontos", Integer, default=0),
        Column("concluido_em", String(64), nullable=True),
        Column("gtd_item_id", String(64), nullable=True),
        Index("idx_acoes_plano_data", "plano_id", "data"),
        Index("idx_acoes_estado", "plano_id", "estado"),
    )

    tabela_pontuacoes = Table(
        "pontuacoes",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("plano_id", String(64), nullable=False, unique=True),
        Column("xp_total", Integer, default=0),
        Column("nivel", Integer, default=1),
        Column("streak", Integer, default=0),
        Column("ultima_data", String(64), nullable=True),
    )
else:
    metadata = None
    tabela_itens = None
    tabela_projetos = None
    tabela_leituras = None
    tabela_historico_leitura = None
    tabela_sincronizacao_notion = None
    tabela_trilhas = None
    tabela_recursos = None
    tabela_planos = None
    tabela_progresso_acoes = None
    tabela_pontuacoes = None


_ENGINES: Dict[str, Any] = {}


def obter_engine(db_url: Optional[str] = None) -> Any:
    """Retorna uma Engine SQLAlchemy configurada e com tabelas criadas."""
    if not TEM_SQLALCHEMY:
        raise RuntimeError(
            "SQLAlchemy e necessario para utilizar DB_URL. "
            "Instale com: pip install sqlalchemy"
        )
    url = (db_url or getattr(config, "DB_URL", "") or "").strip()
    if not url:
        raise ValueError("Nenhuma DB_URL informada ou configurada no ambiente")

    if url not in _ENGINES:
        kwargs: Dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if "mode=memory" in url or url in ("sqlite:///:memory:", "sqlite://"):
                kwargs["poolclass"] = StaticPool
        eng = create_engine(url, **kwargs)
        metadata.create_all(eng)
        _ENGINES[url] = eng

    return _ENGINES[url]


class ArmazenamentoGTDSQLAlchemy:
    """Implementacao de armazenamento para GTD utilizando SQLAlchemy Core."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.engine = obter_engine(db_url)

    # --- Itens ---

    def salvar_item(self, item: Item) -> Item:
        meta_str = json.dumps(item.metadados) if isinstance(item.metadados, dict) else "{}"
        valores = {
            "id": item.id,
            "titulo": item.titulo,
            "nota": item.nota or "",
            "contexto": item.contexto or "@qualquer",
            "estado": item.estado or "inbox",
            "projeto_id": item.projeto_id,
            "prazo": item.prazo,
            "energia": item.energia or "media",
            "criado_em": item.criado_em,
            "concluido_em": item.concluido_em,
            "origem": item.origem or "local",
            "ref_externa": item.ref_externa,
            "metadados": meta_str,
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_itens.c.id).where(tabela_itens.c.id == item.id)).first()
            if existe:
                conn.execute(update(tabela_itens).where(tabela_itens.c.id == item.id).values(**valores))
            else:
                conn.execute(insert(tabela_itens).values(**valores))
        return item

    def obter_item(self, item_id: str) -> Optional[Item]:
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_itens).where(tabela_itens.c.id == item_id)).mappings().first()
            if row:
                return Item.from_dict(dict(row))
        return None

    def buscar_item_por_ref(self, ref_externa: str) -> Optional[Item]:
        if not ref_externa:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(
                select(tabela_itens).where(tabela_itens.c.ref_externa == ref_externa)
            ).mappings().first()
            if row:
                return Item.from_dict(dict(row))
        return None

    def listar_itens(
        self,
        estado: Optional[str] = None,
        contexto: Optional[str] = None,
        projeto_id: Optional[str] = None,
    ) -> List[Item]:
        stmt = select(tabela_itens)
        if estado:
            stmt = stmt.where(tabela_itens.c.estado == estado)
        if contexto:
            stmt = stmt.where(tabela_itens.c.contexto == contexto)
        if projeto_id:
            stmt = stmt.where(tabela_itens.c.projeto_id == projeto_id)

        stmt = stmt.order_by(
            case((tabela_itens.c.prazo.is_(None), 1), else_=0),
            tabela_itens.c.prazo.asc(),
            tabela_itens.c.criado_em.desc(),
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [Item.from_dict(dict(r)) for r in rows]

    def remover_item(self, item_id: str) -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(delete(tabela_itens).where(tabela_itens.c.id == item_id))
            return res.rowcount > 0

    # --- Projetos ---

    def salvar_projeto(self, projeto: Projeto) -> Projeto:
        valores = {
            "id": projeto.id,
            "nome": projeto.nome,
            "descricao": projeto.descricao or "",
            "estado": projeto.estado or "ativo",
            "criado_em": projeto.criado_em,
            "concluido_em": projeto.concluido_em,
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_projetos.c.id).where(tabela_projetos.c.id == projeto.id)).first()
            if existe:
                conn.execute(update(tabela_projetos).where(tabela_projetos.c.id == projeto.id).values(**valores))
            else:
                conn.execute(insert(tabela_projetos).values(**valores))
        return projeto

    def obter_projeto(self, projeto_id: str) -> Optional[Projeto]:
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_projetos).where(tabela_projetos.c.id == projeto_id)).mappings().first()
            if row:
                return Projeto.from_dict(dict(row))
        return None

    def listar_projetos(self, estado: Optional[str] = None) -> List[Projeto]:
        stmt = select(tabela_projetos)
        if estado:
            stmt = stmt.where(tabela_projetos.c.estado == estado)
        stmt = stmt.order_by(tabela_projetos.c.criado_em.desc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [Projeto.from_dict(dict(r)) for r in rows]

    def remover_projeto(self, projeto_id: str) -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(delete(tabela_projetos).where(tabela_projetos.c.id == projeto_id))
            return res.rowcount > 0

    # --- Leituras ---

    def salvar_leitura(self, leitura: Leitura) -> Leitura:
        valores = {
            "id": leitura.id,
            "titulo": leitura.titulo,
            "autor": leitura.autor or "",
            "tipo": leitura.tipo or "livro",
            "estado": leitura.estado or "quero_ler",
            "paginas_total": int(leitura.paginas_total or 0),
            "paginas_lidas": int(leitura.paginas_lidas or 0),
            "fonte_url": leitura.fonte_url or "",
            "criado_em": leitura.criado_em,
            "concluido_em": leitura.concluido_em,
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_leituras.c.id).where(tabela_leituras.c.id == leitura.id)).first()
            if existe:
                conn.execute(update(tabela_leituras).where(tabela_leituras.c.id == leitura.id).values(**valores))
            else:
                conn.execute(insert(tabela_leituras).values(**valores))
        return leitura

    def obter_leitura(self, leitura_id: str) -> Optional[Leitura]:
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_leituras).where(tabela_leituras.c.id == leitura_id)).mappings().first()
            if row:
                return Leitura.from_dict(dict(row))
        return None

    def buscar_leitura_por_url(self, fonte_url: str) -> Optional[Leitura]:
        if not fonte_url:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_leituras).where(tabela_leituras.c.fonte_url == fonte_url)).mappings().first()
            if row:
                return Leitura.from_dict(dict(row))
        return None

    def buscar_leitura_por_titulo(self, titulo: str) -> Optional[Leitura]:
        if not titulo:
            return None
        with self.engine.connect() as conn:
            stmt = select(tabela_leituras).where(
                func.lower(func.trim(tabela_leituras.c.titulo)) == func.lower(func.trim(titulo))
            )
            row = conn.execute(stmt).mappings().first()
            if row:
                return Leitura.from_dict(dict(row))
        return None

    def listar_leituras(
        self,
        estado: Optional[str] = None,
        tipo: Optional[str] = None,
    ) -> List[Leitura]:
        stmt = select(tabela_leituras)
        if estado:
            stmt = stmt.where(tabela_leituras.c.estado == estado)
        if tipo:
            stmt = stmt.where(tabela_leituras.c.tipo == tipo)
        stmt = stmt.order_by(
            case((tabela_leituras.c.estado == "lendo", 0), (tabela_leituras.c.estado == "quero_ler", 1), else_=2),
            tabela_leituras.c.criado_em.desc(),
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [Leitura.from_dict(dict(r)) for r in rows]

    def remover_leitura(self, leitura_id: str) -> bool:
        with self.engine.begin() as conn:
            res = conn.execute(delete(tabela_leituras).where(tabela_leituras.c.id == leitura_id))
            conn.execute(
                delete(tabela_historico_leitura).where(tabela_historico_leitura.c.leitura_id == leitura_id)
            )
            return res.rowcount > 0

    # --- Historico de Leitura ---

    def registrar_progresso_leitura(
        self,
        leitura_id: str,
        paginas: int,
        data_registro: Optional[str] = None,
    ) -> int:
        data_efetiva = data_registro or date.today().isoformat()
        agora = datetime.now().isoformat(timespec="seconds")
        hist_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(tabela_historico_leitura).values(
                    id=hist_id,
                    leitura_id=leitura_id,
                    paginas=int(paginas),
                    data_registro=data_efetiva,
                    criado_em=agora,
                )
            )
        return self.paginas_lidas_na_data(data_efetiva)

    def paginas_lidas_na_data(self, data_registro: Optional[str] = None) -> int:
        data_efetiva = data_registro or date.today().isoformat()
        with self.engine.connect() as conn:
            stmt = select(func.coalesce(func.sum(tabela_historico_leitura.c.paginas), 0)).where(
                tabela_historico_leitura.c.data_registro == data_efetiva
            )
            val = conn.execute(stmt).scalar()
            return int(val or 0)

    # --- Notion Sync Metadata ---

    def salvar_mapeamento_notion(
        self,
        tabela: str,
        id_local: str,
        id_notion: str,
        last_edited_time: Optional[str] = None,
    ) -> None:
        with self.engine.begin() as conn:
            stmt = select(tabela_sincronizacao_notion.c.id_local).where(
                tabela_sincronizacao_notion.c.tabela == tabela,
                tabela_sincronizacao_notion.c.id_local == id_local,
            )
            existe = conn.execute(stmt).first()
            if existe:
                conn.execute(
                    update(tabela_sincronizacao_notion).where(
                        tabela_sincronizacao_notion.c.tabela == tabela,
                        tabela_sincronizacao_notion.c.id_local == id_local,
                    ).values(id_notion=id_notion, last_edited_time=last_edited_time)
                )
            else:
                conn.execute(
                    insert(tabela_sincronizacao_notion).values(
                        tabela=tabela,
                        id_local=id_local,
                        id_notion=id_notion,
                        last_edited_time=last_edited_time,
                    )
                )

    def obter_mapeamento_notion(self, tabela: str, id_local: str) -> Optional[Dict[str, str]]:
        with self.engine.connect() as conn:
            stmt = select(tabela_sincronizacao_notion).where(
                tabela_sincronizacao_notion.c.tabela == tabela,
                tabela_sincronizacao_notion.c.id_local == id_local,
            )
            row = conn.execute(stmt).mappings().first()
            if row:
                return dict(row)
        return None


class ArmazenamentoCoachSQLAlchemy:
    """Implementacao de armazenamento para Coach utilizando SQLAlchemy Core."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.engine = obter_engine(db_url)

    # --- Trilhas e Recursos ---

    def salvar_trilha(self, trilha: Trilha) -> Trilha:
        agora = datetime.now().isoformat(timespec="seconds")
        valores = {
            "id": trilha.id,
            "titulo": trilha.titulo,
            "habilidade": trilha.habilidade,
            "nivel": trilha.nivel or "iniciante",
            "descricao": trilha.descricao or "",
            "criado_em": trilha.criado_em,
            "atualizado_em": trilha.atualizado_em or agora,
            "autor": trilha.autor or "Nextor",
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_trilhas.c.id).where(tabela_trilhas.c.id == trilha.id)).first()
            if existe:
                conn.execute(update(tabela_trilhas).where(tabela_trilhas.c.id == trilha.id).values(**valores))
            else:
                conn.execute(insert(tabela_trilhas).values(**valores))

            for r in trilha.recursos:
                r_val = {
                    "id": r.id,
                    "trilha_id": trilha.id,
                    "tipo": r.tipo,
                    "titulo": r.titulo,
                    "ordem": int(r.ordem or 1),
                    "duracao_min": int(r.duracao_min or 15),
                    "dominio_publico": 1 if r.dominio_publico else 0,
                    "url": r.url,
                    "descricao": r.descricao or "",
                }
                r_existe = conn.execute(select(tabela_recursos.c.id).where(tabela_recursos.c.id == r.id)).first()
                if r_existe:
                    conn.execute(update(tabela_recursos).where(tabela_recursos.c.id == r.id).values(**r_val))
                else:
                    conn.execute(insert(tabela_recursos).values(**r_val))
        return self.obter_trilha(trilha.id) or trilha

    def obter_trilha(self, trilha_id: str) -> Optional[Trilha]:
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_trilhas).where(tabela_trilhas.c.id == trilha_id)).mappings().first()
            if not row:
                return None
            dados = dict(row)
            r_rows = conn.execute(
                select(tabela_recursos)
                .where(tabela_recursos.c.trilha_id == trilha_id)
                .order_by(tabela_recursos.c.ordem.asc())
            ).mappings().all()
            recursos = []
            for r in r_rows:
                rd = dict(r)
                rd["dominio_publico"] = bool(rd["dominio_publico"])
                recursos.append(Recurso.from_dict(rd))
            dados["recursos"] = recursos
            return Trilha.from_dict(dados)

    def listar_trilhas(self) -> List[Trilha]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(tabela_trilhas.c.id).order_by(tabela_trilhas.c.titulo.asc())).scalars().all()
        resultado: List[Trilha] = []
        for tid in rows:
            t = self.obter_trilha(tid)
            if t:
                resultado.append(t)
        return resultado

    def salvar_recurso(self, recurso: Recurso) -> Recurso:
        r_val = {
            "id": recurso.id,
            "trilha_id": recurso.trilha_id,
            "tipo": recurso.tipo,
            "titulo": recurso.titulo,
            "ordem": int(recurso.ordem or 1),
            "duracao_min": int(recurso.duracao_min or 15),
            "dominio_publico": 1 if recurso.dominio_publico else 0,
            "url": recurso.url,
            "descricao": recurso.descricao or "",
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_recursos.c.id).where(tabela_recursos.c.id == recurso.id)).first()
            if existe:
                conn.execute(update(tabela_recursos).where(tabela_recursos.c.id == recurso.id).values(**r_val))
            else:
                conn.execute(insert(tabela_recursos).values(**r_val))
        return recurso

    def obter_recurso(self, recurso_id: str) -> Optional[Recurso]:
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_recursos).where(tabela_recursos.c.id == recurso_id)).mappings().first()
            if not row:
                return None
            d = dict(row)
            d["dominio_publico"] = bool(d["dominio_publico"])
            return Recurso.from_dict(d)

    # --- Planos ---

    def salvar_plano(self, plano: Plano) -> Plano:
        p_val = {
            "id": plano.id,
            "trilha_id": plano.trilha_id,
            "criado_em": plano.criado_em,
            "dias_semana": int(plano.dias_semana or 5),
            "minutos_dia": int(plano.minutos_dia or 30),
            "ativo": 1 if plano.ativo else 0,
            "data_inicio": plano.data_inicio,
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_planos.c.id).where(tabela_planos.c.id == plano.id)).first()
            if existe:
                conn.execute(update(tabela_planos).where(tabela_planos.c.id == plano.id).values(**p_val))
            else:
                conn.execute(insert(tabela_planos).values(**p_val))
        return plano

    def obter_plano(self, plano_id: str) -> Optional[Plano]:
        with self.engine.connect() as conn:
            row = conn.execute(select(tabela_planos).where(tabela_planos.c.id == plano_id)).mappings().first()
            if not row:
                return None
            d = dict(row)
            d["ativo"] = bool(d["ativo"])
            return Plano.from_dict(d)

    def listar_planos(self, ativo_apenas: bool = False) -> List[Plano]:
        stmt = select(tabela_planos)
        if ativo_apenas:
            stmt = stmt.where(tabela_planos.c.ativo == 1)
        stmt = stmt.order_by(tabela_planos.c.criado_em.desc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            planos = []
            for r in rows:
                d = dict(r)
                d["ativo"] = bool(d["ativo"])
                planos.append(Plano.from_dict(d))
            return planos

    # --- Progresso das Acoes ---

    def salvar_acao(self, acao: ProgressoAcao) -> ProgressoAcao:
        a_val = {
            "id": acao.id,
            "plano_id": acao.plano_id,
            "recurso_id": acao.recurso_id,
            "data": acao.data,
            "estado": acao.estado or "pendente",
            "pontos": int(acao.pontos or 0),
            "concluido_em": acao.concluido_em,
            "gtd_item_id": acao.gtd_item_id,
        }
        with self.engine.begin() as conn:
            existe = conn.execute(select(tabela_progresso_acoes.c.id).where(tabela_progresso_acoes.c.id == acao.id)).first()
            if existe:
                conn.execute(update(tabela_progresso_acoes).where(tabela_progresso_acoes.c.id == acao.id).values(**a_val))
            else:
                conn.execute(insert(tabela_progresso_acoes).values(**a_val))
        return acao

    def obter_acao(self, acao_id: str) -> Optional[ProgressoAcao]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(tabela_progresso_acoes).where(tabela_progresso_acoes.c.id == acao_id)
            ).mappings().first()
            if not row:
                return None
            return ProgressoAcao.from_dict(dict(row))

    def obter_acao_por_recurso(self, plano_id: str, recurso_id: str) -> Optional[ProgressoAcao]:
        with self.engine.connect() as conn:
            stmt = select(tabela_progresso_acoes).where(
                tabela_progresso_acoes.c.plano_id == plano_id,
                tabela_progresso_acoes.c.recurso_id == recurso_id,
            ).order_by(tabela_progresso_acoes.c.data.asc()).limit(1)
            row = conn.execute(stmt).mappings().first()
            if not row:
                return None
            return ProgressoAcao.from_dict(dict(row))

    def listar_acoes(
        self,
        plano_id: str,
        data: Optional[str] = None,
        estado: Optional[str] = None,
    ) -> List[ProgressoAcao]:
        stmt = select(tabela_progresso_acoes).where(tabela_progresso_acoes.c.plano_id == plano_id)
        if data:
            stmt = stmt.where(tabela_progresso_acoes.c.data == data[:10])
        if estado:
            stmt = stmt.where(tabela_progresso_acoes.c.estado == estado)
        stmt = stmt.order_by(tabela_progresso_acoes.c.data.asc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [ProgressoAcao.from_dict(dict(r)) for r in rows]

    # --- Pontuacao e Gamificacao ---

    def salvar_pontuacao(self, pontuacao: Pontuacao) -> Pontuacao:
        p_val = {
            "id": pontuacao.id,
            "plano_id": pontuacao.plano_id,
            "xp_total": int(pontuacao.xp_total or 0),
            "nivel": int(pontuacao.nivel or 1),
            "streak": int(pontuacao.streak or 0),
            "ultima_data": pontuacao.ultima_data,
        }
        with self.engine.begin() as conn:
            existe = conn.execute(
                select(tabela_pontuacoes.c.id).where(tabela_pontuacoes.c.plano_id == pontuacao.plano_id)
            ).first()
            if existe:
                conn.execute(
                    update(tabela_pontuacoes)
                    .where(tabela_pontuacoes.c.plano_id == pontuacao.plano_id)
                    .values(**p_val)
                )
            else:
                conn.execute(insert(tabela_pontuacoes).values(**p_val))
        return pontuacao

    def obter_pontuacao(self, plano_id: str) -> Optional[Pontuacao]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(tabela_pontuacoes).where(tabela_pontuacoes.c.plano_id == plano_id)
            ).mappings().first()
            if not row:
                return None
            return Pontuacao.from_dict(dict(row))
