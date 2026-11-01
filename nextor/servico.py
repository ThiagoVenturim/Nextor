"""Servico HTTP local do Nextor: recebe comandos pela rede de casa e responde em voz."""
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
              "conversa_endpoint", "identidade_endpoint")
WEB = Path(__file__).resolve().parent / "web"


def autorizado() -> bool:
    enviado = request.args.get("token") or request.headers.get("X-Nextor-Token")
    return enviado == config.TOKEN


def pega_texto() -> str:
    if request.is_json:
        return ((request.get_json(silent=True) or {}).get("texto") or "").strip()
    return (request.form.get("texto") or request.args.get("texto") or "").strip()


@app.before_request
def checa_token():
    if request.endpoint in PROTEGIDOS and not autorizado():
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
    r = rotear(texto)
    falar(r["resposta"])
    return jsonify(ok=True, intencao=r["intencao"], resposta=r["resposta"])


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
    """Fala no Nest mostrando a boca mexendo; se o Nest nao responder, devolve o aviso."""
    from .companheiro import companheiro
    companheiro.atualizar(atividade="falando")
    try:
        falar(texto)
        return None
    except Exception as e:
        return f"Nao consegui falar no Nest ({e.__class__.__name__})."
    finally:
        companheiro.atualizar(atividade="ocioso")


def main():
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
