"""Testes unitarios offline do endpoint /v1/assistente e gestao de adaptadores.

Sem rede, sem hardware real, sem audio, sem chamada externa.
"""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import adaptadores, config, servico


class BaseAdaptadoresTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_tmp = Path(self.tmp_dir.name)
        self.patch_arq = mock.patch.object(adaptadores, "ARQUIVO", self.caminho_tmp / "adaptadores.json")
        self.patch_log = mock.patch.object(adaptadores, "ARQUIVO_LOG", self.caminho_tmp / "assistentes.log")
        self.patch_token = mock.patch.object(config, "TOKEN", "token-mestre-teste")
        self.patch_arq.start()
        self.patch_log.start()
        self.patch_token.start()
        adaptadores.resetar_estado_testes()
        self.client = servico.app.test_client()

    def tearDown(self):
        adaptadores.resetar_estado_testes()
        self.patch_arq.stop()
        self.patch_log.stop()
        self.patch_token.stop()
        self.tmp_dir.cleanup()


class TestAdaptadoresModel(BaseAdaptadoresTestCase):
    def test_cadastrar_e_listar(self):
        item = adaptadores.cadastrar("siri", "Siri Apple", token="token-siri", limite_por_minuto=30)
        self.assertEqual(item["id"], "siri")
        self.assertEqual(item["nome"], "Siri Apple")
        self.assertEqual(item["token"], "token-siri")
        self.assertEqual(item["limite_por_minuto"], 30)
        self.assertTrue(item["ativo"])

        todos = adaptadores.listar(mascarar=False)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["token"], "token-siri")

        mascarados = adaptadores.listar(mascarar=True)
        self.assertEqual(mascarados[0]["token"], "toke...siri")

    def test_cadastrar_id_vazio_ou_duplicado(self):
        with self.assertRaises(ValueError):
            adaptadores.cadastrar("   ", "Nome")

        adaptadores.cadastrar("alexa", "Alexa")
        with self.assertRaises(ValueError):
            adaptadores.cadastrar("alexa", "Alexa Novamente")

    def test_buscar_por_token_e_id(self):
        adaptadores.cadastrar("telegram", "Bot Telegram", token="token-tg-123")
        encontrado = adaptadores.buscar_por_token("token-tg-123")
        self.assertIsNotNone(encontrado)
        self.assertEqual(encontrado["id"], "telegram")

        self.assertIsNone(adaptadores.buscar_por_token("token-inexistente"))
        self.assertIsNone(adaptadores.buscar_por_token(""))

        por_id = adaptadores.buscar_por_id("TELEGRAM")
        self.assertIsNotNone(por_id)
        self.assertEqual(por_id["token"], "token-tg-123")
        self.assertIsNone(adaptadores.buscar_por_id("inexistente"))

    def test_revogar_e_reativar(self):
        adaptadores.cadastrar("siri", "Siri", token="token-siri")
        self.assertTrue(adaptadores.revogar("siri"))

        adaptador = adaptadores.buscar_por_id("siri")
        self.assertFalse(adaptador["ativo"])
        self.assertIn("revogado_em", adaptador)

        # Listar apenas ativos nao deve trazer o revogado
        self.assertEqual(len(adaptadores.listar(apenas_ativos=True)), 0)

        self.assertTrue(adaptadores.ativar("siri"))
        adaptador_reativado = adaptadores.buscar_por_id("siri")
        self.assertTrue(adaptador_reativado["ativo"])
        self.assertIn("reativado_em", adaptador_reativado)

    def test_remover(self):
        adaptadores.cadastrar("siri", "Siri", token="token-siri")
        self.assertTrue(adaptadores.remover("siri"))
        self.assertIsNone(adaptadores.buscar_por_id("siri"))
        self.assertFalse(adaptadores.remover("siri"))

    def test_rate_limiting_unitario(self):
        adaptadores.cadastrar("app", "App", limite_por_minuto=2)

        permitido1, rest1, _ = adaptadores.verificar_limite("app", limite_por_minuto=2)
        permitido2, rest2, _ = adaptadores.verificar_limite("app", limite_por_minuto=2)
        permitido3, rest3, reset_em = adaptadores.verificar_limite("app", limite_por_minuto=2)

        self.assertTrue(permitido1)
        self.assertEqual(rest1, 1)
        self.assertTrue(permitido2)
        self.assertEqual(rest2, 0)
        self.assertFalse(permitido3)
        self.assertEqual(rest3, 0)
        self.assertGreater(reset_em, 0.0)

    def test_registrar_uso(self):
        adaptadores.cadastrar("alexa", "Alexa")
        adaptadores.registrar_uso("alexa")
        item = adaptadores.buscar_por_id("alexa")
        self.assertEqual(item["total_requisicoes"], 1)
        self.assertIsNotNone(item["ultimo_uso"])

    def test_logs_unitarios(self):
        adaptadores.registrar_log("siri", "que horas sao", intencao="horas", status_http=200)
        adaptadores.registrar_log("siri", "comando invalido", status_http=400, detalhe="erro")

        logs = adaptadores.ler_logs(limite=10)
        self.assertEqual(len(logs), 2)
        # Mais recente primeiro
        self.assertEqual(logs[0]["texto"], "comando invalido")
        self.assertEqual(logs[0]["status"], 400)
        self.assertEqual(logs[1]["texto"], "que horas sao")
        self.assertEqual(logs[1]["status"], 200)


class TestAssistenteEndpoint(BaseAdaptadoresTestCase):
    def setUp(self):
        super().setUp()
        adaptadores.cadastrar("siri", "Siri Apple", token="token-siri-valido", limite_por_minuto=3)

    def test_autenticacao_sem_token(self):
        resp = self.client.post("/v1/assistente", json={"texto": "oi"})
        self.assertEqual(resp.status_code, 401)
        dados = resp.get_json()
        self.assertFalse(dados["ok"])
        self.assertIn("invalido", dados["erro"])

    def test_autenticacao_token_invalido(self):
        resp = self.client.post(
            "/v1/assistente",
            json={"texto": "oi"},
            headers={"Authorization": "Bearer token-falso"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_autenticacao_bearer_header(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "tudo bem", "intencao": "conversa"}):
            resp = self.client.post(
                "/v1/assistente",
                json={"texto": "oi nextor"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["resposta"], "tudo bem")
        self.assertEqual(dados["adaptador"], "siri")

    def test_autenticacao_x_nextor_token_header(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "resposta ok", "intencao": "geral"}):
            resp = self.client.post(
                "/v1/assistente",
                json={"texto": "teste"},
                headers={"X-Nextor-Token": "token-siri-valido"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_autenticacao_query_param(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "via query", "intencao": "geral"}):
            resp = self.client.post(
                "/v1/assistente?token=token-siri-valido",
                json={"texto": "teste query"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_adaptador_revogado_retorna_403(self):
        adaptadores.revogar("siri")
        resp = self.client.post(
            "/v1/assistente",
            json={"texto": "ola"},
            headers={"Authorization": "Bearer token-siri-valido"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("revogado", resp.get_json()["erro"])

    def test_rate_limit_excedido_retorna_429(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "ok", "intencao": "geral"}):
            for _ in range(3):
                r = self.client.post(
                    "/v1/assistente",
                    json={"texto": "msg"},
                    headers={"Authorization": "Bearer token-siri-valido"},
                )
                self.assertEqual(r.status_code, 200)

            # 4a chamada estoura o limite de 3/minuto
            resp4 = self.client.post(
                "/v1/assistente",
                json={"texto": "msg"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
            self.assertEqual(resp4.status_code, 429)
            self.assertIn("Retry-After", resp4.headers)
            self.assertIn("limite", resp4.get_json()["erro"])

    def test_ausencia_de_efeito_colateral_de_audio(self):
        with mock.patch.object(servico, "falar") as mock_falar, \
                mock.patch("nextor.servico.rotear", return_value={"resposta": "sem audio", "intencao": "conversa"}):
            resp = self.client.post(
                "/v1/assistente",
                json={"texto": "bom dia"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
            self.assertEqual(resp.status_code, 200)
            mock_falar.assert_not_called()

    def test_variacoes_de_payload_de_texto(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "recebido", "intencao": "ok"}):
            # campo 'pergunta'
            r1 = self.client.post(
                "/v1/assistente",
                json={"pergunta": "quem e voce?"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
            self.assertEqual(r1.status_code, 200)

            # campo 'comando'
            r2 = self.client.post(
                "/v1/assistente",
                json={"comando": "desliga tudo"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
            self.assertEqual(r2.status_code, 200)

            # form-data
            r3 = self.client.post(
                "/v1/assistente",
                data={"texto": "via form"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
            self.assertEqual(r3.status_code, 200)

    def test_texto_vazio_retorna_400(self):
        resp = self.client.post(
            "/v1/assistente",
            json={"texto": "   "},
            headers={"Authorization": "Bearer token-siri-valido"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("vazio", resp.get_json()["erro"])

    def test_chamada_registra_log(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "resp", "intencao": "tempo"}):
            self.client.post(
                "/v1/assistente",
                json={"texto": "vai chover hoje?"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
        logs = adaptadores.ler_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["adaptador"], "siri")
        self.assertEqual(logs[0]["intencao"], "tempo")
        self.assertEqual(logs[0]["texto"], "vai chover hoje?")
        self.assertEqual(logs[0]["status"], 200)


class TestAssistenteAdminEndpoints(BaseAdaptadoresTestCase):
    def setUp(self):
        super().setUp()
        self.h_mestre = {"X-Nextor-Token": "token-mestre-teste"}

    def test_bloqueio_sem_token_mestre(self):
        self.assertEqual(self.client.get("/v1/assistente/adaptadores").status_code, 401)
        self.assertEqual(self.client.post("/v1/assistente/adaptadores").status_code, 401)
        self.assertEqual(self.client.post("/v1/assistente/adaptadores/siri/revogar").status_code, 401)
        self.assertEqual(self.client.post("/v1/assistente/adaptadores/siri/ativar").status_code, 401)
        self.assertEqual(self.client.get("/v1/assistente/logs").status_code, 401)

    def test_cadastrar_e_listar_via_admin(self):
        cad_resp = self.client.post(
            "/v1/assistente/adaptadores",
            json={"id": "alexa", "nome": "Alexa Echo", "limite_por_minuto": 45},
            headers=self.h_mestre,
        )
        self.assertEqual(cad_resp.status_code, 201)
        cad_dados = cad_resp.get_json()
        self.assertTrue(cad_dados["ok"])
        self.assertEqual(cad_dados["adaptador"]["id"], "alexa")

        # Listagem padrao mascara token
        list_resp = self.client.get("/v1/assistente/adaptadores", headers=self.h_mestre)
        self.assertEqual(list_resp.status_code, 200)
        itens = list_resp.get_json()["adaptadores"]
        self.assertEqual(len(itens), 1)
        self.assertIn("...", itens[0]["token"])

        # Listagem com revelar=1 exibe token completo
        rev_resp = self.client.get("/v1/assistente/adaptadores?revelar=1", headers=self.h_mestre)
        self.assertEqual(rev_resp.status_code, 200)
        itens_rev = rev_resp.get_json()["adaptadores"]
        self.assertEqual(itens_rev[0]["token"], cad_dados["adaptador"]["token"])

    def test_revogar_e_ativar_via_admin(self):
        adaptadores.cadastrar("alexa", "Alexa")

        rev_resp = self.client.post("/v1/assistente/adaptadores/alexa/revogar", headers=self.h_mestre)
        self.assertEqual(rev_resp.status_code, 200)
        self.assertTrue(rev_resp.get_json()["revogado"])
        self.assertFalse(adaptadores.buscar_por_id("alexa")["ativo"])

        ativ_resp = self.client.post("/v1/assistente/adaptadores/alexa/ativar", headers=self.h_mestre)
        self.assertEqual(ativ_resp.status_code, 200)
        self.assertTrue(ativ_resp.get_json()["ativo"])
        self.assertTrue(adaptadores.buscar_por_id("alexa")["ativo"])

    def test_revogar_id_inexistente_retorna_404(self):
        resp = self.client.post("/v1/assistente/adaptadores/fantasma/revogar", headers=self.h_mestre)
        self.assertEqual(resp.status_code, 404)

    def test_consultar_logs_via_admin(self):
        adaptadores.registrar_log("telegram", "teste log", status_http=200)
        resp = self.client.get("/v1/assistente/logs?limite=10", headers=self.h_mestre)
        self.assertEqual(resp.status_code, 200)
        logs = resp.get_json()["logs"]
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["adaptador"], "telegram")


if __name__ == "__main__":
    unittest.main()
