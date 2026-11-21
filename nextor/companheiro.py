"""Companheiro: o "bichinho" do Nextor. Guarda o modo, a expressao e o humor percebido.

Os rostos (pagina /rosto, NexDeck, TV) leem este estado por /estado e /eventos.
"""
import queue
import re
import threading
import time
import unicodedata

from . import config


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

# Quem responde: a persona do Nextor ou outro assistente, cada um com o seu simbolo no rosto.
IDENTIDADES = {
    "nextor": {"nome": "Nextor", "cerebro": None, "frase": "Voltei. Aqui e o Nextor."},
    "claude": {"nome": "Claude", "cerebro": "claude", "frase": "Agora quem responde e o Claude."},
    "agy": {"nome": "agy", "cerebro": "agy", "frase": "Agora quem responde e o agy."},
}
SISTEMA_IDENTIDADE = {
    "claude": "Voce e o Claude, respondendo por voz e pela tela do Nextor. Responda em portugues do Brasil, curto e util.",
    "agy": "Voce e o agy, respondendo por voz e pela tela do Nextor. Responda em portugues do Brasil, curto e util.",
}
CEREBRO_PADRAO = config.CEREBRO

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

ATIVIDADES = (
    "ocioso",
    "ouvindo",
    "pensando",
    "falando",
    "gravando",
    "erro",
    "gravando_aula",
    "gravando_reuniao",
    "gravando_tela",
    "traduzindo_voz",
    "normal",
)

EXPRESSOES = (
    "neutro",
    "feliz",
    "carinho",
    "calmo",
    "sonolento",
    "erro",
)

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


def identidade_pedida(frase: str) -> str | None:
    """Reconhece "usar o Claude", "troca para o agy", "volta para o Nextor", "quero falar com o Claude"."""
    from .chamado import NOMES
    base = _normaliza(frase)
    m = re.search(r"\b(usa|usar|use|troca|trocar|muda|mudar|volta|voltar|falar com|chama|chamar)\b"
                  r"(?: (?:para|pra|pro|com|de))?(?: (?:o|a))? (\w+)", base)
    if m and m.group(2) in NOMES:
        return NOMES[m.group(2)]
    return None


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
        from .fala import idioma_inicial
        self.estado = {
            "identidade": "nextor",
            "idioma": idioma_inicial(),
            "fala": None,  # {"id": ..., "duracao": ...} do ultimo audio para as telas tocarem
            "modo": "normal",
            "acessorio": None,
            "expressao": "neutro",
            "atividade": "ocioso",  # ocioso, ouvindo, pensando, falando, gravando, erro
            "gravando": False,
            "detalhe": "",
            "erro": "",
            "emocao_usuario": "neutro",
            "ultima_mensagem": "",
            "ultima_resposta": "",
            "legenda": "",
            "intencao": "",
            "resultado": None,
            "atualizado_em": time.time(),
        }

    def _gravacao_externa_ativa(self) -> tuple[bool, str]:
        try:
            from . import aulas
            if hasattr(aulas, "gravador") and aulas.gravador.gravando:
                disc = aulas.gravador.disciplina
                return True, f"Gravando aula de {disc}" if disc else "Gravando aula"
        except Exception:
            pass
        try:
            from . import reuniao_tela
            if reuniao_tela.gravador_reuniao.gravando:
                tema = reuniao_tela.gravador_reuniao.tema
                return True, f"Gravando reuniao: {tema}" if tema else "Gravando reuniao"
            if reuniao_tela.gravador_tela.gravando:
                tarefa = reuniao_tela.gravador_tela.tarefa
                return True, f"Gravando tela: {tarefa}" if tarefa else "Gravando tela"
        except Exception:
            pass
        return False, ""

    def ver(self) -> dict:
        ext_grav, ext_detalhe = self._gravacao_externa_ativa()
        with self._trava:
            copia = dict(self.estado)
        ativ = str(copia.get("atividade") or "ocioso")
        if ext_grav or ativ.startswith("gravando"):
            copia["gravando"] = True
            if not copia.get("detalhe") and ext_detalhe:
                copia["detalhe"] = ext_detalhe
        return copia

    def atualizar(self, **campos) -> dict:
        ext_grav, ext_detalhe = self._gravacao_externa_ativa()
        with self._trava:
            if "ultima_resposta" in campos and "legenda" not in campos and campos["ultima_resposta"] is not None:
                campos["legenda"] = campos["ultima_resposta"]
            if "atividade" in campos:
                ativ_nova = str(campos["atividade"] or "ocioso")
                if ativ_nova == "erro":
                    if "expressao" not in campos:
                        campos["expressao"] = "erro"
                elif self.estado.get("atividade") == "erro":
                    if "erro" not in campos:
                        campos["erro"] = ""
                    if self.estado.get("expressao") == "erro" and "expressao" not in campos:
                        campos["expressao"] = REACAO.get(self.estado.get("emocao_usuario", "neutro"), "neutro")
            ativ_efetiva = str(campos.get("atividade", self.estado.get("atividade", "ocioso")))
            if "gravando" in campos:
                grav_flag = bool(campos["gravando"]) or ext_grav or ativ_efetiva.startswith("gravando")
            else:
                grav_flag = ext_grav or ativ_efetiva.startswith("gravando")
            campos["gravando"] = grav_flag
            if grav_flag and not campos.get("detalhe", self.estado.get("detalhe")) and ext_detalhe:
                campos["detalhe"] = ext_detalhe
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
        q = queue.Queue(maxsize=50)
        with self._trava:
            self._ouvintes.append(q)
        return q

    def cancelar(self, q: queue.Queue) -> None:
        with self._trava:
            if q in self._ouvintes:
                self._ouvintes.remove(q)

    def definir_atividade(
        self,
        atividade: str,
        detalhe: str | None = None,
        erro: str | None = None,
        legenda: str | None = None,
        resultado: dict | None = None,
    ) -> dict:
        ativ = (atividade or "").strip().lower()
        if ativ not in ATIVIDADES:
            raise ValueError(f"Atividade desconhecida: {atividade}")
        campos: dict = {"atividade": ativ}
        if detalhe is not None:
            campos["detalhe"] = detalhe
        if erro is not None:
            campos["erro"] = erro
        if legenda is not None:
            campos["legenda"] = legenda
            campos["ultima_resposta"] = legenda
        if resultado is not None:
            campos["resultado"] = resultado
        return self.atualizar(**campos)

    def registrar_erro(self, mensagem: str) -> dict:
        msg = (mensagem or "Erro ao processar solicitacao.").strip()
        return self.atualizar(
            atividade="erro",
            expressao="erro",
            erro=msg,
            ultima_resposta=msg,
            legenda=msg,
        )

    def definir_resultado(self, resultado: dict | None) -> dict:
        return self.atualizar(resultado=resultado)

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


    def definir_identidade(self, nome: str) -> dict:
        if nome not in IDENTIDADES:
            raise ValueError(f"Identidade desconhecida: {nome}")
        info = IDENTIDADES[nome]
        config.CEREBRO = info["cerebro"] or CEREBRO_PADRAO
        estado = self.atualizar(identidade=nome, expressao="feliz")
        return {"estado": estado, "frase": info["frase"]}

    def definir_idioma(self, idioma: str) -> dict:
        from .fala import IDIOMAS
        if idioma not in IDIOMAS:
            raise ValueError(f"Idioma desconhecido: {idioma}")
        return self.atualizar(idioma=idioma)

    def ouvintes(self) -> int:
        with self._trava:
            return len(self._ouvintes)


companheiro = Companheiro()


def conversar_com_humor(texto: str, conversar) -> dict:
    """Detecta o humor, ajusta a expressao, chama o cerebro e devolve a resposta."""
    emocao = detectar_emocao(texto)
    companheiro.atualizar(
        atividade="pensando",
        emocao_usuario=emocao,
        expressao=REACAO[emocao],
        ultima_mensagem=texto,
        erro="",
    )
    from .fala import IDIOMAS
    dicas = [DICA_PARA_O_CEREBRO.get(emocao)]
    idioma = companheiro.ver().get("idioma", "pt-BR")
    if idioma != "pt-BR":
        dicas.append(IDIOMAS[idioma]["instrucao"])
    dicas = [d for d in dicas if d]
    pergunta = f"{texto}\n\n({' '.join(dicas)})" if dicas else texto
    identidade = companheiro.ver().get("identidade", "nextor")
    try:
        if identidade in SISTEMA_IDENTIDADE:
            from .cerebro import responder
            resposta = responder(pergunta, sistema=SISTEMA_IDENTIDADE[identidade], tokens=300)
        else:
            resposta = conversar(pergunta)
    except Exception as e:
        companheiro.registrar_erro(str(e) or "Erro ao consultar o cerebro.")
        raise
    estado = companheiro.atualizar(
        atividade="ocioso",
        ultima_resposta=resposta,
        legenda=resposta,
        expressao=REACAO[emocao],
    )
    return {"resposta": resposta, "emocao": emocao, "estado": estado}


def nome_do_modo(modo: str) -> str:
    return MODOS.get(modo, MODOS["normal"])["nome"]

