"""Persistencia SQLite para o NexVoice: sessoes, trechos traduzidos e auditoria de consentimento (Issue #56)."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Union
import uuid

from .. import config
from .modelos import SessaoNexVoice, TrechoVoz


def _obter_caminho_padrao() -> Path:
    if hasattr(config, "NEXVOICE_DB") and config.NEXVOICE_DB:
        return Path(config.NEXVOICE_DB).resolve()
    return (Path.home() / ".nextor" / "nexvoice.db").resolve()


class ArmazenamentoNexVoice:
    """Gerencia persistencia SQLite de sessoes, trechos de traducao e registro de consentimento."""

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
                CREATE TABLE IF NOT EXISTS sessoes_nexvoice (
                    id TEXT PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    modo TEXT DEFAULT 'ouvir',
                    fonte TEXT DEFAULT 'video',
                    idioma_meu TEXT DEFAULT 'pt-BR',
                    idioma_outro TEXT DEFAULT 'en-US',
                    motor_stt TEXT DEFAULT 'faster_whisper',
                    motor_traducao TEXT DEFAULT 'local',
                    motor_tts TEXT DEFAULT 'piper',
                    sintetizar_voz INTEGER DEFAULT 1,
                    processamento_local_estrito INTEGER DEFAULT 1,
                    consentimento_exigido INTEGER DEFAULT 0,
                    consentimento_confirmado INTEGER DEFAULT 0,
                    consentimento_participantes TEXT DEFAULT '',
                    consentimento_em TEXT,
                    aviso_consentimento TEXT DEFAULT '',
                    disciplina TEXT DEFAULT '',
                    material_id INTEGER,
                    estado TEXT DEFAULT 'ativa',
                    criado_em TEXT NOT NULL,
                    encerrado_em TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trechos_nexvoice (
                    id TEXT PRIMARY KEY,
                    sessao_id TEXT NOT NULL,
                    indice INTEGER NOT NULL,
                    direcao TEXT DEFAULT 'entrada',
                    locutor TEXT DEFAULT 'interlocutor',
                    idioma_origem TEXT DEFAULT 'en-US',
                    idioma_destino TEXT DEFAULT 'pt-BR',
                    texto_original TEXT NOT NULL,
                    texto_traduzido TEXT NOT NULL,
                    inicio_seg REAL DEFAULT 0.0,
                    fim_seg REAL DEFAULT 2.5,
                    latencia_ms INTEGER DEFAULT 0,
                    motor_stt TEXT DEFAULT 'faster_whisper',
                    motor_traducao TEXT DEFAULT 'local',
                    motor_tts TEXT DEFAULT 'piper',
                    fala_id TEXT DEFAULT '',
                    duracao_tts_seg REAL DEFAULT 0.0,
                    criado_em TEXT NOT NULL,
                    FOREIGN KEY (sessao_id) REFERENCES sessoes_nexvoice(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auditoria_consentimento_nexvoice (
                    id TEXT PRIMARY KEY,
                    sessao_id TEXT NOT NULL,
                    modo TEXT NOT NULL,
                    fonte TEXT NOT NULL,
                    participantes TEXT DEFAULT '',
                    aviso TEXT NOT NULL,
                    local_estrito INTEGER DEFAULT 1,
                    registrado_em TEXT NOT NULL,
                    FOREIGN KEY (sessao_id) REFERENCES sessoes_nexvoice(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trechos_nexvoice_sessao ON trechos_nexvoice(sessao_id, indice)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_consentimento_nexvoice_sessao "
                "ON auditoria_consentimento_nexvoice(sessao_id)"
            )

    def salvar_sessao(self, sessao: SessaoNexVoice) -> SessaoNexVoice:
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO sessoes_nexvoice (
                    id, titulo, modo, fonte, idioma_meu, idioma_outro,
                    motor_stt, motor_traducao, motor_tts, sintetizar_voz,
                    processamento_local_estrito, consentimento_exigido,
                    consentimento_confirmado, consentimento_participantes,
                    consentimento_em, aviso_consentimento, disciplina,
                    material_id, estado, criado_em, encerrado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo=excluded.titulo,
                    modo=excluded.modo,
                    fonte=excluded.fonte,
                    idioma_meu=excluded.idioma_meu,
                    idioma_outro=excluded.idioma_outro,
                    motor_stt=excluded.motor_stt,
                    motor_traducao=excluded.motor_traducao,
                    motor_tts=excluded.motor_tts,
                    sintetizar_voz=excluded.sintetizar_voz,
                    processamento_local_estrito=excluded.processamento_local_estrito,
                    consentimento_exigido=excluded.consentimento_exigido,
                    consentimento_confirmado=excluded.consentimento_confirmado,
                    consentimento_participantes=excluded.consentimento_participantes,
                    consentimento_em=excluded.consentimento_em,
                    aviso_consentimento=excluded.aviso_consentimento,
                    disciplina=excluded.disciplina,
                    material_id=excluded.material_id,
                    estado=excluded.estado,
                    encerrado_em=excluded.encerrado_em
            """, (
                sessao.id,
                sessao.titulo,
                sessao.modo,
                sessao.fonte,
                sessao.idioma_meu,
                sessao.idioma_outro,
                sessao.motor_stt,
                sessao.motor_traducao,
                sessao.motor_tts,
                1 if sessao.sintetizar_voz else 0,
                1 if sessao.processamento_local_estrito else 0,
                1 if sessao.consentimento_exigido else 0,
                1 if sessao.consentimento_confirmado else 0,
                sessao.consentimento_participantes,
                sessao.consentimento_em,
                sessao.aviso_consentimento,
                sessao.disciplina,
                sessao.material_id,
                sessao.estado,
                sessao.criado_em,
                sessao.encerrado_em,
            ))
        return self.obter_sessao(sessao.id) or sessao

    def _row_para_sessao(self, row: sqlite3.Row, trechos: Optional[List[TrechoVoz]] = None) -> SessaoNexVoice:
        d = dict(row)
        d["sintetizar_voz"] = bool(d.get("sintetizar_voz", 1))
        d["processamento_local_estrito"] = bool(d.get("processamento_local_estrito", 1))
        d["consentimento_exigido"] = bool(d.get("consentimento_exigido", 0))
        d["consentimento_confirmado"] = bool(d.get("consentimento_confirmado", 0))
        d["trechos"] = trechos if trechos is not None else []
        return SessaoNexVoice.from_dict(d)

    def obter_sessao(self, sessao_id: str) -> Optional[SessaoNexVoice]:
        with self._conexao() as conn:
            cur = conn.execute("SELECT * FROM sessoes_nexvoice WHERE id = ?", (sessao_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur_tr = conn.execute(
                "SELECT * FROM trechos_nexvoice WHERE sessao_id = ? ORDER BY indice ASC, rowid ASC",
                (sessao_id,),
            )
            trechos = [TrechoVoz.from_dict(dict(r)) for r in cur_tr.fetchall()]
            return self._row_para_sessao(row, trechos=trechos)

    def listar_sessoes(
        self,
        modo: Optional[str] = None,
        disciplina: Optional[str] = None,
        estado: Optional[str] = None,
        limite: int = 50,
    ) -> List[SessaoNexVoice]:
        clausulas: List[str] = []
        params: List[Any] = []
        if modo and modo.strip():
            clausulas.append("lower(modo) = lower(?)")
            params.append(modo.strip())
        if disciplina and disciplina.strip():
            clausulas.append("lower(disciplina) = lower(?)")
            params.append(disciplina.strip())
        if estado and estado.strip():
            clausulas.append("lower(estado) = lower(?)")
            params.append(estado.strip())

        where_sql = f"WHERE {' AND '.join(clausulas)}" if clausulas else ""
        params.append(limite)

        with self._conexao() as conn:
            cur = conn.execute(
                f"SELECT * FROM sessoes_nexvoice {where_sql} ORDER BY criado_em DESC, rowid DESC LIMIT ?",
                tuple(params),
            )
            sessoes: List[SessaoNexVoice] = []
            for r in cur.fetchall():
                sid = r["id"]
                cur_tr = conn.execute(
                    "SELECT * FROM trechos_nexvoice WHERE sessao_id = ? ORDER BY indice ASC, rowid ASC",
                    (sid,),
                )
                trechos = [TrechoVoz.from_dict(dict(tr)) for tr in cur_tr.fetchall()]
                sessoes.append(self._row_para_sessao(r, trechos=trechos))
            return sessoes

    def salvar_trecho(self, trecho: TrechoVoz) -> TrechoVoz:
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO trechos_nexvoice (
                    id, sessao_id, indice, direcao, locutor,
                    idioma_origem, idioma_destino, texto_original, texto_traduzido,
                    inicio_seg, fim_seg, latencia_ms, motor_stt,
                    motor_traducao, motor_tts, fala_id, duracao_tts_seg, criado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    indice=excluded.indice,
                    direcao=excluded.direcao,
                    locutor=excluded.locutor,
                    idioma_origem=excluded.idioma_origem,
                    idioma_destino=excluded.idioma_destino,
                    texto_original=excluded.texto_original,
                    texto_traduzido=excluded.texto_traduzido,
                    inicio_seg=excluded.inicio_seg,
                    fim_seg=excluded.fim_seg,
                    latencia_ms=excluded.latencia_ms,
                    motor_stt=excluded.motor_stt,
                    motor_traducao=excluded.motor_traducao,
                    motor_tts=excluded.motor_tts,
                    fala_id=excluded.fala_id,
                    duracao_tts_seg=excluded.duracao_tts_seg
            """, (
                trecho.id,
                trecho.sessao_id,
                trecho.indice,
                trecho.direcao,
                trecho.locutor,
                trecho.idioma_origem,
                trecho.idioma_destino,
                trecho.texto_original,
                trecho.texto_traduzido,
                trecho.inicio_seg,
                trecho.fim_seg,
                trecho.latencia_ms,
                trecho.motor_stt,
                trecho.motor_traducao,
                trecho.motor_tts,
                trecho.fala_id,
                trecho.duracao_tts_seg,
                trecho.criado_em,
            ))
        return trecho

    def listar_trechos(self, sessao_id: str) -> List[TrechoVoz]:
        with self._conexao() as conn:
            cur = conn.execute(
                "SELECT * FROM trechos_nexvoice WHERE sessao_id = ? ORDER BY indice ASC, rowid ASC",
                (sessao_id,),
            )
            return [TrechoVoz.from_dict(dict(r)) for r in cur.fetchall()]

    def registrar_consentimento(
        self,
        sessao_id: str,
        modo: str,
        fonte: str,
        participantes: str,
        aviso: str,
        local_estrito: bool = True,
    ) -> Dict[str, Any]:
        reg_id = f"cons-{uuid.uuid4().hex[:10]}"
        registrado_em = datetime.now().isoformat(timespec="seconds")
        with self._conexao() as conn:
            conn.execute("""
                INSERT INTO auditoria_consentimento_nexvoice (
                    id, sessao_id, modo, fonte, participantes,
                    aviso, local_estrito, registrado_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reg_id,
                sessao_id,
                modo,
                fonte,
                participantes,
                aviso,
                1 if local_estrito else 0,
                registrado_em,
            ))
        return {
            "id": reg_id,
            "sessao_id": sessao_id,
            "modo": modo,
            "fonte": fonte,
            "participantes": participantes,
            "aviso": aviso,
            "local_estrito": local_estrito,
            "registrado_em": registrado_em,
        }

    def listar_consentimentos(self, sessao_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._conexao() as conn:
            if sessao_id:
                cur = conn.execute(
                    "SELECT * FROM auditoria_consentimento_nexvoice WHERE sessao_id = ? ORDER BY registrado_em ASC",
                    (sessao_id,),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM auditoria_consentimento_nexvoice ORDER BY registrado_em DESC"
                )
            res: List[Dict[str, Any]] = []
            for r in cur.fetchall():
                d = dict(r)
                d["local_estrito"] = bool(d.get("local_estrito", 1))
                res.append(d)
            return res
