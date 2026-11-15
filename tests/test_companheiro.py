"""Testes do bichinho (companheiro), modos e rotas do rosto. Sem rede, sem Nest, sem PC."""
import io
import json
import os
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"  # testes nunca tocam audio

from nextor import ambiente, config, servico
from nextor.companheiro import Companheiro, companheiro, conversar_com_humor, detectar_emocao, modo_pedido


class TestEmocao(unittest.TestCase):
    def test_reconhece_humores(self):
        self.assertEqual(detectar_emocao("Passei na prova, to muito feliz!"), "feliz")
        self.assertEqual(detectar_emocao("Hoje eu to triste e desanimado"), "triste")
        self.assertEqual(detectar_emocao("Estou ansioso, tenho prova amanha"), "ansioso")
        self.assertEqual(detectar_emocao("Que cansaco, to exausto"), "cansado")
        self.assertEqual(detectar_emocao("To com raiva desse codigo"), "irritado")
        self.assertEqual(detectar_emocao("Qual a capital da Franca?"), "neutro")

    def test_negacao(self):
        self.assertEqual(detectar_emocao("Nao estou feliz hoje"), "triste")
        self.assertEqual(detectar_emocao("Nao estou cansado"), "neutro")

    def test_acentos(self):
        self.assertEqual(detectar_emocao("Estou PREOCUPADA com o prazo"), "ansioso")


class TestModos(unittest.TestCase):
    def test_reconhece_pedidos(self):
        self.assertEqual(modo_pedido("Nextor, ativa o modo estudo"), "estudo")
        self.assertEqual(modo_pedido("modo leitura"), "leitura")
        self.assertEqual(modo_pedido("entra no modo tranquilo"), "tranquilidade")
        self.assertEqual(modo_pedido("quero relaxar um pouco"), "tranquilidade")
        self.assertEqual(modo_pedido("modo trabalho por favor"), "trabalho")
        self.assertIsNone(modo_pedido("qual o modo de preparo do bolo"))

    def test_acessorio_de_cada_modo(self):
        c = Companheiro()
        with mock.patch.object(ambiente, "aplicar", return_value=[]):
            self.assertEqual(c.definir_modo("estudo")["estado"]["acessorio"], "mochila")
            self.assertEqual(c.definir_modo("trabalho")["estado"]["acessorio"], "gravata")
            self.assertEqual(c.definir_modo("tranquilidade")["estado"]["acessorio"], "relaxado")
            self.assertEqual(c.definir_modo("leitura")["estado"]["acessorio"], "oculos")
            self.assertIsNone(c.definir_modo("normal")["estado"]["acessorio"])
        with self.assertRaises(ValueError):
            c.definir_modo("festa")

    def test_ouvintes_recebem_mudancas(self):
        c = Companheiro()
        fila = c.assinar()
        c.atualizar(atividade="pensando")
        self.assertEqual(fila.get_nowait()["atividade"], "pensando")
        c.cancelar(fila)


class TestAmbiente(unittest.TestCase):
    def test_leitura_baixa_o_brilho_e_acende_luz_quente(self):
        chamadas = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=0):
            chamadas.append((req.full_url, json.loads(req.data), req.get_header("Authorization")))
            return Resp(b"[]")

        env = {"NEXTOR_HA_URL": "http://ha:8123", "NEXTOR_HA_TOKEN": "tk", "NEXTOR_HA_LUZES": "light.sala, light.mesa"}
        with mock.patch.dict(os.environ, env), mock.patch("urllib.request.urlopen", urlopen), \
                mock.patch.object(ambiente, "_brilho_anterior", None),                 mock.patch.object(ambiente, "ler_brilho_pc", return_value=80),                 mock.patch.object(ambiente, "ajustar_brilho_pc") as brilho:
            avisos = ambiente.aplicar("leitura")
        brilho.assert_called_once_with(30)
        url, dados, auth = chamadas[0]
        self.assertEqual(url, "http://ha:8123/api/services/light/turn_on")
        self.assertEqual(dados, {"entity_id": ["light.sala", "light.mesa"], "brightness_pct": 55, "color_temp_kelvin": 3000})
        self.assertEqual(auth, "Bearer tk")
        self.assertTrue(any("Luzes" in a for a in avisos))

    def test_brilho_volta_ao_sair_do_modo(self):
        limpo = {k: v for k, v in os.environ.items() if not k.startswith("NEXTOR_HA_")}
        with mock.patch.dict(os.environ, limpo, clear=True),                 mock.patch.object(ambiente, "_brilho_anterior", None),                 mock.patch.object(ambiente, "ler_brilho_pc", return_value=85),                 mock.patch.object(ambiente, "ajustar_brilho_pc") as brilho:
            ambiente.aplicar("leitura")
            ambiente.aplicar("normal")
        self.assertEqual([c.args[0] for c in brilho.call_args_list], [30, 85])

    def test_cena_configurada_tem_prioridade(self):
        env = {"NEXTOR_HA_URL": "http://ha:8123", "NEXTOR_HA_TOKEN": "tk", "NEXTOR_HA_CENA_ESTUDO": "scene.estudo"}
        with mock.patch.dict(os.environ, env), mock.patch.object(ambiente, "_ha") as ha:
            ambiente.aplicar_luzes("estudo")
        ha.assert_called_once_with("scene/turn_on", {"entity_id": "scene.estudo"})

    def test_sem_home_assistant_nao_quebra(self):
        limpo = {k: v for k, v in os.environ.items() if not k.startswith("NEXTOR_HA_")}
        with mock.patch.dict(os.environ, limpo, clear=True), \
                mock.patch.object(ambiente, "_brilho_anterior", None),                 mock.patch.object(ambiente, "ler_brilho_pc", return_value=None),                 mock.patch.object(ambiente, "ajustar_brilho_pc", side_effect=RuntimeError("sem tela")):
            avisos = ambiente.aplicar("leitura")
        self.assertEqual(avisos, ["Nao consegui mudar o brilho do PC (RuntimeError)."])


class TestConversa(unittest.TestCase):
    def test_dica_de_humor_vai_para_o_cerebro(self):
        recebido = []
        r = conversar_com_humor("To triste, reprovei", lambda t: recebido.append(t) or "Sinto muito. Vamos ver o que deu errado?")
        self.assertEqual(r["emocao"], "triste")
        self.assertIn("acolhimento", recebido[0])
        self.assertEqual(r["estado"]["expressao"], "carinho")
        self.assertEqual(r["estado"]["atividade"], "ocioso")


class TestRotas(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(config, "TOKEN", "segredo")
        self.p.start()
        self.c = servico.app.test_client()
        self.h = {"X-Nextor-Token": "segredo"}

    def tearDown(self):
        self.p.stop()

    def test_rosto_e_publico_mas_estado_exige_token(self):
        self.assertEqual(self.c.get("/rosto").status_code, 200)
        self.assertEqual(self.c.get("/web/bichinho.js").status_code, 200)
        self.assertEqual(self.c.get("/estado").status_code, 401)
        self.assertEqual(self.c.get("/estado", headers=self.h).status_code, 200)

    def test_web_nao_sai_da_pasta(self):
        self.assertEqual(self.c.get("/web/../config.py").status_code, 404)

    def test_modo(self):
        with mock.patch.object(ambiente, "aplicar", return_value=["Tela do PC em 30%."]):
            r = self.c.post("/modo", json={"modo": "leitura"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["estado"]["acessorio"], "oculos")
        self.assertEqual(self.c.post("/modo", json={"modo": "festa"}, headers=self.h).status_code, 400)

    def test_conversa_pela_tela_nao_fala_no_nest(self):
        with mock.patch.object(servico, "conversar", lambda t: "Oi! Tudo certo."), \
                mock.patch.object(servico, "falar") as falar:
            r = self.c.post("/conversa", json={"texto": "oi, to feliz"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["emocao"], "feliz")
        falar.assert_not_called()

    def test_conversa_falha_no_nest_vira_aviso(self):
        with mock.patch.object(servico, "conversar", lambda t: "Oi."), \
                mock.patch.dict(os.environ, {"NEXTOR_VOZ_SAIDA": "nest"}), mock.patch.object(servico, "falar", side_effect=RuntimeError("sem nest")):
            r = self.c.post("/conversa", json={"texto": "oi", "falar": True}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Nest", r.get_json()["aviso"])
        self.assertEqual(companheiro.ver()["atividade"], "ocioso")

    def test_roteador_muda_modo_por_voz(self):
        from nextor import roteador
        with mock.patch.object(ambiente, "aplicar", return_value=[]), mock.patch.object(roteador, "_registra"):
            r = roteador.rotear("Nextor, modo trabalho")
        self.assertEqual(r["intencao"], "modo")
        self.assertIn("Gravata", r["resposta"])

    def test_post_estado_atualiza_campos(self):
        payload = {
            "atividade": "ouvindo",
            "expressao": "calmo",
            "legenda": "Ouvindo sua pergunta...",
            "resultado": {
                "tipo": "tarefas",
                "titulo": "Tarefas",
                "itens": [{"id": "t1", "titulo": "Estudar"}],
            },
        }
        r = self.c.post("/estado", json=payload, headers=self.h)
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertEqual(dados["atividade"], "ouvindo")
        self.assertEqual(dados["expressao"], "calmo")
        self.assertEqual(dados["legenda"], "Ouvindo sua pergunta...")
        self.assertEqual(dados["resultado"]["tipo"], "tarefas")

    def test_post_estado_validacoes(self):
        r1 = self.c.post("/estado", json={"atividade": "invalida"}, headers=self.h)
        self.assertEqual(r1.status_code, 400)
        r2 = self.c.post("/estado", json={"expressao": "invalida"}, headers=self.h)
        self.assertEqual(r2.status_code, 400)

    def test_pagina_rosto_contem_elementos_acessiveis_e_recursos(self):
        r = self.c.get("/rosto")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('id="indicador-gravacao"', html)
        self.assertIn('id="estado-assistente"', html)
        self.assertIn('id="painel-legenda"', html)
        self.assertIn('id="painel-resultado"', html)
        self.assertIn('web/rosto.css', html)
        self.assertIn('web/rosto.js', html)
        self.assertIn('web/bichinho.js', html)

    def test_recursos_estaticos_web_disponiveis(self):
        for arquivo in ("bichinho.js", "bichinho.css", "rosto.js", "rosto.css", "rosto.html"):
            r = self.c.get(f"/web/{arquivo}")
            self.assertEqual(r.status_code, 200, f"Arquivo /web/{arquivo} deve existir")


class TestEstadosDoAssistente(unittest.TestCase):
    def setUp(self):
        self.c = Companheiro()

    def test_estados_principais_aceitos(self):
        for estado in ("ocioso", "ouvindo", "pensando", "falando", "gravando", "erro"):
            res = self.c.definir_atividade(estado)
            self.assertEqual(res["atividade"], estado)

    def test_estado_invalido_rejeitado(self):
        with self.assertRaises(ValueError):
            self.c.definir_atividade("voando")

    def test_registrar_erro(self):
        res = self.c.registrar_erro("Falha de conexao com o modelo")
        self.assertEqual(res["atividade"], "erro")
        self.assertEqual(res["expressao"], "erro")
        self.assertEqual(res["erro"], "Falha de conexao com o modelo")
        self.assertEqual(res["legenda"], "Falha de conexao com o modelo")

    def test_definir_resultado_tarefas_quiz_resumo(self):
        res_tarefas = {"tipo": "tarefas", "titulo": "Lista", "itens": [{"id": "1", "titulo": "Item"}]}
        self.c.definir_resultado(res_tarefas)
        self.assertEqual(self.c.ver()["resultado"]["tipo"], "tarefas")

        res_quiz = {"tipo": "quiz", "titulo": "Quiz", "pergunta": "Qual a resposta?", "opcoes": ["A", "B"]}
        self.c.definir_resultado(res_quiz)
        self.assertEqual(self.c.ver()["resultado"]["tipo"], "quiz")

        res_resumo = {"tipo": "resumo", "titulo": "Resumo", "resumo": "Texto sintetizado", "itens": []}
        self.c.definir_resultado(res_resumo)
        self.assertEqual(self.c.ver()["resultado"]["tipo"], "resumo")

    def test_gravacao_externa_ativa_aulas(self):
        fake_gravador = mock.Mock(gravando=True, disciplina="Calculo")
        with mock.patch("nextor.aulas.gravador", fake_gravador, create=True):
            estado = self.c.ver()
            self.assertTrue(estado["gravando"])
            self.assertIn("Calculo", estado["detalhe"])

    def test_rosto_web_js_estados_e_resultados_no_node(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node nao encontrado")
        script = """
const fs = require('fs');
const vm = require('vm');

class MockElement {
  constructor(tag) {
    this.tagName = (tag || 'DIV').toUpperCase();
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.textContent = '';
    this.hidden = false;
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] || null; }
  removeAttribute(k) { delete this.attributes[k]; }
  replaceChildren(...kids) { this.children = kids; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener() {}
  focus() {}
}

const elements = {
  'indicador-gravacao': new MockElement('div'),
  'detalhe-gravacao': new MockElement('span'),
  'estado-assistente': new MockElement('div'),
  'estado-rotulo': new MockElement('span'),
  'tela-cheia': new MockElement('button'),
  'bichinho': new MockElement('div'),
  'nome': new MockElement('p'),
  'humor': new MockElement('p'),
  'alerta-erro': new MockElement('div'),
  'texto-erro': new MockElement('span'),
  'painel-legenda': new MockElement('section'),
  'ultima-pergunta': new MockElement('span'),
  'balao': new MockElement('p'),
  'painel-resultado': new MockElement('section'),
  'resultado-tipo': new MockElement('span'),
  'resultado-titulo': new MockElement('h2'),
  'resultado-resumo': new MockElement('p'),
  'resultado-lista': new MockElement('ul'),
  'resultado-quiz': new MockElement('div'),
  'quiz-pergunta': new MockElement('p'),
  'quiz-opcoes': new MockElement('div'),
  'quiz-feedback': new MockElement('p'),
  'conversa': new MockElement('form'),
  'texto': new MockElement('input'),
  'com-voz': new MockElement('input'),
  'idioma': new MockElement('select'),
  'aviso': new MockElement('p')
};

const documentMock = {
  getElementById: (id) => elements[id] || null,
  createElement: (tag) => new MockElement(tag),
  createElementNS: (ns, tag) => new MockElement(tag),
  querySelectorAll: () => [],
  documentElement: new MockElement('html'),
  body: new MockElement('body')
};

const windowMock = {
  document: documentMock,
  location: { search: '?token=tk', hash: '', pathname: '/rosto' },
  history: { replaceState: () => {} },
  localStorage: { getItem: () => 'tk', setItem: () => {} },
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  navigator: {},
  EventSource: function() { this.onmessage = null; },
  MutationObserver: function() { this.observe = () => {}; }
};

const sandbox = {
  console,
  window: windowMock,
  document: documentMock,
  location: windowMock.location,
  history: windowMock.history,
  localStorage: windowMock.localStorage,
  EventSource: windowMock.EventSource,
  MutationObserver: windowMock.MutationObserver,
  fetch: windowMock.fetch,
  navigator: windowMock.navigator,
  URLSearchParams
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('nextor/web/bichinho.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('nextor/web/rosto.js', 'utf8'), sandbox);

const R = sandbox.window.NextorRosto;
if (!R) throw new Error('NextorRosto nao encontrado');

const estados = ['ocioso', 'ouvindo', 'pensando', 'falando', 'gravando', 'erro'];
estados.forEach(st => {
  R.desenhar({ atividade: st, ultima_resposta: 'Texto ' + st });
  if (elements['estado-assistente'].getAttribute('data-atividade') !== st) {
    throw new Error('Estado incorreto: ' + st);
  }
});

R.renderResultado({ tipo: 'tarefas', titulo: 'Tarefas', itens: [{ id: '1', titulo: 'Item' }] });
if (elements['painel-resultado'].hidden) throw new Error('painel-resultado oculto para tarefas');

R.renderResultado({ tipo: 'quiz', titulo: 'Quiz', pergunta: 'Pergunta?', opcoes: ['A', 'B'] });
if (elements['painel-resultado'].hidden) throw new Error('painel-resultado oculto para quiz');

R.renderResultado({ tipo: 'resumo', titulo: 'Resumo', resumo: 'Texto', itens: [{ ponto: 'P1' }] });
if (elements['painel-resultado'].hidden) throw new Error('painel-resultado oculto para resumo');
"""
        proc = subprocess.run([node, "-e", script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Falha no teste do rosto em JS: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
