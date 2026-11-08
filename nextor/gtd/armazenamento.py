"""Persistencia em SQLite para o GTD do Nextor.

Armazena itens, projetos, leituras e progresso diario em banco local.
Utiliza exclusivamente consultas parametrizadas com placeholders '?'.
"""
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from .. import config
from .modelos import Item, Projeto, Leitura


def _obter_caminho_padrao() -> Path:
    if hasattr(config, "GTD_DB") and config.GTD_DB:
        return Path(config.GTD_DB).resolve()
    return (Path.home() / ".nextor" / "gtd.db").resolve()


class ArmazenamentoGTD:
    """Gerencia a conexao SQLite e operacoes CRUD para entidades GTD."""

    def __init__(self, caminho_db: Optional[Union[str, Path]] = None):
        self.caminho = Path(caminho_db).resolve() if caminho_db else _obter_caminho_padrao()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar_banco()

    @contextmanager
    def _conexao(self):
        conn = sqlite3.connect(str(self.caminho))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _inicializar_banco(self) -> None:
        """Cria as tabelas necessarias se nao existirem."""
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS itens (
                    id TEXT PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    nota TEXT DEFAULT '',
                    contexto TEXT DEFAULT '@qualquer',
                    estado TEXT DEFAULT 'inbox',
                    projeto_id TEXT,
                    prazo TEXT,
                    energia TEXT DEFAULT 'media',
                    criado_em TEXT NOT NULL,
                    concluido_em TEXT,
                    origem TEXT DEFAULT 'local',
                    ref_externa TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projetos (
                    id TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    descricao TEXT DEFAULT '',
                    estado TEXT DEFAULT 'ativo',
                    criado_em TEXT NOT NULL,
                    concluido_em TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS leituras (
                    id TEXT PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    autor TEXT DEFAULT '',
                    tipo TEXT DEFAULT 'livro',
                    estado TEXT DEFAULT 'quero_ler',
                    paginas_total INTEGER DEFAULT 0,
                    paginas_lidas INTEGER DEFAULT 0,
                    fonte_url TEXT DEFAULT '',
                    criado_em TEXT NOT NULL,
                    concluido_em TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS historico_leitura (
                    id TEXT PRIMARY KEY,
                    leitura_id TEXT NOT NULL,
                    paginas INTEGER NOT NULL,
                    data_registro TEXT NOT NULL,
                    criado_em TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sincronizacao_notion (
                    tabela TEXT NOT NULL,
                    id_local TEXT NOT NULL,
                    id_notion TEXT NOT NULL,
                    last_edited_time TEXT,
                    PRIMARY KEY (tabela, id_local)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_itens_estado ON itens(estado)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_itens_contexto ON itens(contexto)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_itens_projeto ON itens(projeto_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_itens_ref ON itens(ref_externa)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leituras_estado ON leituras(estado)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_data ON historico_leitura(data_registro)")
            conn.commit()

    # --- Operacoes de Itens ---

    def salvar_item(self, item: Item) -> Item:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO itens (
                    id, titulo, nota, contexto, estado, projeto_id,
                    prazo, energia, criado_em, concluido_em, origem, ref_externa
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo = excluded.titulo,
                    nota = excluded.nota,
                    contexto = excluded.contexto,
                    estado = excluded.estado,
                    projeto_id = excluded.projeto_id,
                    prazo = excluded.prazo,
                    energia = excluded.energia,
                    concluido_em = excluded.concluido_em,
                    origem = excluded.origem,
                    ref_externa = excluded.ref_externa
            """, (
                item.id, item.titulo, item.nota, item.contexto, item.estado,
                item.projeto_id, item.prazo, item.energia, item.criado_em,
                item.concluido_em, item.origem, item.ref_externa
            ))
            conn.commit()
        return item

    def obter_item(self, item_id: str) -> Optional[Item]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM itens WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            if row:
                return Item.from_dict(dict(row))
        return None

    def buscar_item_por_ref(self, ref_externa: str) -> Optional[Item]:
        if not ref_externa:
            return None
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM itens WHERE ref_externa = ?", (ref_externa,))
            row = cursor.fetchone()
            if row:
                return Item.from_dict(dict(row))
        return None

    def listar_itens(
        self,
        estado: Optional[str] = None,
        contexto: Optional[str] = None,
        projeto_id: Optional[str] = None,
    ) -> List[Item]:
        query = "SELECT * FROM itens WHERE 1=1"
        params: List[Any] = []
        if estado:
            query += " AND estado = ?"
            params.append(estado)
        if contexto:
            query += " AND contexto = ?"
            params.append(contexto)
        if projeto_id:
            query += " AND projeto_id = ?"
            params.append(projeto_id)

        query += " ORDER BY CASE WHEN prazo IS NULL THEN 1 ELSE 0 END, prazo ASC, criado_em DESC"
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [Item.from_dict(dict(row)) for row in cursor.fetchall()]

    def remover_item(self, item_id: str) -> bool:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM itens WHERE id = ?", (item_id,))
            removido = cursor.rowcount > 0
            conn.commit()
            return removido

    # --- Operacoes de Projetos ---

    def salvar_projeto(self, projeto: Projeto) -> Projeto:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO projetos (id, nome, descricao, estado, criado_em, concluido_em)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nome = excluded.nome,
                    descricao = excluded.descricao,
                    estado = excluded.estado,
                    concluido_em = excluded.concluido_em
            """, (
                projeto.id, projeto.nome, projeto.descricao,
                projeto.estado, projeto.criado_em, projeto.concluido_em
            ))
            conn.commit()
        return projeto

    def obter_projeto(self, projeto_id: str) -> Optional[Projeto]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projetos WHERE id = ?", (projeto_id,))
            row = cursor.fetchone()
            if row:
                return Projeto.from_dict(dict(row))
        return None

    def listar_projetos(self, estado: Optional[str] = None) -> List[Projeto]:
        query = "SELECT * FROM projetos WHERE 1=1"
        params: List[Any] = []
        if estado:
            query += " AND estado = ?"
            params.append(estado)
        query += " ORDER BY criado_em DESC"
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [Projeto.from_dict(dict(row)) for row in cursor.fetchall()]

    def remover_projeto(self, projeto_id: str) -> bool:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM projetos WHERE id = ?", (projeto_id,))
            removido = cursor.rowcount > 0
            conn.commit()
            return removido

    # --- Operacoes de Leituras ---

    def salvar_leitura(self, leitura: Leitura) -> Leitura:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leituras (
                    id, titulo, autor, tipo, estado,
                    paginas_total, paginas_lidas, fonte_url, criado_em, concluido_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo = excluded.titulo,
                    autor = excluded.autor,
                    tipo = excluded.tipo,
                    estado = excluded.estado,
                    paginas_total = excluded.paginas_total,
                    paginas_lidas = excluded.paginas_lidas,
                    fonte_url = excluded.fonte_url,
                    concluido_em = excluded.concluido_em
            """, (
                leitura.id, leitura.titulo, leitura.autor, leitura.tipo, leitura.estado,
                leitura.paginas_total, leitura.paginas_lidas, leitura.fonte_url,
                leitura.criado_em, leitura.concluido_em
            ))
            conn.commit()
        return leitura

    def obter_leitura(self, leitura_id: str) -> Optional[Leitura]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leituras WHERE id = ?", (leitura_id,))
            row = cursor.fetchone()
            if row:
                return Leitura.from_dict(dict(row))
        return None

    def buscar_leitura_por_url(self, fonte_url: str) -> Optional[Leitura]:
        if not fonte_url:
            return None
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leituras WHERE fonte_url = ?", (fonte_url,))
            row = cursor.fetchone()
            if row:
                return Leitura.from_dict(dict(row))
        return None

    def buscar_leitura_por_titulo(self, titulo: str) -> Optional[Leitura]:
        if not titulo:
            return None
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM leituras WHERE LOWER(TRIM(titulo)) = LOWER(TRIM(?))", (titulo,))
            row = cursor.fetchone()
            if row:
                return Leitura.from_dict(dict(row))
        return None

    def listar_leituras(
        self,
        estado: Optional[str] = None,
        tipo: Optional[str] = None,
    ) -> List[Leitura]:
        query = "SELECT * FROM leituras WHERE 1=1"
        params: List[Any] = []
        if estado:
            query += " AND estado = ?"
            params.append(estado)
        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)
        query += " ORDER BY CASE WHEN estado = 'lendo' THEN 0 WHEN estado = 'quero_ler' THEN 1 ELSE 2 END, criado_em DESC"
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [Leitura.from_dict(dict(row)) for row in cursor.fetchall()]

    def remover_leitura(self, leitura_id: str) -> bool:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM leituras WHERE id = ?", (leitura_id,))
            cursor.execute("DELETE FROM historico_leitura WHERE leitura_id = ?", (leitura_id,))
            removido = cursor.rowcount > 0
            conn.commit()
            return removido

    # --- Historico e Metas de Leitura ---

    def registrar_progresso_leitura(
        self,
        leitura_id: str,
        paginas: int,
        data_registro: Optional[str] = None,
    ) -> int:
        """Registra sessao de leitura e retorna total lido na data."""
        data_efetiva = data_registro or date.today().isoformat()
        agora = datetime.now().isoformat(timespec="seconds")
        hist_id = str(uuid.uuid4())
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO historico_leitura (id, leitura_id, paginas, data_registro, criado_em)
                VALUES (?, ?, ?, ?, ?)
            """, (hist_id, leitura_id, paginas, data_efetiva, agora))
            conn.commit()
        return self.paginas_lidas_na_data(data_efetiva)

    def paginas_lidas_na_data(self, data_registro: Optional[str] = None) -> int:
        data_efetiva = data_registro or date.today().isoformat()
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(SUM(paginas), 0) FROM historico_leitura
                WHERE data_registro = ?
            """, (data_efetiva,))
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    # --- Notion Sync Metadata ---

    def salvar_mapeamento_notion(
        self,
        tabela: str,
        id_local: str,
        id_notion: str,
        last_edited_time: Optional[str] = None,
    ) -> None:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sincronizacao_notion (tabela, id_local, id_notion, last_edited_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tabela, id_local) DO UPDATE SET
                    id_notion = excluded.id_notion,
                    last_edited_time = excluded.last_edited_time
            """, (tabela, id_local, id_notion, last_edited_time))
            conn.commit()

    def obter_mapeamento_notion(self, tabela: str, id_local: str) -> Optional[Dict[str, str]]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sincronizacao_notion WHERE tabela = ? AND id_local = ?
            """, (tabela, id_local))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None
