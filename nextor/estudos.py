"""Modulo de estudos: biblioteca de materias por disciplina com indexacao FTS5."""
import html
import ipaddress
import os
import re
import shutil
import socket
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

EXTENSOES_PERMITIDAS = {".pdf", ".docx", ".txt", ".md"}
LIMITE_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


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


def validar_caminho_local(
    caminho: Path | str,
    pastas_autorizadas: Optional[List[Path]] = None,
) -> Path:
    """Valida se o arquivo local tem extensao permitida, nao e oculto/sensivel e esta em pasta autorizada."""
    p = Path(caminho).resolve()
    nome = p.name

    if nome.startswith("."):
        raise ValueError("Arquivos ocultos nao sao permitidos.")

    extensao = p.suffix.lower()
    if extensao not in EXTENSOES_PERMITIDAS:
        raise ValueError(
            f"Extensao '{extensao}' nao permitida. Apenas arquivos de estudo (.pdf, .docx, .txt, .md) sao aceitos."
        )

    nome_lower = nome.lower()
    if (
        nome_lower.startswith(".env")
        or nome_lower.startswith("secret")
        or nome_lower.startswith("token")
        or any(nome_lower.endswith(suf) for suf in (".key", ".pem", ".crt", ".cer", ".pfx", ".p12"))
    ):
        raise ValueError(f"Arquivo '{nome}' recusado por regras de seguranca.")

    if not p.is_file():
        raise ValueError(f"Arquivo nao encontrado ou nao e um arquivo regular: {p}")

    autorizadas = (
        pastas_autorizadas
        if pastas_autorizadas is not None
        else config.obter_pastas_importacao_estudos()
    )
    permitido = False
    for aut in autorizadas:
        try:
            if p.is_relative_to(aut.resolve()):
                permitido = True
                break
        except (ValueError, AttributeError):
            pass

    if not permitido:
        raise ValueError(f"Acesso negado: o arquivo '{nome}' esta fora das pastas autorizadas para importacao.")

    return p


def validar_url_segura(url: str) -> None:
    """Valida esquema e bloqueia SSRF (IPs privados, loopback, link-local e localhost)."""
    parsed = urllib.parse.urlparse(url)
    esquema = parsed.scheme.lower()
    if esquema not in ("http", "https"):
        raise ValueError("Apenas protocolos HTTP e HTTPS sao permitidos.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL invalida: hostname ausente.")

    hostname_lower = hostname.lower()
    if hostname_lower in ("localhost", "localhost.localdomain", "broadcasthost"):
        raise ValueError("Acesso bloqueado: host local nao permitido (prevencao de SSRF).")

    # Verifica se o proprio hostname e um endereco IP literal (ex: 127.0.0.1, 192.168.1.1)
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            raise ValueError(
                f"Acesso bloqueado ao IP {hostname}: enderecos privados, loopback e reservados sao proibidos (prevencao de SSRF)."
            )
        return
    except ValueError as e:
        if "Acesso bloqueado" in str(e):
            raise
        pass

    porta = parsed.port or (443 if esquema == "https" else 80)
    try:
        enderecos = socket.getaddrinfo(hostname, porta, proto=socket.IPPROTO_TCP)
        for item in enderecos:
            sockaddr = item[4]
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
                or ip_obj.is_unspecified
            ):
                raise ValueError(
                    f"Acesso bloqueado ao IP {ip_str}: enderecos privados, loopback e reservados sao proibidos (prevencao de SSRF)."
                )
    except socket.gaierror:
        pass


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


def baixar_link(
    url: str,
    timeout: float = 10.0,
    max_bytes: int = LIMITE_DOWNLOAD_BYTES,
) -> Tuple[str, str]:
    validar_url_segura(url)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Nextor/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ct_header = resp.headers.get("Content-Type")
        if ct_header is not None and isinstance(ct_header, str):
            content_type = ct_header.lower()
            if not any(
                ct in content_type for ct in ("text/", "application/xhtml+xml", "application/xml", "application/json")
            ):
                raise ValueError(f"Tipo de conteudo nao suportado: '{content_type}'. Apenas texto e HTML sao aceitos.")

        content_length = resp.headers.get("Content-Length")
        if content_length and isinstance(content_length, (int, str)):
            try:
                if int(content_length) > max_bytes:
                    raise ValueError(f"Download recusado: tamanho de {content_length} bytes excede o limite de 10 MB.")
            except (ValueError, TypeError):
                pass

        charset = resp.headers.get_content_charset() or "utf-8"
        buffer = bytearray()
        chunk_size = 65536
        while True:
            bloco = resp.read(chunk_size)
            if not bloco:
                break
            buffer.extend(bloco)
            if len(buffer) > max_bytes:
                raise ValueError("Download interrompido: o conteudo excedeu o limite maximo de 10 MB.")

        try:
            texto_html = buffer.decode(charset, errors="replace")
        except Exception:
            texto_html = buffer.decode("utf-8", errors="replace")

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
    pastas_autorizadas: Optional[List[Path]] = None,
    canal: str = "local",
    apenas_links: bool = False,
) -> Dict[str, Any]:
    origem_str = str(origem).strip()
    eh_url = origem_str.startswith("http://") or origem_str.startswith("https://")

    if canal == "remoto" or apenas_links:
        if not eh_url:
            return {
                "ok": False,
                "erro": "Canal remoto aceita apenas links (http/https), nunca caminhos locais.",
            }

    disc = obter_disciplina(disciplina_nome, caminho_db=caminho_db)
    if not disc:
        disc = criar_disciplina(disciplina_nome, base_dir=base_dir, caminho_db=caminho_db)

    pasta_disc = Path(disc["pasta"])
    pasta_disc.mkdir(parents=True, exist_ok=True)
    conteudo_texto = ""
    tipo_resolvido = tipo.lower().strip()
    caminho_destino = ""

    if eh_url:
        tipo_resolvido = tipo_resolvido or "link"
        try:
            tit_url, texto = baixar_link(origem_str)
        except ValueError as e:
            return {"ok": False, "erro": str(e)}

        conteudo_texto = texto
        titulo_final = titulo.strip() or tit_url or origem_str
        slug_tit = normalizar_slug(titulo_final)
        arquivo_local = pasta_disc / f"{slug_tit}.txt"
        arquivo_local.write_text(f"URL: {origem_str}\n\n{conteudo_texto}", encoding="utf-8")
        caminho_destino = str(arquivo_local)
    else:
        autorizadas = pastas_autorizadas
        if autorizadas is None:
            autorizadas = config.obter_pastas_importacao_estudos()
            if base_dir:
                b_path = Path(base_dir).resolve()
                autorizadas = list(autorizadas) + [b_path, b_path.parent]
        try:
            origem_path = validar_caminho_local(origem, pastas_autorizadas=autorizadas)
        except ValueError as e:
            return {"ok": False, "erro": str(e)}

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
        arquivo_destino = pasta_disc / Path(origem_path).name
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
