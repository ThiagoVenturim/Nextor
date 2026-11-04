"""Modulo organizador de pastas para o Nextor.

Permite organizar arquivos por tipo, data ou disciplina com:
- Seguranca estrita de caminhos (resolve + is_relative_to contra NEXTOR_ORGANIZAR_PASTAS_PERMITIDAS)
- Fluxo obrigatorio em duas etapas: previa antes de mover e execucao sob confirmacao
- Preservacao total de dados: nunca apaga arquivos e registra historico para desfazer
- Prevencao de colisao de nomes ao mover
"""
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from . import config

log = logging.getLogger("nextor.organizador")

CATEGORIAS_EXTENSOES: Dict[str, Set[str]] = {
    "Documentos": {".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".epub", ".md"},
    "Imagens": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tiff"},
    "Planilhas": {".xlsx", ".xls", ".csv", ".ods"},
    "Apresentacoes": {".pptx", ".ppt", ".odp"},
    "Audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"},
    "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "Instaladores": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm"},
    "Codigo": {".py", ".js", ".ts", ".html", ".css", ".json", ".sql", ".sh", ".ps1", ".bat", ".cpp", ".c", ".java"},
}

# Cache de previas pendentes em memoria
_PREVIAS_PENDENTES: Dict[str, dict] = {}
_ULTIMA_PREVIA: Optional[dict] = None


class PastaNaoPermitidaError(PermissionError):
    """Excecao levantada quando um caminho nao esta na lista de pastas permitidas."""
    pass


def obter_pastas_permitidas() -> List[Path]:
    """Retorna lista de caminhos absolutos e resolvidos permitidos para organizacao."""
    return config.obter_pastas_organizacao_permitidas()


def validar_pasta_permitida(caminho: Any) -> Path:
    """Valida estritamente se o caminho fornecido existe, e diretorio e reside
    dentro de uma das pastas configuradas em NEXTOR_ORGANIZAR_PASTAS_PERMITIDAS.
    Rejeita tentativas de path traversal e acesso a raiz ou pastas do sistema.
    """
    if not caminho:
        raise PastaNaoPermitidaError("Caminho nao fornecido.")

    try:
        p = Path(caminho).resolve()
    except Exception as e:
        raise PastaNaoPermitidaError(f"Caminho invalido: {e}")

    if not p.exists() or not p.is_dir():
        raise PastaNaoPermitidaError(f"Diretorio inexistente ou nao e uma pasta: {p}")

    # Impede organizar raiz do sistema ou home inteira diretamente
    home = Path.home().resolve()
    if p == home or p == Path(p.anchor).resolve():
        raise PastaNaoPermitidaError("Nao e permitido organizar a raiz do disco ou a pasta home diretamente.")

    permitidas = obter_pastas_permitidas()
    permitido = False
    for base in permitidas:
        base_res = base.resolve()
        if p == base_res or p.is_relative_to(base_res):
            permitido = True
            break

    if not permitido:
        raise PastaNaoPermitidaError(f"Acesso negado: pasta '{p}' nao esta na lista de pastas permitidas.")

    return p


def resolver_destino_sem_colisao(destino: Path) -> Path:
    """Gera um caminho unico incrementando sufixo numerico se o destino ja existir."""
    if not destino.exists():
        return destino

    parent = destino.parent
    stem = destino.stem
    suffix = destino.suffix
    contador = 1
    while True:
        novo = parent / f"{stem}_{contador}{suffix}"
        if not novo.exists():
            return novo
        contador += 1


def obter_categoria_por_extensao(extensao: str) -> str:
    """Classifica a extensao do arquivo na categoria correspondente."""
    ext_limpa = extensao.strip().lower()
    if not ext_limpa.startswith("."):
        ext_limpa = f".{ext_limpa}"

    for categoria, extensoes in CATEGORIAS_EXTENSOES.items():
        if ext_limpa in extensoes:
            return categoria
    return "Outros"


def classificar_por_data(arquivo: Path) -> str:
    """Classifica o arquivo pela data de modificacao no formato YYYY/YYYY-MM."""
    try:
        mtime = datetime.fromtimestamp(arquivo.stat().st_mtime)
        return f"{mtime.year}/{mtime.year}-{mtime.month:02d}"
    except Exception:
        agora = datetime.now()
        return f"{agora.year}/{agora.year}-{agora.month:02d}"


def classificar_por_disciplina(arquivo: Path, disciplinas_disponiveis: Optional[List[str]] = None) -> str:
    """Classifica o arquivo associando seu nome a uma das disciplinas conhecidas."""
    nome = arquivo.stem.lower()

    lista_disc = disciplinas_disponiveis
    if lista_disc is None:
        try:
            from . import estudos
            lista_disc = [d["nome"] for d in estudos.listar_disciplinas()]
        except Exception:
            lista_disc = []

    for d in lista_disc:
        d_limpa = d.strip().lower()
        if d_limpa and d_limpa in nome:
            return d.strip()

    return "Sem_Disciplina"


def gerar_previa(
    pasta: Any,
    criterio: str = "tipo",
    disciplinas: Optional[List[str]] = None,
) -> dict:
    """Gera uma previa das movimentacoes sem alterar nenhum arquivo em disco."""
    global _ULTIMA_PREVIA
    caminho_pasta = validar_pasta_permitida(pasta)
    criterio_limpo = criterio.strip().lower()

    if criterio_limpo not in ("tipo", "data", "disciplina"):
        criterio_limpo = "tipo"

    movimentacoes: List[Dict[str, str]] = []
    contagem_categorias: Dict[str, int] = {}

    # Varre apenas arquivos diretos da pasta raiz para evitar rebaguncar subdiretorios
    for item in caminho_pasta.iterdir():
        if not item.is_file() or item.name.startswith("."):
            continue

        if criterio_limpo == "tipo":
            subpasta = obter_categoria_por_extensao(item.suffix)
        elif criterio_limpo == "data":
            subpasta = classificar_por_data(item)
        elif criterio_limpo == "disciplina":
            subpasta = classificar_por_disciplina(item, disciplinas)
        else:
            subpasta = "Outros"

        destino_pasta = caminho_pasta / subpasta
        destino_arquivo = destino_pasta / item.name

        # So adiciona se o destino for diferente da origem
        if destino_arquivo != item:
            movimentacoes.append({
                "origem": str(item),
                "destino": str(destino_arquivo),
                "nome": item.name,
                "categoria": subpasta,
            })
            contagem_categorias[subpasta] = contagem_categorias.get(subpasta, 0) + 1

    id_sessao = f"prev_{uuid.uuid4().hex[:8]}"
    previa = {
        "ok": True,
        "id_sessao": id_sessao,
        "pasta": str(caminho_pasta),
        "criterio": criterio_limpo,
        "total_arquivos": len(movimentacoes),
        "movimentacoes": movimentacoes,
        "resumo_categorias": contagem_categorias,
        "criado_em": datetime.now().isoformat(),
    }

    _PREVIAS_PENDENTES[id_sessao] = previa
    _ULTIMA_PREVIA = previa
    return previa


def _carregar_historico(caminho_arquivo: Optional[Path] = None) -> List[dict]:
    p = caminho_arquivo or config.HISTORICO_ORGANIZACOES
    if not p.exists():
        return []
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except Exception as e:
        log.warning("Falha ao ler historico de organizacoes: %s", e)
        return []


def _salvar_historico(historico: List[dict], caminho_arquivo: Optional[Path] = None) -> None:
    p = caminho_arquivo or config.HISTORICO_ORGANIZACOES
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(historico, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.error("Falha ao salvar historico de organizacoes: %s", e)


def executar_organizacao(
    id_sessao: Optional[str] = None,
    movimentacoes: Optional[List[dict]] = None,
    pasta: Optional[str] = None,
    caminho_historico: Optional[Path] = None,
) -> dict:
    """Executa as movimentacoes planejadas, garantindo preservacao e registro de historico."""
    global _ULTIMA_PREVIA
    previa_selecionada = None

    if id_sessao and id_sessao in _PREVIAS_PENDENTES:
        previa_selecionada = _PREVIAS_PENDENTES.pop(id_sessao)
    elif _ULTIMA_PREVIA and (not id_sessao or _ULTIMA_PREVIA.get("id_sessao") == id_sessao):
        previa_selecionada = _ULTIMA_PREVIA
        _ULTIMA_PREVIA = None

    if previa_selecionada:
        lista_movs = previa_selecionada.get("movimentacoes", [])
        pasta_alvo = previa_selecionada.get("pasta", "")
        criterio = previa_selecionada.get("criterio", "tipo")
    elif movimentacoes:
        lista_movs = movimentacoes
        pasta_alvo = pasta or (Path(movimentacoes[0]["origem"]).parent if movimentacoes else "")
        criterio = "personalizado"
    else:
        return {"ok": False, "erro": "nenhuma_previa_pendente", "mensagem": "Nenhuma previa para executar."}

    if not lista_movs:
        return {"ok": True, "total_movidos": 0, "mensagem": "Nenhum arquivo para mover."}

    movidos_sucesso: List[Dict[str, str]] = []

    for mov in lista_movs:
        origem = Path(mov["origem"])
        if not origem.exists() or not origem.is_file():
            continue

        destino_pretendido = Path(mov["destino"])
        destino_pretendido.parent.mkdir(parents=True, exist_ok=True)
        destino_final = resolver_destino_sem_colisao(destino_pretendido)

        try:
            shutil.move(str(origem), str(destino_final))
            movidos_sucesso.append({
                "origem": str(origem),
                "destino": str(destino_final),
            })
        except Exception as e:
            log.error("Erro ao mover %s para %s: %s", origem, destino_final, e)

    id_op = f"op_{uuid.uuid4().hex[:8]}"
    registro_op = {
        "id_operacao": id_op,
        "timestamp": datetime.now().isoformat(),
        "pasta": str(pasta_alvo),
        "criterio": criterio,
        "total_movidos": len(movidos_sucesso),
        "desfeita": False,
        "movimentos": movidos_sucesso,
    }

    historico = _carregar_historico(caminho_historico)
    historico.append(registro_op)
    _salvar_historico(historico, caminho_historico)

    return {
        "ok": True,
        "id_operacao": id_op,
        "total_movidos": len(movidos_sucesso),
        "movimentos": movidos_sucesso,
        "pasta": str(pasta_alvo),
    }


def desfazer_ultima_organizacao(
    pasta: Optional[str] = None,
    caminho_historico: Optional[Path] = None,
) -> dict:
    """Desfaz a ultima operacao de organizacao ativa, retornando arquivos aos locais originais."""
    historico = _carregar_historico(caminho_historico)
    if not historico:
        return {"ok": False, "erro": "nenhuma_operacao_encontrada", "mensagem": "Nenhuma operacao para desfazer."}

    alvo_pasta_str = str(Path(pasta).resolve()) if pasta else None

    # Procura da operacao mais recente para a mais antiga
    op_encontrada = None
    for op in reversed(historico):
        if op.get("desfeita", False):
            continue
        if alvo_pasta_str and op.get("pasta") != alvo_pasta_str:
            continue
        op_encontrada = op
        break

    if not op_encontrada:
        return {"ok": False, "erro": "nenhuma_operacao_ativa", "mensagem": "Nenhuma operacao ativa encontrada para desfazer."}

    desfeitos: List[Dict[str, str]] = []
    # Restaura em ordem inversa de movimentacao
    for m in reversed(op_encontrada.get("movimentos", [])):
        origem_original = Path(m["origem"])
        destino_atual = Path(m["destino"])

        if not destino_atual.exists():
            continue

        origem_original.parent.mkdir(parents=True, exist_ok=True)
        destino_restaurado = resolver_destino_sem_colisao(origem_original)

        try:
            shutil.move(str(destino_atual), str(destino_restaurado))
            desfeitos.append({
                "origem": str(destino_atual),
                "destino": str(destino_restaurado),
            })

            # Remove subdiretorio se ficou vazio
            subpasta = destino_atual.parent
            if subpasta.exists() and subpasta != Path(op_encontrada.get("pasta", "")).resolve():
                try:
                    if not any(subpasta.iterdir()):
                        subpasta.rmdir()
                except OSError:
                    pass
        except Exception as e:
            log.error("Erro ao desfazer movimentacao de %s: %s", destino_atual, e)

    op_encontrada["desfeita"] = True
    op_encontrada["desfeita_em"] = datetime.now().isoformat()
    _salvar_historico(historico, caminho_historico)

    return {
        "ok": True,
        "id_operacao": op_encontrada["id_operacao"],
        "total_desfeitos": len(desfeitos),
        "movimentos": desfeitos,
        "pasta": op_encontrada.get("pasta", ""),
    }


def listar_historico(
    limite: int = 10,
    caminho_historico: Optional[Path] = None,
) -> List[dict]:
    """Retorna as ultimas operacoes registradas no historico."""
    historico = _carregar_historico(caminho_historico)
    return historico[-limite:]


def mapear_alvo_por_nome(nome_alvo: str) -> Optional[Path]:
    """Mapeia um nome falado (ex: 'downloads', 'documentos') para uma pasta permitida correspondente."""
    alvo = (nome_alvo or "").strip().lower()
    if not alvo:
        return None

    permitidas = obter_pastas_permitidas()
    # 1. Checa por correspondencia exata de nome de pasta
    for p in permitidas:
        if p.name.lower() == alvo:
            return p

    # 2. Mapeamento comum
    home = Path.home()
    if alvo in ("download", "downloads", "baixados"):
        candidato = (home / "Downloads").resolve()
        if candidato in permitidas or any(candidato.is_relative_to(perm) for perm in permitidas):
            return candidato
    if alvo in ("documento", "documentos", "docs", "meus documentos"):
        for nome in ("Documents", "Documentos"):
            candidato = (home / nome).resolve()
            if candidato in permitidas or any(candidato.is_relative_to(perm) for perm in permitidas):
                return candidato

    # 3. Checa se o alvo e um caminho relativo ou subpasta de alguma permitida
    for p in permitidas:
        sub = (p / alvo).resolve()
        if sub.exists() and sub.is_dir():
            return sub

    return None


def gerar_previa_por_frase(alvo_nome: str, criterio: str = "tipo") -> str:
    """Gera previa a partir do nome falado e retorna mensagem amigavel."""
    pasta = mapear_alvo_por_nome(alvo_nome)
    if not pasta:
        return f"Nao encontrei ou nao tenho permissao para acessar a pasta '{alvo_nome}'."

    try:
        previa = gerar_previa(pasta, criterio=criterio)
    except PastaNaoPermitidaError as e:
        return f"Acesso negado: {e}"
    except Exception as e:
        return f"Nao foi possivel analisar a pasta: {e}"

    total = previa.get("total_arquivos", 0)
    if total == 0:
        return f"A pasta {pasta.name} ja esta organizada ou nao possui arquivos soltos."

    resumo_cat = previa.get("resumo_categorias", {})
    detalhes = ", ".join(f"{qtd} em {cat}" for cat, qtd in resumo_cat.items())
    return (
        f"Previa gerada para {pasta.name}: {total} arquivos serao organizados por {previa['criterio']} "
        f"({detalhes}). Para confirmar, diga 'confirma organizacao'."
    )


def confirmar_organizacao_pendente() -> str:
    """Confirma e executa a ultima previa pendente."""
    resultado = executar_organizacao()
    if not resultado.get("ok"):
        return resultado.get("mensagem", "Nenhuma organizacao pendente para confirmar.")

    total = resultado.get("total_movidos", 0)
    return f"Organizacao concluida: {total} arquivos movidos com sucesso."


def desfazer_organizacao_por_frase(alvo_nome: Optional[str] = None) -> str:
    """Desfaz a ultima organizacao e retorna mensagem amigavel."""
    pasta = mapear_alvo_por_nome(alvo_nome) if alvo_nome else None
    pasta_str = str(pasta) if pasta else None

    resultado = desfazer_ultima_organizacao(pasta=pasta_str)
    if not resultado.get("ok"):
        return resultado.get("mensagem", "Nao encontrei organizacao recente para desfazer.")

    total = resultado.get("total_desfeitos", 0)
    return f"Organizacao desfeita: {total} arquivos restaurados para seus locais originais."
