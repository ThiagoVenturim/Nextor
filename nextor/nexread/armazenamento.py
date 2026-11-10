"""Persistencia em SQLite para o NexRead (Issue #55)."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import List, Optional, Union

from .. import config
from .modelos import ArtigoLido, GravacaoLeitura, Marcacao, MensagemChatArtigo


def _obter_caminho_padrao() -> Path:
    if hasattr(config, "NEXREAD_DB") and config.NEXREAD_DB:
        return Path(config.NEXREAD_DB).resolve()
    return (Path.home() / ".nextor" / "nexread.db").resolve()


class ArmazenamentoNexRead:
    """Gerencia persistencia SQLite para artigos traduzidos, marcacoes, gravacoes e conversas."""

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
        with self._conexao() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artigos_lidos (
                    id TEXT PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    url TEXT DEFAULT '',
                    titulo_traduzido TEXT DEFAULT '',
                    autor TEXT DEFAULT '',
                    veiculo TEXT DEFAULT '',
                    ano INTEGER,
                    idioma_origem TEXT DEFAULT 'auto',
                    idioma_destino TEXT DEFAULT 'pt-BR',
                    motor_traducao TEXT DEFAULT 'local',
                    modo_layout TEXT DEFAULT 'bilingue',
                    tipo_origem TEXT DEFAULT 'html',
                    blocos_json TEXT DEFAULT '[]',
                    html_traduzido TEXT DEFAULT '',
                    disciplina TEXT DEFAULT '',
                    material_id INTEGER,
                    aberta_pelo_usuario INTEGER DEFAULT 1,
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS marcacoes (
                    id TEXT PRIMARY KEY,
                    artigo_id TEXT NOT NULL,
                    bloco_id TEXT DEFAULT '',
                    trecho_original TEXT NOT NULL,
                    trecho_traduzido TEXT DEFAULT '',
                    nota TEXT DEFAULT '',
                    cor TEXT DEFAULT 'amarelo',
                    tags_json TEXT DEFAULT '[]',
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY (artigo_id) REFERENCES artigos_lidos(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gravacoes_leitura (
                    id TEXT PRIMARY KEY,
                    artigo_id TEXT NOT NULL,
                    titulo TEXT NOT NULL,
                    transcricao TEXT NOT NULL,
                    caminho_audio TEXT DEFAULT '',
                    duracao_seg INTEGER DEFAULT 0,
                    bloco_id TEXT DEFAULT '',
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY (artigo_id) REFERENCES artigos_lidos(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversas_artigo (
                    id TEXT PRIMARY KEY,
                    artigo_id TEXT NOT NULL,
                    papel TEXT NOT NULL,
                    conteudo TEXT NOT NULL,
                    acao TEXT DEFAULT 'perguntar',
                    fontes_json TEXT DEFAULT '[]',
                    artigos_relacionados_json TEXT DEFAULT '[]',
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY (artigo_id) REFERENCES artigos_lidos(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_marcacoes_artigo ON marcacoes(artigo_id, criado_em)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_gravacoes_artigo ON gravacoes_leitura(artigo_id, criado_em)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversas_artigo ON conversas_artigo(artigo_id, criado_em)")

    # -------------------------------------------------------------
    # Artigos Lidos / Sessoes de Leitura
    # -------------------------------------------------------------

    def salvar_artigo(self, artigo: ArtigoLido) -> ArtigoLido:
        blocos_json = json.dumps([b.to_dict() for b in artigo.blocos], ensure_ascii=False)
        atualizado = artigo.atualizado_em or datetime.now().isoformat(timespec="seconds")
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO artigos_lidos (
                    id, titulo, url, titulo_traduzido, autor, veiculo, ano,
                    idioma_origem, idioma_destino, motor_traducao, modo_layout,
                    tipo_origem, blocos_json, html_traduzido, disciplina,
                    material_id, aberta_pelo_usuario, criado_em, atualizado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo=excluded.titulo,
                    url=excluded.url,
                    titulo_traduzido=excluded.titulo_traduzido,
                    autor=excluded.autor,
                    veiculo=excluded.veiculo,
                    ano=excluded.ano,
                    idioma_origem=excluded.idioma_origem,
                    idioma_destino=excluded.idioma_destino,
                    motor_traducao=excluded.motor_traducao,
                    modo_layout=excluded.modo_layout,
                    tipo_origem=excluded.tipo_origem,
                    blocos_json=excluded.blocos_json,
                    html_traduzido=excluded.html_traduzido,
                    disciplina=excluded.disciplina,
                    material_id=excluded.material_id,
                    aberta_pelo_usuario=excluded.aberta_pelo_usuario,
                    atualizado_em=excluded.atualizado_em
            """, (
                artigo.id,
                artigo.titulo,
                artigo.url,
                artigo.titulo_traduzido,
                artigo.autor,
                artigo.veiculo,
                artigo.ano,
                artigo.idioma_origem,
                artigo.idioma_destino,
                artigo.motor_traducao,
                artigo.modo_layout,
                artigo.tipo_origem,
                blocos_json,
                artigo.html_traduzido,
                artigo.disciplina,
                artigo.material_id,
                1 if artigo.aberta_pelo_usuario else 0,
                artigo.criado_em,
                atualizado,
            ))
        return self.obter_artigo(artigo.id) or artigo

    def _row_para_artigo(self, row: sqlite3.Row) -> ArtigoLido:
        d = dict(row)
        blocos_raw = d.pop("blocos_json", "[]")
        try:
            d["blocos"] = json.loads(blocos_raw) if blocos_raw else []
        except Exception:
            d["blocos"] = []
        d["aberta_pelo_usuario"] = bool(d.get("aberta_pelo_usuario", 1))
        return ArtigoLido.from_dict(d)

    def obter_artigo(self, artigo_id: str) -> Optional[ArtigoLido]:
        with self._conexao() as conn:
            cur = conn.execute("SELECT * FROM artigos_lidos WHERE id = ?", (artigo_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_para_artigo(row)

    def listar_artigos(self, disciplina: Optional[str] = None, limite: int = 50) -> List[ArtigoLido]:
        with self._conexao() as conn:
            if disciplina and disciplina.strip():
                cur = conn.execute(
                    "SELECT * FROM artigos_lidos WHERE lower(disciplina) = lower(?) ORDER BY criado_em DESC LIMIT ?",
                    (disciplina.strip(), limite),
                )
            else:
                cur = conn.execute("SELECT * FROM artigos_lidos ORDER BY criado_em DESC LIMIT ?", (limite,))
            return [self._row_para_artigo(r) for r in cur.fetchall()]

    # -------------------------------------------------------------
    # Marcacoes e Anotacoes
    # -------------------------------------------------------------

    def salvar_marcacao(self, marcacao: Marcacao) -> Marcacao:
        tags_json = json.dumps(marcacao.tags, ensure_ascii=False)
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO marcacoes (
                    id, artigo_id, bloco_id, trecho_original, trecho_traduzido,
                    nota, cor, tags_json, criado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    bloco_id=excluded.bloco_id,
                    trecho_original=excluded.trecho_original,
                    trecho_traduzido=excluded.trecho_traduzido,
                    nota=excluded.nota,
                    cor=excluded.cor,
                    tags_json=excluded.tags_json
            """, (
                marcacao.id,
                marcacao.artigo_id,
                marcacao.bloco_id,
                marcacao.trecho_original,
                marcacao.trecho_traduzido,
                marcacao.nota,
                marcacao.cor,
                tags_json,
                marcacao.criado_em,
            ))
        return marcacao

    def _row_para_marcacao(self, row: sqlite3.Row) -> Marcacao:
        d = dict(row)
        tags_raw = d.pop("tags_json", "[]")
        try:
            d["tags"] = json.loads(tags_raw) if tags_raw else []
        except Exception:
            d["tags"] = []
        return Marcacao.from_dict(d)

    def obter_marcacao(self, marcacao_id: str) -> Optional[Marcacao]:
        with self._conexao() as conn:
            cur = conn.execute("SELECT * FROM marcacoes WHERE id = ?", (marcacao_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_para_marcacao(row)

    def listar_marcacoes(self, artigo_id: Optional[str] = None) -> List[Marcacao]:
        with self._conexao() as conn:
            if artigo_id:
                cur = conn.execute(
                    "SELECT * FROM marcacoes WHERE artigo_id = ? ORDER BY criado_em ASC, rowid ASC",
                    (artigo_id,),
                )
            else:
                cur = conn.execute("SELECT * FROM marcacoes ORDER BY criado_em DESC, rowid DESC")
            return [self._row_para_marcacao(r) for r in cur.fetchall()]

    def remover_marcacao(self, marcacao_id: str) -> bool:
        with self._conexao() as conn:
            cur = conn.execute("DELETE FROM marcacoes WHERE id = ?", (marcacao_id,))
            return cur.rowcount > 0

    # -------------------------------------------------------------
    # Gravacoes de Leitura
    # -------------------------------------------------------------

    def salvar_gravacao(self, gravacao: GravacaoLeitura) -> GravacaoLeitura:
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO gravacoes_leitura (
                    id, artigo_id, titulo, transcricao, caminho_audio,
                    duracao_seg, bloco_id, criado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo=excluded.titulo,
                    transcricao=excluded.transcricao,
                    caminho_audio=excluded.caminho_audio,
                    duracao_seg=excluded.duracao_seg,
                    bloco_id=excluded.bloco_id
            """, (
                gravacao.id,
                gravacao.artigo_id,
                gravacao.titulo,
                gravacao.transcricao,
                gravacao.caminho_audio,
                gravacao.duracao_seg,
                gravacao.bloco_id,
                gravacao.criado_em,
            ))
        return gravacao

    def listar_gravacoes(self, artigo_id: str) -> List[GravacaoLeitura]:
        with self._conexao() as conn:
            cur = conn.execute(
                "SELECT * FROM gravacoes_leitura WHERE artigo_id = ? ORDER BY criado_em ASC, rowid ASC",
                (artigo_id,),
            )
            return [GravacaoLeitura.from_dict(dict(r)) for r in cur.fetchall()]

    # -------------------------------------------------------------
    # Conversas sobre o Artigo
    # -------------------------------------------------------------

    def salvar_mensagem_chat(self, msg: MensagemChatArtigo) -> MensagemChatArtigo:
        fontes_json = json.dumps(msg.fontes, ensure_ascii=False)
        rel_json = json.dumps(msg.artigos_relacionados, ensure_ascii=False)
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO conversas_artigo (
                    id, artigo_id, papel, conteudo, acao,
                    fontes_json, artigos_relacionados_json, criado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.id,
                msg.artigo_id,
                msg.papel,
                msg.conteudo,
                msg.acao,
                fontes_json,
                rel_json,
                msg.criado_em,
            ))
        return msg

    def listar_mensagens_chat(self, artigo_id: str) -> List[MensagemChatArtigo]:
        with self._conexao() as conn:
            cur = conn.execute(
                "SELECT * FROM conversas_artigo WHERE artigo_id = ? ORDER BY criado_em ASC, rowid ASC",
                (artigo_id,),
            )
            resultado = []
            for row in cur.fetchall():
                d = dict(row)
                try:
                    d["fontes"] = json.loads(d.pop("fontes_json", "[]") or "[]")
                except Exception:
                    d["fontes"] = []
                try:
                    d["artigos_relacionados"] = json.loads(d.pop("artigos_relacionados_json", "[]") or "[]")
                except Exception:
                    d["artigos_relacionados"] = []
                resultado.append(MensagemChatArtigo.from_dict(d))
            return resultado
