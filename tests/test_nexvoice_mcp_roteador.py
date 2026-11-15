"""Testes unitarios offline das ferramentas MCP e do roteador de voz para o NexVoice (Issue #56)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config
from nextor.mcp_server import (
    nexvoice_encerrar_sessao,
    nexvoice_exportar_legendas,
    nexvoice_iniciar_sessao,
    nexvoice_salvar_estudos,
    nexvoice_traduzir_trecho,
)
from nextor.nexvoice import ArmazenamentoNexVoice
from nextor.roteador import rotear


class TestNexVoiceMCPRoteador(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_nexvoice = self.base_path / "test_nexvoice.db"
        self.estudos_dir = self.base_path / "estudos"
        self.estudos_db = self.estudos_dir / "indice_estudos.db"

        self.patch_nv_db = mock.patch.object(config, "NEXVOICE_DB", self.db_nexvoice)
        self.patch_est_dir = mock.patch.object(config, "ESTUDOS_DIR", self.estudos_dir)
        self.patch_est_db = mock.patch.object(config, "ESTUDOS_DB", self.estudos_db)
        self.patch_nv_tts = mock.patch.object(config, "NEXVOICE_TTS_MOTOR", "stub")
        self.patch_nv_db.start()
        self.patch_est_dir.start()
        self.patch_est_db.start()
        self.patch_nv_tts.start()

    def tearDown(self):
        self.patch_nv_db.stop()
        self.patch_est_dir.stop()
        self.patch_est_db.stop()
        self.patch_nv_tts.stop()
        self.temp_dir.cleanup()

    def test_mcp_nexvoice_ferramentas_bidirecionais(self):
        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            resp_ini = nexvoice_iniciar_sessao(
                titulo="Reuniao de Arquitetura",
                modo="reuniao",
                fonte="reuniao",
                idioma_meu="pt-BR",
                idioma_outro="en-US",
                consentimento_confirmado=True,
                consentimento_participantes="Equipe Core",
            )
            self.assertIn("Sessao NexVoice iniciada", resp_ini)
            self.assertIn("Aviso obrigatorio de etica e privacidade", resp_ini)

            banco = ArmazenamentoNexVoice(self.db_nexvoice)
            sessoes = banco.listar_sessoes()
            self.assertEqual(len(sessoes), 1)
            sessao_id = sessoes[0].id

            # Interlocutor fala em ingles -> traduz para portugues
            resp_ent = nexvoice_traduzir_trecho(
                sessao_id=sessao_id,
                texto_fala="Hello everyone, welcome to the meeting",
                direcao="entrada",
                locutor="John",
            )
            self.assertIn("bem-vindos a reuniao", resp_ent.lower())

            # Usuario fala em portugues -> traduz para ingles
            resp_sai = nexvoice_traduzir_trecho(
                sessao_id=sessao_id,
                texto_fala="Eu concordo com a proposta tecnica",
                direcao="saida",
                locutor="eu",
            )
            self.assertIn("i agree with the technical proposal", resp_sai.lower())

            # Exportar legendas SRT
            srt = nexvoice_exportar_legendas(sessao_id=sessao_id, bilingue=True)
            self.assertIn("-->", srt)
            self.assertIn("[John]", srt)

            # Salvar nos estudos
            resp_est = nexvoice_salvar_estudos(sessao_id=sessao_id, disciplina="Engenharia de Software")
            self.assertIn("Engenharia de Software", resp_est)

            # Encerrar sessao com ata
            resp_fim = nexvoice_encerrar_sessao(sessao_id=sessao_id, gerar_ata=True)
            self.assertIn("encerrada (2 trechos)", resp_fim)
            self.assertIn("Resumo da ata:", resp_fim)

    def test_roteador_voz_nexvoice(self):
        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            # Tentativa de iniciar reuniao sem consentimento via voz avisa do bloqueio
            r_bloq = rotear("ei Nextor, traduzir reuniao no nexvoice: Alinhamento")
            self.assertEqual(r_bloq["intencao"], "nexvoice_iniciar")
            self.assertIn("consentimento", r_bloq["resposta"].lower())

            # Iniciar reuniao com consentimento confirmado
            r_ini = rotear("iniciar nexvoice em reuniao com consentimento: Alinhamento Semanal")
            self.assertEqual(r_ini["intencao"], "nexvoice_iniciar")
            self.assertIn("NexVoice iniciado no modo reuniao", r_ini["resposta"])

            # Ouvir fala do interlocutor
            r_ouv = rotear("nexvoice traduzir: Hello everyone, welcome to the meeting")
            self.assertEqual(r_ouv["intencao"], "nexvoice_traduzir_trecho")
            self.assertIn("en-US -> pt-BR", r_ouv["resposta"])

            # Falar na reuniao no meu idioma para sair no idioma da outra pessoa
            r_fal = rotear("nexvoice falar: Podemos comecar a apresentacao")
            self.assertEqual(r_fal["intencao"], "nexvoice_traduzir_trecho")
            self.assertIn("pt-BR -> en-US", r_fal["resposta"])
            self.assertIn("we can start the presentation", r_fal["resposta"].lower())

            # Salvar nos estudos
            r_salv = rotear("salvar sessao do nexvoice em Sistemas Distribuidos")
            self.assertEqual(r_salv["intencao"], "nexvoice_salvar_estudos")
            self.assertIn("Sistemas Distribuidos", r_salv["resposta"])

            # Encerrar
            r_enc = rotear("encerrar nexvoice")
            self.assertEqual(r_enc["intencao"], "nexvoice_encerrar")
            self.assertIn("encerrada", r_enc["resposta"])


if __name__ == "__main__":
    unittest.main()
