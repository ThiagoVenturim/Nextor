"""Carregamento e gerenciamento de trilhas embutidas e de usuario (Issue #57)."""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import uuid

try:
    import yaml
except ImportError:
    yaml = None

from .. import config
from .modelos import Recurso, Trilha

log = logging.getLogger("nextor.coach.trilhas")

PASTA_EMBUTIDAS = Path(__file__).resolve().parent / "trilhas"


def _obter_pasta_usuario(pasta: Optional[Union[str, Path]] = None) -> Path:
    if pasta:
        p = Path(pasta).resolve()
    elif hasattr(config, "COACH_TRILHAS_DIR") and config.COACH_TRILHAS_DIR:
        p = Path(config.COACH_TRILHAS_DIR).resolve()
    else:
        p = (Path.home() / ".nextor" / "trilhas").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ler_arquivo_trilha(caminho: Path) -> Optional[Trilha]:
    if not caminho.exists() or not caminho.is_file():
        return None
    ext = caminho.suffix.lower()
    try:
        conteudo = caminho.read_text(encoding="utf-8")
        if ext in (".yaml", ".yml"):
            if yaml is None:
                log.warning("PyYAML nao instalado; ignorando arquivo yaml: %s", caminho)
                return None
            dados = yaml.safe_load(conteudo)
        elif ext == ".json":
            dados = json.loads(conteudo)
        else:
            return None

        if not isinstance(dados, dict):
            return None

        # Garante id caso nao tenha
        if not dados.get("id"):
            dados["id"] = caminho.stem

        return Trilha.from_dict(dados)
    except Exception as e:
        log.error("Erro ao ler trilha em %s: %s", caminho, e)
        return None


def carregar_trilhas_embutidas() -> List[Trilha]:
    """Carrega todas as trilhas abertas e em dominio publico distribuidas no Nextor."""
    trilhas: List[Trilha] = []
    if not PASTA_EMBUTIDAS.exists():
        return trilhas

    for arq in sorted(PASTA_EMBUTIDAS.iterdir()):
        if arq.suffix.lower() in (".yaml", ".yml", ".json"):
            t = _ler_arquivo_trilha(arq)
            if t:
                trilhas.append(t)
    return trilhas


def carregar_trilhas_usuario(pasta: Optional[Union[str, Path]] = None) -> List[Trilha]:
    """Carrega as trilhas criadas ou customizadas pelo usuario."""
    pasta_u = _obter_pasta_usuario(pasta)
    trilhas: List[Trilha] = []
    for arq in sorted(pasta_u.iterdir()):
        if arq.suffix.lower() in (".yaml", ".yml", ".json"):
            t = _ler_arquivo_trilha(arq)
            if t:
                trilhas.append(t)
    return trilhas


def carregar_todas_trilhas(pasta_usuario: Optional[Union[str, Path]] = None) -> List[Trilha]:
    """Retorna todas as trilhas disponiveis, com preferencia para versoes do usuario."""
    mapa: Dict[str, Trilha] = {}
    # 1. Embutidas primeiro
    for t in carregar_trilhas_embutidas():
        mapa[t.id] = t
    # 2. Versoes do usuario sobrescrevem se tiverem mesmo ID
    for t in carregar_trilhas_usuario(pasta_usuario):
        mapa[t.id] = t
    return list(mapa.values())


def obter_trilha(trilha_id: str, pasta_usuario: Optional[Union[str, Path]] = None) -> Optional[Trilha]:
    """Busca uma trilha por ID entre usuario e embutidas."""
    tid = (trilha_id or "").strip()
    if not tid:
        return None
    for t in carregar_todas_trilhas(pasta_usuario):
        if t.id == tid:
            return t
    return None


def salvar_trilha_usuario(
    trilha: Trilha,
    formato: str = "yaml",
    pasta: Optional[Union[str, Path]] = None,
) -> Path:
    """Grava ou atualiza a trilha na pasta local do usuario."""
    pasta_u = _obter_pasta_usuario(pasta)
    ext = ".json" if formato.lower() == "json" or yaml is None else ".yaml"
    caminho = pasta_u / f"{trilha.id}{ext}"

    dados = trilha.to_dict()
    if ext == ".json":
        caminho.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        caminho.write_text(yaml.safe_dump(dados, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return caminho


def criar_trilha(
    id_trilha: str,
    titulo: str,
    habilidade: str,
    nivel: str = "iniciante",
    descricao: str = "",
    recursos: Optional[List[Union[Dict, Recurso]]] = None,
    pasta: Optional[Union[str, Path]] = None,
) -> Trilha:
    """Cria uma nova trilha personalizada para o usuario."""
    tid = (id_trilha or "").strip() or f"trilha_{uuid.uuid4().hex[:8]}"
    recs: List[Recurso] = []
    if recursos:
        for idx, r in enumerate(recursos, start=1):
            if isinstance(r, Recurso):
                recs.append(r)
            elif isinstance(r, dict):
                r_dict = dict(r)
                r_dict.setdefault("trilha_id", tid)
                r_dict.setdefault("ordem", idx)
                recs.append(Recurso.from_dict(r_dict))

    trilha = Trilha(
        id=tid,
        titulo=titulo or "Trilha personalizada",
        habilidade=habilidade or "geral",
        nivel=nivel or "iniciante",
        descricao=descricao or "",
        recursos=recs,
        autor="Usuario",
    )
    salvar_trilha_usuario(trilha, pasta=pasta)
    return trilha
