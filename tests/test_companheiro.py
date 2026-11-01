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


if __name__ == "__main__":
    unittest.main()
