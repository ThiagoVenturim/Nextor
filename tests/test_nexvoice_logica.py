"""Testes unitarios offline da logica do NexVoice: ouvir, reuniao bidirecional, etica e estudos (Issue #56)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, estudos, fala
from nextor.nexvoice import (
    ArmazenamentoNexVoice,
    confirmar_consentimento_sessao,
    encerrar_sessao_nexvoice,
    exportar_legendas_srt,
    gerar_ata_reuniao_bilingue,
    gerar_wav_stub,
    iniciar_sessao_nexvoice,
    processar_stream_trechos,
    processar_trecho_ao_vivo,
    salvar_sessao_nos_estudos,
)


class TestNexVoiceLogica(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_nexvoice = self.base_path / "test_nexvoice.db"
        self.estudos_dir = self.base_path / "estudos"
        self.estudos_db = self.estudos_dir / "indice_estudos.db"
        self.anotacoes_path = self.base_path / "anotacoes_teste.md"

        self.patch_nv_db = mock.patch.object(config, "NEXVOICE_DB", self.db_nexvoice)
        self.patch_est_dir = mock.patch.object(config, "ESTUDOS_DIR", self.estudos_dir)
        self.patch_est_db = mock.patch.object(config, "ESTUDOS_DB", self.estudos_db)
        self.patch_anot = mock.patch.object(config, "ANOTACOES", self.anotacoes_path)
        self.patch_nv_db.start()
        self.patch_est_dir.start()
        self.patch_est_db.start()
        self.patch_anot.start()

        self.banco = ArmazenamentoNexVoice(self.db_nexvoice)

    def tearDown(self):
        self.patch_nv_db.stop()
        self.patch_est_dir.stop()
        self.patch_est_db.stop()
        self.patch_anot.stop()
        self.temp_dir.cleanup()

    def test_modo_ouvir_video_com_stt_stub_traducao_local_e_tts_piper(self):
        wav_bytes = gerar_wav_stub(duracao_seg=1.0)
        sessao = iniciar_sessao_nexvoice(
            titulo="Video sobre Redes Neurais",
            modo="ouvir",
            fonte="video",
            idioma_meu="pt-BR",
            idioma_outro="en-US",
            motor_stt="faster_whisper",
            motor_traducao="local",
            motor_tts="piper",
            db=self.banco,
        )
        self.assertEqual(sessao.modo, "ouvir")
        self.assertFalse(sessao.consentimento_exigido)
        self.assertTrue(sessao.consentimento_confirmado)

        def fake_stt(audio_bytes=None, caminho_wav=None, idioma_origem="en-US"):
            self.assertIsNotNone(audio_bytes)
            return "Neural networks require training data"

        def fake_tts(texto: str, idioma: str):
            return gerar_wav_stub(duracao_seg=1.2), "audio/wav", "piper"

        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            trecho = processar_trecho_ao_vivo(
                sessao_id=sessao.id,
                audio_bytes=wav_bytes,
                direcao="entrada",
                locutor="apresentador",
                stt_fn=fake_stt,
                tts_fn=fake_tts,
                db=self.banco,
            )

        self.assertEqual(trecho.indice, 1)
        self.assertEqual(trecho.idioma_origem, "en-US")
        self.assertEqual(trecho.idioma_destino, "pt-BR")
        self.assertEqual(trecho.texto_original, "Neural networks require training data")
        self.assertIn("redes neurais", trecho.texto_traduzido.lower())
        self.assertEqual(trecho.motor_tts, "piper")
        self.assertTrue(bool(trecho.fala_id))
        self.assertIsNotNone(fala.pegar(trecho.fala_id))
        self.assertIn("[00:00] [apresentador <- pt-BR]", trecho.legenda_formatada)

    def test_etica_bloqueia_reuniao_e_aula_sem_consentimento_expresso(self):
        with self.assertRaises(PermissionError) as ctx_reuniao:
            iniciar_sessao_nexvoice(
                titulo="Reuniao Sem Aviso",
                modo="reuniao",
                consentimento_confirmado=False,
                db=self.banco,
            )
        self.assertIn("consentimento", str(ctx_reuniao.exception).lower())

        with self.assertRaises(PermissionError) as ctx_aula:
            iniciar_sessao_nexvoice(
                titulo="Aula ao Vivo Sem Autorizacao",
                modo="ouvir",
                fonte="aula",
                consentimento_confirmado=False,
                db=self.banco,
            )
        self.assertIn("consentimento", str(ctx_aula.exception).lower())

        # Criando sessao pendente e tentando processar antes de confirmar consentimento
        sessao_pendente = iniciar_sessao_nexvoice(
            titulo="Reuniao Aguardando",
            modo="reuniao",
            consentimento_confirmado=False,
            permitir_consentimento_pendente=True,
            db=self.banco,
        )
        with self.assertRaises(PermissionError):
            processar_trecho_ao_vivo(
                sessao_id=sessao_pendente.id,
                texto_fala="Hello everyone, welcome to the meeting",
                db=self.banco,
            )

        # Confirmando consentimento e verificando auditoria SQLite
        confirmar_consentimento_sessao(
            sessao_id=sessao_pendente.id,
            participantes="Alice, Bob e Thiago",
            db=self.banco,
        )
        auditoria = self.banco.listar_consentimentos(sessao_pendente.id)
        self.assertEqual(len(auditoria), 1)
        self.assertEqual(auditoria[0]["participantes"], "Alice, Bob e Thiago")
        self.assertTrue(auditoria[0]["local_estrito"])

        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            tr = processar_trecho_ao_vivo(
                sessao_id=sessao_pendente.id,
                texto_fala="Hello everyone, welcome to the meeting",
                db=self.banco,
            )
        self.assertIn("reuniao", tr.texto_traduzido.lower())

    def test_etica_bloqueia_motores_de_nuvem_quando_local_estrito_ativo(self):
        with self.assertRaises(PermissionError) as ctx_nuvem:
            iniciar_sessao_nexvoice(
                titulo="Reuniao Confidencial",
                modo="reuniao",
                consentimento_confirmado=True,
                processamento_local_estrito=True,
                motor_traducao="claude",
                db=self.banco,
            )
        self.assertIn("nuvem", str(ctx_nuvem.exception).lower())

        with self.assertRaises(PermissionError) as ctx_gtts:
            iniciar_sessao_nexvoice(
                titulo="Reuniao Confidencial TTS",
                modo="reuniao",
                consentimento_confirmado=True,
                processamento_local_estrito=True,
                motor_tts="gtts",
                db=self.banco,
            )
        self.assertIn("nuvem", str(ctx_gtts.exception).lower())

    def test_modo_reuniao_bidirecional_streaming_e_ata_bilingue(self):
        sessao = iniciar_sessao_nexvoice(
            titulo="Arquitetura Global",
            modo="reuniao",
            idioma_meu="pt-BR",
            idioma_outro="en-US",
            consentimento_confirmado=True,
            consentimento_participantes="Equipe Internacional",
            motor_tts="stub",
            db=self.banco,
        )

        fluxo = [
            {
                "direcao": "entrada",
                "locutor": "Sarah",
                "texto": "Hello everyone, welcome to the meeting",
                "inicio_seg": 0.0,
                "fim_seg": 3.0,
            },
            {
                "direcao": "saida",
                "locutor": "eu",
                "texto": "Decidimos usar processamento local por privacidade",
                "inicio_seg": 3.0,
                "fim_seg": 6.5,
            },
            {
                "direcao": "entrada",
                "locutor": "Sarah",
                "texto": "Please send the report tomorrow",
                "inicio_seg": 6.5,
                "fim_seg": 9.5,
            },
            {
                "direcao": "saida",
                "locutor": "eu",
                "texto": "Vou enviar o codigo hoje",
                "inicio_seg": 9.5,
                "fim_seg": 12.0,
            },
        ]

        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            trechos = processar_stream_trechos(
                sessao_id=sessao.id,
                trechos_entrada=fluxo,
                db=self.banco,
            )

        self.assertEqual(len(trechos), 4)
        # Entrada (Sarah fala EN -> eu ouco PT)
        self.assertEqual(trechos[0].idioma_origem, "en-US")
        self.assertEqual(trechos[0].idioma_destino, "pt-BR")
        self.assertIn("bem-vindos a reuniao", trechos[0].texto_traduzido.lower())

        # Saida (Eu falo PT -> Sarah ouve EN)
        self.assertEqual(trechos[1].idioma_origem, "pt-BR")
        self.assertEqual(trechos[1].idioma_destino, "en-US")
        self.assertIn("we decided to use local processing for privacy", trechos[1].texto_traduzido.lower())
        self.assertIn("->", trechos[1].legenda_formatada)

        self.assertEqual(trechos[3].idioma_origem, "pt-BR")
        self.assertEqual(trechos[3].idioma_destino, "en-US")
        self.assertIn("i will send the code today", trechos[3].texto_traduzido.lower())

        # Ata bilingue e encerramento
        ata = gerar_ata_reuniao_bilingue(sessao.id, salvar_anotacoes=True, db=self.banco)
        self.assertTrue(ata["ok"])
        self.assertEqual(ata["total_trechos"], 4)
        self.assertTrue(len(ata["decisoes"]) >= 1)
        self.assertTrue(len(ata["itens_acao"]) >= 1)

        encerrado = encerrar_sessao_nexvoice(sessao.id, gerar_ata=True, db=self.banco)
        self.assertEqual(encerrado["sessao"]["estado"], "encerrada")
        self.assertIn("00:00:00,000 --> 00:00:03,000", encerrado["legendas_srt"])

    def test_exportar_srt_e_salvar_aula_traduzida_nos_estudos_fts5(self):
        sessao = iniciar_sessao_nexvoice(
            titulo="Lecture on Deep Learning",
            modo="ouvir",
            fonte="aula",
            idioma_meu="pt-BR",
            idioma_outro="en-US",
            consentimento_confirmado=True,
            consentimento_participantes="Prof. Turing",
            disciplina="Inteligencia Artificial",
            motor_tts="stub",
            db=self.banco,
        )

        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            processar_trecho_ao_vivo(
                sessao_id=sessao.id,
                texto_fala="Welcome to our machine learning lecture",
                inicio_seg=0.0,
                fim_seg=4.0,
                db=self.banco,
            )
            processar_trecho_ao_vivo(
                sessao_id=sessao.id,
                texto_fala="Neural networks require training data",
                inicio_seg=4.0,
                fim_seg=8.5,
                db=self.banco,
            )

        srt = exportar_legendas_srt(sessao.id, bilingue=True, db=self.banco)
        self.assertIn("00:00:00,000 --> 00:00:04,000", srt)
        self.assertIn("00:00:04,000 --> 00:00:08,500", srt)
        self.assertIn("aprendizado de maquina", srt.lower())

        res_est = salvar_sessao_nos_estudos(
            sessao_id=sessao.id,
            disciplina_nome="Inteligencia Artificial",
            db=self.banco,
            base_dir_estudos=self.estudos_dir,
            caminho_db_estudos=self.estudos_db,
        )
        self.assertTrue(res_est["ok"])
        self.assertTrue(Path(res_est["caminho_arquivo"]).exists())
        self.assertTrue(Path(res_est["caminho_srt"]).exists())

        busca = estudos.buscar_materiais(
            "treinamento",
            disciplina_nome="Inteligencia Artificial",
            caminho_db=self.estudos_db,
        )
        self.assertEqual(len(busca), 1)
        self.assertIn("NexVoice", busca[0]["titulo"])


if __name__ == "__main__":
    unittest.main()
