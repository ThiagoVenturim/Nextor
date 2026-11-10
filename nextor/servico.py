"""Servico HTTP local do Nextor: recebe comandos pela rede de casa e responde em voz."""
import hmac
import json
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, request, jsonify, send_from_directory

from . import config
from .voz import falar

try:
    from .cerebro import conversar
except Exception:
    conversar = None
try:
    from .agenda import eventos_hoje, eventos_proximos, resumo_falado
except Exception:
    eventos_hoje = eventos_proximos = resumo_falado = None
try:
    from .noticias import resumir as resumir_noticias
except Exception:
    resumir_noticias = None
try:
    from .roteador import rotear
except Exception:
    rotear = None

app = Flask(__name__)
PROTEGIDOS = ("anotar", "falar_endpoint", "conversar_endpoint", "notas",
              "agenda", "noticias", "comando", "automacoes_endpoint", "texto_endpoint",
              "nest_endpoint", "estado_endpoint", "modo_endpoint", "eventos_endpoint",
              "conversa_endpoint", "identidade_endpoint", "voz_endpoint", "fala_endpoint",
              "estudos_disciplinas_endpoint", "estudos_materiais_endpoint", "estudos_buscar_endpoint",
              "estudos_aulas_gravar_endpoint", "estudos_aulas_parar_endpoint", "estudos_aulas_status_endpoint",
              "estudos_resumo_endpoint", "estudos_flashcards_exportar_endpoint",
              "estudos_quiz_gerar_endpoint", "estudos_quiz_responder_endpoint", "estudos_quiz_historico_endpoint",
              "estudos_perguntar_endpoint",
              "estudos_artigos_buscar_endpoint", "estudos_artigos_salvar_endpoint",
              "organizador_previa_endpoint", "organizador_executar_endpoint",
              "organizador_desfazer_endpoint", "organizador_historico_endpoint",
              "github_kanban_endpoint", "github_issues_endpoint", "github_issues_criar_endpoint",
              "github_mover_endpoint", "github_confirmar_endpoint", "github_cancelar_endpoint",
              "pendencias_endpoint", "pendencias_concluir_endpoint",
              "reuniao_iniciar_endpoint", "reuniao_parar_endpoint",
              "tela_iniciar_endpoint", "tela_marcar_endpoint", "tela_parar_endpoint",
              "canvas_cursos_endpoint", "canvas_tarefas_endpoint", "canvas_avisos_endpoint",
              "classroom_cursos_endpoint", "classroom_atividades_endpoint", "classroom_avisos_endpoint")
WEB = Path(__file__).resolve().parent / "web"


TOKEN_PADRAO_INVALIDO = "troque-este-token"
TAMANHO_MINIMO_TOKEN = 24


def validar_token_mestre(token: str | None = None) -> bool:
    tk = (token if token is not None else config.TOKEN) or ""
    if tk == TOKEN_PADRAO_INVALIDO or len(tk) < TAMANHO_MINIMO_TOKEN:
        return False
    return True


def exigir_token_mestre_valido() -> None:
    if not validar_token_mestre():
        msg = (
            f"Erro de seguranca: NEXTOR_TOKEN invalido ou inseguro (deve ter no minimo {TAMANHO_MINIMO_TOKEN} "
            f"caracteres e nao pode ser '{TOKEN_PADRAO_INVALIDO}').\n"
            f"Gere um token seguro executando no terminal:\n"
            f"  python -c \"import secrets; print(secrets.token_urlsafe(24))\"\n"
            f"e configure-o no seu arquivo .env (campo NEXTOR_TOKEN)."
        )
        raise SystemExit(msg)


def _obter_token() -> str:
    enviado = request.args.get("token") or request.headers.get("X-Nextor-Token")
    if not enviado:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            enviado = auth[7:].strip()
    return enviado or ""


def autorizado() -> bool:
    enviado = _obter_token()
    mestre = config.TOKEN or ""
    if not enviado or not mestre:
        return False
    return hmac.compare_digest(enviado, mestre)


def pega_texto() -> str:
    if request.is_json:
        dados = request.get_json(silent=True) or {}
        return (dados.get("texto") or dados.get("pergunta") or dados.get("comando") or "").strip()
    return (request.form.get("texto") or request.args.get("texto") or
            request.form.get("pergunta") or request.args.get("pergunta") or
            request.form.get("comando") or request.args.get("comando") or "").strip()


@app.before_request
def checa_token():
    if request.endpoint in PROTEGIDOS:
        if autorizado():
            return
        if request.endpoint == "comando":
            from . import dispositivos
            disp = dispositivos.buscar_por_token(_obter_token())
            if disp and disp.get("ativo", True):
                return
        return jsonify(erro="token invalido"), 401


@app.post("/comando")
def comando():
    if rotear is None:
        return jsonify(erro="roteador indisponivel"), 503
    texto = pega_texto()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    from .chamado import entender
    if entender(texto)["chamado"]:
        from .janela import abrir_rosto
        abrir_rosto()
    from . import dispositivos
    token_atual = _obter_token()
    disp_atual = dispositivos.buscar_por_token(token_atual) if token_atual else None
    if disp_atual:
        id_disp = disp_atual["id"]
    else:
        id_disp = (request.is_json and (request.get_json(silent=True) or {}).get("dispositivo")) or request.values.get("dispositivo")
    r = rotear(texto, id_dispositivo=id_disp)
    from .companheiro import companheiro
    companheiro.atualizar(ultima_mensagem=texto, ultima_resposta=r["resposta"])
    aviso = _falar_sem_quebrar(r["resposta"])
    return jsonify(ok=True, intencao=r["intencao"], resposta=r["resposta"], aviso=aviso)


@app.post("/anotar")
def anotar():
    texto = pega_texto()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    carimbo = datetime.now().strftime("%Y-%m-%d %H:%M")
    with config.ANOTACOES.open("a", encoding="utf-8") as f:
        f.write(f"- [{carimbo}] {texto}\n")
    falar(f"Anotei: {texto}")
    return jsonify(ok=True, nota=texto, quando=carimbo)


@app.post("/falar")
def falar_endpoint():
    texto = pega_texto()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    falar(texto)
    return jsonify(ok=True, falado=texto)


@app.post("/conversar")
def conversar_endpoint():
    if conversar is None:
        return jsonify(erro="cerebro indisponivel"), 503
    texto = pega_texto()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    resposta = conversar(texto)
    falar(resposta)
    return jsonify(ok=True, pergunta=texto, resposta=resposta)


@app.route("/agenda", methods=["GET", "POST"])
def agenda():
    if eventos_hoje is None:
        return jsonify(erro="agenda indisponivel"), 503
    quando = (request.values.get("quando") or "hoje").lower()
    if quando.startswith("prox") or quando == "semana":
        evs = eventos_proximos(7)
        frase = resumo_falado(evs, prefixo_dia=True)
    else:
        evs = eventos_hoje()
        frase = "Hoje: " + resumo_falado(evs)
    falar(frase)
    return jsonify(ok=True, quando=quando, quantidade=len(evs), frase=frase)


@app.post("/texto")
def texto_endpoint():
    from . import texto as tx
    acao = request.values.get("acao", "escrever")
    conteudo = pega_texto() or request.values.get("conteudo", "")
    if not conteudo:
        return jsonify(erro="texto vazio"), 400
    if acao == "traduzir":
        res = tx.traduzir(conteudo, request.values.get("idioma", "ingles"))
    elif acao == "resumir":
        res = tx.resumir_texto(conteudo)
    else:
        res = tx.escrever(conteudo)
    falar(res["aviso"])
    return jsonify(ok=True, acao=acao, arquivo=res["arquivo"], texto=res["texto"])


@app.route("/noticias", methods=["GET", "POST"])
def noticias():
    if resumir_noticias is None:
        return jsonify(erro="noticias indisponivel"), 503
    assunto = request.values.get("assunto", "")
    frase = resumir_noticias(assunto)
    falar(frase)
    return jsonify(ok=True, assunto=assunto or "padrao", frase=frase)


@app.get("/notas")
def notas():
    if not config.ANOTACOES.exists():
        return "Nenhuma nota ainda.", 200, {"Content-Type": "text/plain; charset=utf-8"}
    return config.ANOTACOES.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/automacoes", methods=["GET", "POST", "DELETE"])
def automacoes_endpoint():
    from . import automacoes as au
    if request.method == "POST":
        hora = request.values.get("hora", "")
        acao = request.values.get("acao", "falar")
        texto = request.values.get("texto", "")
        return jsonify(ok=True, automacao=au.adicionar(hora, acao, texto))
    if request.method == "DELETE":
        return jsonify(ok=au.remover(request.values.get("id", "")))
    return jsonify(automacoes=au.listar())


PAINEL_HTML = (WEB / "painel.html").read_text(encoding="utf-8") if (WEB / "painel.html").is_file() else ""


@app.get("/")
@app.get("/painel")
def painel():
    if (WEB / "painel.html").is_file():
        return send_from_directory(WEB, "painel.html")
    return PAINEL_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/manifest.webmanifest")
def pwa_manifest_universal():
    return send_from_directory(WEB, "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/sw.js")
def pwa_sw_universal():
    resp = send_from_directory(WEB, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/icone-192.png")
def pwa_icone_192():
    return send_from_directory(WEB, "icone-192.png", mimetype="image/png")


@app.get("/icone-512.png")
def pwa_icone_512():
    return send_from_directory(WEB, "icone-512.png", mimetype="image/png")


@app.get("/download")
@app.get("/instalar")
def download_pagina():
    return send_from_directory(WEB, "download.html")


@app.get("/v1/plataformas")
def plataformas_endpoint():
    from . import multiplataforma
    ua = request.headers.get("User-Agent", "")
    detectada = multiplataforma.detectar_plataforma(ua)
    return jsonify(
        ok=True,
        plataforma_detectada=detectada,
        plataformas=multiplataforma.listar_plataformas(),
        pwa=multiplataforma.verificar_requisitos_pwa(),
    )


@app.route("/nest", methods=["GET", "POST"])
def nest_endpoint():
    from . import nest as n
    acao = request.values.get("acao", "status")
    try:
        if acao == "volume":
            return jsonify(ok=True, resultado=n.volume(int(request.values.get("nivel", "50"))))
        if acao == "parar":
            return jsonify(ok=True, resultado=n.parar())
        return jsonify(ok=True, status=n.status())
    except Exception as e:
        return jsonify(erro=str(e)), 503


# --- Rosto do Nextor (bichinho), modos e conversa pela tela ---------------------

@app.get("/rosto")
def rosto():
    return send_from_directory(WEB, "rosto.html")


@app.get("/web/<path:nome>")
def web_arquivo(nome):
    return send_from_directory(WEB, nome)


@app.get("/estado")
def estado_endpoint():
    from .companheiro import companheiro
    return jsonify(companheiro.ver())


@app.post("/modo")
def modo_endpoint():
    from .companheiro import MODOS, companheiro
    dados = request.get_json(silent=True) or request.values
    modo = (dados.get("modo") or "").strip().lower()
    if modo not in MODOS:
        return jsonify(erro=f"modo invalido; use {', '.join(MODOS)}"), 400
    r = companheiro.definir_modo(modo)
    if str(dados.get("falar", "")).lower() in ("1", "true", "sim"):
        _falar_sem_quebrar(r["frase"])
    return jsonify(ok=True, modo=modo, frase=r["frase"], avisos=r["avisos"], estado=r["estado"])


@app.post("/identidade")
def identidade_endpoint():
    from .companheiro import IDENTIDADES, companheiro
    dados = request.get_json(silent=True) or request.values
    nome = (dados.get("identidade") or "").strip().lower()
    if nome not in IDENTIDADES:
        return jsonify(erro=f"identidade invalida; use {', '.join(IDENTIDADES)}"), 400
    r = companheiro.definir_identidade(nome)
    return jsonify(ok=True, identidade=nome, frase=r["frase"], estado=r["estado"])


@app.get("/eventos")
def eventos_endpoint():
    from .companheiro import companheiro
    fila = companheiro.assinar()

    def fluxo():
        try:
            yield f"data: {json.dumps(companheiro.ver())}\n\n"
            while True:
                try:
                    estado = fila.get(timeout=15)
                    yield f"data: {json.dumps(estado)}\n\n"
                except Exception:
                    yield ": ping\n\n"
        finally:
            companheiro.cancelar(fila)

    return Response(fluxo(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/conversa")
def conversa_endpoint():
    """Conversa pela tela (rosto, NexDeck). So fala no Nest se pedirem."""
    from .companheiro import conversar_com_humor
    if conversar is None:
        return jsonify(erro="cerebro indisponivel"), 503
    dados = request.get_json(silent=True) or request.values
    texto = (dados.get("texto") or "").strip()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    if len(texto) > 2000:
        return jsonify(erro="texto longo demais"), 400
    r = conversar_com_humor(texto, conversar)
    aviso = None
    if str(dados.get("falar", "")).lower() in ("1", "true", "sim"):
        aviso = _falar_sem_quebrar(r["resposta"])
    return jsonify(ok=True, resposta=r["resposta"], emocao=r["emocao"], estado=r["estado"], aviso=aviso)


def _falar_sem_quebrar(texto: str) -> str | None:
    """Da voz ao Nextor conforme NEXTOR_VOZ_SAIDA: "pc" (padrao), "nest" ou "ambos".

    No PC, se alguma tela do rosto estiver aberta ela toca o audio e mexe a boca; senao o som sai
    direto pelas caixas do computador. Falhas viram aviso, nunca erro.
    """
    import os
    import threading
    from . import fala
    from .companheiro import companheiro
    saida = os.getenv("NEXTOR_VOZ_SAIDA", "pc").strip().lower()
    avisos = []
    if saida in ("pc", "tela", "ambos"):
        try:
            dados, mime, _motor = fala.sintetizar(texto, companheiro.ver().get("idioma", "pt-BR"))
            dur = fala.duracao(dados, mime, texto)
            if companheiro.ouvintes() > 0:
                fala_id = fala.guardar(dados, mime)
                companheiro.atualizar(atividade="falando", fala={"id": fala_id, "duracao": dur})
                threading.Timer(dur + 0.3, lambda: companheiro.atualizar(atividade="ocioso")).start()
            else:
                companheiro.atualizar(atividade="falando")

                def tocar():
                    try:
                        fala.tocar_no_pc(dados, mime)
                    except Exception as e:
                        print(f"[fala] nao tocou no PC: {e}")
                    finally:
                        companheiro.atualizar(atividade="ocioso")
                threading.Thread(target=tocar, daemon=True).start()
        except Exception as e:
            avisos.append(f"Sem voz no PC ({e.__class__.__name__}).")
    if saida in ("nest", "ambos"):
        try:
            falar(texto)
        except Exception as e:
            avisos.append(f"Nao consegui falar no Nest ({e.__class__.__name__}).")
    return " ".join(avisos) or None


@app.route("/voz", methods=["GET", "POST"])
def voz_endpoint():
    from . import fala
    from .companheiro import companheiro
    if request.method == "POST":
        dados = request.get_json(silent=True) or request.values
        idioma = (dados.get("idioma") or "").strip()
        if idioma not in fala.IDIOMAS:
            return jsonify(erro=f"idioma invalido; use {', '.join(fala.IDIOMAS)}"), 400
        companheiro.definir_idioma(idioma)
    disponiveis = {i: (fala.pasta_piper() / f"{fala.voz_piper(i)}.onnx").is_file() for i in fala.IDIOMAS}
    return jsonify(idioma=companheiro.ver()["idioma"],
                   idiomas={i: v["nome"] for i, v in fala.IDIOMAS.items()},
                   voz_natural=disponiveis)


@app.get("/fala/<fala_id>")
def fala_endpoint(fala_id):
    from . import fala
    audio = fala.pegar(fala_id)
    if audio is None:
        return jsonify(erro="audio expirou"), 404
    return Response(audio[0], mimetype=audio[1], headers={"Cache-Control": "no-store"})
@app.route("/estudos/disciplinas", methods=["GET", "POST"])
def estudos_disciplinas_endpoint():
    from . import estudos
    if request.method == "POST":
        dados = request.get_json(silent=True) or request.form
        nome = (dados.get("nome") or "").strip()
        if not nome:
            return jsonify(erro="nome da disciplina obrigatorio"), 400
        res = estudos.criar_disciplina(nome)
        return jsonify(res), 200 if res.get("ok") else 400
    return jsonify(ok=True, disciplinas=estudos.listar_disciplinas())


@app.route("/estudos/disciplinas/<nome_disciplina>/materiais", methods=["GET", "POST"])
def estudos_materiais_endpoint(nome_disciplina):
    from . import estudos
    if request.method == "POST":
        if "arquivo" in request.files:
            arq = request.files["arquivo"]
            if not arq.filename:
                return jsonify(erro="arquivo sem nome"), 400
            nome_seguro = Path(arq.filename).name
            pasta_disc = estudos.obter_pasta_disciplina(nome_disciplina)
            destino = pasta_disc / nome_seguro
            arq.save(str(destino))
            res = estudos.importar_material(
                nome_disciplina,
                destino,
                titulo=request.form.get("titulo", ""),
                pastas_autorizadas=[pasta_disc],
                canal="local",
            )
            return jsonify(res), 200 if res.get("ok") else 400

        dados = request.get_json(silent=True) or request.form
        origem = (dados.get("origem") or "").strip()
        if not origem:
            return jsonify(erro="origem do material (arquivo ou url) obrigatoria"), 400
        res = estudos.importar_material(
            nome_disciplina,
            origem,
            titulo=(dados.get("titulo") or "").strip(),
            tipo=(dados.get("tipo") or "").strip(),
            canal="local",
        )
        return jsonify(res), 200 if res.get("ok") else 400

    return jsonify(ok=True, materiais=estudos.listar_materiais(nome_disciplina))


@app.get("/estudos/buscar")
def estudos_buscar_endpoint():
    from . import estudos
    termo = (request.args.get("q") or "").strip()
    disciplina = (request.args.get("disciplina") or "").strip()
    if not termo:
        return jsonify(erro="parametro q obrigatorio"), 400
    limite = int(request.args.get("limite") or 10)
    resultados = estudos.buscar_materiais(termo, disciplina_nome=disciplina, limite=limite)
    return jsonify(ok=True, termo=termo, disciplina=disciplina, resultados=resultados)


@app.post("/estudos/aulas/gravar")
def estudos_aulas_gravar_endpoint():
    from . import aulas
    dados = request.get_json(silent=True) or request.form
    disciplina = (dados.get("disciplina") or "").strip()
    if not disciplina:
        return jsonify(erro="disciplina obrigatoria"), 400
    res = aulas.iniciar_gravacao(disciplina)
    return jsonify(res), 200 if res.get("ok") else 400


@app.post("/estudos/aulas/parar")
def estudos_aulas_parar_endpoint():
    from . import aulas
    res = aulas.parar_gravacao()
    return jsonify(res), 200 if res.get("ok") else 400


@app.get("/estudos/aulas/status")
def estudos_aulas_status_endpoint():
    from . import aulas
    return jsonify(ok=True, **aulas.status_gravacao())


@app.post("/estudos/resumo")
def estudos_resumo_endpoint():
    dados = request.get_json(silent=True) or request.values
    disc = (dados.get("disciplina") or "").strip()
    alvo = (dados.get("alvo") or dados.get("termo") or "").strip()
    gerar_cards = str(dados.get("gerar_flashcards", "true")).lower() in ("1", "true", "sim")
    formato = (dados.get("formato") or "csv").strip()

    if not disc:
        return jsonify(ok=False, erro="Nome da disciplina e obrigatorio."), 400

    from . import resumos
    res = resumos.resumir_estudos(
        disciplina_nome=disc,
        alvo=alvo,
        gerar_cards=gerar_cards,
        formato_exportacao=formato,
    )
    if not res.get("ok"):
        return jsonify(ok=False, erro=res.get("erro", "Erro ao gerar resumo.")), 404

    return jsonify(res)


@app.route("/estudos/flashcards/exportar", methods=["GET", "POST"])
def estudos_flashcards_exportar_endpoint():
    disc = (request.args.get("disciplina") or (request.is_json and request.get_json(silent=True) or {}).get("disciplina") or request.values.get("disciplina") or "").strip()
    alvo = (request.args.get("alvo") or (request.is_json and request.get_json(silent=True) or {}).get("alvo") or request.values.get("alvo") or "").strip()
    formato = (request.args.get("formato") or (request.is_json and request.get_json(silent=True) or {}).get("formato") or request.values.get("formato") or "csv").lower().strip()

    if not disc:
        return jsonify(ok=False, erro="Nome da disciplina e obrigatorio."), 400

    from . import resumos
    res = resumos.resumir_estudos(
        disciplina_nome=disc,
        alvo=alvo,
        gerar_cards=True,
        formato_exportacao=formato,
    )
    if not res.get("ok"):
        return jsonify(ok=False, erro=res.get("erro", "Nenhum material encontrado para exportar flashcards.")), 404

    flashcards = res.get("flashcards", [])
    if not flashcards:
        return jsonify(ok=False, erro="Nenhum flashcard disponivel para exportar."), 404

    conteudo_export = resumos.exportar_flashcards_anki(flashcards, formato=formato)
    mime = "text/tab-separated-values; charset=utf-8" if formato == "tsv" else "text/csv; charset=utf-8"
    ext = "tsv" if formato == "tsv" else "csv"
    slug_disc = resumos.normalizar_slug(disc)
    headers = {
        "Content-Type": mime,
        "Content-Disposition": f'attachment; filename="flashcards_{slug_disc}.{ext}"',
    }
    return conteudo_export, 200, headers


@app.post("/estudos/quiz/gerar")
def estudos_quiz_gerar_endpoint():
    dados = request.get_json(silent=True) or request.values
    disc = (dados.get("disciplina") or "").strip()
    try:
        qtd = int(dados.get("quantidade", 3))
    except (ValueError, TypeError):
        qtd = 3

    if not disc:
        return jsonify(ok=False, erro="Nome da disciplina e obrigatorio."), 400

    from . import quiz
    res = quiz.obter_ou_gerar_questoes_quiz(disciplina_nome=disc, quantidade=qtd)
    if not res.get("ok"):
        return jsonify(ok=False, erro=res.get("erro", "Erro ao obter questoes.")), 404

    return jsonify(res)


@app.post("/estudos/quiz/responder")
def estudos_quiz_responder_endpoint():
    dados = request.get_json(silent=True) or request.values
    questao_id = dados.get("questao_id")
    resposta = (dados.get("resposta") or "").strip()

    if not questao_id or not resposta:
        return jsonify(ok=False, erro="questao_id e resposta sao obrigatorios."), 400

    try:
        q_id = int(questao_id)
    except (ValueError, TypeError):
        return jsonify(ok=False, erro="questao_id invalido."), 400

    from . import quiz
    res = quiz.registrar_tentativa(questao_id=q_id, resposta_usuario=resposta)
    if not res.get("ok"):
        return jsonify(ok=False, erro=res.get("erro", "Erro ao processar resposta.")), 404

    return jsonify(res)


@app.get("/estudos/quiz/historico")
def estudos_quiz_historico_endpoint():
    disc = (request.args.get("disciplina") or request.values.get("disciplina") or "").strip()
    from . import quiz
    res = quiz.obter_historico_quiz(disciplina_nome=disc)
    return jsonify(res)


@app.post("/estudos/perguntar")
def estudos_perguntar_endpoint():
    dados = request.get_json(silent=True) or request.values
    pergunta = (dados.get("pergunta") or dados.get("texto") or "").strip()
    disc = (dados.get("disciplina") or "").strip()

    if not pergunta:
        return jsonify(ok=False, erro="Campo 'pergunta' e obrigatorio."), 400

    from . import qa_estudos
    res = qa_estudos.responder_com_material(pergunta=pergunta, disciplina_nome=disc)
    return jsonify(res)


@app.route("/estudos/artigos/buscar", methods=["GET", "POST"])
def estudos_artigos_buscar_endpoint():
    dados = request.get_json(silent=True) or request.values
    termo = (dados.get("termo") or request.args.get("termo") or "").strip()
    fonte = (dados.get("fonte") or request.args.get("fonte") or "todos").strip()
    try:
        limite = int(dados.get("limite") or request.args.get("limite") or 5)
    except (ValueError, TypeError):
        limite = 5

    if not termo:
        return jsonify(ok=False, erro="Campo 'termo' e obrigatorio."), 400

    from . import artigos_cientificos
    resultados = artigos_cientificos.buscar_artigos(termo, fonte=fonte, limite=limite)
    return jsonify(ok=True, termo=termo, total=len(resultados), artigos=resultados)


@app.post("/estudos/artigos/salvar")
def estudos_artigos_salvar_endpoint():
    dados = request.get_json(silent=True) or request.values
    disc = (dados.get("disciplina") or "").strip()
    artigo = dados.get("artigo")

    if not disc:
        return jsonify(ok=False, erro="Campo 'disciplina' e obrigatorio."), 400

    if not artigo or not isinstance(artigo, dict):
        autores_raw = dados.get("autores", [])
        if isinstance(autores_raw, str):
            autores = [a.strip() for a in autores_raw.split(",") if a.strip()]
        else:
            autores = list(autores_raw)

        artigo = {
            "titulo": dados.get("titulo") or "Artigo Cientifico",
            "autores": autores,
            "ano": dados.get("ano") or datetime.now().year,
            "resumo": dados.get("resumo") or "",
            "referencia_abnt": dados.get("referencia_abnt") or "",
            "url": dados.get("url") or "",
            "pdf_url": dados.get("pdf_url") or "",
            "veiculo": dados.get("veiculo") or "Repositorio",
        }

    from . import artigos_cientificos
    res = artigos_cientificos.salvar_artigo_na_disciplina(artigo, disciplina_nome=disc)
    return jsonify(res), 200 if res.get("ok") else 400

# --- Assistentes externos (Siri, Alexa, Telegram, etc) -------------------------

@app.post("/v1/assistente")
def assistente_endpoint():
    """Ponto de entrada unico para assistentes externos.

    Texto entra, texto sai, sem efeito colateral de tocar voz no Nest ou PC.
    Requer token valido por adaptador (Bearer, X-Nextor-Token ou ?token=).
    Aplica rate limiting e registra cada requisicao em log.
    """
    from . import adaptadores

    token = request.args.get("token") or request.headers.get("X-Nextor-Token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    adaptador = adaptadores.buscar_por_token(token) if token else None
    if not adaptador:
        return jsonify(ok=False, erro="token de adaptador invalido"), 401
    if not adaptador.get("ativo", True):
        return jsonify(ok=False, erro="adaptador revogado"), 403

    permitido, restantes, reset_em = adaptadores.verificar_limite(
        adaptador["id"], adaptador.get("limite_por_minuto", 60)
    )
    if not permitido:
        adaptadores.registrar_log(adaptador["id"], "", intencao="", status_http=429, detalhe="limite excedido")
        resp = jsonify(ok=False, erro="limite de requisicoes excedido", reset_em_segundos=reset_em)
        resp.status_code = 429
        resp.headers["Retry-After"] = str(int(reset_em) + 1)
        return resp

    if rotear is None:
        adaptadores.registrar_log(adaptador["id"], "", intencao="", status_http=503, detalhe="roteador indisponivel")
        return jsonify(ok=False, erro="roteador indisponivel"), 503

    texto = pega_texto()
    if not texto:
        adaptadores.registrar_log(adaptador["id"], "", intencao="", status_http=400, detalhe="texto vazio")
        return jsonify(ok=False, erro="texto vazio"), 400

    from . import dispositivos
    token_atual = _obter_token()
    disp_atual = dispositivos.buscar_por_token(token_atual) if token_atual else None
    if disp_atual:
        id_disp = disp_atual["id"]
    else:
        id_disp = (request.is_json and (request.get_json(silent=True) or {}).get("dispositivo")) or request.values.get("dispositivo")
    r = rotear(texto, canal="remoto", id_dispositivo=id_disp)
    from .companheiro import companheiro
    companheiro.atualizar(ultima_mensagem=texto, ultima_resposta=r.get("resposta", ""))

    adaptadores.registrar_uso(adaptador["id"])
    adaptadores.registrar_log(adaptador["id"], texto, intencao=r.get("intencao", ""), status_http=200)

    return jsonify(
        ok=True,
        resposta=r.get("resposta", ""),
        intencao=r.get("intencao", ""),
        adaptador=adaptador["id"],
    )


@app.route("/v1/assistente/adaptadores", methods=["GET", "POST"])
def assistente_adaptadores_endpoint():
    if not autorizado():
        return jsonify(ok=False, erro="token mestre invalido"), 401
    from . import adaptadores
    if request.method == "POST":
        dados = request.get_json(silent=True) or request.values
        id_adaptador = (dados.get("id") or "").strip()
        nome = (dados.get("nome") or "").strip()
        token = (dados.get("token") or "").strip() or None
        limite = int(dados.get("limite_por_minuto", 60))
        try:
            item = adaptadores.cadastrar(id_adaptador, nome, token=token, limite_por_minuto=limite)
            return jsonify(ok=True, adaptador=item), 201
        except ValueError as e:
            return jsonify(ok=False, erro=str(e)), 400
    revelar = str(request.args.get("revelar", "")).lower() in ("1", "true", "sim")
    return jsonify(ok=True, adaptadores=adaptadores.listar(mascarar=not revelar))


@app.post("/v1/assistente/adaptadores/<id_adaptador>/revogar")
def assistente_revogar_endpoint(id_adaptador):
    if not autorizado():
        return jsonify(ok=False, erro="token mestre invalido"), 401
    from . import adaptadores
    ok = adaptadores.revogar(id_adaptador)
    if not ok:
        return jsonify(ok=False, erro="adaptador nao encontrado"), 404
    return jsonify(ok=True, id=id_adaptador, revogado=True)


@app.post("/v1/assistente/adaptadores/<id_adaptador>/ativar")
def assistente_ativar_endpoint(id_adaptador):
    if not autorizado():
        return jsonify(ok=False, erro="token mestre invalido"), 401
    from . import adaptadores
    ok = adaptadores.ativar(id_adaptador)
    if not ok:
        return jsonify(ok=False, erro="adaptador nao encontrado"), 404
    return jsonify(ok=True, id=id_adaptador, ativo=True)


@app.get("/v1/assistente/logs")
def assistente_logs_endpoint():
    if not autorizado():
        return jsonify(ok=False, erro="token mestre invalido"), 401
    from . import adaptadores
    limite = int(request.args.get("limite", 50))
    return jsonify(ok=True, logs=adaptadores.ler_logs(limite=limite))


# --- Adaptador Telegram -------------------------------------------------------

@app.post("/v1/telegram/webhook")
def telegram_webhook_endpoint():
    """Webhook para integracao de mensagens do Telegram."""
    from . import telegram_bot
    dados = request.get_json(silent=True)
    if not dados:
        return jsonify(ok=False, erro="payload_invalido"), 400
    resultado = telegram_bot.processar_update(dados, enviar_resposta=False)
    status_code = 200 if resultado.get("ok") else (403 if not resultado.get("autorizado", True) else 400)
    return jsonify(resultado), status_code


# --- Adaptador Alexa ----------------------------------------------------------

@app.post("/v1/alexa")
def alexa_endpoint():
    """Endpoint compativel com custom skill da Amazon Alexa."""
    from . import alexa_skill
    raw_body = request.get_data()
    dados = request.get_json(silent=True)
    if dados is None:
        return jsonify(ok=False, erro="payload_invalido"), 400

    headers_dict = dict(request.headers)
    token_query = request.args.get("token")
    if token_query and "x-nextor-token" not in {k.lower(): v for k, v in headers_dict.items()}:
        headers_dict["x-nextor-token"] = token_query

    resp_json, status_code = alexa_skill.processar_requisicao_alexa(
        dados=dados,
        raw_body=raw_body,
        headers=headers_dict,
    )
    return jsonify(resp_json), status_code


# --- Organizador de Pastas (Issue #15) ----------------------------------------

@app.post("/v1/organizador/previa")
def organizador_previa_endpoint():
    """Gera previa da organizacao de uma pasta sem mover arquivos."""
    from . import organizador
    dados = request.get_json(silent=True) or request.values
    pasta = (dados.get("pasta") or "").strip()
    criterio = (dados.get("criterio") or "tipo").strip()
    if not pasta:
        return jsonify(ok=False, erro="pasta_obrigatoria"), 400

    try:
        previa = organizador.gerar_previa(pasta, criterio=criterio)
        return jsonify(previa), 200
    except organizador.PastaNaoPermitidaError as e:
        return jsonify(ok=False, erro="pasta_nao_permitida", mensagem=str(e)), 403
    except Exception as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.post("/v1/organizador/executar")
def organizador_executar_endpoint():
    """Executa as movimentacoes de uma previa pendente."""
    from . import organizador
    dados = request.get_json(silent=True) or request.values
    id_sessao = (dados.get("id_sessao") or "").strip() or None
    movs = dados.get("movimentacoes") if isinstance(dados.get("movimentacoes"), list) else None
    pasta = (dados.get("pasta") or "").strip() or None

    resultado = organizador.executar_organizacao(id_sessao=id_sessao, movimentacoes=movs, pasta=pasta)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/organizador/desfazer")
def organizador_desfazer_endpoint():
    """Desfaz a ultima operacao de organizacao ativa."""
    from . import organizador
    dados = request.get_json(silent=True) or request.values
    pasta = (dados.get("pasta") or "").strip() or None

    resultado = organizador.desfazer_ultima_organizacao(pasta=pasta)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.get("/v1/organizador/historico")
def organizador_historico_endpoint():
    """Retorna historico das operacoes de organizacao realizadas."""
    from . import organizador
    limite = int(request.args.get("limite", 10))
    historico = organizador.listar_historico(limite=limite)
    return jsonify(ok=True, historico=historico), 200


# --- Integracao GitHub (Issue #16) --------------------------------------------

@app.get("/v1/github/kanban")
def github_kanban_endpoint():
    """Retorna tarefas do kanban agrupadas por status."""
    from . import github_integration
    usuario = request.args.get("usuario")
    dados = github_integration.listar_itens_kanban(usuario=usuario)
    return jsonify(dados), 200


@app.get("/v1/github/issues")
def github_issues_endpoint():
    """Retorna lista de issues atribuidas ao usuario."""
    from . import github_integration
    usuario = request.args.get("usuario")
    estado = request.args.get("estado", "open")
    issues = github_integration.listar_issues_atribuidas(usuario=usuario, estado=estado)
    return jsonify(ok=True, total=len(issues), issues=issues), 200


@app.post("/v1/github/issues")
def github_issues_criar_endpoint():
    """Cria ou propoe criacao de issue no GitHub com confirmacao."""
    from . import github_integration
    dados = request.get_json(silent=True) or request.values
    repo = (dados.get("repo") or "").strip()
    titulo = (dados.get("titulo") or "").strip()
    corpo = (dados.get("corpo") or "").strip()
    confirmar = str(dados.get("confirmar", "")).lower() in ("1", "true", "sim")

    if not titulo:
        return jsonify(ok=False, erro="titulo_obrigatorio"), 400

    proposta = github_integration.propor_criacao_issue(repo=repo, titulo=titulo, corpo=corpo)
    if not confirmar:
        return jsonify(proposta), 200

    resultado = github_integration.confirmar_acao_pendente(id_acao=proposta.get("id_acao"))
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/github/kanban/mover")
def github_mover_endpoint():
    """Move ou propoe movimentacao de cartao no kanban com confirmacao."""
    from . import github_integration
    dados = request.get_json(silent=True) or request.values
    issue = (dados.get("issue") or dados.get("numero") or "").strip()
    coluna = (dados.get("coluna") or "").strip()
    repo = (dados.get("repo") or "").strip() or None
    confirmar = str(dados.get("confirmar", "")).lower() in ("1", "true", "sim")

    if not issue or not coluna:
        return jsonify(ok=False, erro="parametros_invalidos"), 400

    proposta = github_integration.propor_movimentacao_cartao(issue_ref=issue, coluna=coluna, repo=repo)
    if not confirmar:
        return jsonify(proposta), 200

    resultado = github_integration.confirmar_acao_pendente(id_acao=proposta.get("id_acao"))
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/github/confirmar")
def github_confirmar_endpoint():
    """Confirma e executa a acao pendente no GitHub."""
    from . import github_integration
    dados = request.get_json(silent=True) or request.values
    id_acao = (dados.get("id_acao") or "").strip() or None

    resultado = github_integration.confirmar_acao_pendente(id_acao=id_acao)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/github/cancelar")
def github_cancelar_endpoint():
    """Cancela a acao pendente no GitHub."""
    from . import github_integration
    resultado = github_integration.cancelar_acao_pendente()
    return jsonify(resultado), 200


# --- Integracao Canvas LMS (Issue #17) ----------------------------------------

@app.get("/v1/canvas/cursos")
def canvas_cursos_endpoint():
    """Lista os cursos ativos matriculados no Canvas LMS."""
    from . import canvas_lms
    if not canvas_lms.esta_configurado():
        return jsonify(ok=False, erro="Canvas LMS nao configurado. Configure CANVAS_BASE_URL e CANVAS_TOKEN."), 503

    cursos = canvas_lms.listar_cursos_ativos()
    return jsonify(ok=True, total=len(cursos), cursos=cursos), 200


@app.get("/v1/canvas/tarefas")
def canvas_tarefas_endpoint():
    """Lista tarefas e prazos no Canvas LMS."""
    from . import canvas_lms
    if not canvas_lms.esta_configurado():
        return jsonify(ok=False, erro="Canvas LMS nao configurado. Configure CANVAS_BASE_URL e CANVAS_TOKEN."), 503

    curso_id = request.args.get("curso_id")
    disciplina = request.args.get("disciplina") or ""
    apenas_pendentes = str(request.args.get("apenas_pendentes", "true")).lower() in ("1", "true", "sim")

    tarefas = canvas_lms.listar_tarefas(
        curso_id=curso_id,
        disciplina_nome=disciplina,
        apenas_pendentes=apenas_pendentes,
    )
    resumo = canvas_lms.resumo_tarefas_falado(tarefas, disciplina=disciplina)

    tarefas_json = []
    for t in tarefas:
        item = dict(t)
        item.pop("dt_prazo", None)
        tarefas_json.append(item)

    return jsonify(
        ok=True,
        total=len(tarefas_json),
        resumo_falado=resumo,
        tarefas=tarefas_json,
    ), 200


@app.get("/v1/canvas/avisos")
def canvas_avisos_endpoint():
    """Lista avisos e comunicados no Canvas LMS."""
    from . import canvas_lms
    if not canvas_lms.esta_configurado():
        return jsonify(ok=False, erro="Canvas LMS nao configurado. Configure CANVAS_BASE_URL e CANVAS_TOKEN."), 503

    curso_id = request.args.get("curso_id")
    disciplina = request.args.get("disciplina") or ""
    try:
        limite = int(request.args.get("limite", 5))
    except (ValueError, TypeError):
        limite = 5

    avisos = canvas_lms.listar_avisos(
        curso_id=curso_id,
        disciplina_nome=disciplina,
        limite=limite,
    )
    resumo = canvas_lms.resumo_avisos_falado(avisos, disciplina=disciplina)

    return jsonify(
        ok=True,
        total=len(avisos),
        resumo_falado=resumo,
        avisos=avisos,
    ), 200


# --- Integracao Google Sala de Aula / Classroom (Issue #18) -------------------

@app.get("/v1/classroom/cursos")
def classroom_cursos_endpoint():
    """Lista cursos ativos matriculados no Google Sala de Aula."""
    from . import google_classroom
    if not google_classroom.esta_configurado():
        return jsonify(ok=False, erro="Google Sala de Aula nao configurado. Configure GOOGLE_CLASSROOM_TOKEN."), 503

    cursos = google_classroom.listar_cursos_ativos()
    return jsonify(
        ok=True,
        total=len(cursos),
        cursos=cursos,
    ), 200


@app.get("/v1/classroom/atividades")
def classroom_atividades_endpoint():
    """Lista atividades e prazos no Google Sala de Aula."""
    from . import google_classroom
    if not google_classroom.esta_configurado():
        return jsonify(ok=False, erro="Google Sala de Aula nao configurado. Configure GOOGLE_CLASSROOM_TOKEN."), 503

    curso_id = request.args.get("curso_id")
    disciplina = request.args.get("disciplina") or ""
    apenas_pendentes = str(request.args.get("apenas_pendentes", "true")).lower() in ("1", "true", "sim")

    atividades = google_classroom.listar_atividades(
        curso_id=curso_id,
        disciplina_nome=disciplina,
        apenas_pendentes=apenas_pendentes,
    )
    resumo = google_classroom.resumo_atividades_falado(atividades, disciplina=disciplina)

    atividades_json = []
    for a in atividades:
        item = dict(a)
        item.pop("dt_prazo", None)
        atividades_json.append(item)

    return jsonify(
        ok=True,
        total=len(atividades_json),
        resumo_falado=resumo,
        atividades=atividades_json,
    ), 200


@app.get("/v1/classroom/avisos")
def classroom_avisos_endpoint():
    """Lista comunicados e avisos no Google Sala de Aula."""
    from . import google_classroom
    if not google_classroom.esta_configurado():
        return jsonify(ok=False, erro="Google Sala de Aula nao configurado. Configure GOOGLE_CLASSROOM_TOKEN."), 503

    curso_id = request.args.get("curso_id")
    disciplina = request.args.get("disciplina") or ""
    try:
        limite = int(request.args.get("limite", 5))
    except (ValueError, TypeError):
        limite = 5

    avisos = google_classroom.listar_avisos(
        curso_id=curso_id,
        disciplina_nome=disciplina,
        limite=limite,
    )
    resumo = google_classroom.resumo_avisos_falado(avisos, disciplina=disciplina)

    return jsonify(
        ok=True,
        total=len(avisos),
        resumo_falado=resumo,
        avisos=avisos,
    ), 200


# --- Painel de Tarefas e Pendencias (Issue #13) -------------------------------

@app.get("/v1/pendencias")
def pendencias_endpoint():
    """Retorna lista consolidada e ordenada de pendencias de multiplas fontes."""
    from . import pendencias
    apenas_hoje = str(request.args.get("apenas_hoje", "")).lower() in ("1", "true", "sim")
    fonte = request.args.get("fonte")

    incluir_anotacoes = fonte is None or fonte == "anotacoes"
    incluir_agenda = fonte is None or fonte == "agenda"
    incluir_github = fonte is None or fonte == "github"
    incluir_canvas = fonte is None or fonte == "canvas"
    incluir_classroom = fonte is None or fonte in ("classroom", "google_classroom")

    lista = pendencias.coletar_todas_pendencias(
        incluir_anotacoes=incluir_anotacoes,
        incluir_agenda=incluir_agenda,
        incluir_github=incluir_github,
        incluir_canvas=incluir_canvas,
        incluir_classroom=incluir_classroom,
    )
    if apenas_hoje:
        lista = [p for p in lista if p.get("para_hoje") or p.get("atrasada")]

    resumo = pendencias.gerar_resumo_falado(lista, apenas_hoje=apenas_hoje)
    total_hoje = sum(1 for p in lista if p.get("para_hoje"))
    total_atrasadas = sum(1 for p in lista if p.get("atrasada"))

    lista_json = []
    for p in lista:
        item = dict(p)
        item.pop("dt_prazo", None)
        item.pop("linha_original", None)
        lista_json.append(item)

    return jsonify(
        ok=True,
        total=len(lista_json),
        total_hoje=total_hoje,
        total_atrasadas=total_atrasadas,
        resumo_falado=resumo,
        pendencias=lista_json,
    ), 200


@app.post("/v1/pendencias/concluir")
def pendencias_concluir_endpoint():
    """Marca uma tarefa/pendencia como concluida."""
    from . import pendencias
    dados = request.get_json(silent=True) or request.values
    id_tarefa = (dados.get("id") or dados.get("id_tarefa") or "").strip()
    confirmar = str(dados.get("confirmar", "")).lower() in ("1", "true", "sim")

    if not id_tarefa:
        return jsonify(ok=False, erro="id_obrigatorio"), 400

    resultado = pendencias.concluir_tarefa(id_tarefa, confirmar=confirmar)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


# --- Gravacao de Reunioes e Tela (Issue #14) ----------------------------------

@app.post("/v1/reuniao/iniciar")
def reuniao_iniciar_endpoint():
    """Inicia gravacao de reuniao com consentimento informado."""
    from . import reuniao_tela
    dados = request.get_json(silent=True) or request.values
    tema = (dados.get("tema") or "Reuniao").strip()
    participantes = (dados.get("participantes") or "").strip() or None

    resultado = reuniao_tela.gravador_reuniao.iniciar(tema=tema, participantes=participantes)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/reuniao/parar")
def reuniao_parar_endpoint():
    """Encerra gravacao de reuniao, transcreve e estrutura resumo com decisoes e acoes."""
    from . import reuniao_tela
    dados = request.get_json(silent=True) or request.values
    salvar_anotacoes = str(dados.get("salvar_anotacoes", "true")).lower() in ("1", "true", "sim")

    resultado = reuniao_tela.gravador_reuniao.parar(salvar_anotacoes=salvar_anotacoes)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/tela/iniciar")
def tela_iniciar_endpoint():
    """Inicia gravacao de tela da tarefa com ffmpeg e consentimento."""
    from . import reuniao_tela
    dados = request.get_json(silent=True) or request.values
    tarefa = (dados.get("tarefa") or "Tarefa").strip()

    resultado = reuniao_tela.gravador_tela.iniciar(tarefa=tarefa)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/tela/marcar")
def tela_marcar_endpoint():
    """Insere marcador temporal por voz ou texto na gravacao de tela ativa."""
    from . import reuniao_tela
    dados = request.get_json(silent=True) or request.values
    nota = (dados.get("nota") or dados.get("marcador") or "").strip()

    if not nota:
        return jsonify(ok=False, erro="nota_obrigatoria"), 400

    resultado = reuniao_tela.gravador_tela.adicionar_marcador(nota=nota)
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


@app.post("/v1/tela/parar")
def tela_parar_endpoint():
    """Encerra gravacao de tela e salva marcadores."""
    from . import reuniao_tela
    resultado = reuniao_tela.gravador_tela.parar()
    status_code = 200 if resultado.get("ok") else 400
    return jsonify(resultado), status_code


# --- Dispositivos e telas (celular, tablet, notebook, PC, TV) ------------------

@app.route("/v1/dispositivos", methods=["GET", "POST"])
def dispositivos_endpoint():
    from . import dispositivos
    token = _obter_token()
    eh_mestre = autorizado()

    if request.method == "POST":
        if not eh_mestre:
            return jsonify(ok=False, erro="token mestre invalido"), 401
        dados = request.get_json(silent=True) or request.values
        id_disp = (dados.get("id") or "").strip()
        nome = (dados.get("nome") or "").strip()
        tipo = (dados.get("tipo") or "").strip()
        token_custom = (dados.get("token") or "").strip() or None
        perms = dados.get("permissoes")
        if isinstance(perms, str):
            perms = [p.strip() for p in perms.split(",") if p.strip()]
        try:
            item = dispositivos.cadastrar(id_disp, nome, tipo, permissoes=perms, token=token_custom)
            host = request.host.split(":")[0] if request.host else "localhost"
            token_puro = item.get("token", "")
            url_parear = dispositivos.gerar_url_pareamento(item["id"], token_puro=token_puro, host=host, porta=config.PORTA)
            return jsonify(ok=True, dispositivo=item, url_pareamento=url_parear), 201
        except ValueError as e:
            return jsonify(ok=False, erro=str(e)), 400

    disp_solicitante = dispositivos.buscar_por_token(token) if not eh_mestre else None
    if not eh_mestre and not disp_solicitante:
        return jsonify(ok=False, erro="nao autorizado"), 401

    revelar = eh_mestre and str(request.args.get("revelar", "")).lower() in ("1", "true", "sim")
    return jsonify(ok=True, dispositivos=dispositivos.listar(mascarar=not revelar))


@app.post("/v1/dispositivos/<id_dispositivo>/revogar")
def dispositivo_revogar_endpoint(id_dispositivo):
    if not autorizado():
        return jsonify(ok=False, erro="token mestre invalido"), 401
    from . import dispositivos
    ok = dispositivos.revogar(id_dispositivo)
    if not ok:
        return jsonify(ok=False, erro="dispositivo nao encontrado"), 404
    return jsonify(ok=True, id=id_dispositivo, revogado=True)


@app.post("/v1/dispositivos/<id_dispositivo>/ativar")
def dispositivo_ativar_endpoint(id_dispositivo):
    if not autorizado():
        return jsonify(ok=False, erro="token mestre invalido"), 401
    from . import dispositivos
    ok = dispositivos.ativar(id_dispositivo)
    if not ok:
        return jsonify(ok=False, erro="dispositivo nao encontrado"), 404
    return jsonify(ok=True, id=id_dispositivo, ativo=True)


@app.post("/v1/dispositivos/<id_dispositivo>/presenca")
def dispositivo_presenca_endpoint(id_dispositivo):
    from . import dispositivos
    token = _obter_token()
    disp = dispositivos.buscar_por_id(id_dispositivo)
    if not disp:
        return jsonify(ok=False, erro="dispositivo nao encontrado"), 404
    disp_autenticado = dispositivos.buscar_por_token(token)
    eh_proprio = (disp_autenticado and disp_autenticado.get("id") == disp["id"] and disp.get("ativo", True))
    if not (autorizado() or eh_proprio):
        return jsonify(ok=False, erro="nao autorizado"), 401

    ip = request.remote_addr
    ua = request.headers.get("User-Agent")
    atualizado = dispositivos.registrar_presenca(id_dispositivo, ip=ip, user_agent=ua)
    dispositivos.definir_ativo(id_dispositivo)
    return jsonify(ok=True, dispositivo=atualizado)


@app.get("/v1/dispositivos/ativo")
def dispositivo_ativo_endpoint():
    from . import dispositivos
    token = _obter_token()
    disp = dispositivos.buscar_por_token(token)
    if token != config.TOKEN and not disp:
        return jsonify(ok=False, erro="nao autorizado"), 401
    ativo = dispositivos.dispositivo_ativo()
    return jsonify(ok=True, ativo=ativo)


@app.post("/v1/dispositivos/hand-off")
def dispositivo_handoff_endpoint():
    """Encaminha uma resposta ou continuacao para outro aparelho ('mostra na TV', etc)."""
    from . import dispositivos
    token = _obter_token()
    disp_origem = dispositivos.buscar_por_token(token)
    if token != config.TOKEN and not disp_origem:
        return jsonify(ok=False, erro="nao autorizado"), 401

    dados = request.get_json(silent=True) or request.values
    alvo = (dados.get("alvo") or dados.get("dispositivo") or "").strip()
    texto = (dados.get("texto") or "").strip()
    titulo = (dados.get("titulo") or "Nextor").strip()

    if not alvo:
        return jsonify(ok=False, erro="alvo nao especificado"), 400
    if not texto:
        return jsonify(ok=False, erro="texto vazio"), 400

    disp_alvo = dispositivos.buscar_por_tipo_ou_nome(alvo)
    if not disp_alvo:
        return jsonify(ok=False, erro=f"dispositivo alvo '{alvo}' nao encontrado"), 404
    if not disp_alvo.get("ativo", True):
        return jsonify(ok=False, erro=f"dispositivo alvo '{disp_alvo['nome']}' esta desativado ou revogado"), 403

    msg = dispositivos.enviar_resposta_dispositivo(disp_alvo["id"], texto, titulo=titulo)
    return jsonify(ok=True, mensagem=msg, dispositivo_alvo=disp_alvo["id"])


@app.get("/v1/dispositivos/<id_dispositivo>/mensagens")
def dispositivo_mensagens_endpoint(id_dispositivo):
    from . import dispositivos
    token = _obter_token()
    disp = dispositivos.buscar_por_id(id_dispositivo)
    if not disp:
        return jsonify(ok=False, erro="dispositivo nao encontrado"), 404
    disp_autenticado = dispositivos.buscar_por_token(token)
    eh_proprio = (disp_autenticado and disp_autenticado.get("id") == disp["id"] and disp.get("ativo", True))
    if not (autorizado() or eh_proprio):
        return jsonify(ok=False, erro="nao autorizado"), 401

    limpar = str(request.args.get("limpar", "")).lower() in ("1", "true", "sim")
    mensagens = dispositivos.obter_mensagens_pendentes(id_dispositivo, limpar=limpar)
    return jsonify(ok=True, id=id_dispositivo, mensagens=mensagens)


@app.get("/dispositivo/conectar")
def dispositivo_conectar_pagina():
    """Tela simples para aparelhos pareados (TV, celular, tablet) exibirem respostas."""
    from . import dispositivos
    id_disp = request.args.get("id", "").strip()
    disp = dispositivos.buscar_por_id(id_disp)
    if not disp:
        return "Dispositivo nao encontrado.", 404, {"Content-Type": "text/plain; charset=utf-8"}
    if not disp.get("ativo", True):
        return "Dispositivo desativado ou revogado.", 403, {"Content-Type": "text/plain; charset=utf-8"}

    token = request.args.get("token", "").strip()
    if token:
        disp_token = dispositivos.buscar_por_token(token)
        if not disp_token or disp["id"] != disp_token["id"]:
            return "Token invalido.", 401, {"Content-Type": "text/plain; charset=utf-8"}
        dispositivos.registrar_presenca(id_disp, ip=request.remote_addr, user_agent=request.headers.get("User-Agent"))
        dispositivos.definir_ativo(id_disp)

    html = f"""<!doctype html><html lang=pt-BR><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Nextor - {disp['nome']}</title>
<style>
:root{{color-scheme:light dark;--a:#4f46e5}}
body{{font-family:system-ui,sans-serif;max-width:720px;margin:0 auto;padding:24px;background:Canvas;color:CanvasText;text-align:center}}
.card{{border:1px solid #8884;border-radius:16px;padding:24px;margin:20px 0;background:Canvas}}
h1{{margin:0 0 8px 0;font-size:1.8rem}}
.tipo{{opacity:.7;font-size:1rem;margin-bottom:16px}}
#resposta{{font-size:1.4rem;line-height:1.5;min-height:80px;white-space:pre-wrap;padding:16px}}
.status{{font-size:.85rem;opacity:.6}}
</style>
<div class=card>
  <h1>Nextor</h1>
  <div class=tipo>{disp['nome']} ({disp['tipo']})</div>
  <div id=resposta>Aparelho conectado e pronto.</div>
  <div class=status id=status>Conectando...</div>
</div>
<script>
const id = {json.dumps(disp['id'])};
const hashParams = new URLSearchParams(window.location.hash.slice(1));
let tk = hashParams.get('token') || new URLSearchParams(window.location.search).get('token') || '';
if (tk) {{
  try {{
    sessionStorage.setItem('nextor_disp_' + id, tk);
    if (window.location.hash) {{
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }}
  }} catch(e) {{}}
}} else {{
  try {{
    tk = sessionStorage.getItem('nextor_disp_' + id) || '';
  }} catch(e) {{}}
}}

async function checar(){{
  if (!tk) {{
    document.getElementById('status').textContent = 'Token nao informado';
    return;
  }}
  try{{
    const r = await fetch('/v1/dispositivos/' + encodeURIComponent(id) + '/mensagens?limpar=1&token=' + encodeURIComponent(tk));
    if (r.status === 401 || r.status === 403) {{
      document.getElementById('status').textContent = 'Token invalido ou revogado';
      return;
    }}
    const d = await r.json();
    if(d.ok && d.mensagens && d.mensagens.length > 0){{
      const ultima = d.mensagens[d.mensagens.length - 1];
      document.getElementById('resposta').textContent = ultima.texto;
      document.getElementById('status').textContent = 'Atualizado ' + ultima.quando;
    }} else {{
      document.getElementById('status').textContent = 'Online';
    }}
  }}catch(e){{}}
}}
setInterval(checar, 2500);
checar();
</script></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


# -------------------------------------------------------------
# Painel GTD e Produtividade Pessoal no Celular (Issues #42, #43, #44)
# -------------------------------------------------------------

def autorizado_gtd() -> bool:
    """Verifica autenticacao estrita para rotas GTD via header.

    Requisitos:
    - Token mestre deve ser valido (validar_token_mestre)
    - Token fornecido no header (X-Nextor-Token ou Authorization: Bearer)
    - Token na query string e explicitamente rejeitado
    - Comparacao usando hmac.compare_digest em tempo constante
    """
    if not validar_token_mestre():
        return False
    if request.args.get("token"):
        return False
    enviado = request.headers.get("X-Nextor-Token")
    if not enviado:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            enviado = auth[7:].strip()
    mestre = config.TOKEN or ""
    if not enviado or not mestre:
        return False
    return hmac.compare_digest(enviado, mestre)


@app.get("/gtd")
@app.get("/gtd/")
@app.get("/gtd/app")
def gtd_pwa_index():
    pasta_pwa = WEB / "gtd"
    return send_from_directory(pasta_pwa, "index.html")


@app.get("/gtd/<path:filename>")
def gtd_pwa_estaticos(filename):
    pasta_pwa = WEB / "gtd"
    arquivo = (pasta_pwa / filename).resolve()
    if not str(arquivo).startswith(str(pasta_pwa.resolve())):
        return jsonify(erro="acesso negado"), 403
    if arquivo.is_file():
        return send_from_directory(pasta_pwa, filename)
    return send_from_directory(pasta_pwa, "index.html")


@app.get("/gtd/itens")
def gtd_listar_itens_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd import ArmazenamentoGTD
    banco = ArmazenamentoGTD()
    estado = request.args.get("estado")
    contexto = request.args.get("contexto")
    projeto_id = request.args.get("projeto_id")
    itens = banco.listar_itens(estado=estado, contexto=contexto, projeto_id=projeto_id)
    return jsonify(ok=True, itens=[i.to_dict() for i in itens])


@app.post("/gtd/itens")
def gtd_criar_item_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    titulo = (dados.get("titulo") or "").strip()
    if not titulo:
        return jsonify(ok=False, erro="titulo obrigatorio"), 400

    from .gtd import ArmazenamentoGTD, Item
    import uuid
    banco = ArmazenamentoGTD()
    item = Item(
        id=str(uuid.uuid4()),
        titulo=titulo,
        nota=(dados.get("nota") or "").strip(),
        contexto=dados.get("contexto", "@qualquer"),
        estado=dados.get("estado", "inbox"),
        projeto_id=dados.get("projeto_id"),
        prazo=dados.get("prazo"),
        energia=dados.get("energia", "media"),
    )
    salvo = banco.salvar_item(item)
    return jsonify(ok=True, item=salvo.to_dict())


@app.post("/gtd/capturar")
def gtd_capturar_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    titulo = (dados.get("titulo") or "").strip()
    if not titulo:
        return jsonify(ok=False, erro="titulo obrigatorio"), 400

    from .gtd import capturar
    item = capturar(
        titulo=titulo,
        nota=(dados.get("nota") or "").strip(),
        contexto=dados.get("contexto", "@qualquer"),
        energia=dados.get("energia", "media"),
        prazo=dados.get("prazo"),
        projeto_id=dados.get("projeto_id"),
    )
    return jsonify(ok=True, item=item.to_dict())


@app.post("/gtd/processar")
def gtd_processar_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    item_id = (dados.get("item_id") or dados.get("id") or "").strip()
    novo_estado = (dados.get("novo_estado") or dados.get("estado") or "").strip()
    if not item_id or not novo_estado:
        return jsonify(ok=False, erro="item_id e novo_estado sao obrigatorios"), 400

    from .gtd import processar
    try:
        resultado = processar(
            item_id=item_id,
            novo_estado=novo_estado,
            novo_contexto=dados.get("novo_contexto") or dados.get("contexto"),
            projeto_id=dados.get("projeto_id"),
            prazo=dados.get("prazo"),
            energia=dados.get("energia"),
        )
        if resultado is None:
            return jsonify(ok=True, removido=True)
        return jsonify(ok=True, item=resultado.to_dict())
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.get("/gtd/hoje")
def gtd_hoje_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd import agenda_do_dia
    res = agenda_do_dia()
    return jsonify(ok=True, **res)


@app.get("/gtd/leituras")
def gtd_listar_leituras_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd import listar_leituras
    estado = request.args.get("estado")
    tipo = request.args.get("tipo")
    leituras = listar_leituras(estado=estado, tipo=tipo)
    return jsonify(ok=True, leituras=[l.to_dict() for l in leituras])


@app.post("/gtd/leituras")
def gtd_criar_leitura_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    titulo = (dados.get("titulo") or "").strip()
    if not titulo:
        return jsonify(ok=False, erro="titulo obrigatorio"), 400

    from .gtd import criar_leitura
    leitura = criar_leitura(
        titulo=titulo,
        autor=(dados.get("autor") or "").strip(),
        tipo=dados.get("tipo", "livro"),
        estado=dados.get("estado", "quero_ler"),
        paginas_total=int(dados.get("paginas_total") or 0),
        paginas_lidas=int(dados.get("paginas_lidas") or 0),
        fonte_url=(dados.get("fonte_url") or "").strip(),
    )
    return jsonify(ok=True, leitura=leitura.to_dict())


@app.post("/gtd/leituras/<id_leitura>/progresso")
def gtd_progresso_leitura_endpoint(id_leitura: str):
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    try:
        paginas = int(dados.get("paginas", 0))
    except (ValueError, TypeError):
        paginas = 0
    if paginas <= 0:
        return jsonify(ok=False, erro="paginas deve ser maior que zero"), 400

    from .gtd import atualizar_progresso
    try:
        res = atualizar_progresso(id_leitura, paginas)
        return jsonify(ok=True, progresso=res, **res)
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.post("/gtd/sincronizar")
def gtd_sincronizar_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd.integracoes import sincronizar_tudo
    res = sincronizar_tudo()
    return jsonify(ok=True, **res)


@app.get("/gtd/projetos")
def gtd_listar_projetos_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd import ArmazenamentoGTD
    banco = ArmazenamentoGTD()
    estado = request.args.get("estado")
    projetos = banco.listar_projetos(estado=estado)
    return jsonify(ok=True, projetos=[p.to_dict() for p in projetos])


@app.post("/gtd/projetos")
def gtd_criar_projeto_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or dados.get("titulo") or "").strip()
    if not nome:
        return jsonify(ok=False, erro="nome obrigatorio"), 400

    from .gtd import ArmazenamentoGTD, Projeto
    import uuid
    banco = ArmazenamentoGTD()
    projeto = Projeto(
        id=str(uuid.uuid4()),
        nome=nome,
        descricao=(dados.get("descricao") or "").strip(),
        estado=dados.get("estado", "ativo"),
    )
    salvo = banco.salvar_projeto(projeto)
    return jsonify(ok=True, projeto=salvo.to_dict())


@app.get("/gtd/revisao")
def gtd_revisao_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd import revisao_semanal
    res = revisao_semanal()
    return jsonify(ok=True, **res)


@app.get("/gtd/config")
def gtd_obter_config_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd.configuracao import obter_config_completa
    res = obter_config_completa()
    return jsonify(ok=True, **res)


@app.put("/gtd/config")
def gtd_salvar_config_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify(ok=False, erro="corpo da requisicao deve ser um objeto JSON"), 400
    if "metodo_ativo" in dados:
        from .gtd.metodos.registro import REGISTRO_METODOS
        m = str(dados["metodo_ativo"]).strip().lower()
        if m not in REGISTRO_METODOS:
            return jsonify(ok=False, erro=f"Metodo desconhecido: {m}"), 400
    from .gtd.configuracao import salvar_config
    salvo = salvar_config(dados)
    return jsonify(ok=True, config=salvo)


@app.get("/gtd/visao")
def gtd_visao_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd import ArmazenamentoGTD
    from .gtd.configuracao import carregar_config
    from .gtd.metodos import obter_metodo
    cfg = carregar_config()
    slug_metodo = request.args.get("metodo") or cfg.get("metodo_ativo", "gtd")
    metodo = obter_metodo(slug_metodo)

    banco = ArmazenamentoGTD()
    itens = banco.listar_itens()

    eventos = []
    try:
        from . import agenda
        if hasattr(agenda, "eventos_hoje"):
            evs = agenda.eventos_hoje() or []
            for e in evs:
                inicio = e.get("inicio")
                hora_str = inicio.strftime("%H:%M") if hasattr(inicio, "strftime") else "Dia todo"
                eventos.append({"titulo": e.get("titulo", ""), "horario": hora_str})
    except Exception:
        eventos = []

    res = metodo.visao_dia(itens, eventos)
    return jsonify(ok=True, **res)


@app.get("/gtd/pomodoro/estado")
def gtd_pomodoro_estado_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd.metodos import pomodoro
    return jsonify(ok=True, **pomodoro.obter_estado())


@app.post("/gtd/pomodoro/<acao>")
def gtd_pomodoro_acao_endpoint(acao: str):
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .gtd.metodos import pomodoro
    from .gtd import ArmazenamentoGTD

    dados = request.get_json(silent=True) or {}
    a = acao.strip().lower()

    if a == "iniciar":
        item_id = dados.get("item_id")
        try:
            duracao = int(dados.get("duracao_min", 25))
        except (ValueError, TypeError):
            duracao = 25
        modo = dados.get("modo", "foco")
        res = pomodoro.iniciar(item_id=item_id, duracao_min=duracao, modo=modo)
        return jsonify(ok=True, **res)

    if a == "pausar":
        res = pomodoro.pausar()
        return jsonify(ok=True, **res)

    if a == "parar":
        res = pomodoro.parar()
        return jsonify(ok=True, **res)

    if a == "concluir":
        banco = ArmazenamentoGTD()
        res = pomodoro.concluir(db=banco)
        try:
            from .notificacoes import notificar
            notificar(
                evento="pomodoro_fim",
                titulo="Pomodoro Concluido",
                corpo=f"Sessao finalizada com sucesso. {res.get('tarefa_associada', '')}".strip(),
            )
        except Exception:
            pass
        return jsonify(ok=True, **res)

    return jsonify(ok=False, erro="acao pomodoro desconhecida"), 400


@app.post("/gtd/notificacoes/teste")
def gtd_notificacao_teste_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    canal = dados.get("canal")
    canais_especificos = [canal] if canal else None
    titulo = dados.get("titulo") or "Teste de Notificacao"
    corpo = dados.get("corpo") or "Esta e uma notificacao de teste do Nextor GTD."

    from .notificacoes import notificar
    from .gtd.configuracao import carregar_config
    cfg = carregar_config()
    res = notificar(
        evento="lembrete",
        titulo=titulo,
        corpo=corpo,
        canais_especificos=canais_especificos,
        config_usuario=cfg,
    )
    return jsonify(ok=True, **res)


# -------------------------------------------------------------
# Coach de Estudos (Issue #57)
# -------------------------------------------------------------

def autorizado_coach() -> bool:
    """Verifica autenticacao estrita para rotas do Coach de Estudos via header em tempo constante."""
    return autorizado_gtd()


@app.get("/coach/trilhas")
def coach_listar_trilhas_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .coach import carregar_todas_trilhas
    trilhas = carregar_todas_trilhas()
    return jsonify(ok=True, trilhas=[t.to_dict() for t in trilhas])


@app.post("/coach/trilhas")
def coach_criar_trilha_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    titulo = (dados.get("titulo") or "").strip()
    habilidade = (dados.get("habilidade") or "").strip()
    if not titulo:
        return jsonify(ok=False, erro="titulo e obrigatorio"), 400
    from .coach import criar_trilha
    trilha = criar_trilha(
        id_trilha=dados.get("id", ""),
        titulo=titulo,
        habilidade=habilidade or "geral",
        nivel=dados.get("nivel", "iniciante"),
        descricao=dados.get("descricao", ""),
        recursos=dados.get("recursos", []),
    )
    return jsonify(ok=True, trilha=trilha.to_dict()), 201


@app.get("/coach/planos")
def coach_listar_planos_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .coach import ArmazenamentoCoach
    banco = ArmazenamentoCoach()
    planos = banco.listar_planos(ativo_apenas=False)
    return jsonify(ok=True, planos=[p.to_dict() for p in planos])


@app.post("/coach/planos")
def coach_criar_plano_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    trilha_id = (dados.get("trilha_id") or "ingles_iniciante").strip()
    dias_semana = int(dados.get("dias_semana", 5))
    minutos_dia = int(dados.get("minutos_dia", 30))
    data_inicio = dados.get("data_inicio")

    from .coach import criar_plano
    try:
        plano = criar_plano(
            trilha=trilha_id,
            ritmo={"dias_semana": dias_semana, "minutos_dia": minutos_dia},
            data_inicio=data_inicio,
        )
        return jsonify(ok=True, plano=plano.to_dict()), 201
    except Exception as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.get("/coach/acao-do-dia")
def coach_acao_do_dia_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    plano_id = request.args.get("plano_id", "").strip()
    data = request.args.get("data")
    from .coach import ArmazenamentoCoach, acao_do_dia, obter_ou_criar_plano_padrao
    banco = ArmazenamentoCoach()
    plano = banco.obter_plano(plano_id) if plano_id else obter_ou_criar_plano_padrao(banco)
    if not plano:
        return jsonify(ok=False, erro="nenhum plano encontrado"), 404

    acao = acao_do_dia(plano, data=data, db=banco)
    if not acao:
        return jsonify(ok=True, acao=None, motivo="dia cheio ou sem acoes pendentes")

    rec = banco.obter_recurso(acao.recurso_id)
    return jsonify(
        ok=True,
        acao=acao.to_dict(),
        recurso=rec.to_dict() if rec else None,
    )


@app.post("/coach/concluir")
def coach_concluir_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    plano_id = (dados.get("plano_id") or "").strip()
    recurso_id = (dados.get("recurso_id") or "").strip()
    data = dados.get("data")

    from .coach import ArmazenamentoCoach, acao_do_dia, concluir, obter_ou_criar_plano_padrao
    banco = ArmazenamentoCoach()
    plano = banco.obter_plano(plano_id) if plano_id else obter_ou_criar_plano_padrao(banco)
    if not plano:
        return jsonify(ok=False, erro="nenhum plano encontrado"), 404

    if not recurso_id:
        acao_pend = acao_do_dia(plano, data=data, db=banco, verificar_dia_saturado=False)
        if not acao_pend:
            return jsonify(ok=False, erro="nenhuma acao pendente encontrada"), 400
        recurso_id = acao_pend.recurso_id

    try:
        resultado = concluir(plano=plano.id, recurso=recurso_id, data=data, db=banco)
        return jsonify(**resultado)
    except Exception as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.get("/coach/resumo")
def coach_resumo_endpoint():
    if not autorizado_coach():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    plano_id = request.args.get("plano_id", "").strip()
    from .coach import ArmazenamentoCoach, obter_ou_criar_plano_padrao, resumo
    banco = ArmazenamentoCoach()
    plano = banco.obter_plano(plano_id) if plano_id else obter_ou_criar_plano_padrao(banco)
    if not plano:
        return jsonify(ok=False, erro="nenhum plano encontrado"), 404

    r = resumo(plano, db=banco)
    return jsonify(ok=True, **r)


# ============================================================================
# Endpoints do Calendario, Reunioes e Timeboxing (Issue #51)
# ============================================================================

@app.get("/gtd/agenda/dia")
def gtd_agenda_dia_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from . import agenda
    evs = agenda.eventos_dia()
    analise = agenda.analisar_dia(evs)
    # Serializa datetimes para string no retorno JSON
    evs_json = []
    for e in evs:
        item_e = dict(e)
        if hasattr(item_e.get("inicio"), "isoformat"):
            item_e["inicio"] = item_e["inicio"].isoformat()
        if hasattr(item_e.get("fim"), "isoformat"):
            item_e["fim"] = item_e["fim"].isoformat()
        evs_json.append(item_e)

    analise_json = dict(analise)
    analise_json["blocos_livres"] = [
        {
            **b,
            "inicio": b["inicio"].isoformat() if hasattr(b.get("inicio"), "isoformat") else str(b.get("inicio")),
            "fim": b["fim"].isoformat() if hasattr(b.get("fim"), "isoformat") else str(b.get("fim")),
        }
        for b in analise.get("blocos_livres", [])
    ]
    analise_json["conflitos"] = [
        {
            "evento1": c["evento1"],
            "evento2": c["evento2"],
            "duracao_minutos": c["duracao_minutos"],
            "inicio_conflito": c["inicio_conflito"].isoformat() if hasattr(c.get("inicio_conflito"), "isoformat") else str(c.get("inicio_conflito")),
            "fim_conflito": c["fim_conflito"].isoformat() if hasattr(c.get("fim_conflito"), "isoformat") else str(c.get("fim_conflito")),
        }
        for c in analise.get("conflitos", [])
    ]
    analise_json["sugestoes_timeboxing"] = [
        {
            **s,
            "inicio": s["inicio"].isoformat() if hasattr(s.get("inicio"), "isoformat") else str(s.get("inicio")),
            "fim": s["fim"].isoformat() if hasattr(s.get("fim"), "isoformat") else str(s.get("fim")),
        }
        for s in analise.get("sugestoes_timeboxing", [])
    ]

    return jsonify(ok=True, eventos=evs_json, analise=analise_json)


@app.get("/gtd/agenda/semana")
def gtd_agenda_semana_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from . import agenda
    evs = agenda.eventos_semana()
    evs_json = []
    for e in evs:
        item_e = dict(e)
        if hasattr(item_e.get("inicio"), "isoformat"):
            item_e["inicio"] = item_e["inicio"].isoformat()
        if hasattr(item_e.get("fim"), "isoformat"):
            item_e["fim"] = item_e["fim"].isoformat()
        evs_json.append(item_e)
    return jsonify(ok=True, eventos=evs_json, total=len(evs_json))


@app.get("/gtd/agenda/proxima-reuniao")
def gtd_proxima_reuniao_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from . import agenda
    prox = agenda.proxima_reuniao()
    if prox:
        prox_json = dict(prox)
        if hasattr(prox_json.get("inicio"), "isoformat"):
            prox_json["inicio"] = prox_json["inicio"].isoformat()
        if hasattr(prox_json.get("fim"), "isoformat"):
            prox_json["fim"] = prox_json["fim"].isoformat()
    else:
        prox_json = None
    return jsonify(ok=True, proxima_reuniao=prox_json)


@app.get("/gtd/agenda/blocos-livres")
def gtd_blocos_livres_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from . import agenda
    evs = agenda.eventos_dia()
    blocos = agenda.calcular_blocos_livres(evs)
    sugestoes = agenda.sugerir_timeboxing(blocos)
    blocos_json = [
        {
            **b,
            "inicio": b["inicio"].isoformat() if hasattr(b.get("inicio"), "isoformat") else str(b.get("inicio")),
            "fim": b["fim"].isoformat() if hasattr(b.get("fim"), "isoformat") else str(b.get("fim")),
        }
        for b in blocos
    ]
    sugestoes_json = [
        {
            **s,
            "inicio": s["inicio"].isoformat() if hasattr(s.get("inicio"), "isoformat") else str(s.get("inicio")),
            "fim": s["fim"].isoformat() if hasattr(s.get("fim"), "isoformat") else str(s.get("fim")),
        }
        for s in sugestoes
    ]
    return jsonify(ok=True, blocos_livres=blocos_json, sugestoes_timeboxing=sugestoes_json)


@app.post("/gtd/agenda/tarefa-de-evento")
def gtd_tarefa_de_evento_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    evento = dados.get("evento") or dados
    if not isinstance(evento, dict) or not (evento.get("titulo") or evento.get("summary")):
        return jsonify(ok=False, erro="evento_invalido"), 400
    contexto = dados.get("contexto", "@trabalho")

    from .gtd import criar_tarefa_de_evento
    item = criar_tarefa_de_evento(evento, contexto=contexto)
    return jsonify(ok=True, item=item.to_dict())


@app.post("/gtd/agenda/evento-de-tarefa")
def gtd_evento_de_tarefa_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    item_id = (dados.get("item_id") or dados.get("id") or "").strip()
    if not item_id:
        return jsonify(ok=False, erro="item_id_obrigatorio"), 400
    horario = str(dados.get("horario", "09:00")).strip()
    duracao = int(dados.get("duracao_minutos", 60))

    from .gtd import criar_evento_de_tarefa
    try:
        evento = criar_evento_de_tarefa(item_id, horario=horario, duracao_minutos=duracao)
        evento_json = dict(evento)
        if hasattr(evento_json.get("inicio"), "isoformat"):
            evento_json["inicio"] = evento_json["inicio"].isoformat()
        if hasattr(evento_json.get("fim"), "isoformat"):
            evento_json["fim"] = evento_json["fim"].isoformat()
        return jsonify(ok=True, evento=evento_json)
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 404


@app.post("/gtd/agenda/abrir-reuniao")
def gtd_abrir_reuniao_endpoint():
    if not autorizado_gtd():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    link = dados.get("link_video") or dados.get("link") or ""
    titulo = dados.get("titulo") or "Reuniao"

    from .notificacoes import notificar
    from .gtd.configuracao import carregar_config
    cfg = carregar_config()
    res = notificar(
        evento="lembrete",
        titulo="Acesso a Reuniao",
        corpo=f"Link de acesso para '{titulo}': {link}" if link else f"Reuniao '{titulo}' sem link informado.",
        config_usuario=cfg,
    )
    return jsonify(ok=True, despachado=res.get("sucesso", False), link=link)


# ============================================================================
# NexRead: Tradutor de Artigo/Pagina ao Vivo com Estudo (Issue #55)
# ============================================================================

def autorizado_nexread() -> bool:
    """Verifica autenticacao estrita para rotas da API do NexRead via header em tempo constante."""
    return autorizado_gtd()


@app.get("/nexread")
@app.get("/nexread/")
@app.get("/nexread/app")
def nexread_pwa_index():
    pasta_pwa = WEB / "nexread"
    return send_from_directory(pasta_pwa, "index.html")


@app.get("/nexread/<path:filename>")
def nexread_pwa_estaticos(filename: str):
    pasta_pwa = WEB / "nexread"
    arquivo = (pasta_pwa / filename).resolve()
    if not str(arquivo).startswith(str(pasta_pwa.resolve())):
        return jsonify(erro="acesso negado"), 403
    if arquivo.is_file():
        return send_from_directory(pasta_pwa, filename)
    return send_from_directory(pasta_pwa, "index.html")


@app.post("/nexread/traduzir")
def nexread_traduzir_endpoint():
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    aberta_pelo_usuario = dados.get("aberta_pelo_usuario", True)
    if isinstance(aberta_pelo_usuario, str):
        aberta_pelo_usuario = aberta_pelo_usuario.strip().lower() not in ("0", "false", "nao")

    from .nexread import traduzir_pagina_ao_vivo
    try:
        artigo = traduzir_pagina_ao_vivo(
            conteudo_html=dados.get("conteudo_html", ""),
            texto=dados.get("texto", ""),
            url=dados.get("url", ""),
            caminho_pdf=dados.get("caminho_pdf") or None,
            titulo=dados.get("titulo", ""),
            autor=dados.get("autor", ""),
            idioma_destino=dados.get("idioma_destino") or None,
            idioma_origem=dados.get("idioma_origem", "auto"),
            motor=dados.get("motor") or None,
            modo_layout=dados.get("modo_layout", "bilingue"),
            disciplina=dados.get("disciplina", ""),
            aberta_pelo_usuario=bool(aberta_pelo_usuario),
        )
        return jsonify(ok=True, artigo=artigo.to_dict(), html_traduzido=artigo.html_traduzido), 201
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.get("/nexread/artigos")
def nexread_listar_artigos_endpoint():
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .nexread import ArmazenamentoNexRead
    banco = ArmazenamentoNexRead()
    disc = request.args.get("disciplina")
    artigos = banco.listar_artigos(disciplina=disc)
    return jsonify(ok=True, artigos=[a.to_dict() for a in artigos])


@app.get("/nexread/artigos/<artigo_id>")
def nexread_obter_artigo_endpoint(artigo_id: str):
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .nexread import ArmazenamentoNexRead
    banco = ArmazenamentoNexRead()
    artigo = banco.obter_artigo(artigo_id)
    if not artigo:
        return jsonify(ok=False, erro="artigo nao encontrado"), 404
    marcacoes = banco.listar_marcacoes(artigo.id)
    gravacoes = banco.listar_gravacoes(artigo.id)
    conversas = banco.listar_mensagens_chat(artigo.id)
    return jsonify(
        ok=True,
        artigo=artigo.to_dict(),
        marcacoes=[m.to_dict() for m in marcacoes],
        gravacoes=[g.to_dict() for g in gravacoes],
        conversas=[c.to_dict() for c in conversas],
    )


@app.route("/nexread/marcacoes", methods=["GET", "POST"])
def nexread_marcacoes_endpoint():
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .nexread import ArmazenamentoNexRead, marcar_trecho
    banco = ArmazenamentoNexRead()
    if request.method == "GET":
        artigo_id = request.args.get("artigo_id")
        lista = banco.listar_marcacoes(artigo_id=artigo_id)
        return jsonify(ok=True, marcacoes=[m.to_dict() for m in lista])

    dados = request.get_json(silent=True) or {}
    artigo_id = (dados.get("artigo_id") or "").strip()
    trecho = (dados.get("trecho") or dados.get("trecho_original") or "").strip()
    if not artigo_id or not trecho:
        return jsonify(ok=False, erro="artigo_id e trecho sao obrigatorios"), 400

    try:
        marcacao = marcar_trecho(
            artigo_id=artigo_id,
            trecho=trecho,
            nota=dados.get("nota", ""),
            cor=dados.get("cor", "amarelo"),
            bloco_id=dados.get("bloco_id", ""),
            trecho_traduzido=dados.get("trecho_traduzido", ""),
            tags=dados.get("tags") or [],
            db=banco,
        )
        artigo = banco.obter_artigo(artigo_id)
        return jsonify(
            ok=True,
            marcacao=marcacao.to_dict(),
            html_traduzido=artigo.html_traduzido if artigo else "",
        ), 201
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.delete("/nexread/marcacoes/<marcacao_id>")
def nexread_remover_marcacao_endpoint(marcacao_id: str):
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    from .nexread import ArmazenamentoNexRead
    banco = ArmazenamentoNexRead()
    removido = banco.remover_marcacao(marcacao_id)
    if not removido:
        return jsonify(ok=False, erro="marcacao nao encontrada"), 404
    return jsonify(ok=True, removido=True)


@app.post("/nexread/gravacoes")
def nexread_gravacoes_endpoint():
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    artigo_id = (dados.get("artigo_id") or "").strip()
    transcricao = (dados.get("transcricao") or dados.get("texto") or "").strip()
    if not artigo_id or not transcricao:
        return jsonify(ok=False, erro="artigo_id e transcricao sao obrigatorios"), 400

    from .nexread import gravar_nota_leitura
    try:
        gravacao = gravar_nota_leitura(
            artigo_id=artigo_id,
            transcricao=transcricao,
            titulo=dados.get("titulo", "Nota de voz do estudo"),
            caminho_audio=dados.get("caminho_audio", ""),
            duracao_seg=int(dados.get("duracao_seg") or 0),
            bloco_id=dados.get("bloco_id", ""),
        )
        return jsonify(ok=True, gravacao=gravacao.to_dict()), 201
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.post("/nexread/salvar-estudos")
def nexread_salvar_estudos_endpoint():
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    artigo_id = (dados.get("artigo_id") or "").strip()
    disciplina = (dados.get("disciplina") or "").strip()
    if not artigo_id or not disciplina:
        return jsonify(ok=False, erro="artigo_id e disciplina sao obrigatorios"), 400

    from .nexread import salvar_na_biblioteca_estudos
    try:
        res = salvar_na_biblioteca_estudos(artigo_id=artigo_id, disciplina_nome=disciplina)
        return jsonify(**res), 200
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


@app.post("/nexread/conversar")
def nexread_conversar_endpoint():
    if not autorizado_nexread():
        return jsonify(ok=False, erro="token invalido ou ausente no header"), 401
    dados = request.get_json(silent=True) or {}
    artigo_id = (dados.get("artigo_id") or "").strip()
    if not artigo_id:
        return jsonify(ok=False, erro="artigo_id e obrigatorio"), 400

    from .nexread import conversar_sobre_artigo
    try:
        res = conversar_sobre_artigo(
            artigo_id=artigo_id,
            pergunta=dados.get("pergunta", ""),
            acao=dados.get("acao", "perguntar"),
            buscar_fontes_cientificas=bool(dados.get("buscar_fontes_cientificas", False)),
        )
        return jsonify(**res), 200
    except ValueError as e:
        return jsonify(ok=False, erro=str(e)), 400


def main():
    exigir_token_mestre_valido()
    from .automacoes import iniciar_agendador
    iniciar_agendador()
    try:
        from .nest import iniciar_vigia_se_configurado
        iniciar_vigia_se_configurado()
    except Exception as e:
        print(f"[nest] vigia nao iniciou: {e}")
    print(f"Nextor ouvindo na porta {config.PORTA}. Persona: {config.PERSONA}. Perfil: {config.PERFIL or 'padrao'}.")
    print(f"Painel: http://localhost:{config.PORTA}/painel?token=SEU_TOKEN")
    print(f"Rosto:  http://localhost:{config.PORTA}/rosto?token=SEU_TOKEN")
    app.run(host="0.0.0.0", port=config.PORTA)


if __name__ == "__main__":
    main()
