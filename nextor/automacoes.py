"""
Automacoes do Nextor: o nosso "Home Assistant", sem apps de terceiros.

Um agendador simples roda dentro do servico e dispara acoes em horarios definidos
(ex.: rotina da manha as 7h). As automacoes ficam em automacoes.json (fora do git).

Acoes: rotina (bom dia), agenda, noticias, falar (texto), comando (frase roteada).
"""
import json
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

ARQUIVO = config.RAIZ / "automacoes.json"
TZ = ZoneInfo(config.FUSO)


def _semente() -> list:
    return [{
        "id": "bom-dia",
        "hora": config.ROTINA_HORA,
        "acao": "rotina",
        "texto": "",
        "ativo": True,
        "ultima": "",
    }]


def carregar() -> list:
    if not ARQUIVO.exists():
        salvar(_semente())
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except Exception:
        return []


def salvar(lista: list) -> None:
    ARQUIVO.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")


def listar() -> list:
    return carregar()


def adicionar(hora: str, acao: str, texto: str = "") -> dict:
    lista = carregar()
    nova = {
        "id": f"{acao}-{int(time.time())}",
        "hora": hora.strip(),
        "acao": acao.strip(),
        "texto": texto.strip(),
        "ativo": True,
        "ultima": "",
    }
    lista.append(nova)
    salvar(lista)
    return nova


def remover(id_: str) -> bool:
    lista = carregar()
    nova = [a for a in lista if a.get("id") != id_]
    salvar(nova)
    return len(nova) != len(lista)


def executar(acao: str, texto: str = "") -> str:
    if acao == "rotina":
        from .rotina import bom_dia
        return bom_dia()
    if acao == "agenda":
        from .agenda import eventos_hoje, resumo_falado
        from .voz import falar
        frase = "Hoje: " + resumo_falado(eventos_hoje())
        falar(frase)
        return frase
    if acao == "noticias":
        from .noticias import resumir
        from .voz import falar
        frase = resumir(texto)
        falar(frase)
        return frase
    if acao == "comando":
        from .roteador import rotear
        from .voz import falar
        r = rotear(texto)
        falar(r["resposta"])
        return r["resposta"]
    # padrao: falar
    from .voz import falar
    falar(texto)
    return texto


def _loop():
    while True:
        try:
            agora = datetime.now(TZ)
            hhmm = agora.strftime("%H:%M")
            hoje = agora.strftime("%Y-%m-%d")
            lista = carregar()
            mudou = False
            for a in lista:
                if a.get("ativo") and a.get("hora") == hhmm and a.get("ultima") != hoje:
                    a["ultima"] = hoje
                    mudou = True
                    try:
                        print(f"[automacoes] disparando {a.get('id')} ({a.get('acao')})")
                        executar(a.get("acao", "falar"), a.get("texto", ""))
                    except Exception as e:
                        print(f"[automacoes] erro em {a.get('id')}: {e}")
            if mudou:
                salvar(lista)
        except Exception as e:
            print(f"[automacoes] loop: {e}")
        time.sleep(30)


def iniciar_agendador() -> None:
    carregar()  # garante a semente
    t = threading.Thread(target=_loop, name="nextor-automacoes", daemon=True)
    t.start()
    print("[automacoes] agendador ativo.")
