"""Testes das frases de chamada e da troca de identidade (Nextor, Claude, agy). Sem rede."""
import unittest
from unittest import mock

from nextor import ambiente, config, roteador, servico
from nextor.chamado import entender
from nextor.companheiro import CEREBRO_PADRAO, companheiro, conversar_com_humor, identidade_pedida


class TestChamado(unittest.TestCase):
    def test_frases_do_dia_a_dia(self):
        casos = {
            "ei Nextor, modo estudo": ("nextor", "modo estudo"),
            "Ola Nextor": ("nextor", ""),
            "fala Nextor, o que tenho hoje": ("nextor", "o que tenho hoje"),
            "meu bom Nextor, anota comprar pao": ("nextor", "anota comprar pao"),
            "meu amigo nexto, modo leitura": ("nextor", "modo leitura"),
            "bom nexto": ("nextor", ""),
            "fala enxtor": ("nextor", ""),
            "e ai nestor, tudo bem?": ("nextor", "tudo bem?"),
            "Ei Claude, explica derivada": ("claude", "explica derivada"),
            "oi agy, resume o capitulo": ("agy", "resume o capitulo"),
            "Nextôr, tudo certo": ("nextor", "tudo certo"),
        }
        for frase, (nome, comando) in casos.items():
            with self.subTest(frase=frase):
                r = entender(frase)
                self.assertTrue(r["chamado"])
                self.assertEqual(r["nome"], nome)
                self.assertEqual(r["comando"], comando)

    def test_nao_confunde_com_frase_comum(self):
        for frase in ("quero ler sobre o Nestor Kirchner", "salva o arquivo", "o next do capitulo", ""):
            with self.subTest(frase=frase):
                self.assertFalse(entender(frase)["chamado"])

    def test_pedido_de_identidade(self):
        self.assertEqual(identidade_pedida("usar o Claude"), "claude")
        self.assertEqual(identidade_pedida("troca para o agy"), "agy")
        self.assertEqual(identidade_pedida("volta pro Nextor"), "nextor")
        self.assertEqual(identidade_pedida("quero falar com o Claude"), "claude")
        self.assertIsNone(identidade_pedida("usar o caderno"))


class TestIdentidade(unittest.TestCase):
    def tearDown(self):
        companheiro.definir_identidade("nextor")

    def test_troca_o_cerebro(self):
        companheiro.definir_identidade("claude")
        self.assertEqual(config.CEREBRO, "claude")
        self.assertEqual(companheiro.ver()["identidade"], "claude")
        companheiro.definir_identidade("nextor")
        self.assertEqual(config.CEREBRO, CEREBRO_PADRAO)

    def test_outra_identidade_usa_prompt_proprio(self):
        companheiro.definir_identidade("agy")
        with mock.patch("nextor.cerebro.responder", return_value="Resposta do agy.") as responder:
            r = conversar_com_humor("explica fotossintese", lambda t: "persona do Nextor")
        self.assertEqual(r["resposta"], "Resposta do agy.")
        self.assertIn("agy", responder.call_args.kwargs["sistema"])

    def test_chamar_pelo_nome_troca_identidade_e_acorda(self):
        with mock.patch.object(roteador, "_registra"):
            r = roteador.rotear("Ei Claude")
        self.assertEqual(r["intencao"], "chamado")
        self.assertEqual(companheiro.ver()["identidade"], "claude")
        self.assertEqual(companheiro.ver()["atividade"], "ouvindo")

    def test_chamado_com_comando_executa(self):
        with mock.patch.object(roteador, "_registra"), mock.patch.object(ambiente, "aplicar", return_value=[]):
            r = roteador.rotear("meu amigo Nextor, modo leitura")
        self.assertEqual(r["intencao"], "modo")
        self.assertEqual(companheiro.ver()["acessorio"], "oculos")


class TestRotasIdentidade(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(config, "TOKEN", "segredo")
        self.p.start()
        self.c = servico.app.test_client()
        self.h = {"X-Nextor-Token": "segredo"}

    def tearDown(self):
        self.p.stop()
        companheiro.definir_identidade("nextor")

    def test_rota_identidade(self):
        self.assertEqual(self.c.post("/identidade", json={"identidade": "claude"}).status_code, 401)
        r = self.c.post("/identidade", json={"identidade": "claude"}, headers=self.h)
        self.assertEqual(r.get_json()["estado"]["identidade"], "claude")
        self.assertEqual(self.c.post("/identidade", json={"identidade": "siri"}, headers=self.h).status_code, 400)

    def test_comando_chamado_abre_o_rosto(self):
        with mock.patch("nextor.janela.abrir_rosto") as abrir, mock.patch.object(servico, "falar"), \
                mock.patch.object(roteador, "_registra"):
            self.c.post("/comando", json={"texto": "ei Nextor"}, headers=self.h)
            self.c.post("/comando", json={"texto": "modo normal"}, headers=self.h)
        self.assertEqual(abrir.call_count, 1)

    def test_comando_responde_mesmo_sem_nest(self):
        with mock.patch.object(servico, "falar", side_effect=RuntimeError("sem nest")),                 mock.patch.object(roteador, "_registra"), mock.patch.object(ambiente, "aplicar", return_value=[]):
            r = self.c.post("/comando", json={"texto": "modo leitura"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Nest", r.get_json()["aviso"])
        self.assertEqual(companheiro.ver()["ultima_resposta"], r.get_json()["resposta"])


if __name__ == "__main__":
    unittest.main()
