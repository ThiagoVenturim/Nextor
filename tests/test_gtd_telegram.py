"""Testes unitarios offline dos comandos GTD no bot do Telegram (Issue #43, #44)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, telegram_bot
from nextor.gtd.armazenamento import ArmazenamentoGTD


class TestTelegramGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_telegram_gtd.db"
        self.patch_db = mock.patch.object(config, "GTD_DB", self.caminho_db)
        self.patch_db.start()
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.patch_db.stop()
        self.tmp.cleanup()

    def test_comando_hoje_responde_agenda_gtd(self):
        with mock.patch("nextor.gtd.agenda_do_dia", return_value={"resumo_falado": "Voce tem 2 tarefas hoje."}):
            resp = telegram_bot.tratar_comando("/hoje", "")
            self.assertEqual(resp, "Voce tem 2 tarefas hoje.")

    def test_comando_li_soma_paginas(self):
        with mock.patch.object(config, "LEITURA_META_DIARIA", 20):
            resp = telegram_bot.tratar_comando("/li", "15")
            self.assertIn("15", resp)
            self.assertIn("Total hoje", resp)

    def test_mensagem_livre_chat_dono_vira_item_inbox(self):
        dono_id = "777888"
        with mock.patch.dict(os.environ, {
            "TELEGRAM_USUARIOS_AUTORIZADOS": dono_id,
            "TELEGRAM_DONO_CHAT_ID": dono_id,
        }), mock.patch.object(config, "TELEGRAM_DONO_CHAT_ID", dono_id):

            update = {
                "message": {
                    "from": {"id": int(dono_id)},
                    "chat": {"id": int(dono_id)},
                    "text": "Lembrar de comprar fichario para a faculdade",
                }
            }
            res = telegram_bot.processar_update(update, enviar_resposta=False)
            self.assertTrue(res["ok"])
            self.assertIn("Item adicionado ao inbox", res["resposta"])
            self.assertIn("Lembrar de comprar fichario", res["resposta"])

            # Verifica se foi realmente salvo no banco GTD
            itens = self.banco.listar_itens(estado="inbox")
            self.assertEqual(len(itens), 1)
            self.assertEqual(itens[0].titulo, "Lembrar de comprar fichario para a faculdade")


if __name__ == "__main__":
    unittest.main()
