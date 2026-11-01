"""Testes da voz no PC (motores, idiomas, audio servido) e do ouvinte. Sem som, sem rede, sem microfone."""
import io
import os
import unittest
import wave
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"  # testes nunca tocam audio

from nextor import config, fala, servico  # noqa: E402
from nextor.companheiro import companheiro, conversar_com_humor  # noqa: E402
from nextor.ouvinte import Escuta  # noqa: E402


def wav_de(segundos: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * segundos))
    return buf.getvalue()


class TestMotores(unittest.TestCase):
    def test_cai_para_o_proximo_motor(self):
        with mock.patch.dict(fala.MOTORES, {
            "piper": mock.Mock(side_effect=FileNotFoundError("sem voz")),
            "sapi": mock.Mock(return_value=(b"wav", "audio/wav")),
            "gtts": mock.Mock(),
        }):
            dados, mime, motor = fala.sintetizar("oi", "pt-BR")
        self.assertEqual((dados, mime, motor), (b"wav", "audio/wav", "sapi"))

    def test_motor_escolhido_no_env(self):
        gtts = mock.Mock(return_value=(b"mp3", "audio/mpeg"))
        with mock.patch.dict(os.environ, {"NEXTOR_VOZ_MOTOR": "gtts"}), mock.patch.dict(fala.MOTORES, {"gtts": gtts}):
            self.assertEqual(fala.sintetizar("hello", "en-US")[2], "gtts")
        gtts.assert_called_once_with("hello", "en-US")

    def test_idioma_desconhecido_vira_portugues(self):
        piper = mock.Mock(return_value=(b"x", "audio/wav"))
        with mock.patch.dict(fala.MOTORES, {"piper": piper}):
            fala.sintetizar("oi", "de-DE")
        piper.assert_called_once_with("oi", "pt-BR")

    def test_voz_piper_configuravel(self):
        self.assertEqual(fala.voz_piper("fr-FR"), "fr_FR-siwis-medium")
        with mock.patch.dict(os.environ, {"NEXTOR_VOZ_PT_BR": "pt_BR-edresson-low"}):
            self.assertEqual(fala.voz_piper("pt-BR"), "pt_BR-edresson-low")

    def test_duracao(self):
        self.assertAlmostEqual(fala.duracao(wav_de(2.0), "audio/wav", "x"), 2.0, places=2)
        self.assertGreaterEqual(fala.duracao(b"mp3", "audio/mpeg", "texto curto"), 1.5)

    def test_guarda_so_os_ultimos(self):
        ids = [fala.guardar(b"a", "audio/wav") for _ in range(fala.MAX_AUDIOS + 3)]
        self.assertIsNone(fala.pegar(ids[0]))
        self.assertEqual(fala.pegar(ids[-1]), (b"a", "audio/wav"))


class TestIdioma(unittest.TestCase):
    def tearDown(self):
        companheiro.definir_idioma("pt-BR")

    def test_cerebro_responde_no_idioma(self):
        companheiro.definir_idioma("es-ES")
        recebido = []
        conversar_com_humor("hola", lambda t: recebido.append(t) or "Hola!")
        self.assertIn("espanol", recebido[0])
        with self.assertRaises(ValueError):
            companheiro.definir_idioma("klingon")


class TestRotasVoz(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(config, "TOKEN", "segredo")
        self.p.start()
        self.c = servico.app.test_client()
        self.h = {"X-Nextor-Token": "segredo"}

    def tearDown(self):
        self.p.stop()
        companheiro.definir_idioma("pt-BR")

    def test_trocar_idioma(self):
        r = self.c.post("/voz", json={"idioma": "fr-FR"}, headers=self.h)
        self.assertEqual(r.get_json()["idioma"], "fr-FR")
        self.assertIn("en-US", r.get_json()["idiomas"])
        self.assertEqual(self.c.post("/voz", json={"idioma": "xx"}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.get("/voz").status_code, 401)

    def test_fala_vai_para_a_tela_quando_ha_rosto_aberto(self):
        fila = companheiro.assinar()
        try:
            with mock.patch.dict(os.environ, {"NEXTOR_VOZ_SAIDA": "pc"}), \
                    mock.patch.object(fala, "sintetizar", return_value=(wav_de(0.2), "audio/wav", "piper")), \
                    mock.patch.object(servico, "conversar", lambda t: "Oi!"):
                r = self.c.post("/conversa", json={"texto": "oi", "falar": True}, headers=self.h)
            self.assertIsNone(r.get_json()["aviso"])
            fala_id = companheiro.ver()["fala"]["id"]
            audio = self.c.get(f"/fala/{fala_id}", headers=self.h)
            self.assertEqual(audio.status_code, 200)
            self.assertEqual(audio.mimetype, "audio/wav")
            self.assertEqual(self.c.get(f"/fala/{fala_id}").status_code, 401)
        finally:
            companheiro.cancelar(fila)

    def test_sem_voz_vira_aviso(self):
        with mock.patch.dict(os.environ, {"NEXTOR_VOZ_SAIDA": "pc"}), \
                mock.patch.object(fala, "sintetizar", side_effect=RuntimeError("nada")), \
                mock.patch.object(servico, "conversar", lambda t: "Oi!"):
            r = self.c.post("/conversa", json={"texto": "oi", "falar": True}, headers=self.h)
        self.assertIn("Sem voz no PC", r.get_json()["aviso"])


class TestEscuta(unittest.TestCase):
    def test_chamado_com_comando(self):
        e = Escuta(janela=8)
        self.assertEqual(e.decidir("ei nextor modo leitura", agora=0), "ei nextor modo leitura")

    def test_chamado_e_depois_o_comando(self):
        e = Escuta(janela=8)
        self.assertEqual(e.decidir("fala nextor", agora=0), "fala nextor")
        self.assertEqual(e.decidir("o que tenho hoje", agora=5), "o que tenho hoje")
        self.assertIsNone(e.decidir("outra conversa na sala", agora=6))

    def test_janela_expira(self):
        e = Escuta(janela=8)
        e.decidir("ei nextor", agora=0)
        self.assertIsNone(e.decidir("o que tenho hoje", agora=9))

    def test_ignora_conversa_sem_chamado(self):
        self.assertIsNone(Escuta().decidir("vamos jantar fora hoje"))
        self.assertIsNone(Escuta().decidir(""))


if __name__ == "__main__":
    unittest.main()
