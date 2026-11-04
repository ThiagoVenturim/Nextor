"""Testes unitarios offline do adaptador da Alexa (issue #9).

Sem rede, sem hardware real, sem audio, sem chamada externa.
Cobre:
1) validar_url_certificado (protocolo, host, porta, prefixo de caminho, path traversal);
2) validar_certificado (SAN/CN echo-api.amazon.com, vigencia temporal);
3) validar_timestamp (tolerancia 150s, expirado, formato invalido);
4) validar_assinatura_requisicao (assinatura RSA/SHA-1 em memoria, adulteracao, b64 corrompido);
5) validar_application_id (session, context, hmac em tempo constante, divergencia);
6) processar_requisicao_alexa (LaunchRequest, HelpIntent, CancelIntent, ComandoLivreIntent, SessionEndedRequest);
7) endpoint /v1/alexa no Flask (payload invalido, cabecalhos ausentes, 200 de sucesso, token opcional).
"""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import alexa_skill, config, servico


def _gerar_chave_rsa():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _gerar_cert_x509(
    chave_privada,
    san_dns=None,
    common_name="echo-api.amazon.com",
    not_before=None,
    not_after=None,
):
    agora = datetime.now(timezone.utc)
    nb = not_before or (agora - timedelta(days=1))
    na = not_after or (agora + timedelta(days=365))
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(chave_privada.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nb)
        .not_valid_after(na)
    )
    if san_dns is not None:
        names = [x509.DNSName(d) for d in san_dns]
        builder = builder.add_extension(
            x509.SubjectAlternativeName(names),
            critical=False,
        )
    return builder.sign(chave_privada, hashes.SHA256())


class TestValidarUrlCertificado(unittest.TestCase):
    def test_url_valida_padrao(self):
        url = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"
        self.assertTrue(alexa_skill.validar_url_certificado(url))

    def test_url_valida_com_porta_443(self):
        url = "https://s3.amazonaws.com:443/echo.api/echo-api-cert-8.pem"
        self.assertTrue(alexa_skill.validar_url_certificado(url))

    def test_url_case_insensitive_esquema_e_host(self):
        url = "HTTPS://S3.AMAZONAWS.COM/echo.api/cert.pem"
        self.assertTrue(alexa_skill.validar_url_certificado(url))

    def test_rejeita_esquema_http(self):
        url = "http://s3.amazonaws.com/echo.api/echo-api-cert.pem"
        self.assertFalse(alexa_skill.validar_url_certificado(url))

    def test_rejeita_host_incorreto(self):
        urls = [
            "https://malicioso.com/echo.api/cert.pem",
            "https://s3.amazonaws.com.br/echo.api/cert.pem",
            "https://s3.amazonaws.com.evil.com/echo.api/cert.pem",
            "https://amazonaws.com/echo.api/cert.pem",
        ]
        for u in urls:
            with self.subTest(url=u):
                self.assertFalse(alexa_skill.validar_url_certificado(u))

    def test_rejeita_porta_diferente_de_443(self):
        url = "https://s3.amazonaws.com:8443/echo.api/cert.pem"
        self.assertFalse(alexa_skill.validar_url_certificado(url))

    def test_rejeita_caminho_que_nao_inicia_com_echo_api(self):
        urls = [
            "https://s3.amazonaws.com/outra_pasta/cert.pem",
            "https://s3.amazonaws.com/Echo.api/cert.pem",  # case-sensitive
            "https://s3.amazonaws.com/echo.api",  # sem barra final
        ]
        for u in urls:
            with self.subTest(url=u):
                self.assertFalse(alexa_skill.validar_url_certificado(u))

    def test_rejeita_path_traversal(self):
        urls = [
            "https://s3.amazonaws.com/echo.api/../hack.pem",
            "https://s3.amazonaws.com/echo.api/pasta/../../hack.pem",
            "https://s3.amazonaws.com/echo.api/..",
        ]
        for u in urls:
            with self.subTest(url=u):
                self.assertFalse(alexa_skill.validar_url_certificado(u))

    def test_rejeita_valores_nulos_ou_vazios(self):
        self.assertFalse(alexa_skill.validar_url_certificado(""))
        self.assertFalse(alexa_skill.validar_url_certificado(None))
        self.assertFalse(alexa_skill.validar_url_certificado(12345))


class TestValidarCertificado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chave = _gerar_chave_rsa()

    def test_certificado_valido_com_san_echo_api(self):
        cert = _gerar_cert_x509(self.chave, san_dns=["echo-api.amazon.com"])
        self.assertTrue(alexa_skill.validar_certificado(cert))

    def test_certificado_valido_com_cn_fallback_sem_san(self):
        cert = _gerar_cert_x509(self.chave, san_dns=None, common_name="echo-api.amazon.com")
        self.assertTrue(alexa_skill.validar_certificado(cert))

    def test_rejeita_certificado_sem_echo_api_no_san_nem_cn(self):
        cert = _gerar_cert_x509(self.chave, san_dns=["outro.amazon.com"], common_name="outro.amazon.com")
        self.assertFalse(alexa_skill.validar_certificado(cert))

    def test_rejeita_certificado_expirado(self):
        agora = datetime.now(timezone.utc)
        cert = _gerar_cert_x509(
            self.chave,
            san_dns=["echo-api.amazon.com"],
            not_before=agora - timedelta(days=10),
            not_after=agora - timedelta(days=1),
        )
        self.assertFalse(alexa_skill.validar_certificado(cert, agora=agora))

    def test_rejeita_certificado_ainda_nao_vigente(self):
        agora = datetime.now(timezone.utc)
        cert = _gerar_cert_x509(
            self.chave,
            san_dns=["echo-api.amazon.com"],
            not_before=agora + timedelta(days=1),
            not_after=agora + timedelta(days=30),
        )
        self.assertFalse(alexa_skill.validar_certificado(cert, agora=agora))


class TestValidarTimestamp(unittest.TestCase):
    def test_timestamp_dentro_tolerancia_150_segundos(self):
        agora = datetime.now(timezone.utc)
        ts_30s_atras = (agora - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        self.assertTrue(alexa_skill.validar_timestamp(ts_30s_atras, agora=agora))

        ts_exatos_150s = (agora - timedelta(seconds=150)).isoformat().replace("+00:00", "Z")
        self.assertTrue(alexa_skill.validar_timestamp(ts_exatos_150s, agora=agora))

        # Aceita pequeno drift no futuro (ex: 20s)
        ts_futuro = (agora + timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
        self.assertTrue(alexa_skill.validar_timestamp(ts_futuro, agora=agora))

    def test_rejeita_timestamp_expirado_maior_que_150_segundos(self):
        agora = datetime.now(timezone.utc)
        ts_151s = (agora - timedelta(seconds=151)).isoformat().replace("+00:00", "Z")
        self.assertFalse(alexa_skill.validar_timestamp(ts_151s, agora=agora))

        ts_antigo = (agora - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        self.assertFalse(alexa_skill.validar_timestamp(ts_antigo, agora=agora))

    def test_rejeita_timestamp_invalido_ou_vazio(self):
        self.assertFalse(alexa_skill.validar_timestamp(""))
        self.assertFalse(alexa_skill.validar_timestamp("nao_e_iso"))
        self.assertFalse(alexa_skill.validar_timestamp(None))
        self.assertFalse(alexa_skill.validar_timestamp(12345678))


class TestValidarAssinaturaRequisicao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chave = _gerar_chave_rsa()
        cls.cert = _gerar_cert_x509(cls.chave, san_dns=["echo-api.amazon.com"])
        cls.cert_pem = cls.cert.public_bytes(Encoding.PEM)
        cls.cert_url = "https://s3.amazonaws.com/echo.api/echo-api-cert-1.pem"

    def setUp(self):
        alexa_skill.limpar_cache_certificados()

    def test_assinatura_valida_rsa_sha1(self):
        corpo = b'{"request":{"type":"LaunchRequest"}}'
        sig_raw = self.chave.sign(corpo, padding.PKCS1v15(), hashes.SHA1())
        sig_b64 = base64.b64encode(sig_raw).decode("utf-8")

        sucesso, erro = alexa_skill.validar_assinatura_requisicao(
            raw_body=corpo,
            signature_b64=sig_b64,
            cert_url=self.cert_url,
            baixador_cert=lambda u: self.cert_pem,
        )
        self.assertTrue(sucesso)
        self.assertEqual(erro, "")

    def test_assinatura_valida_rsa_sha256(self):
        corpo = b'{"request":{"type":"IntentRequest"}}'
        sig_raw = self.chave.sign(corpo, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.b64encode(sig_raw).decode("utf-8")

        sucesso, erro = alexa_skill.validar_assinatura_requisicao(
            raw_body=corpo,
            signature_b64=sig_b64,
            cert_url=self.cert_url,
            baixador_cert=lambda u: self.cert_pem,
        )
        self.assertTrue(sucesso)
        self.assertEqual(erro, "")

    def test_rejeita_corpo_adulterado(self):
        corpo_original = b'{"request":{"type":"LaunchRequest"}}'
        corpo_adulterado = b'{"request":{"type":"LaunchRequest","hacked":true}}'
        sig_raw = self.chave.sign(corpo_original, padding.PKCS1v15(), hashes.SHA1())
        sig_b64 = base64.b64encode(sig_raw).decode("utf-8")

        sucesso, erro = alexa_skill.validar_assinatura_requisicao(
            raw_body=corpo_adulterado,
            signature_b64=sig_b64,
            cert_url=self.cert_url,
            baixador_cert=lambda u: self.cert_pem,
        )
        self.assertFalse(sucesso)
        self.assertEqual(erro, "falha_verificacao_assinatura")

    def test_rejeita_assinatura_base64_corrompida(self):
        sucesso, erro = alexa_skill.validar_assinatura_requisicao(
            raw_body=b"payload",
            signature_b64="a",  # Comprimento invalido para base64 dispara erro de decodificacao
            cert_url=self.cert_url,
            baixador_cert=lambda u: self.cert_pem,
        )
        self.assertFalse(sucesso)
        self.assertEqual(erro, "assinatura_base64_invalida")

    def test_rejeita_url_certificado_invalida(self):
        sucesso, erro = alexa_skill.validar_assinatura_requisicao(
            raw_body=b"payload",
            signature_b64="c2lnbmF0dXJl",
            cert_url="http://inseguro.com/cert.pem",
            baixador_cert=lambda u: self.cert_pem,
        )
        self.assertFalse(sucesso)
        self.assertEqual(erro, "url_certificado_invalida")

    def test_rejeita_quando_certificado_expirado(self):
        agora = datetime.now(timezone.utc)
        cert_expirado = _gerar_cert_x509(
            self.chave,
            san_dns=["echo-api.amazon.com"],
            not_before=agora - timedelta(days=20),
            not_after=agora - timedelta(days=5),
        )
        pem_exp = cert_expirado.public_bytes(Encoding.PEM)

        sucesso, erro = alexa_skill.validar_assinatura_requisicao(
            raw_body=b"payload",
            signature_b64="c2lnbmF0dXJl",
            cert_url=self.cert_url,
            agora=agora,
            baixador_cert=lambda u: pem_exp,
        )
        self.assertFalse(sucesso)
        self.assertEqual(erro, "certificado_invalido_ou_expirado")


class TestValidarApplicationId(unittest.TestCase):
    def test_extrai_e_valida_de_session(self):
        dados = {
            "session": {
                "application": {
                    "applicationId": "amzn1.ask.skill.12345678-abcd-1234-abcd-1234567890ab"
                }
            }
        }
        self.assertTrue(alexa_skill.validar_application_id(dados, app_id_esperado="amzn1.ask.skill.12345678-abcd-1234-abcd-1234567890ab"))
        self.assertFalse(alexa_skill.validar_application_id(dados, app_id_esperado="amzn1.ask.skill.outro-id"))

    def test_extrai_e_valida_de_context(self):
        dados = {
            "context": {
                "System": {
                    "application": {
                        "applicationId": "amzn1.ask.skill.context-123"
                    }
                }
            }
        }
        self.assertTrue(alexa_skill.validar_application_id(dados, app_id_esperado="amzn1.ask.skill.context-123"))

    def test_rejeita_quando_esperado_mas_ausente_na_requisicao(self):
        dados = {"session": {}}
        self.assertFalse(alexa_skill.validar_application_id(dados, app_id_esperado="amzn1.ask.skill.obrigatorio"))

    def test_permite_quando_nao_configurado_esperado_vazio(self):
        dados = {"session": {"application": {"applicationId": "qualquer"}}}
        self.assertTrue(alexa_skill.validar_application_id(dados, app_id_esperado=""))


class TestProcessarRequisicaoAlexa(unittest.TestCase):
    def test_launch_request_saudacao_sessao_aberta(self):
        dados = {
            "request": {
                "type": "LaunchRequest",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        }
        resp, code = alexa_skill.processar_requisicao_alexa(dados, verificar_assinatura=False)
        self.assertEqual(code, 200)
        self.assertIn("response", resp)
        self.assertFalse(resp["response"]["shouldEndSession"])
        self.assertIn("pronto", resp["response"]["outputSpeech"]["text"])
        self.assertIn("reprompt", resp["response"])

    def test_amazon_help_intent(self):
        dados = {
            "request": {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.HelpIntent"},
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        }
        resp, code = alexa_skill.processar_requisicao_alexa(dados, verificar_assinatura=False)
        self.assertEqual(code, 200)
        self.assertFalse(resp["response"]["shouldEndSession"])
        self.assertIn("Como posso ajudar?", resp["response"]["outputSpeech"]["text"])

    def test_amazon_cancel_ou_stop_intent_encerra_sessao(self):
        dados = {
            "request": {
                "type": "IntentRequest",
                "intent": {"name": "AMAZON.CancelIntent"},
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        }
        resp, code = alexa_skill.processar_requisicao_alexa(dados, verificar_assinatura=False)
        self.assertEqual(code, 200)
        self.assertTrue(resp["response"]["shouldEndSession"])
        self.assertEqual(resp["response"]["outputSpeech"]["text"], "Ate logo.")

    def test_comando_livre_intent_com_slot_chama_assistente(self):
        dados = {
            "request": {
                "type": "IntentRequest",
                "intent": {
                    "name": "ComandoLivreIntent",
                    "slots": {
                        "comando": {"name": "comando", "value": "como esta o tempo hoje"}
                    },
                },
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        }
        with mock.patch("nextor.alexa_skill.chamar_assistente", return_value="Previsao de sol com 26 graus.") as mock_ast:
            resp, code = alexa_skill.processar_requisicao_alexa(dados, verificar_assinatura=False)
            self.assertEqual(code, 200)
            mock_ast.assert_called_once_with("como esta o tempo hoje")
            self.assertEqual(resp["response"]["outputSpeech"]["text"], "Previsao de sol com 26 graus.")
            self.assertTrue(resp["response"]["shouldEndSession"])

    def test_session_ended_request(self):
        dados = {
            "request": {
                "type": "SessionEndedRequest",
                "reason": "USER_INITIATED",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        }
        resp, code = alexa_skill.processar_requisicao_alexa(dados, verificar_assinatura=False)
        self.assertEqual(code, 200)
        self.assertTrue(resp["response"]["shouldEndSession"])
        self.assertEqual(resp["response"]["outputSpeech"]["text"], "")


class TestEndpointAlexaFlask(unittest.TestCase):
    def setUp(self):
        self.client = servico.app.test_client()

    def test_payload_invalido_retorna_400(self):
        resp = self.client.post("/v1/alexa", data="corpo_nao_json")
        self.assertEqual(resp.status_code, 400)
        dados = resp.get_json()
        self.assertFalse(dados["ok"])
        self.assertEqual(dados["erro"], "payload_invalido")

    def test_cabecalhos_ausentes_com_verificacao_assinatura_ativa(self):
        with mock.patch.dict(os.environ, {"ALEXA_VERIFICAR_ASSINATURA": "1"}):
            req_data = {
                "request": {
                    "type": "LaunchRequest",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            }
            resp = self.client.post("/v1/alexa", json=req_data)
            self.assertEqual(resp.status_code, 400)
            dados = resp.get_json()
            self.assertFalse(dados["ok"])
            self.assertEqual(dados["erro"], "cabecalhos_assinatura_ausentes")

    def test_requisicao_bem_sucedida_com_verificacao_desativada(self):
        with mock.patch.dict(os.environ, {"ALEXA_VERIFICAR_ASSINATURA": "0"}):
            req_data = {
                "request": {
                    "type": "LaunchRequest",
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            }
            resp = self.client.post("/v1/alexa", json=req_data)
            self.assertEqual(resp.status_code, 200)
            dados = resp.get_json()
            self.assertIn("response", dados)
            self.assertIn("outputSpeech", dados["response"])

    def test_validacao_opcional_token_adaptador(self):
        req_data = {
            "request": {
                "type": "LaunchRequest",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        }
        with mock.patch.dict(os.environ, {
            "ALEXA_VERIFICAR_ASSINATURA": "0",
            "ALEXA_ADAPTADOR_TOKEN": "token-secreto-alexa",
        }):
            # Sem token -> 401
            r_sem = self.client.post("/v1/alexa", json=req_data)
            self.assertEqual(r_sem.status_code, 401)
            self.assertEqual(r_sem.get_json()["erro"], "token_invalido")

            # Com token errado -> 401
            r_err = self.client.post("/v1/alexa", json=req_data, headers={"X-Nextor-Token": "token-falso"})
            self.assertEqual(r_err.status_code, 401)

            # Com header correto -> 200
            r_hdr = self.client.post("/v1/alexa", json=req_data, headers={"X-Nextor-Token": "token-secreto-alexa"})
            self.assertEqual(r_hdr.status_code, 200)

            # Com query param ?token= -> 200
            r_qry = self.client.post("/v1/alexa?token=token-secreto-alexa", json=req_data)
            self.assertEqual(r_qry.status_code, 200)


if __name__ == "__main__":
    unittest.main()
