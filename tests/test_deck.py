"""Testes da ponte com o NexDeck, sem rede (urlopen e simulado)."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from nextor import config, deck, roteador

DECK = {"pages": [{"name": "Midia", "buttons": [
    {"id": "play", "label": "Play/Pause"},
    {"id": "vol_up", "label": "Vol +"},
    {"id": "lock", "label": "Bloquear"},
    {"id": "shutdown", "label": "Desligar"},
]}]}


class Resposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def falso_urlopen(chamadas, erro_em=None):
    def abrir(req, timeout=0):
        chamadas.append((req.get_method(), req.full_url, req.get_header("Authorization")))
        if erro_em and erro_em in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 409, "confirm", {}, None)
        corpo = DECK if req.get_method() == "GET" else {"ok": True}
        return Resposta(json.dumps(corpo).encode())
    return abrir


class TestDeck(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(config, DECK_URL="http://pc:3210", DECK_TOKEN="tk")
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_acha_por_nome_sem_acento_e_simbolos(self):
        botoes = DECK["pages"][0]["buttons"]
        self.assertEqual(deck.achar("bloquear", botoes)["id"], "lock")
        self.assertEqual(deck.achar("vol mais", botoes)["id"], "vol_up")
        self.assertEqual(deck.achar("play", botoes)["id"], "play")
        self.assertIsNone(deck.achar("formatar disco", botoes))

    def test_aperta_com_token(self):
        chamadas = []
        with mock.patch("urllib.request.urlopen", falso_urlopen(chamadas)):
            self.assertEqual(deck.apertar("bloquear"), "Feito: Bloquear.")
        self.assertEqual(chamadas[-1], ("POST", "http://pc:3210/api/buttons/lock/run", "Bearer tk"))

    def test_acao_com_confirmacao_nao_roda_por_voz(self):
        with mock.patch("urllib.request.urlopen", falso_urlopen([], erro_em="/shutdown/")):
            self.assertIn("confirmacao", deck.apertar("desligar"))

    def test_sem_configuracao(self):
        with mock.patch.multiple(config, DECK_URL="", DECK_TOKEN=""):
            self.assertIn("nao esta configurado", deck.apertar("play"))

    def test_roteador_reconhece_gatilho(self):
        chamadas = []
        with mock.patch("urllib.request.urlopen", falso_urlopen(chamadas)), \
                mock.patch.object(roteador, "_registra"):
            r = roteador.rotear("Nextor, no computador, bloquear")
        self.assertEqual(r["intencao"], "deck")
        self.assertEqual(r["resposta"], "Feito: Bloquear.")


if __name__ == "__main__":
    unittest.main()
