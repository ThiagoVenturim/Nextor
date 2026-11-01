"""Companheiro: o "bichinho" do Nextor. Guarda o modo, a expressao e o humor percebido.

Os rostos (pagina /rosto, NexDeck, TV) leem este estado por /estado e /eventos.
"""
import queue
import re
import threading
import time
import unicodedata


MODOS = {
    "normal": {"nome": "Normal", "acessorio": None, "frase": "Voltei ao normal."},
    "estudo": {"nome": "Estudo", "acessorio": "mochila", "frase": "Modo estudo. Peguei a mochila, bora aprender."},
    "trabalho": {"nome": "Trabalho", "acessorio": "gravata", "frase": "Modo trabalho. Gravata no lugar."},
    "tranquilidade": {"nome": "Tranquilidade", "acessorio": "relaxado", "frase": "Modo tranquilidade. Respira fundo."},
    "leitura": {"nome": "Leitura", "acessorio": "oculos", "frase": "Modo leitura. Oculos no rosto e luz mais baixa."},
}

APELIDOS_MODO = {
    "estudo": "estudo", "estudar": "estudo", "aula": "estudo",
    "trabalho": "trabalho", "trabalhar": "trabalho", "foco": "trabalho",
    "tranquilo": "tranquilidade", "tranquilidade": "tranquilidade", "relaxar": "tranquilidade",
    "relax": "tranquilidade", "descanso": "tranquilidade", "calmo": "tranquilidade",
    "leitura": "leitura", "ler": "leitura",
    "normal": "normal", "padrao": "normal",
}

# Palavras que indicam como a pessoa esta. Lista curta e explicavel de proposito:
# e um palpite pelo texto, nao um diagnostico.
SINAIS_EMOCAO = {
    "feliz": ("feliz", "alegre", "animado", "animada", "consegui", "passei", "otimo", "maravilha",
              "adorei", "amei", "que bom", "show", "obrigado", "obrigada", "uhul", "aprovado", "aprovada"),
    "triste": ("triste", "chateado", "chateada", "desanimado", "desanimada", "sozinho", "sozinha",
               "chorei", "chorando", "reprovei", "perdi", "saudade", "deprimido", "deprimida"),
    "ansioso": ("ansioso", "ansiosa", "nervoso", "nervosa", "preocupado", "preocupada", "medo",
                "prova amanha", "prazo", "atrasado", "atrasada", "nao vou dar conta"),
    "cansado": ("cansado", "cansada", "exausto", "exausta", "sono", "sonolento", "esgotado", "esgotada"),
    "irritado": ("irritado", "irritada", "raiva", "bravo", "brava", "odeio", "saco cheio", "estressado", "estressada"),
}
NEGACOES = ("nao", "nem", "nunca")

# Como o bichinho reage ao humor percebido.
REACAO = {
    "feliz": "feliz",
    "triste": "carinho",
    "ansioso": "calmo",
    "cansado": "sonolento",
    "irritado": "calmo",
    "neutro": "neutro",
}

DICA_PARA_O_CEREBRO = {
    "triste": "A pessoa parece triste. Responda com acolhimento e sem pressa.",
    "ansioso": "A pessoa parece ansiosa. Responda com calma e passos pequenos.",
    "cansado": "A pessoa parece cansada. Seja breve e sugira uma pausa se fizer sentido.",
    "irritado": "A pessoa parece irritada. Seja direto e paciente.",
    "feliz": "A pessoa parece feliz. Compartilhe a alegria.",
}


def _normaliza(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento.lower()))


def detectar_emocao(texto: str) -> str:
    """Palpite simples do humor pelo texto: feliz, triste, ansioso, cansado, irritado ou neutro."""
    base = f" {_normaliza(texto)} "
    pontos = {}
    for emocao, sinais in SINAIS_EMOCAO.items():
        for sinal in sinais:
            pos = base.find(f" {sinal} ")
            if pos < 0:
                continue
            antes = base[:pos].split()[-3:]
            negado = any(n in antes for n in NEGACOES)
            if negado and emocao == "feliz":
                pontos["triste"] = pontos.get("triste", 0) + 1
            elif not negado:
                pontos[emocao] = pontos.get(emocao, 0) + 1
    if not pontos:
        return "neutro"
    return max(pontos, key=pontos.get)


def modo_pedido(frase: str) -> str | None:
    """Reconhece "modo estudo", "ativa o modo leitura", "quero relaxar" etc."""
    base = _normaliza(frase)
    m = re.search(r"\bmodo (\w+)", base)
    if m and m.group(1) in APELIDOS_MODO:
        return APELIDOS_MODO[m.group(1)]
    if re.search(r"\b(quero|vou|hora de) (relaxar|descansar)\b", base):
        return "tranquilidade"
    return None


class Companheiro:
    def __init__(self):
        self._trava = threading.Lock()
        self._ouvintes: list[queue.Queue] = []
        self.estado = {
            "modo": "normal",
            "acessorio": None,
            "expressao": "neutro",
            "atividade": "ocioso",  # ocioso, ouvindo, pensando, falando, gravando
            "emocao_usuario": "neutro",
            "ultima_mensagem": "",
            "ultima_resposta": "",
            "atualizado_em": time.time(),
        }

    def ver(self) -> dict:
        with self._trava:
            return dict(self.estado)

    def atualizar(self, **campos) -> dict:
        with self._trava:
            self.estado.update(campos, atualizado_em=time.time())
            copia = dict(self.estado)
            ouvintes = list(self._ouvintes)
        for q in ouvintes:
            try:
                q.put_nowait(copia)
            except queue.Full:
                pass
        return copia

    def assinar(self) -> queue.Queue:
        q = queue.Queue(maxsize=20)
        with self._trava:
            self._ouvintes.append(q)
        return q

    def cancelar(self, q: queue.Queue) -> None:
        with self._trava:
            if q in self._ouvintes:
                self._ouvintes.remove(q)

    def definir_modo(self, modo: str, aplicar_ambiente: bool = True) -> dict:
        if modo not in MODOS:
            raise ValueError(f"Modo desconhecido: {modo}")
        info = MODOS[modo]
        avisos = []
        if aplicar_ambiente:
            from . import ambiente
            avisos = ambiente.aplicar(modo)
        estado = self.atualizar(modo=modo, acessorio=info["acessorio"],
                                expressao="feliz" if modo != "tranquilidade" else "calmo")
        return {"estado": estado, "frase": info["frase"], "avisos": avisos}


companheiro = Companheiro()


def conversar_com_humor(texto: str, conversar) -> dict:
    """Detecta o humor, ajusta a expressao, chama o cerebro e devolve a resposta."""
    emocao = detectar_emocao(texto)
    companheiro.atualizar(atividade="pensando", emocao_usuario=emocao,
                          expressao=REACAO[emocao], ultima_mensagem=texto)
    dica = DICA_PARA_O_CEREBRO.get(emocao)
    pergunta = f"{texto}\n\n({dica})" if dica else texto
    try:
        resposta = conversar(pergunta)
    finally:
        companheiro.atualizar(atividade="ocioso")
    estado = companheiro.atualizar(ultima_resposta=resposta, expressao=REACAO[emocao])
    return {"resposta": resposta, "emocao": emocao, "estado": estado}


def nome_do_modo(modo: str) -> str:
    return MODOS.get(modo, MODOS["normal"])["nome"]

