"""Testes unitarios offline do endpoint /v1/assistente e gestao de adaptadores.

Sem rede, sem hardware real, sem audio, sem chamada externa.
Cobre hash sha256 de tokens, comparacao constant-time, sanitizacao de log,
revogacao estrita por id e ausencia de efeito colateral de audio.
"""
import os
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
        # Token puro retornado apenas uma unica vez no retorno do cadastrar
        self.assertEqual(item["token"], "token-siri")
        self.assertEqual(item["prefixo"], "token-si...")
        self.assertEqual(item["limite_por_minuto"], 30)
        self.assertTrue(item["ativo"])

        todos = adaptadores.listar(mascarar=False)
        self.assertEqual(len(todos), 1)
        self.assertNotIn("token", todos[0])
        self.assertIn("token_hash", todos[0])
        self.assertEqual(todos[0]["prefixo"], "token-si...")

        mascarados = adaptadores.listar(mascarar=True)
        self.assertNotIn("token", mascarados[0])
        self.assertNotIn("token_hash", mascarados[0])
        self.assertEqual(mascarados[0]["prefixo"], "token-si...")

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
        self.assertNotIn("token", por_id)
        self.assertEqual(por_id["prefixo"], "token-tg...")
        self.assertIn("token_hash", por_id)
        self.assertIsNone(adaptadores.buscar_por_id("inexistente"))

    def test_token_puro_nao_aparece_no_arquivo_json(self):
        token_secreto = "nxt_segredo_super_confidencial_98765"
        adaptadores.cadastrar("segredo", "Dispositivo Secreto", token=token_secreto)

        conteudo_disco = adaptadores.ARQUIVO.read_text(encoding="utf-8")
        self.assertNotIn(token_secreto, conteudo_disco)
        self.assertIn(adaptadores._hash_token(token_secreto), conteudo_disco)
        self.assertIn("nxt_segr...", conteudo_disco)

    def test_autenticacao_hmac_tempo_constante_e_token_incorreto_mesmo_tamanho(self):
        token_valido = "nxt_1234567890abcdef12345678"
        token_invalido_mesmo_tamanho = "nxt_1234567890abcdef12345679"
        adaptadores.cadastrar("hmac_test", "HMAC Test", token=token_valido)

        self.assertIsNotNone(adaptadores.buscar_por_token(token_valido))
        self.assertIsNone(adaptadores.buscar_por_token(token_invalido_mesmo_tamanho))
        self.assertIsNone(adaptadores.buscar_por_token("nxt_outro_tamanho"))
        self.assertIsNone(adaptadores.buscar_por_token(""))

    def test_revogacao_e_ativacao_estrita_por_id(self):
        adaptadores.cadastrar("siri", "Siri", token="token-siri")

        # Passar token puro nao revoga (aceita estritamente o id)
        self.assertFalse(adaptadores.revogar("token-siri"))
        self.assertTrue(adaptadores.buscar_por_id("siri")["ativo"])

        # Revogar com id funciona
        self.assertTrue(adaptadores.revogar("siri"))
        adaptador = adaptadores.buscar_por_id("siri")
        self.assertFalse(adaptador["ativo"])
        self.assertIn("revogado_em", adaptador)

        # Listar apenas ativos nao traz o revogado
        self.assertEqual(len(adaptadores.listar(apenas_ativos=True)), 0)

        # Passar token puro nao reativa
        self.assertFalse(adaptadores.ativar("token-siri"))
        self.assertFalse(adaptadores.buscar_por_id("siri")["ativo"])

        # Ativar com id funciona
        self.assertTrue(adaptadores.ativar("siri"))
        adaptador_reativado = adaptadores.buscar_por_id("siri")
        self.assertTrue(adaptador_reativado["ativo"])
        self.assertIn("reativado_em", adaptador_reativado)

    def test_remover_estrito_por_id(self):
        adaptadores.cadastrar("siri", "Siri", token="token-siri")
        self.assertFalse(adaptadores.remover("token-siri"))
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

    def test_sanitizacao_log_quebras_de_linha_e_tabs(self):
        adaptadores.registrar_log(
            "siri",
            "linha 1\nlinha 2\r\nlinha 3\tcom tab",
            intencao="comando",
            status_http=200,
            detalhe="detalhe\ncom\tquebra",
        )
        conteudo = adaptadores.ARQUIVO_LOG.read_text(encoding="utf-8")
        linhas = conteudo.strip().split("\n")
        self.assertEqual(len(linhas), 1)
        self.assertIn("linha 1\\nlinha 2 linha 3\\tcom tab", linhas[0])
        self.assertIn("detalhe\\ncom\\tquebra", linhas[0])
        self.assertNotIn("\r", conteudo)

    def test_sanitizacao_log_truncamento_120_caracteres(self):
        texto_longo = "X" * 200
        adaptadores.registrar_log("siri", texto_longo, status_http=200)
        logs = adaptadores.ler_logs(limite=1)
        self.assertEqual(len(logs[0]["texto"]), 120)
        self.assertEqual(logs[0]["texto"], "X" * 120)

    def test_respeito_variavel_ambiente_nextor_log_assistentes(self):
        with mock.patch.dict(os.environ, {"NEXTOR_LOG_ASSISTENTES": "0"}):
            adaptadores.registrar_log("siri", "deve ser ignorado", status_http=200)
        self.assertFalse(adaptadores.ARQUIVO_LOG.exists())
        self.assertEqual(len(adaptadores.ler_logs()), 0)

    def test_respeito_variavel_ambiente_nextor_log_texto_nao(self):
        with mock.patch.dict(os.environ, {"NEXTOR_LOG_TEXTO": "nao"}):
            adaptadores.registrar_log("siri", "texto estritamente privado", intencao="privada", status_http=200)
        logs = adaptadores.ler_logs(limite=1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["texto"], "")
        self.assertEqual(logs[0]["adaptador"], "siri")
        self.assertEqual(logs[0]["intencao"], "privada")


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

    def test_chamada_registra_log_sanitizado(self):
        with mock.patch("nextor.servico.rotear", return_value={"resposta": "resp", "intencao": "tempo"}):
            self.client.post(
                "/v1/assistente",
                json={"texto": "vai chover hoje?\nOu amanha?"},
                headers={"Authorization": "Bearer token-siri-valido"},
            )
        logs = adaptadores.ler_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["adaptador"], "siri")
        self.assertEqual(logs[0]["intencao"], "tempo")
        self.assertEqual(logs[0]["texto"], "vai chover hoje?\\nOu amanha?")
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
        # Token puro retornado na criacao
        self.assertTrue(cad_dados["adaptador"]["token"].startswith("nxt_"))

        # Listagem padrao mascara: sem token puro e sem token_hash
        list_resp = self.client.get("/v1/assistente/adaptadores", headers=self.h_mestre)
        self.assertEqual(list_resp.status_code, 200)
        itens = list_resp.get_json()["adaptadores"]
        self.assertEqual(len(itens), 1)
        self.assertIn("...", itens[0]["prefixo"])
        self.assertNotIn("token", itens[0])
        self.assertNotIn("token_hash", itens[0])

        # Listagem com revelar=1 exibe token_hash, mas nunca o token puro
        rev_resp = self.client.get("/v1/assistente/adaptadores?revelar=1", headers=self.h_mestre)
        self.assertEqual(rev_resp.status_code, 200)
        itens_rev = rev_resp.get_json()["adaptadores"]
        self.assertIn("token_hash", itens_rev[0])
        self.assertNotIn("token", itens_rev[0])

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
