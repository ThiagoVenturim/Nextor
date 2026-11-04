"""Testes unitarios offline de seguranca da plataforma Nextor (issue #27).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Cobre:
1) validar_token_mestre recusa 'troque-este-token' e tokens menores que 24 caracteres,
   e exigir_token_mestre_valido dispara SystemExit com instrucoes de geracao;
2) autorizado() compara tokens mestre usando hmac.compare_digest em tempo constante;
3) gerar_url_pareamento usa fragmento #token= (em vez de ?token=) e a pagina le o fragmento,
   guarda em storage e limpa a URL;
4) em /comando e /v1/assistente, chamadas com token de aparelho forcam id_dispositivo a ser
   sempre o dono do token (ignorando dispositivo no corpo/query se divergir).
"""
import hmac
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config, dispositivos, roteador, servico


class TestValidacaoTokenMestre(unittest.TestCase):
    def test_recusa_token_padrao_inseguro(self):
        self.assertFalse(servico.validar_token_mestre(servico.TOKEN_PADRAO_INVALIDO))
        self.assertFalse(servico.validar_token_mestre("troque-este-token"))

    def test_recusa_tokens_menores_que_24_caracteres(self):
        self.assertFalse(servico.validar_token_mestre(""))
        self.assertFalse(servico.validar_token_mestre("12345678901234567890123"))  # 23 chars
        self.assertFalse(servico.validar_token_mestre("curto"))

    def test_aceita_token_com_24_ou_mais_caracteres(self):
        self.assertTrue(servico.validar_token_mestre("123456789012345678901234"))  # 24 chars
        self.assertTrue(servico.validar_token_mestre("nxt_mestre_super_seguro_e_longo_123456789"))

    def test_usa_config_token_por_padrao(self):
        with mock.patch.object(config, "TOKEN", "troque-este-token"):
            self.assertFalse(servico.validar_token_mestre())

        with mock.patch.object(config, "TOKEN", "nxt_token_valido_com_mais_de_24_chars_seguro"):
            self.assertTrue(servico.validar_token_mestre())

    def test_exigir_token_mestre_valido_dispara_system_exit_com_instrucoes(self):
        with mock.patch.object(config, "TOKEN", "troque-este-token"):
            with self.assertRaises(SystemExit) as ctx:
                servico.exigir_token_mestre_valido()
            msg = str(ctx.exception)
            self.assertIn("NEXTOR_TOKEN", msg)
            self.assertIn("secrets.token_urlsafe(24)", msg)
            self.assertIn("troque-este-token", msg)

        with mock.patch.object(config, "TOKEN", "token-curto"):
            with self.assertRaises(SystemExit):
                servico.exigir_token_mestre_valido()

        # Token valido nao deve disparar excecao
        with mock.patch.object(config, "TOKEN", "nxt_token_valido_com_mais_de_24_chars_seguro"):
            try:
                servico.exigir_token_mestre_valido()
            except SystemExit:
                self.fail("exigir_token_mestre_valido nao deveria disparar SystemExit com token valido")


class TestAutorizadoHMAC(unittest.TestCase):
    def setUp(self):
        self.token_mestre = "nxt_mestre_seguro_123456789012345"
        self.patch_token = mock.patch.object(config, "TOKEN", self.token_mestre)
        self.patch_token.start()
        self.client = servico.app.test_client()

    def tearDown(self):
        self.patch_token.stop()

    def test_autorizado_com_token_mestre_correto(self):
        with servico.app.test_request_context(headers={"X-Nextor-Token": self.token_mestre}):
            self.assertTrue(servico.autorizado())

        with servico.app.test_request_context(headers={"Authorization": f"Bearer {self.token_mestre}"}):
            self.assertTrue(servico.autorizado())

        with servico.app.test_request_context(query_string={"token": self.token_mestre}):
            self.assertTrue(servico.autorizado())

    def test_autorizado_rejeita_token_incorreto_mesmo_tamanho(self):
        token_errado = self.token_mestre[:-1] + ("x" if self.token_mestre[-1] != "x" else "y")
        self.assertEqual(len(token_errado), len(self.token_mestre))

        with servico.app.test_request_context(headers={"X-Nextor-Token": token_errado}):
            self.assertFalse(servico.autorizado())

    def test_autorizado_rejeita_token_vazio_ou_ausente(self):
        with servico.app.test_request_context():
            self.assertFalse(servico.autorizado())

        with servico.app.test_request_context(headers={"X-Nextor-Token": ""}):
            self.assertFalse(servico.autorizado())

    def test_autorizado_usa_hmac_compare_digest(self):
        with mock.patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as mock_hmac:
            with servico.app.test_request_context(headers={"X-Nextor-Token": self.token_mestre}):
                self.assertTrue(servico.autorizado())
                mock_hmac.assert_called_once_with(self.token_mestre, self.token_mestre)


class TestPareamentoFragmentoEStorage(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_tmp = Path(self.tmp_dir.name)
        self.patch_arq = mock.patch.object(dispositivos, "ARQUIVO", self.caminho_tmp / "dispositivos.json")
        self.patch_arq.start()
        dispositivos.resetar_estado_testes()
        self.client = servico.app.test_client()

    def tearDown(self):
        dispositivos.resetar_estado_testes()
        self.patch_arq.stop()
        self.tmp_dir.cleanup()

    def test_gerar_url_pareamento_usa_fragmento_hash(self):
        disp = dispositivos.cadastrar("tv-sala", "TV da Sala", tipo="tv")
        url = dispositivos.gerar_url_pareamento("tv-sala", token_puro=disp["token"], host="192.168.1.100", porta=5005)

        # O token puro deve estar no fragmento (#token=), nao na query (?token=)
        self.assertIn("?id=tv-sala#token=", url)
        self.assertNotIn("?token=", url)
        self.assertNotIn("&token=", url)
        self.assertTrue(url.endswith(f"#token={disp['token']}"))

    def test_pagina_conectar_le_fragmento_salva_storage_e_limpa_url(self):
        disp = dispositivos.cadastrar("tv-display", "TV Display", tipo="tv")
        resp = self.client.get(f"/dispositivo/conectar?id={disp['id']}")

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Verifica presenca do script de leitura do hash
        self.assertIn("window.location.hash", html)
        self.assertIn("sessionStorage.setItem('nextor_disp_' + id, tk)", html)
        self.assertIn("history.replaceState", html)
        self.assertIn("/v1/dispositivos/", html)


class TestForcarIdDispositivoDonoDoToken(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_tmp = Path(self.tmp_dir.name)
        self.patch_arq = mock.patch.object(dispositivos, "ARQUIVO", self.caminho_tmp / "dispositivos.json")
        self.patch_token = mock.patch.object(config, "TOKEN", "nxt_token_mestre_super_longo_123456")
        self.patch_arq.start()
        self.patch_token.start()
        dispositivos.resetar_estado_testes()
        self.client = servico.app.test_client()

    def tearDown(self):
        dispositivos.resetar_estado_testes()
        self.patch_arq.stop()
        self.patch_token.stop()
        self.tmp_dir.cleanup()

    def test_comando_forca_id_dispositivo_do_token_mesmo_se_divergir_no_payload(self):
        # TV so visualiza (sem permissao 'executar'); PC tem permissao 'executar'
        tv = dispositivos.cadastrar("tv-sala", "TV Sala", tipo="tv")
        pc = dispositivos.cadastrar("pc-escritorio", "PC Escritorio", tipo="pc")

        with mock.patch.object(servico, "_falar_sem_quebrar", return_value=""), \
                mock.patch("nextor.roteador._registra"):
            # A TV envia token proprio, mas tenta forjar 'dispositivo: pc-escritorio' no corpo
            resp = self.client.post(
                "/comando",
                json={"texto": "no pc, bloquear", "dispositivo": "pc-escritorio"},
                headers={"Authorization": f"Bearer {tv['token']}"},
            )

        self.assertEqual(resp.status_code, 200)
        dados = resp.get_json()
        # Como o servico forcou id_dispositivo = 'tv-sala' (dono do token),
        # a acao deck foi negada por falta de permissao da TV!
        self.assertIn("nao tem permissao", dados["resposta"])

    def test_assistente_forca_id_dispositivo_do_token(self):
        tv = dispositivos.cadastrar("tv-quarto", "TV Quarto", tipo="tv")
        # Adaptador para /v1/assistente
        from nextor import adaptadores
        with mock.patch.object(adaptadores, "ARQUIVO", self.caminho_tmp / "adaptadores.json"):
            adaptador = adaptadores.cadastrar("siri", "Siri Apple", token="token-siri-123")

            # Quando chamado com token de TV no X-Nextor-Token e token de adaptador via param
            with mock.patch("nextor.roteador._registra"):
                resp = self.client.post(
                    f"/v1/assistente?token={adaptador['token']}",
                    json={"texto": "no pc, bloquear", "dispositivo": "pc-inexistente"},
                    headers={"X-Nextor-Token": tv["token"]},
                )

            self.assertEqual(resp.status_code, 200)
            # A acao foi negada porque o id_dispositivo forçado foi tv-quarto
            self.assertIn("nao tem permissao", resp.get_json()["resposta"])


if __name__ == "__main__":
    unittest.main()
