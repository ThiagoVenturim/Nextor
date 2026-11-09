"""Testes unitarios offline da integracao entre Coach de Estudos e Painel GTD (Issue #57)."""
from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config
from nextor.coach.armazenamento import ArmazenamentoCoach
from nextor.coach.coach import concluir, criar_plano
from nextor.coach.integracao_gtd import (
    criar_tarefa_gtd_para_acao,
    sincronizar_conclusao_gtd,
)
from nextor.coach.modelos import Recurso, Trilha
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.gtd import processar


class TestCoachGTDIntegracao(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.coach_db_path = Path(self.temp_dir.name) / "test_coach.db"
        self.gtd_db_path = Path(self.temp_dir.name) / "test_gtd.db"

        self.patch_coach = mock.patch.object(config, "COACH_DB", self.coach_db_path)
        self.patch_gtd = mock.patch.object(config, "GTD_DB", self.gtd_db_path)
        self.patch_coach.start()
        self.patch_gtd.start()

        self.banco_coach = ArmazenamentoCoach(self.coach_db_path)
        self.banco_gtd = ArmazenamentoGTD(self.gtd_db_path)

        self.recurso = Recurso(
            trilha_id="t_gtd",
            tipo="video",
            titulo="Gramatica Essencial",
            ordem=1,
            duracao_min=20,
        )
        self.trilha = Trilha(
            id="t_gtd",
            titulo="Trilha GTD",
            habilidade="idiomas",
            recursos=[self.recurso],
        )
        self.banco_coach.salvar_trilha(self.trilha)

    def tearDown(self):
        self.patch_coach.stop()
        self.patch_gtd.stop()
        self.temp_dir.cleanup()

    def test_acao_vira_tarefa_gtd_com_contexto_estudo_e_prazo(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco_coach,
            integrar_gtd=False,
        )

        acoes = self.banco_coach.listar_acoes(plano.id)
        self.assertEqual(len(acoes), 1)
        acao = acoes[0]

        # Converte para tarefa no GTD
        item_gtd = criar_tarefa_gtd_para_acao(
            acao=acao,
            recurso=self.recurso,
            db_coach=self.banco_coach,
            db_gtd=self.banco_gtd,
        )

        self.assertIsNotNone(item_gtd.id)
        self.assertEqual(item_gtd.contexto, "@estudo")
        self.assertEqual(item_gtd.prazo, "2026-11-09")
        self.assertEqual(item_gtd.origem, "coach")
        self.assertIn("Gramatica Essencial", item_gtd.titulo)

        # Verifica se o ID do item GTD foi salvo na acao
        acao_atualizada = self.banco_coach.obter_acao(acao.id)
        self.assertEqual(acao_atualizada.gtd_item_id, item_gtd.id)

    def test_concluir_tarefa_no_gtd_sincroniza_com_coach(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco_coach,
            integrar_gtd=False,
        )
        acao = self.banco_coach.listar_acoes(plano.id)[0]
        item_gtd = criar_tarefa_gtd_para_acao(
            acao=acao,
            recurso=self.recurso,
            db_coach=self.banco_coach,
            db_gtd=self.banco_gtd,
        )

        # Marca a tarefa como feita no GTD
        processar(item_gtd.id, novo_estado="feito", db=self.banco_gtd)

        # Verifica se a acao no coach foi atualizada para "feito"
        acao_final = self.banco_coach.obter_acao(acao.id)
        self.assertEqual(acao_final.estado, "feito")
        self.assertTrue(acao_final.pontos > 0)

        # Verifica se o XP foi computado
        pts = self.banco_coach.obter_pontuacao(plano.id)
        self.assertTrue(pts.xp_total > 0)
        self.assertEqual(pts.streak, 1)

    def test_concluir_no_coach_marca_tarefa_gtd_como_feita(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco_coach,
            integrar_gtd=False,
        )
        acao = self.banco_coach.listar_acoes(plano.id)[0]
        item_gtd = criar_tarefa_gtd_para_acao(
            acao=acao,
            recurso=self.recurso,
            db_coach=self.banco_coach,
            db_gtd=self.banco_gtd,
        )

        # Conclui pelo Coach
        concluir(plano, self.recurso.id, data=hoje, db=self.banco_coach, db_gtd=self.banco_gtd)

        # Tarefa no GTD deve estar feita
        item_atualizado = self.banco_gtd.obter_item(item_gtd.id)
        self.assertEqual(item_atualizado.estado, "feito")
        self.assertIsNotNone(item_atualizado.concluido_em)


if __name__ == "__main__":
    unittest.main()
