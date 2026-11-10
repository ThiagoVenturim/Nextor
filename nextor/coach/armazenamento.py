"""Persistencia em SQLite parametrizada para o coach de estudos do Nextor (Issue #57)."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import List, Optional, Union

from .. import config
from .modelos import Plano, Pontuacao, ProgressoAcao, Recurso, Trilha


def _obter_caminho_padrao() -> Path:
    if hasattr(config, "COACH_DB") and config.COACH_DB:
        return Path(config.COACH_DB).resolve()
    return (Path.home() / ".nextor" / "coach.db").resolve()


class ArmazenamentoCoach:
    """Gerencia conexao SQLite e operacoes CRUD para o coach de estudos."""

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
        """Cria as tabelas necessarias de forma parametrizada e idempotente."""
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trilhas (
                    id TEXT PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    habilidade TEXT NOT NULL,
                    nivel TEXT DEFAULT 'iniciante',
                    descricao TEXT DEFAULT '',
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT,
                    autor TEXT DEFAULT 'Nextor'
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recursos (
                    id TEXT PRIMARY KEY,
                    trilha_id TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    ordem INTEGER DEFAULT 1,
                    duracao_min INTEGER DEFAULT 15,
                    dominio_publico INTEGER DEFAULT 0,
                    url TEXT,
                    descricao TEXT DEFAULT '',
                    FOREIGN KEY (trilha_id) REFERENCES trilhas(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS planos (
                    id TEXT PRIMARY KEY,
                    trilha_id TEXT NOT NULL,
                    criado_em TEXT NOT NULL,
                    dias_semana INTEGER DEFAULT 5,
                    minutos_dia INTEGER DEFAULT 30,
                    ativo INTEGER DEFAULT 1,
                    data_inicio TEXT NOT NULL,
                    FOREIGN KEY (trilha_id) REFERENCES trilhas(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS progresso_acoes (
                    id TEXT PRIMARY KEY,
                    plano_id TEXT NOT NULL,
                    recurso_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    estado TEXT DEFAULT 'pendente',
                    pontos INTEGER DEFAULT 0,
                    concluido_em TEXT,
                    gtd_item_id TEXT,
                    FOREIGN KEY (plano_id) REFERENCES planos(id) ON DELETE CASCADE,
                    FOREIGN KEY (recurso_id) REFERENCES recursos(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pontuacoes (
                    id TEXT PRIMARY KEY,
                    plano_id TEXT NOT NULL UNIQUE,
                    xp_total INTEGER DEFAULT 0,
                    nivel INTEGER DEFAULT 1,
                    streak INTEGER DEFAULT 0,
                    ultima_data TEXT,
                    FOREIGN KEY (plano_id) REFERENCES planos(id) ON DELETE CASCADE
                )
            """)
            # Indices para busca rapida
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_recursos_trilha ON recursos(trilha_id, ordem)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acoes_plano_data ON progresso_acoes(plano_id, data)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_acoes_estado ON progresso_acoes(plano_id, estado)")

    # -------------------------------------------------------------
    # Trilhas e Recursos
    # -------------------------------------------------------------

    def salvar_trilha(self, trilha: Trilha) -> Trilha:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trilhas (id, titulo, habilidade, nivel, descricao, criado_em, atualizado_em, autor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo=excluded.titulo,
                    habilidade=excluded.habilidade,
                    nivel=excluded.nivel,
                    descricao=excluded.descricao,
                    atualizado_em=excluded.atualizado_em,
                    autor=excluded.autor
            """, (
                trilha.id,
                trilha.titulo,
                trilha.habilidade,
                trilha.nivel,
                trilha.descricao,
                trilha.criado_em,
                trilha.atualizado_em or datetime.now().isoformat(timespec="seconds"),
                trilha.autor,
            ))

            for r in trilha.recursos:
                cursor.execute("""
                    INSERT INTO recursos (id, trilha_id, tipo, titulo, ordem, duracao_min, dominio_publico, url, descricao)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        trilha_id=excluded.trilha_id,
                        tipo=excluded.tipo,
                        titulo=excluded.titulo,
                        ordem=excluded.ordem,
                        duracao_min=excluded.duracao_min,
                        dominio_publico=excluded.dominio_publico,
                        url=excluded.url,
                        descricao=excluded.descricao
                """, (
                    r.id,
                    trilha.id,
                    r.tipo,
                    r.titulo,
                    r.ordem,
                    r.duracao_min,
                    1 if r.dominio_publico else 0,
                    r.url,
                    r.descricao,
                ))
        return self.obter_trilha(trilha.id) or trilha

    def obter_trilha(self, trilha_id: str) -> Optional[Trilha]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trilhas WHERE id = ?", (trilha_id,))
            linha = cursor.fetchone()
            if not linha:
                return None
            dados = dict(linha)
            cursor.execute("SELECT * FROM recursos WHERE trilha_id = ? ORDER BY ordem ASC", (trilha_id,))
            recursos = []
            for r_row in cursor.fetchall():
                r_dict = dict(r_row)
                r_dict["dominio_publico"] = bool(r_dict["dominio_publico"])
                recursos.append(Recurso.from_dict(r_dict))
            dados["recursos"] = recursos
            return Trilha.from_dict(dados)

    def listar_trilhas(self) -> List[Trilha]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM trilhas ORDER BY titulo ASC")
            ids = [row["id"] for row in cursor.fetchall()]
        resultado: List[Trilha] = []
        for tid in ids:
            t = self.obter_trilha(tid)
            if t:
                resultado.append(t)
        return resultado

    def salvar_recurso(self, recurso: Recurso) -> Recurso:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO recursos (id, trilha_id, tipo, titulo, ordem, duracao_min, dominio_publico, url, descricao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    trilha_id=excluded.trilha_id,
                    tipo=excluded.tipo,
                    titulo=excluded.titulo,
                    ordem=excluded.ordem,
                    duracao_min=excluded.duracao_min,
                    dominio_publico=excluded.dominio_publico,
                    url=excluded.url,
                    descricao=excluded.descricao
            """, (
                recurso.id,
                recurso.trilha_id,
                recurso.tipo,
                recurso.titulo,
                recurso.ordem,
                recurso.duracao_min,
                1 if recurso.dominio_publico else 0,
                recurso.url,
                recurso.descricao,
            ))
        return recurso

    def obter_recurso(self, recurso_id: str) -> Optional[Recurso]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recursos WHERE id = ?", (recurso_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["dominio_publico"] = bool(d["dominio_publico"])
            return Recurso.from_dict(d)

    # -------------------------------------------------------------
    # Planos
    # -------------------------------------------------------------

    def salvar_plano(self, plano: Plano) -> Plano:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO planos (id, trilha_id, criado_em, dias_semana, minutos_dia, ativo, data_inicio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    trilha_id=excluded.trilha_id,
                    dias_semana=excluded.dias_semana,
                    minutos_dia=excluded.minutos_dia,
                    ativo=excluded.ativo,
                    data_inicio=excluded.data_inicio
            """, (
                plano.id,
                plano.trilha_id,
                plano.criado_em,
                plano.dias_semana,
                plano.minutos_dia,
                1 if plano.ativo else 0,
                plano.data_inicio,
            ))
        return plano

    def obter_plano(self, plano_id: str) -> Optional[Plano]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM planos WHERE id = ?", (plano_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["ativo"] = bool(d["ativo"])
            return Plano.from_dict(d)

    def listar_planos(self, ativo_apenas: bool = False) -> List[Plano]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            if ativo_apenas:
                cursor.execute("SELECT * FROM planos WHERE ativo = 1 ORDER BY criado_em DESC")
            else:
                cursor.execute("SELECT * FROM planos ORDER BY criado_em DESC")
            planos = []
            for row in cursor.fetchall():
                d = dict(row)
                d["ativo"] = bool(d["ativo"])
                planos.append(Plano.from_dict(d))
            return planos

    # -------------------------------------------------------------
    # Progresso das Acoes
    # -------------------------------------------------------------

    def salvar_acao(self, acao: ProgressoAcao) -> ProgressoAcao:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO progresso_acoes (id, plano_id, recurso_id, data, estado, pontos, concluido_em, gtd_item_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    plano_id=excluded.plano_id,
                    recurso_id=excluded.recurso_id,
                    data=excluded.data,
                    estado=excluded.estado,
                    pontos=excluded.pontos,
                    concluido_em=excluded.concluido_em,
                    gtd_item_id=excluded.gtd_item_id
            """, (
                acao.id,
                acao.plano_id,
                acao.recurso_id,
                acao.data,
                acao.estado,
                acao.pontos,
                acao.concluido_em,
                acao.gtd_item_id,
            ))
        return acao

    def obter_acao(self, acao_id: str) -> Optional[ProgressoAcao]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM progresso_acoes WHERE id = ?", (acao_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return ProgressoAcao.from_dict(dict(row))

    def obter_acao_por_recurso(self, plano_id: str, recurso_id: str) -> Optional[ProgressoAcao]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM progresso_acoes
                WHERE plano_id = ? AND recurso_id = ?
                ORDER BY data ASC
                LIMIT 1
            """, (plano_id, recurso_id))
            row = cursor.fetchone()
            if not row:
                return None
            return ProgressoAcao.from_dict(dict(row))

    def listar_acoes(
        self,
        plano_id: str,
        data: Optional[str] = None,
        estado: Optional[str] = None,
    ) -> List[ProgressoAcao]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM progresso_acoes WHERE plano_id = ?"
            params = [plano_id]
            if data:
                query += " AND data = ?"
                params.append(data[:10])
            if estado:
                query += " AND estado = ?"
                params.append(estado)
            query += " ORDER BY data ASC, rowid ASC"
            cursor.execute(query, params)
            return [ProgressoAcao.from_dict(dict(r)) for r in cursor.fetchall()]

    # -------------------------------------------------------------
    # Pontuacao e Gamificacao
    # -------------------------------------------------------------

    def salvar_pontuacao(self, pontuacao: Pontuacao) -> Pontuacao:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pontuacoes (id, plano_id, xp_total, nivel, streak, ultima_data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(plano_id) DO UPDATE SET
                    xp_total=excluded.xp_total,
                    nivel=excluded.nivel,
                    streak=excluded.streak,
                    ultima_data=excluded.ultima_data
            """, (
                pontuacao.id,
                pontuacao.plano_id,
                pontuacao.xp_total,
                pontuacao.nivel,
                pontuacao.streak,
                pontuacao.ultima_data,
            ))
        return pontuacao

    def obter_pontuacao(self, plano_id: str) -> Optional[Pontuacao]:
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pontuacoes WHERE plano_id = ?", (plano_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Pontuacao.from_dict(dict(row))
