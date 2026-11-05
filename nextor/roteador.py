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

    # Resposta a quiz interativo pendente (Issue #6)
    try:
        from .quiz import sessao_quiz
        if sessao_quiz.obter_ativa():
            m_resp = re.search(r"^(?:letra\s+|opcao\s+)?([a-d]|verdadeiro|falso|v|f)$", base.strip(), flags=re.IGNORECASE)
            if m_resp:
                letra_ou_vf = m_resp.group(1).upper()
                resultado = sessao_quiz.responder(letra_ou_vf)
                if resultado and resultado.get("ok"):
                    _registra(frase, "estudos_quiz_resposta")
                    return {"intencao": "estudos_quiz_resposta", "resposta": resultado["mensagem"]}
    except Exception:
        pass

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

    # Perguntas sobre a materia com fontes (Issue #5)
    m_qa_diz = re.search(r"o que (?:o )?meu material diz sobre\s+(.+)$", limpa, flags=re.IGNORECASE)
    if m_qa_diz:
        termo_qa = m_qa_diz.group(1).strip(" ?.")
        _registra(frase, "estudos_perguntar")
        return {"intencao": "estudos_perguntar", "resposta": _fazer_estudos_perguntar(termo_qa)}

    if any(k in base for k in ("segundo o meu material", "pelo meu material", "no meu material", "segundo meu material")):
        texto_limpo_qa = re.sub(
            r"\b(segundo\s+o\s+meu\s+material|pelo\s+meu\s+material|no\s+meu\s+material|segundo\s+meu\s+material)\b",
            "",
            limpa,
            flags=re.IGNORECASE,
        ).strip(" ?.,:")
        _registra(frase, "estudos_perguntar")
        return {"intencao": "estudos_perguntar", "resposta": _fazer_estudos_perguntar(texto_limpo_qa)}

    # Busca de artigos cientificos em fontes abertas (Issue #7)
    m_salvar_art = re.search(r"^salvar\s+artigo\s+(.+?)\s+(?:na\s+disciplina|em|para)\s+(.+)$", limpa, flags=re.IGNORECASE)
    if m_salvar_art:
        art_id = m_salvar_art.group(1).strip(" ?.")
        disc_art = m_salvar_art.group(2).strip(" ?.")
        _registra(frase, "estudos_salvar_artigo")
        return {"intencao": "estudos_salvar_artigo", "resposta": _fazer_estudos_salvar_artigo(art_id, disc_art)}

    m_art_disc = re.search(r"^(?:busca|buscar|pesquisa|pesquisar|procura|procurar)\s+artigos?\s+(?:sobre|de)\s+(.+?)\s+(?:para|em|na disciplina)\s+(.+)$", limpa, flags=re.IGNORECASE)
    if m_art_disc:
        termo_art = m_art_disc.group(1).strip()
        disc_art = m_art_disc.group(2).strip(" ?.")
        _registra(frase, "estudos_buscar_artigos")
        return {"intencao": "estudos_buscar_artigos", "resposta": _fazer_estudos_buscar_artigos(termo_art, disciplina=disc_art)}

    m_art = re.search(r"^(?:busca|buscar|pesquisa|pesquisar|procura|procurar)\s+artigos?\s+(?:sobre|de)\s+(.+)$", limpa, flags=re.IGNORECASE)
    if m_art:
        termo_art = m_art.group(1).strip(" ?.")
        _registra(frase, "estudos_buscar_artigos")
        return {"intencao": "estudos_buscar_artigos", "resposta": _fazer_estudos_buscar_artigos(termo_art)}

    # Quizzes de estudos com repeticao espacada (Issue #6)
    if base in ("quiz do dia", "quiz de hoje", "fazer o quiz do dia", "iniciar quiz do dia", "quiz diario", "quiz diário"):
        _registra(frase, "estudos_quiz_do_dia")
        return {"intencao": "estudos_quiz_do_dia", "resposta": _fazer_estudos_quiz_do_dia()}

    m_quiz = re.search(r"^(?:me\s+faz\s+(?:um\s+)?|fazer\s+(?:um\s+)?|iniciar\s+(?:o\s+)?|comecar\s+(?:o\s+)?|quero\s+(?:um\s+)?)?quiz\s+(?:de\s+|da\s+|do\s+|em\s+)?(.+)$", limpa, flags=re.IGNORECASE)
    if m_quiz and not any(k in base for k in ("dia", "hoje")):
        disc_quiz = m_quiz.group(1).strip(" ?.")
        _registra(frase, "estudos_quiz")
        return {"intencao": "estudos_quiz", "resposta": _fazer_estudos_iniciar_quiz(disc_quiz)}

    # Resumos de estudos (Issue #4) e flashcards Anki
    m_flash = re.search(r"^(?:gerar\s+|criar\s+|fazer\s+)?flashcards\s+(?:de\s+|da\s+|do\s+|em\s+)?(.+)$", limpa, flags=re.IGNORECASE)
    if m_flash:
        disc_flash = m_flash.group(1).strip(" ?.")
        _registra(frase, "estudos_flashcards")
        return {"intencao": "estudos_flashcards", "resposta": _fazer_estudos_resumo(disc_flash, alvo="", gerar_cards=True)}

    m_resumo_aula = re.search(r"^resum\w*\s+(?:a\s+)?(?:ultima\s+aula|aula)\s+(?:de\s+|da\s+|do\s+|em\s+)?(.+)$", limpa, flags=re.IGNORECASE)
    if m_resumo_aula:
        disc_res = m_resumo_aula.group(1).strip(" ?.")
        _registra(frase, "estudos_resumo")
        return {"intencao": "estudos_resumo", "resposta": _fazer_estudos_resumo(disc_res, alvo="ultima aula", gerar_cards=True)}

    m_resumo_cap = re.search(r"^resum\w*\s+(?:o\s+)?(capitulo\s+[\w\d]+|modulo\s+[\w\d]+|material\s+[\w\d]+)\s+(?:de\s+|da\s+|do\s+|em\s+)?(.+)$", limpa, flags=re.IGNORECASE)
    if m_resumo_cap:
        alvo_cap = m_resumo_cap.group(1).strip()
        disc_res = m_resumo_cap.group(2).strip(" ?.")
        _registra(frase, "estudos_resumo")
        return {"intencao": "estudos_resumo", "resposta": _fazer_estudos_resumo(disc_res, alvo=alvo_cap, gerar_cards=True)}

    m_resumo_disc = re.search(r"^resum\w*\s+(?:a\s+disciplina\s+|a\s+materia\s+)(?:de\s+|da\s+|do\s+|em\s+)?(.+)$", limpa, flags=re.IGNORECASE)
    if m_resumo_disc:
        disc_res = m_resumo_disc.group(1).strip(" ?.")
        _registra(frase, "estudos_resumo")
        return {"intencao": "estudos_resumo", "resposta": _fazer_estudos_resumo(disc_res, alvo="", gerar_cards=True)}

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

    # Skill Integracao GitHub (Issue #16)
    if any(k in base for k in ("meu kanban", "no kanban", "ver kanban", "listar kanban")):
        _registra(frase, "github_kanban")
        return {"intencao": "github_kanban", "resposta": _fazer_github_kanban()}

    if any(k in base for k in ("minhas issues", "listar issues", "quais issues", "ver issues")):
        _registra(frase, "github_issues")
        return {"intencao": "github_issues", "resposta": _fazer_github_issues()}

    if "confirma criacao" in base or "confirmar criacao" in base or "confirma movimentacao" in base or "confirmar movimentacao" in base or (base in ("confirma", "confirmar") and _tem_acao_pendente_github()):
        _registra(frase, "github_confirmar")
        return {"intencao": "github_confirmar", "resposta": _fazer_github_confirmar()}

    if "cancela criacao" in base or "cancelar criacao" in base or "cancela movimentacao" in base or "cancelar movimentacao" in base:
        _registra(frase, "github_cancelar")
        return {"intencao": "github_cancelar", "resposta": _fazer_github_cancelar()}

    m_issue = re.search(r"(?:cria|criar|crie)\s+(?:uma\s+)?issue(?:\s+no\s+|\s+em\s+|\s+para\s+o\s+)?([^\s:]+)?[:,\s]+(.+)$", limpa, flags=re.IGNORECASE)
    if m_issue:
        repo_alvo = (m_issue.group(1) or "").strip()
        titulo_issue = (m_issue.group(2) or "").strip(" ?.")
        _registra(frase, "github_propor_issue")
        return {"intencao": "github_propor_issue", "resposta": _fazer_github_propor_issue(repo_alvo, titulo_issue)}

    m_mover = re.search(r"(?:move|mover|mova)\s+(?:o\s+)?cartao\s+(?:da\s+issue\s+|de\s+|do\s+)?([^\s]+)\s+para\s+(.+)$", limpa, flags=re.IGNORECASE)
    if m_mover:
        issue_ref = m_mover.group(1).strip(" ?.")
        coluna_alvo = m_mover.group(2).strip(" ?.")
        _registra(frase, "github_propor_mover")
        return {"intencao": "github_propor_mover", "resposta": _fazer_github_propor_mover(issue_ref, coluna_alvo)}

    # Skill Painel de Tarefas e Pendencias (Issue #13)
    if "confirma conclusao" in base or "confirmar conclusao" in base or "confirme a conclusao" in base or (base in ("confirma", "confirmar") and _tem_conclusao_pendente()):
        _registra(frase, "pendencias_confirmar_conclusao")
        return {"intencao": "pendencias_confirmar_conclusao", "resposta": _fazer_confirmar_conclusao_tarefa()}

    if "cancela conclusao" in base or "cancelar conclusao" in base:
        _registra(frase, "pendencias_cancelar_conclusao")
        return {"intencao": "pendencias_cancelar_conclusao", "resposta": _fazer_cancelar_conclusao_tarefa()}

    m_concluir = re.search(r"(?:marca|marcar|conclui|concluir)\s+(?:a\s+)?tarefa\s+(.+?)(?:\s+como\s+(?:feita|feito|concluida|concluido))?$", limpa, flags=re.IGNORECASE)
    if m_concluir:
        alvo_tarefa = m_concluir.group(1).strip(" ?.")
        _registra(frase, "pendencias_concluir")
        return {"intencao": "pendencias_concluir", "resposta": _fazer_concluir_tarefa(alvo_tarefa)}

    if any(k in base for k in ("minhas pendencias", "quais sao minhas pendencias", "listar pendencias", "ver pendencias")):
        _registra(frase, "pendencias")
        return {"intencao": "pendencias", "resposta": _fazer_pendencias(apenas_hoje=False)}

    if any(k in base for k in ("para fazer hoje", "pra fazer hoje", "que fazer hoje", "tarefas de hoje", "o que fazer hoje", "minhas tarefas hoje")):
        _registra(frase, "pendencias_hoje")
        return {"intencao": "pendencias_hoje", "resposta": _fazer_pendencias(apenas_hoje=True)}

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


def _fazer_estudos_resumo(disciplina: str, alvo: str = "", gerar_cards: bool = True) -> str:
    try:
        from . import resumos
        res = resumos.resumir_estudos(disciplina_nome=disciplina, alvo=alvo, gerar_cards=gerar_cards)
        return res.get("aviso") or res.get("erro", "Nao consegui gerar o resumo agora.")
    except Exception:
        return "Nao consegui gerar o resumo dos estudos agora."


def _tem_acao_pendente_github() -> bool:
    try:
        from . import github_integration
        return github_integration.obter_acao_pendente() is not None
    except Exception:
        return False


def _fazer_github_kanban() -> str:
    try:
        from . import github_integration
        return github_integration.resumo_kanban_por_voz()
    except Exception as e:
        return f"Nao consegui acessar o kanban: {e}"


def _fazer_github_issues() -> str:
    try:
        from . import github_integration
        return github_integration.resumo_issues_por_voz()
    except Exception as e:
        return f"Nao consegui acessar as issues: {e}"


def _fazer_github_propor_issue(repo: str, titulo: str) -> str:
    try:
        from . import github_integration
        res = github_integration.propor_criacao_issue(repo=repo, titulo=titulo)
        return res.get("mensagem") or res.get("erro", "Erro ao propor criacao de issue.")
    except Exception as e:
        return f"Nao consegui preparar a criacao da issue: {e}"


def _fazer_github_propor_mover(issue_ref: str, coluna: str) -> str:
    try:
        from . import github_integration
        res = github_integration.propor_movimentacao_cartao(issue_ref=issue_ref, coluna=coluna)
        return res.get("mensagem") or res.get("erro", "Erro ao propor movimentacao de cartao.")
    except Exception as e:
        return f"Nao consegui preparar a movimentacao do cartao: {e}"


def _fazer_github_confirmar() -> str:
    try:
        from . import github_integration
        res = github_integration.confirmar_acao_pendente()
        return res.get("mensagem") or res.get("erro", "Nenhuma acao pendente para confirmar.")
    except Exception as e:
        return f"Nao consegui confirmar a acao no GitHub: {e}"


def _fazer_github_cancelar() -> str:
    try:
        from . import github_integration
        res = github_integration.cancelar_acao_pendente()
        return res.get("mensagem") or "Acao cancelada com sucesso."
    except Exception as e:
        return f"Nao consegui cancelar a acao: {e}"


def _fazer_estudos_quiz_do_dia() -> str:
    try:
        from . import quiz
        res = quiz.quiz_do_dia()
        return res.get("aviso") or res.get("erro", "Nao consegui iniciar o quiz do dia agora.")
    except Exception:
        return "Nao consegui preparar o quiz do dia agora."


def _fazer_estudos_iniciar_quiz(disciplina: str) -> str:
    try:
        from . import quiz
        return quiz.iniciar_quiz_por_voz(disciplina)
    except Exception:
        return f"Nao consegui iniciar o quiz de {disciplina} agora."


def _tem_conclusao_pendente() -> bool:
    try:
        from . import pendencias
        return pendencias.obter_conclusao_pendente() is not None
    except Exception:
        return False


def _fazer_pendencias(apenas_hoje: bool = False) -> str:
    try:
        from . import pendencias, dispositivos
        lista = pendencias.coletar_todas_pendencias()
        if apenas_hoje:
            lista = [p for p in lista if p.get("para_hoje") or p.get("atrasada")]
        fala = pendencias.gerar_resumo_falado(lista, apenas_hoje=apenas_hoje)

        disp_ativo = dispositivos.dispositivo_ativo()
        if disp_ativo and disp_ativo.get("id"):
            linhas = [f"- {p['titulo']} ({p['fonte']})" for p in lista[:10]]
            detalhe_tela = f"{fala}\n\nTarefas:\n" + "\n".join(linhas)
            dispositivos.enviar_resposta_dispositivo(
                disp_ativo["id"],
                texto=detalhe_tela,
                titulo="Painel de Tarefas",
                intencao="pendencias",
            )
        return fala
    except Exception as e:
        return f"Nao consegui listar as pendencias agora: {e}"


def _fazer_concluir_tarefa(alvo: str) -> str:
    try:
        from . import pendencias
        return pendencias.concluir_tarefa_por_voz(alvo)
    except Exception as e:
        return f"Nao consegui concluir a tarefa: {e}"


def _fazer_confirmar_conclusao_tarefa() -> str:
    try:
        from . import pendencias
        return pendencias.confirmar_conclusao_pendente()
    except Exception as e:
        return f"Nao consegui confirmar a conclusao da tarefa: {e}"


def _fazer_cancelar_conclusao_tarefa() -> str:
    try:
        from . import pendencias
        return pendencias.cancelar_conclusao_pendente()
    except Exception as e:
        return f"Nao consegui cancelar a conclusao: {e}"


def _fazer_estudos_perguntar(pergunta_ou_topico: str, disciplina: str = "") -> str:
    try:
        from . import qa_estudos
        res = qa_estudos.responder_com_material(pergunta=pergunta_ou_topico, disciplina_nome=disciplina)
        return res.get("resposta_fala") or res.get("resposta_detalhada") or "Nao consegui responder com base no seu material agora."
    except Exception:
        return "Nao consegui consultar o seu material agora."


def _fazer_estudos_buscar_artigos(termo: str, disciplina: str = "") -> str:
    try:
        from . import artigos_cientificos
        artigos = artigos_cientificos.buscar_artigos(termo, limite=3)
        return artigos_cientificos.resumo_artigos_falado(artigos, termo)
    except Exception:
        return f"Nao consegui buscar artigos sobre {termo} agora."


def _fazer_estudos_salvar_artigo(artigo_id_ou_termo: str, disciplina: str) -> str:
    try:
        from . import artigos_cientificos
        artigos = artigos_cientificos.buscar_artigos(artigo_id_ou_termo, limite=1)
        if not artigos:
            return f"Nao encontrei o artigo '{artigo_id_ou_termo}' para salvar."
        res = artigos_cientificos.salvar_artigo_na_disciplina(artigos[0], disciplina_nome=disciplina)
        return res.get("aviso") or f"Artigo salvo em {disciplina}."
    except Exception:
        return f"Nao consegui salvar o artigo em {disciplina} agora."


if __name__ == "__main__":
    import sys
    r = rotear(" ".join(sys.argv[1:]) or "ei Nextor, o que tenho amanha?")
    print(f"[{r['intencao']}] {r['resposta']}")
