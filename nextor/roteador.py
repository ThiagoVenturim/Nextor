"""Roteador de intencoes: entende a frase e decide a habilidade (anotar/agenda/noticias/conversar)."""
import re
import unicodedata
from datetime import datetime

from . import config

PREFIXOS = r"^(ei|ola|oi|opa|fala|bom dia|boa tarde|boa noite|e ai)?[, ]*(nextor|nestor)?[,: ]*"
PALAVRAS_AGENDA = ("agenda", "compromisso", "reuniao", "audiencia", "prazo", "calendario")
PALAVRAS_NOTICIA = ("noticia", "noticias", "novidade", "novidades", "manchete", "manchetes")
PALAVRAS_ANOTAR = ("anota", "anotar", "anote", "lembra", "lembrar", "lembrete")
# "no computador, bloquear" / "no pc play" / "deck volume mais" -> aperta um botao do NexDeck.
GATILHO_DECK = r"^(no computador|no pc|no notebook|deck)[,: ]+(.+)$"
# "mostra na tv", "continua no celular", "passa pro pc" -> hand-off entre aparelhos.
GATILHO_DISPOSITIVO = r"^(mostra|mostrar|continua|continuar|passa|passar|manda|mandar)\s+(na|no|pra|pro)\s+([a-z0-9_-]+)(?:[:,\s]+(.*))?$"


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _limpa(frase: str) -> str:
    return re.sub(PREFIXOS, "", frase.strip(), flags=re.IGNORECASE).strip()


def _registra(frase: str, intencao: str) -> None:
    try:
        with config.LOG_COMANDOS.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{intencao}\t{frase}\n")
    except Exception:
        pass


def rotear(frase: str, canal: str = "local", id_dispositivo: str | None = None) -> dict:
    from .chamado import entender
    from .companheiro import companheiro, identidade_pedida
    # "ei Nextor", "meu amigo Nextor", "ola Claude"...: quem foi chamado responde e o rosto acorda.
    chamado = entender(frase)
    if chamado["chamado"]:
        if chamado["nome"] != companheiro.ver().get("identidade"):
            companheiro.definir_identidade(chamado["nome"])
        companheiro.atualizar(atividade="ouvindo")
        if not chamado["comando"].strip():
            _registra(frase, "chamado")
            return {"intencao": "chamado", "resposta": "Oi, pode falar."}
        frase = chamado["comando"]
    limpa = _limpa(frase)
    base = _sem_acento(limpa)

    identidade = identidade_pedida(limpa)
    if identidade:
        _registra(frase, "identidade")
        return {"intencao": "identidade", "resposta": companheiro.definir_identidade(identidade)["frase"]}

    # Skill de texto (traduzir / resumir / escrever) - antes das outras intencoes.
    if "traduz" in base:
        m = re.search(r"traduz\w*\s+(.*?)\s+para\s+(.+)$", limpa, flags=re.IGNORECASE)
        if m:
            conteudo, idioma = m.group(1).strip(), m.group(2).strip(" ?.")
        else:
            conteudo = re.sub(r".*?traduz\w*\s+", "", limpa, count=1, flags=re.IGNORECASE).strip()
            idioma = "ingles"
        _registra(frase, "traduzir")
        return {"intencao": "traduzir", "resposta": _fazer_texto("traduzir", conteudo, idioma)}
    if "resum" in base:
        conteudo = re.sub(r".*?resum\w*\s+", "", limpa, count=1, flags=re.IGNORECASE).strip()
        _registra(frase, "resumir")
        return {"intencao": "resumir", "resposta": _fazer_texto("resumir", conteudo)}
    if "escrev" in base or "conta uma historia" in base or base.startswith("historia"):
        pedido = re.sub(r".*?escrev\w*\s+", "", limpa, count=1, flags=re.IGNORECASE).strip() or limpa
        _registra(frase, "escrever")
        return {"intencao": "escrever", "resposta": _fazer_texto("escrever", pedido)}

    from .companheiro import modo_pedido
    modo = modo_pedido(limpa)
    if modo:
        _registra(frase, "modo")
        return {"intencao": "modo", "resposta": _fazer_modo(modo)}

    m_disp = re.match(GATILHO_DISPOSITIVO, base)
    if m_disp:
        alvo = m_disp.group(3)
        resto = (m_disp.group(4) or "").strip()
        _registra(frase, "dispositivo")
        return {"intencao": "dispositivo", "resposta": _fazer_dispositivo(alvo, resto)}

    m = re.match(GATILHO_DECK, base)
    if m:
        if id_dispositivo:
            from . import dispositivos
            if not dispositivos.tem_permissao(id_dispositivo, "executar"):
                _registra(frase, "deck_negado")
                return {"intencao": "deck", "resposta": "Este aparelho nao tem permissao para executar acoes no computador."}
        _registra(frase, "deck")
        return {"intencao": "deck", "resposta": _fazer_deck(m.group(2).strip(" ?."))}

    for p in PALAVRAS_ANOTAR:
        if base.startswith(p) or f" {p} " in f" {base} ":
            texto = re.sub(rf".*\b{p}\b( que| o que| para)?", "", limpa, count=1, flags=re.IGNORECASE).strip(" ,:")
            resposta = _fazer_anotar(texto or limpa)
            _registra(frase, "anotar")
            return {"intencao": "anotar", "resposta": resposta}

    if any(w in base for w in PALAVRAS_NOTICIA):
        m = re.search(r"sobre (.+)$", limpa, flags=re.IGNORECASE)
        assunto = m.group(1).strip(" ?.") if m else ""
        _registra(frase, "noticias")
        return {"intencao": "noticias", "resposta": _fazer_noticias(assunto)}

    if "volume" in base:
        m = re.search(r"(\d{1,3})", base)
        _registra(frase, "nest_volume")
        if m:
            return {"intencao": "nest", "resposta": _fazer_nest("volume", int(m.group(1)))}
        if "aument" in base or "mais alto" in base:
            return {"intencao": "nest", "resposta": _fazer_nest("volume", 80)}
        if "diminu" in base or "mais baixo" in base or "abaix" in base:
            return {"intencao": "nest", "resposta": _fazer_nest("volume", 25)}
    if base.startswith("para") and ("musica" in base or "som" in base or "tocar" in base) or "parar a musica" in base:
        _registra(frase, "nest_parar")
        return {"intencao": "nest", "resposta": _fazer_nest("parar")}

    # Skill de Estudos (biblioteca de materias e busca FTS5)
    # Gravacao de aulas (Issue #3)
    if "para a gravacao" in base or "parar a gravacao" in base or "para gravacao" in base or "parar gravacao" in base or "encerrar gravacao" in base or "terminar gravacao" in base:
        _registra(frase, "estudos_parar_gravacao")
        return {"intencao": "estudos_parar_gravacao", "resposta": _fazer_estudos_parar_gravacao()}

    m_grav = re.search(r"(?:grava|gravar|iniciar gravacao)(?:\s+a|\s+da|\s+de)?\s+aula\s+(?:de\s+|da\s+)?(.+)$", limpa, flags=re.IGNORECASE)
    if m_grav:
        disc_aula = m_grav.group(1).strip(" ?.")
        _registra(frase, "estudos_gravar_aula")
        return {"intencao": "estudos_gravar_aula", "resposta": _fazer_estudos_gravar_aula(disc_aula)}

    if base.startswith("nova disciplina") or base.startswith("criar disciplina") or base.startswith("crie a disciplina"):
        nome_disc = re.sub(r"^(nova disciplina|criar disciplina|crie a disciplina)\s+", "", limpa, flags=re.IGNORECASE).strip(" .:")
        _registra(frase, "estudos_criar_disciplina")
        return {"intencao": "estudos_criar_disciplina", "resposta": _fazer_estudos_criar_disciplina(nome_disc)}

    if base.startswith("adiciona") or base.startswith("adicionar"):
        m = re.search(r"adiciona\w*\s+(?:este\s+|o\s+)?(?:pdf|docx|arquivo|documento|texto|link)?\s*(.*?)\s+em\s+(.+)$", limpa, flags=re.IGNORECASE)
        if m:
            origem_mat, disc_mat = m.group(1).strip(), m.group(2).strip(" ?.")
            _registra(frase, "estudos_adicionar")
            if canal != "local":
                return {"intencao": "estudos_adicionar", "resposta": _fazer_estudos_adicionar(disc_mat, origem_mat, canal=canal)}
            return {"intencao": "estudos_adicionar", "resposta": _fazer_estudos_adicionar(disc_mat, origem_mat)}

    m_mat = re.search(r"(?:o que (?:eu )?tenho de material (?:de|em)\s+|listar materiais? (?:de|em)\s+|materiais? (?:de|em)\s+)(.+)$", limpa, flags=re.IGNORECASE)
    if m_mat:
        disc_mat = m_mat.group(1).strip(" ?.")
        _registra(frase, "estudos_listar_materiais")
        return {"intencao": "estudos_listar_materiais", "resposta": _fazer_estudos_listar_materiais(disc_mat)}

    if base in ("disciplinas", "minhas disciplinas", "listar disciplinas", "quais disciplinas eu tenho", "o que tenho de disciplinas"):
        _registra(frase, "estudos_listar_disciplinas")
        return {"intencao": "estudos_listar_disciplinas", "resposta": _fazer_estudos_listar_disciplinas()}

    m_busca = re.search(r"(?:busca|buscar|pesquisa|pesquisar)\s+(?:material\s+)?(?:sobre\s+)?(.*?)\s+em\s+(.+)$", limpa, flags=re.IGNORECASE)
    if m_busca:
        termo_busca, disc_busca = m_busca.group(1).strip(), m_busca.group(2).strip(" ?.")
        _registra(frase, "estudos_buscar")
        return {"intencao": "estudos_buscar", "resposta": _fazer_estudos_buscar(termo_busca, disc_busca)}

    # Skill Organizador de Pastas (Issue #15)
    if "desfaz organizacao" in base or "desfazer organizacao" in base or "desfaz a organizacao" in base or "desfazer a organizacao" in base:
        _registra(frase, "organizador_desfazer")
        return {"intencao": "organizador_desfazer", "resposta": _fazer_organizador_desfazer()}

    if "confirma organizacao" in base or "confirmar organizacao" in base or "confirme a organizacao" in base or "confirmar a organizacao" in base:
        _registra(frase, "organizador_confirmar")
        return {"intencao": "organizador_confirmar", "resposta": _fazer_organizador_confirmar()}

    m_org = re.search(r"(?:organiza|organizar)\s+(?:minha\s+|a\s+)?pasta\s+(.+?)(?:\s+por\s+(tipo|data|disciplina))?$", limpa, flags=re.IGNORECASE)
    if m_org:
        alvo_pasta = m_org.group(1).strip(" ?.")
        criterio_pasta = (m_org.group(2) or "tipo").strip().lower()
        _registra(frase, "organizador_previa")
        return {"intencao": "organizador_previa", "resposta": _fazer_organizador_previa(alvo_pasta, criterio_pasta)}

    if any(w in base for w in PALAVRAS_AGENDA) or "o que tenho" in base or "o que eu tenho" in base:
        quando = "proximos" if any(k in base for k in ("amanha", "semana", "proxim")) else "hoje"
        _registra(frase, "agenda")
        return {"intencao": "agenda", "resposta": _fazer_agenda(quando)}

    _registra(frase, "conversar")
    return {"intencao": "conversar", "resposta": _fazer_conversar(limpa or frase)}


def _fazer_anotar(texto: str) -> str:
    carimbo = datetime.now().strftime("%Y-%m-%d %H:%M")
    with config.ANOTACOES.open("a", encoding="utf-8") as f:
        f.write(f"- [{carimbo}] {texto}\n")
    return f"Anotei: {texto}"


def _fazer_agenda(quando: str) -> str:
    try:
        from .agenda import eventos_hoje, eventos_proximos, resumo_falado
        if quando == "proximos":
            return resumo_falado(eventos_proximos(7), prefixo_dia=True)
        return "Hoje: " + resumo_falado(eventos_hoje())
    except Exception:
        return "Nao consegui ler a agenda agora."


def _fazer_noticias(assunto: str) -> str:
    try:
        from .noticias import resumir
        return resumir(assunto)
    except Exception:
        return "Nao consegui buscar as noticias agora."


def _fazer_modo(modo: str) -> str:
    try:
        from .companheiro import companheiro
        r = companheiro.definir_modo(modo)
        return " ".join([r["frase"], *r["avisos"]])
    except Exception:
        return "Nao consegui mudar de modo agora."


def _fazer_dispositivo(alvo: str, resto: str = "") -> str:
    try:
        from . import dispositivos
        from .companheiro import companheiro
        disp = dispositivos.buscar_por_tipo_ou_nome(alvo)
        if not disp:
            return f"Nao encontrei o aparelho {alvo}."
        if not disp.get("ativo", True):
            return f"O aparelho {disp['nome']} esta desativado ou revogado."

        if resto:
            r = rotear(resto)
            conteudo = r.get("resposta", resto)
        else:
            estado = companheiro.ver()
            conteudo = estado.get("ultima_resposta") or "Pronto para continuar aqui."

        dispositivos.enviar_resposta_dispositivo(disp["id"], conteudo)
        artigo = "na" if disp["tipo"] == "tv" else "no"
        return f"Mostrando {artigo} {disp['nome']}."
    except Exception:
        return f"Nao consegui enviar para {alvo} agora."


def _fazer_deck(nome: str) -> str:
    try:
        from . import deck
        return deck.apertar(nome)
    except Exception:
        return "Nao consegui falar com o NexDeck agora."


def _fazer_nest(acao: str, nivel: int = 50) -> str:
    try:
        from . import nest
        if acao == "volume":
            return nest.volume(nivel)
        return nest.parar()
    except Exception as e:
        return "Nao consegui controlar o Nest agora."


def _fazer_texto(acao: str, conteudo: str, idioma: str = "ingles") -> str:
    try:
        from .texto import traduzir, resumir_texto, escrever
        if acao == "traduzir":
            return traduzir(conteudo, idioma)["aviso"]
        if acao == "resumir":
            return resumir_texto(conteudo)["aviso"]
        return escrever(conteudo)["aviso"]
    except Exception:
        return "Nao consegui gerar o texto agora."


def _fazer_conversar(frase: str) -> str:
    try:
        from .cerebro import conversar
        return conversar(frase)
    except Exception:
        return "Estou aqui, mas meu cerebro esta fora do ar agora."


def _fazer_estudos_criar_disciplina(nome: str) -> str:
    try:
        from . import estudos
        res = estudos.criar_disciplina(nome)
        return res.get("aviso") or res.get("erro", "Erro ao criar disciplina.")
    except Exception:
        return "Nao consegui criar a disciplina agora."


def _fazer_estudos_adicionar(disciplina: str, origem: str, canal: str = "local") -> str:
    if not origem:
        return f"Informe o arquivo ou link para adicionar em {disciplina}."
    try:
        from . import estudos
        res = estudos.importar_material(disciplina, origem, canal=canal)
        return res.get("aviso") or res.get("erro", "Erro ao adicionar material.")
    except Exception:
        return f"Nao consegui adicionar o material em {disciplina} agora."


def _fazer_estudos_listar_materiais(disciplina: str) -> str:
    try:
        from . import estudos
        return estudos.resumo_materiais(disciplina)
    except Exception:
        return f"Nao consegui listar os materiais de {disciplina} agora."


def _fazer_estudos_listar_disciplinas() -> str:
    try:
        from . import estudos
        return estudos.resumo_disciplinas()
    except Exception:
        return "Nao consegui listar as disciplinas agora."


def _fazer_estudos_buscar(termo: str, disciplina: str = "") -> str:
    try:
        from . import estudos
        return estudos.resumo_busca(termo, disciplina_nome=disciplina)
    except Exception:
        return "Nao consegui buscar os materiais agora."


def _fazer_estudos_gravar_aula(disciplina: str) -> str:
    try:
        from . import aulas
        res = aulas.iniciar_gravacao(disciplina)
        return res.get("aviso") or res.get("erro", "Erro ao iniciar gravacao.")
    except Exception:
        return "Nao consegui iniciar a gravacao da aula agora."


def _fazer_estudos_parar_gravacao() -> str:
    try:
        from . import aulas
        res = aulas.parar_gravacao()
        return res.get("aviso") or res.get("erro", "Erro ao encerrar gravacao.")
    except Exception:
        return "Nao consegui encerrar a gravacao agora."


def _fazer_organizador_previa(alvo: str, criterio: str = "tipo") -> str:
    try:
        from . import organizador
        return organizador.gerar_previa_por_frase(alvo, criterio=criterio)
    except Exception as e:
        return f"Nao consegui gerar a previa da organizacao: {e}"


def _fazer_organizador_confirmar() -> str:
    try:
        from . import organizador
        return organizador.confirmar_organizacao_pendente()
    except Exception as e:
        return f"Nao consegui executar a organizacao: {e}"


def _fazer_organizador_desfazer(alvo: str | None = None) -> str:
    try:
        from . import organizador
        return organizador.desfazer_organizacao_por_frase(alvo)
    except Exception as e:
        return f"Nao consegui desfazer a organizacao: {e}"


if __name__ == "__main__":
    import sys
    r = rotear(" ".join(sys.argv[1:]) or "ei Nextor, o que tenho amanha?")
    print(f"[{r['intencao']}] {r['resposta']}")
