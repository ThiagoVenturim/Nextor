"""
Nextor - servico local no notebook.

Recebe notas, pedidos de fala e conversas pela rede de casa (ex.: atalho do iPhone)
e responde falando no Nest Mini. As notas ficam guardadas em anotacoes.md.

Rodar:
    .venv/Scripts/python.exe nextor_service.py

Endpoints (POST), todos exigem o token em ?token=... ou no cabecalho X-Nextor-Token:
    /anotar     campo "texto": salva a nota e o Nextor confirma em voz
    /falar      campo "texto": o Nextor fala o texto
    /conversar  campo "texto": o Nextor pensa (IA local) e responde em voz
    /notas      (GET) devolve as ultimas notas em texto

Seguranca: so responde na rede local e exige um token simples. Nao abrir porta no
roteador. Para usar fora de casa, usar uma VPN privada (ex.: Tailscale) no futuro.
"""
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify

from nextor import falar  # voz: gera fala + envia ao Nest

try:
    from nextor_brain import conversar  # cerebro local (Ollama)
except Exception:
    conversar = None

try:
    from nextor_agenda import eventos_hoje, eventos_proximos, resumo_falado
except Exception:
    eventos_hoje = eventos_proximos = resumo_falado = None

try:
    from nextor_noticias import resumir as resumir_noticias
except Exception:
    resumir_noticias = None

try:
    from nextor_router import rotear
except Exception:
    rotear = None

try:
    from settings import TOKEN, PORTA
except ImportError:
    TOKEN, PORTA = "troque-este-token", 5005

PASTA = Path(__file__).resolve().parent
ARQUIVO_NOTAS = PASTA / "anotacoes.md"

app = Flask(__name__)


def autorizado() -> bool:
    enviado = request.args.get("token") or request.headers.get("X-Nextor-Token")
    return enviado == TOKEN


def pega_texto() -> str:
    if request.is_json:
        dados = request.get_json(silent=True) or {}
        return (dados.get("texto") or "").strip()
    return (request.form.get("texto") or request.args.get("texto") or "").strip()


@app.before_request
def checa_token():
    protegidos = ("anotar", "falar", "conversar_endpoint", "notas", "agenda", "noticias", "comando")
    if request.endpoint in protegidos and not autorizado():
        return jsonify(erro="token invalido"), 401


@app.post("/anotar")
def anotar():
    texto = pega_texto()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    carimbo = datetime.now().strftime("%Y-%m-%d %H:%M")
    with ARQUIVO_NOTAS.open("a", encoding="utf-8") as f:
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
        return jsonify(erro="cerebro indisponivel (Ollama/modelo)"), 503
    texto = pega_texto()
    if not texto:
        return jsonify(erro="texto vazio"), 400
    resposta = conversar(texto)
    falar(resposta)
    return jsonify(ok=True, pergunta=texto, resposta=resposta)


@app.route("/agenda", methods=["GET", "POST"])
def agenda():
    if eventos_hoje is None:
        return jsonify(erro="agenda indisponivel (libs)"), 503
    quando = (request.values.get("quando") or "hoje").lower()
    if quando.startswith("prox") or quando == "semana":
        eventos = eventos_proximos(7)
        frase = resumo_falado(eventos, prefixo_dia=True)
    else:
        eventos = eventos_hoje()
        frase = "Hoje: " + resumo_falado(eventos)
    falar(frase)
    return jsonify(ok=True, quando=quando, quantidade=len(eventos), frase=frase)


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


@app.route("/noticias", methods=["GET", "POST"])
def noticias():
    if resumir_noticias is None:
        return jsonify(erro="noticias indisponivel (libs)"), 503
    assunto = request.values.get("assunto", "")
    frase = resumir_noticias(assunto)
    falar(frase)
    return jsonify(ok=True, assunto=assunto or "padrao", frase=frase)


@app.get("/notas")
def notas():
    if not ARQUIVO_NOTAS.exists():
        return "Nenhuma nota ainda.", 200, {"Content-Type": "text/plain; charset=utf-8"}
    return ARQUIVO_NOTAS.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    print(f"Nextor ouvindo na porta {PORTA}.")
    print(f"Notas em: {ARQUIVO_NOTAS}")
    app.run(host="0.0.0.0", port=PORTA)
