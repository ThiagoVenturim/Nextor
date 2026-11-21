"""Testes unitarios offline do bot do Telegram (issue #10).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Cobre:
1) Filtro estrito por TELEGRAM_USUARIOS_AUTORIZADOS (autorizado, nao autorizado, fail-closed sem lista);
2) Despacho de texto para /v1/assistente;
3) Processamento de audio/voz com transcricao offline (mock);
4) Comandos do modo estudante (/quiz, /resumo e /anotar);
5) Endpoint /v1/telegram/webhook no servico HTTP.
"""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import adaptadores, config, servico, telegram_bot


class BaseTelegramTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.caminho_tmp = Path(self.tmp_dir.name)
        self.patch_arq = mock.patch.object(adaptadores, "ARQUIVO", self.caminho_tmp / "adaptadores.json")
        self.patch_log = mock.patch.object(adaptadores, "ARQUIVO_LOG", self.caminho_tmp / "assistentes.log")
        self.patch_arq.start()
        self.patch_log.start()
        adaptadores.resetar_estado_testes()
        self.client = servico.app.test_client()

    def tearDown(self):
        adaptadores.resetar_estado_testes()
        self.patch_arq.stop()
        self.patch_log.stop()
        self.tmp_dir.cleanup()


class TestFiltroUsuariosAutorizados(BaseTelegramTestCase):
    def test_parse_multiplos_separadores(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "123, 456; 789 101112"}):
            autorizados = telegram_bot.obter_usuarios_autorizados()
            self.assertEqual(autorizados, {"123", "456", "789", "101112"})

    def test_usuario_autorizado_sucesso(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "123456,78910"}):
            self.assertTrue(telegram_bot.usuario_autorizado(123456))
            self.assertTrue(telegram_bot.usuario_autorizado("123456"))
            self.assertTrue(telegram_bot.usuario_autorizado(" 78910 "))
            self.assertFalse(telegram_bot.usuario_autorizado(999999))
            self.assertFalse(telegram_bot.usuario_autorizado(None))

    def test_fail_closed_sem_lista_autorizada(self):
        # Sem variavel de ambiente e sem config -> ninguem autorizado
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": ""}), \
                mock.patch.object(config, "TELEGRAM_USUARIOS_AUTORIZADOS", ""):
            self.assertEqual(telegram_bot.obter_usuarios_autorizados(), set())
            self.assertFalse(telegram_bot.usuario_autorizado(123456))
            self.assertFalse(telegram_bot.usuario_autorizado("qualquer_id"))

    def test_processar_update_recusa_usuario_nao_autorizado(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "1001"}):
            update_intruso = {
                "message": {
                    "from": {"id": 9999},
                    "chat": {"id": 9999},
                    "text": "ola assistente",
                }
            }
            res = telegram_bot.processar_update(update_intruso, enviar_resposta=False)
            self.assertFalse(res["ok"])
            self.assertFalse(res["autorizado"])
            self.assertEqual(res["user_id"], 9999)
            self.assertIn("nao autorizado", res["resposta"])


class TestDespachoAssistente(BaseTelegramTestCase):
    def test_chamar_assistente_texto_vazio(self):
        self.assertEqual(telegram_bot.chamar_assistente("   "), "Texto vazio.")

    def test_chamar_assistente_sucesso_via_http(self):
        class MockHttpResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps({"ok": True, "resposta": "Hoje vai fazer 24 graus."}).encode("utf-8")

        with mock.patch("urllib.request.urlopen", return_value=MockHttpResponse()) as mock_url:
            resp = telegram_bot.chamar_assistente("previsao do tempo", token_adaptador="tk-teste")
            self.assertEqual(resp, "Hoje vai fazer 24 graus.")
            req = mock_url.call_args[0][0]
            self.assertEqual(req.get_header("Authorization"), "Bearer tk-teste")
            dados = json.loads(req.data.decode("utf-8"))
            self.assertEqual(dados["texto"], "previsao do tempo")

    def test_chamar_assistente_erro_http(self):
        class MockHttpError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__(
                    url="http://localhost:5005/v1/assistente",
                    code=401,
                    msg="Unauthorized",
                    hdrs={},
                    fp=io.BytesIO(json.dumps({"ok": False, "erro": "token de adaptador invalido"}).encode("utf-8")),
                )

        with mock.patch("urllib.request.urlopen", side_effect=MockHttpError()):
            resp = telegram_bot.chamar_assistente("comando qualquer", token_adaptador="tk-invalido")
            self.assertIn("Erro ao consultar assistente (401)", resp)
            self.assertIn("token de adaptador invalido", resp)

    def test_chamar_assistente_fallback_local(self):
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("Offline")), \
                mock.patch("nextor.roteador.rotear", return_value={"resposta": "Resposta local fallback"}):
            resp = telegram_bot.chamar_assistente("meu comando")
            self.assertEqual(resp, "Resposta local fallback")

    def test_processar_update_despacha_texto_para_assistente(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "123"}), \
                mock.patch("nextor.telegram_bot.chamar_assistente", return_value="Assistente respondeu com exito.") as mock_chamar:
            update = {
                "message": {
                    "from": {"id": 123},
                    "chat": {"id": 123},
                    "text": "quem descobriu o Brasil?",
                }
            }
            res = telegram_bot.processar_update(update, enviar_resposta=False)
            self.assertTrue(res["ok"])
            self.assertTrue(res["autorizado"])
            self.assertEqual(res["resposta"], "Assistente respondeu com exito.")
            mock_chamar.assert_called_once_with("quem descobriu o Brasil?")


class TestProcessamentoAudio(BaseTelegramTestCase):
    def test_processar_update_com_voz_transcrita(self):
        def baixador_fake(file_id, token):
            return b"fake_ogg_audio_bytes"

        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "42"}), \
                mock.patch("nextor.telegram_bot.transcrever_audio", return_value="tocar musica classica") as mock_transcrever, \
                mock.patch("nextor.telegram_bot.chamar_assistente", return_value="Tocando musica.") as mock_assistente:
            update = {
                "message": {
                    "from": {"id": 42},
                    "chat": {"id": 42},
                    "voice": {"file_id": "voz_12345"},
                }
            }
            res = telegram_bot.processar_update(
                update,
                enviar_resposta=False,
                baixador_audio=baixador_fake,
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["eh_audio"])
            self.assertEqual(res["texto_entrada"], "tocar musica classica")
            self.assertEqual(res["resposta"], "Tocando musica.")
            mock_transcrever.assert_called_once_with(b"fake_ogg_audio_bytes")
            mock_assistente.assert_called_once_with("tocar musica classica")

    def test_processar_update_audio_incompreensivel(self):
        def baixador_fake(file_id, token):
            return b"silencio_bytes"

        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "42"}), \
                mock.patch("nextor.telegram_bot.transcrever_audio", return_value=""):
            update = {
                "message": {
                    "from": {"id": 42},
                    "chat": {"id": 42},
                    "audio": {"file_id": "audio_mudo"},
                }
            }
            res = telegram_bot.processar_update(
                update,
                enviar_resposta=False,
                baixador_audio=baixador_fake,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["resposta"], "Nao consegui compreender o audio.")

    def test_transcrever_audio_arquivo_inexistente_retorna_vazio(self):
        self.assertEqual(telegram_bot.transcrever_audio(Path("arquivo_inexistente.wav")), "")


class TestComandosModoEstudante(BaseTelegramTestCase):
    def test_comando_quiz_sem_disciplina_orienta(self):
        with mock.patch("nextor.estudos.listar_disciplinas", return_value=[{"nome": "Constitucional", "slug": "constitucional"}]):
            resp = telegram_bot.tratar_comando("/quiz", "")
            self.assertIn("/quiz <disciplina>", resp)
            self.assertIn("Constitucional", resp)

    def test_comando_quiz_disciplina_inexistente(self):
        with mock.patch("nextor.estudos.listar_disciplinas", return_value=[{"nome": "Civil", "slug": "civil"}]):
            resp = telegram_bot.tratar_comando("/quiz", "Penal")
            self.assertIn("Penal", resp)
            self.assertIn("nao encontrada", resp)

    def test_comando_quiz_com_disciplina_valida(self):
        disc = [{"nome": "Direito Civil", "slug": "direito-civil"}]
        materiais = [{"titulo": "Contratos", "conteudo": "Principio da autonomia privada e boa-fe objetiva."}]
        with mock.patch("nextor.estudos.listar_disciplinas", return_value=disc), \
                mock.patch("nextor.estudos.listar_materiais", return_value=materiais), \
                mock.patch("nextor.cerebro.conversar", return_value="Questao 1: Qual o principio...\nA) Autonomia\nB) Ilicitude\nCorreta: A"):
            resp = telegram_bot.tratar_comando("/quiz", "direito-civil")
            self.assertIn("[Quiz - Direito Civil]", resp)
            self.assertIn("Questao 1", resp)

    def test_comando_resumo_geral_e_disciplina(self):
        with mock.patch("nextor.estudos.resumo_disciplinas", return_value="Voce tem 3 disciplinas.") as mock_geral:
            resp = telegram_bot.tratar_comando("/resumo", "")
            self.assertEqual(resp, "Voce tem 3 disciplinas.")
            mock_geral.assert_called_once()

        disc = [{"nome": "Processo Civil", "slug": "processo-civil"}]
        with mock.patch("nextor.estudos.listar_disciplinas", return_value=disc), \
                mock.patch("nextor.estudos.resumo_materiais", return_value="Resumo de Processo Civil") as mock_disc:
            resp = telegram_bot.tratar_comando("/resumo", "processo-civil")
            self.assertEqual(resp, "Resumo de Processo Civil")
            mock_disc.assert_called_once_with("Processo Civil")

    def test_comando_anotar(self):
        # Sem argumento
        self.assertIn("Uso: /anotar", telegram_bot.tratar_comando("/anotar", ""))

        # Com argumento despacha 'anota ...' para o assistente
        with mock.patch("nextor.telegram_bot.chamar_assistente", return_value="Nota salva com sucesso.") as mock_assistente:
            resp = telegram_bot.tratar_comando("/anotar", "estudar capitulo 5 amanha")
            self.assertEqual(resp, "Nota salva com sucesso.")
            mock_assistente.assert_called_once_with("anota estudar capitulo 5 amanha")

    def test_comando_start_e_ajuda(self):
        resp = telegram_bot.tratar_comando("/start")
        self.assertIn("Nextor no Telegram", resp)
        self.assertIn("/quiz", resp)
        self.assertIn("/resumo", resp)
        self.assertIn("/anotar", resp)


class TestWebhookTelegramEndpoint(BaseTelegramTestCase):
    def test_webhook_payload_invalido_retorna_400(self):
        resp = self.client.post("/v1/telegram/webhook", data="corpo_nao_json")
        self.assertEqual(resp.status_code, 400)
        dados = resp.get_json()
        self.assertFalse(dados["ok"])
        self.assertEqual(dados["erro"], "payload_invalido")

    def test_webhook_usuario_nao_autorizado_retorna_403(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "777"}):
            update_rejeitado = {
                "message": {
                    "from": {"id": 888},
                    "chat": {"id": 888},
                    "text": "mensagem secreta",
                }
            }
            resp = self.client.post("/v1/telegram/webhook", json=update_rejeitado)
            self.assertEqual(resp.status_code, 403)
            dados = resp.get_json()
            self.assertFalse(dados["ok"])
            self.assertFalse(dados["autorizado"])

    def test_webhook_usuario_autorizado_retorna_200(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_USUARIOS_AUTORIZADOS": "777"}), \
                mock.patch("nextor.telegram_bot.chamar_assistente", return_value="Resposta via webhook."):
            update_valido = {
                "message": {
                    "from": {"id": 777},
                    "chat": {"id": 777},
                    "text": "como vai?",
                }
            }
            resp = self.client.post("/v1/telegram/webhook", json=update_valido)
            self.assertEqual(resp.status_code, 200)
            dados = resp.get_json()
            self.assertTrue(dados["ok"])
            self.assertTrue(dados["autorizado"])
            self.assertEqual(dados["resposta"], "Resposta via webhook.")


if __name__ == "__main__":
    unittest.main()
