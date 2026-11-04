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
              "estudos_disciplinas_endpoint", "estudos_materiais_endpoint", "estudos_buscar_endpoint")
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


PAINEL_HTML = """<!doctype html><html lang=pt-BR><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Nextor</title>
<style>
:root{color-scheme:light dark;--a:#4f46e5}
body{font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:16px;background:Canvas;color:CanvasText}
h1{font-size:1.4rem}button{padding:10px 14px;margin:4px 0;border:0;border-radius:8px;background:var(--a);color:#fff;font-size:1rem}
input,select{padding:10px;margin:4px 0;width:100%;box-sizing:border-box;border:1px solid #8884;border-radius:8px;background:Canvas;color:CanvasText}
.row{display:flex;gap:8px}.row>*{flex:1}.card{border:1px solid #8884;border-radius:12px;padding:12px;margin:12px 0}
small{opacity:.7}#log{white-space:pre-wrap;font-size:.9rem;opacity:.85}
</style>
<h1>Nextor</h1><small>painel local</small>
<div class=card>
  <input id=texto placeholder="fale, pergunte ou anote...">
  <div class=row><button onclick="cmd('/comando')">Comando</button><button onclick="cmd('/anotar')">Anotar</button><button onclick="cmd('/falar')">Falar</button></div>
  <div class=row><button onclick="go('/agenda')">Agenda hoje</button><button onclick="go('/noticias')">Noticias</button></div>
</div>
<div class=card>
  <h3>Automacoes</h3>
  <div class=row><input id=hora placeholder="07:00" style=flex:0.5>
  <select id=acao><option value=rotina>bom dia</option><option value=agenda>agenda</option><option value=noticias>noticias</option><option value=falar>falar</option><option value=comando>comando</option></select></div>
  <input id=atexto placeholder="texto (para falar/comando)">
  <button onclick=addAuto()>Adicionar automacao</button>
  <div id=autos></div>
</div>
<div id=log></div>
<script>
const tk=new URLSearchParams(location.search).get('token')||'';
const log=m=>document.getElementById('log').textContent=(typeof m==='string'?m:JSON.stringify(m,null,2));
async function post(p,params){const b=new URLSearchParams(params);const r=await fetch(p+'?token='+encodeURIComponent(tk),{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b});return r.json()}
async function cmd(p){const t=document.getElementById('texto').value;log('...');log(await post(p,{texto:t}))}
async function go(p){log('...');log(await post(p,{}))}
async function addAuto(){await post('/automacoes',{hora:document.getElementById('hora').value,acao:document.getElementById('acao').value,texto:document.getElementById('atexto').value});carregar()}
async function del(id){await fetch('/automacoes?token='+encodeURIComponent(tk)+'&id='+encodeURIComponent(id),{method:'DELETE'});carregar()}
async function carregar(){const r=await fetch('/automacoes?token='+encodeURIComponent(tk));const d=await r.json();document.getElementById('autos').innerHTML=(d.automacoes||[]).map(a=>`<div class=row><span style=flex:3>${a.hora} - ${a.acao} ${a.texto||''}</span><button style=flex:0.5 onclick="del('${a.id}')">x</button></div>`).join('')}
carregar();
</script></html>"""


@app.get("/painel")
def painel():
    return PAINEL_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


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


# --- Dispositivos e telas (celular, tablet, notebook, PC, TV) ------------------

@app.route("/v1/dispositivos", methods=["GET", "POST"])
def dispositivos_endpoint():
    from . import dispositivos
    token = _obter_token()
    eh_mestre = (token == config.TOKEN)

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
    if not (token == config.TOKEN or eh_proprio):
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
    if not (token == config.TOKEN or eh_proprio):
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
