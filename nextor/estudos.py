"""Modulo de estudos: biblioteca de materias por disciplina com indexacao FTS5."""
import html
import os
import re
import shutil
import sqlite3
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config

try:
    import pypdf
except ImportError:
    pypdf = None


def normalizar_slug(texto: str) -> str:
    """Gera um identificador seguro para nome de pasta e chave interna."""
    s = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "_", s) or "sem_nome"


def obter_pasta_disciplina(disciplina_nome: str, base_dir: Optional[Path] = None) -> Path:
    raiz = base_dir or config.ESTUDOS_DIR
    slug = normalizar_slug(disciplina_nome)
    pasta = raiz / slug
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def conectar_db(caminho_db: Optional[Path] = None) -> sqlite3.Connection:
    caminho = caminho_db or config.ESTUDOS_DB
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(caminho))
    con.row_factory = sqlite3.Row
    with con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS disciplinas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                pasta TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS materiais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disciplina_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                tipo TEXT NOT NULL,
                caminho_ou_url TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                FOREIGN KEY (disciplina_id) REFERENCES disciplinas(id) ON DELETE CASCADE
            )
            """
        )
        con.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS materiais_fts USING fts5(
                conteudo,
                titulo,
                disciplina,
                material_id UNINDEXED
            )
            """
        )
    return con


def extrair_texto_pdf(caminho: Path) -> str:
    if pypdf is None:
        return ""
    try:
        reader = pypdf.PdfReader(str(caminho))
        partes = []
        for pag in reader.pages:
            t = pag.extract_text() or ""
            if t.strip():
                partes.append(t.strip())
        return "\n\n".join(partes)
    except Exception:
        return ""


def extrair_texto_docx(caminho: Path) -> str:
    try:
        with zipfile.ZipFile(caminho) as z:
            xml_data = z.read("word/document.xml")
        tree = ET.fromstring(xml_data)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragrafos = []
        for p in tree.iter(f"{{{ns['w']}}}p"):
            textos = [t.text for t in p.iter(f"{{{ns['w']}}}t") if t.text]
            if textos:
                paragrafos.append("".join(textos))
        return "\n\n".join(paragrafos)
    except Exception:
        return ""


def extrair_texto_arquivo_plano(caminho: Path) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return caminho.read_text(encoding=enc)
        except Exception:
            continue
    return ""


def extrair_texto_html(conteudo_html: str) -> Tuple[str, str]:
    titulo = ""
    m_tit = re.search(r"<title>(.*?)</title>", conteudo_html, re.IGNORECASE | re.DOTALL)
    if m_tit:
        titulo = html.unescape(m_tit.group(1)).strip()

    sem_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", conteudo_html, flags=re.IGNORECASE | re.DOTALL)
    sem_tags = re.sub(r"<[^>]+>", " ", sem_scripts)
    texto = html.unescape(sem_tags)
    linhas = [re.sub(r"\s+", " ", linha).strip() for linha in texto.splitlines()]
    texto_limpo = "\n".join(l for l in linhas if l)
    return titulo, texto_limpo


def baixar_link(url: str, timeout: float = 10.0) -> Tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Nextor/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read()
        try:
            texto_html = raw.decode(charset, errors="replace")
        except Exception:
            texto_html = raw.decode("utf-8", errors="replace")
    return extrair_texto_html(texto_html)


def criar_disciplina(
    nome: str,
    base_dir: Optional[Path] = None,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    nome_limpo = nome.strip()
    if not nome_limpo:
        return {"ok": False, "erro": "Nome da disciplina nao pode ser vazio."}

    pasta = obter_pasta_disciplina(nome_limpo, base_dir=base_dir)
    slug = pasta.name
    criado_em = datetime.now().isoformat(timespec="seconds")

    con = conectar_db(caminho_db)
    try:
        with con:
            con.execute(
                """
                INSERT INTO disciplinas (nome, slug, pasta, criado_em)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET nome = excluded.nome
                """,
                (nome_limpo, slug, str(pasta), criado_em),
            )
            cur = con.execute("SELECT id FROM disciplinas WHERE slug = ?", (slug,))
            row = cur.fetchone()
            d_id = row["id"] if row else 0
        return {
            "ok": True,
            "id": d_id,
            "nome": nome_limpo,
            "slug": slug,
            "pasta": str(pasta),
            "aviso": f"Disciplina {nome_limpo} criada.",
        }
    finally:
        con.close()


def obter_disciplina(
    identificador: str,
    caminho_db: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    slug = normalizar_slug(identificador)
    con = conectar_db(caminho_db)
    try:
        cur = con.execute(
            "SELECT id, nome, slug, pasta, criado_em FROM disciplinas WHERE slug = ? OR lower(nome) = ?",
            (slug, identificador.strip().lower()),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def listar_disciplinas(caminho_db: Optional[Path] = None) -> List[Dict[str, Any]]:
    con = conectar_db(caminho_db)
    try:
        cur = con.execute("SELECT id, nome, slug, pasta, criado_em FROM disciplinas ORDER BY nome COLLATE NOCASE")
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def resumo_disciplinas(caminho_db: Optional[Path] = None) -> str:
    lista = listar_disciplinas(caminho_db)
    if not lista:
        return "Voce ainda nao cadastrou nenhuma disciplina."
    nomes = [d["nome"] for d in lista]
    if len(nomes) == 1:
        return f"Voce tem 1 disciplina cadastrada: {nomes[0]}."
    return f"Voce tem {len(nomes)} disciplinas: {', '.join(nomes[:-1])} e {nomes[-1]}."


def importar_material(
    disciplina_nome: str,
    origem: str | Path,
    titulo: str = "",
    tipo: str = "",
    base_dir: Optional[Path] = None,
    caminho_db: Optional[Path] = None,
) -> Dict[str, Any]:
    disc = obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        disc = criar_disciplina(disciplina_nome, base_dir=base_dir, caminho_db=caminho_db)

    pasta_disc = Path(disc["pasta"])
    pasta_disc.mkdir(parents=True, exist_ok=True)
    origem_str = str(origem).strip()
    eh_url = origem_str.startswith("http://") or origem_str.startswith("https://")
    conteudo_texto = ""
    tipo_resolvido = tipo.lower().strip()
    caminho_destino = ""

    if eh_url:
        tipo_resolvido = tipo_resolvido or "link"
        tit_url, texto = baixar_link(origem_str)
        conteudo_texto = texto
        titulo_final = titulo.strip() or tit_url or origem_str
        slug_tit = normalizar_slug(titulo_final)
        arquivo_local = pasta_disc / f"{slug_tit}.txt"
        arquivo_local.write_text(f"URL: {origem_str}\n\n{conteudo_texto}", encoding="utf-8")
        caminho_destino = str(arquivo_local)
    else:
        origem_path = Path(origem)
        if not origem_path.exists():
            return {"ok": False, "erro": f"Arquivo nao encontrado: {origem_str}"}

        sufixo = origem_path.suffix.lower()
        if not tipo_resolvido:
            if sufixo == ".pdf":
                tipo_resolvido = "pdf"
            elif sufixo in (".docx", ".doc"):
                tipo_resolvido = "docx"
            elif sufixo == ".md":
                tipo_resolvido = "markdown"
            elif sufixo == ".txt":
                tipo_resolvido = "txt"
            else:
                tipo_resolvido = sufixo.lstrip(".") or "documento"

        titulo_final = titulo.strip() or origem_path.name
        arquivo_destino = pasta_disc / origem_path.name
        if origem_path.resolve() != arquivo_destino.resolve():
            shutil.copy2(origem_path, arquivo_destino)
        caminho_destino = str(arquivo_destino)

        if tipo_resolvido == "pdf":
            conteudo_texto = extrair_texto_pdf(arquivo_destino)
        elif tipo_resolvido in ("docx", "doc"):
            conteudo_texto = extrair_texto_docx(arquivo_destino)
        else:
            conteudo_texto = extrair_texto_arquivo_plano(arquivo_destino)

    criado_em = datetime.now().isoformat(timespec="seconds")
    con = conectar_db(caminho_db)
    try:
        with con:
            cur = con.execute(
                """
                INSERT INTO materiais (disciplina_id, titulo, tipo, caminho_ou_url, conteudo, criado_em)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (disc["id"], titulo_final, tipo_resolvido, caminho_destino, conteudo_texto, criado_em),
            )
            mat_id = cur.lastrowid
            con.execute(
                """
                INSERT INTO materiais_fts (conteudo, titulo, disciplina, material_id)
                VALUES (?, ?, ?, ?)
                """,
                (conteudo_texto, titulo_final, disc["nome"], mat_id),
            )
        return {
            "ok": True,
            "id": mat_id,
            "disciplina": disc["nome"],
            "titulo": titulo_final,
            "tipo": tipo_resolvido,
            "caminho": caminho_destino,
            "tamanho_texto": len(conteudo_texto),
            "aviso": f"Material {titulo_final} adicionado em {disc['nome']}.",
        }
    finally:
        con.close()


def listar_materiais(
    disciplina_nome: str,
    caminho_db: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    disc = obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        return []

    con = conectar_db(caminho_db)
    try:
        cur = con.execute(
            """
            SELECT id, disciplina_id, titulo, tipo, caminho_ou_url, criado_em
            FROM materiais
            WHERE disciplina_id = ?
            ORDER BY criado_em DESC
            """,
            (disc["id"],),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def resumo_materiais(disciplina_nome: str, caminho_db: Optional[Path] = None) -> str:
    disc = obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        return f"A disciplina {disciplina_nome} ainda nao existe."

    materiais = listar_materiais(disciplina_nome, caminho_db=caminho_db)
    if not materiais:
        return f"Nenhum material encontrado para {disc['nome']}."

    nomes = [m["titulo"] for m in materiais]
    qtd = len(nomes)
    if qtd == 1:
        return f"Na disciplina {disc['nome']} voce tem 1 material: {nomes[0]}."
    if qtd <= 4:
        return f"Na disciplina {disc['nome']} voce tem {qtd} materiais: {', '.join(nomes[:-1])} e {nomes[-1]}."
    return f"Na disciplina {disc['nome']} voce tem {qtd} materiais, incluindo {', '.join(nomes[:3])}."


def buscar_materiais(
    termo: str,
    disciplina_nome: str = "",
    limite: int = 10,
    caminho_db: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    termo_limpo = termo.strip()
    if not termo_limpo:
        return []

    tokens = [re.sub(r"[^\w]", "", tok) for tok in termo_limpo.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []

    termo_fts = " ".join(f'"{tok}"' for tok in tokens)
    con = conectar_db(caminho_db)
    try:
        if disciplina_nome.strip():
            disc = obter_disciplina(disciplina_nome, caminho_db=caminho_db)
            nome_filtro = disc["nome"] if disc else disciplina_nome.strip()
            sql = """
                SELECT material_id, titulo, disciplina,
                       snippet(materiais_fts, 0, '', '', '...', 15) AS trecho
                FROM materiais_fts
                WHERE materiais_fts MATCH ? AND lower(disciplina) = lower(?)
                LIMIT ?
            """
            params = (termo_fts, nome_filtro, limite)
        else:
            sql = """
                SELECT material_id, titulo, disciplina,
                       snippet(materiais_fts, 0, '', '', '...', 15) AS trecho
                FROM materiais_fts
                WHERE materiais_fts MATCH ?
                LIMIT ?
            """
            params = (termo_fts, limite)

        cur = con.execute(sql, params)
        resultados = []
        for r in cur.fetchall():
            row_dict = dict(r)
            mat_cur = con.execute(
                "SELECT tipo, caminho_ou_url FROM materiais WHERE id = ?",
                (row_dict["material_id"],),
            )
            det = mat_cur.fetchone()
            if det:
                row_dict["tipo"] = det["tipo"]
                row_dict["caminho"] = det["caminho_ou_url"]
            resultados.append(row_dict)
        return resultados
    finally:
        con.close()


def resumo_busca(
    termo: str,
    disciplina_nome: str = "",
    limite: int = 5,
    caminho_db: Optional[Path] = None,
) -> str:
    resultados = buscar_materiais(termo, disciplina_nome=disciplina_nome, limite=limite, caminho_db=caminho_db)
    alvo = f" em {disciplina_nome}" if disciplina_nome.strip() else ""
    if not resultados:
        return f"Nao encontrei nenhum material sobre {termo}{alvo}."

    titulos = [f"{r['titulo']} ({r['disciplina']})" if not disciplina_nome else r["titulo"] for r in resultados]
    qtd = len(titulos)
    if qtd == 1:
        return f"Encontrei 1 material sobre {termo}{alvo}: {titulos[0]}."
    return f"Encontrei {qtd} materiais sobre {termo}{alvo}: {', '.join(titulos[:3])}."
