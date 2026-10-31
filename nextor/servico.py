"""Servico HTTP local do Nextor: recebe comandos pela rede de casa e responde em voz."""
from datetime import datetime

from flask import Flask, request, jsonify

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
              "agenda", "noticias", "comando")


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


def main():
    print(f"Nextor ouvindo na porta {config.PORTA}. Persona: {config.PERSONA}.")
    print(f"Notas em: {config.ANOTACOES}")
    app.run(host="0.0.0.0", port=config.PORTA)


if __name__ == "__main__":
    main()
