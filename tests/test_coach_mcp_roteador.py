"""Testes unitarios offline do servidor MCP e roteador de voz para o Coach (Issue #57)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config

from nextor.coach.armazenamento import ArmazenamentoCoach
from nextor.coach.coach import criar_plano
from nextor.coach.modelos import Recurso, Trilha
from nextor.mcp_server import (
    coach_acao_do_dia,
    coach_concluir,
    coach_criar_trilha,
    coach_progresso,
)
from nextor.roteador import rotear


class TestCoachMCPRoteador(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.coach_db = Path(self.temp_dir.name) / "test_coach.db"
        self.patch_db = mock.patch.object(config, "COACH_DB", self.coach_db)
        self.patch_db.start()
        self.banco = ArmazenamentoCoach(self.coach_db)

        # Trilha e plano padrao para os testes
        self.recurso = Recurso(
            trilha_id="ingles_iniciante",
            tipo="video",
            titulo="Sons e Fonetica",
            ordem=1,
            duracao_min=15,
            url="https://archive.org/video",
        )
        self.trilha = Trilha(
            id="ingles_iniciante",
            titulo="Ingles Basico",
            habilidade="ingles",
            recursos=[self.recurso],
        )
        self.banco.salvar_trilha(self.trilha)
        self.plano = criar_plano(self.trilha, ritmo={"dias_semana": 5, "minutos_dia": 30}, db=self.banco, integrar_gtd=False)

    def tearDown(self):
        self.patch_db.stop()
        self.temp_dir.cleanup()

    def test_mcp_coach_ferramentas(self):
        with mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=False):

            # 1. coach_acao_do_dia
            resp_acao = coach_acao_do_dia(plano_id=self.plano.id)
            self.assertIn("Sons e Fonetica", resp_acao)
            self.assertIn("15 min", resp_acao)

            # 2. coach_concluir
            resp_concluir = coach_concluir(recurso_id=self.recurso.id, plano_id=self.plano.id)
            self.assertIn("concluida com sucesso", resp_concluir)
            self.assertIn("XP", resp_concluir)

            # 3. coach_progresso
            resp_prog = coach_progresso(plano_id=self.plano.id)
            self.assertIn("1/1 licoes feitas (100.0%)", resp_prog)
            self.assertIn("Nivel 1", resp_prog)

            # 4. coach_criar_trilha
            rec_json = json.dumps([{"tipo": "artigo", "titulo": "Leitura Aberta", "duracao_min": 10}])
            with mock.patch("nextor.coach.trilhas._obter_pasta_usuario", return_value=Path(self.temp_dir.name)):
                resp_nova = coach_criar_trilha(
                    titulo="Espanhol Basico",
                    habilidade="espanhol",
                    recursos_json=rec_json,
                )
                self.assertIn("Espanhol Basico", resp_nova)
                self.assertIn("criada com sucesso", resp_nova)

    def test_roteador_voz_qual_meu_estudo_de_hoje(self):
        with mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=False):

            # Variacoes comuns de fala
            frases = [
                "qual meu estudo de hoje",
                "ei Nextor, qual meu estudo de hoje?",
                "o que tenho para estudar hoje",
                "qual a licao de hoje",
            ]
            for frase in frases:
                res = rotear(frase)
                self.assertEqual(res["intencao"], "coach_estudo_hoje")
                self.assertIn("Sons e Fonetica", res["resposta"])

    def test_roteador_voz_concluir_licao(self):
        with mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=False):

            res = rotear("conclui a licao de ingles")
            self.assertEqual(res["intencao"], "coach_concluir")
            self.assertIn("Concluido: Sons e Fonetica", res["resposta"])
            self.assertIn("XP", res["resposta"])


if __name__ == "__main__":
    unittest.main()
