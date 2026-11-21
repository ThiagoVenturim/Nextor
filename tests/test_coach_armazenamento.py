"""Testes unitarios offline da persistencia SQLite do Coach de Estudos (Issue #57)."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor.coach.armazenamento import ArmazenamentoCoach
from nextor.coach.modelos import Plano, Pontuacao, ProgressoAcao, Recurso, Trilha


class TestCoachArmazenamento(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_coach.db"
        self.banco = ArmazenamentoCoach(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_salvar_e_obter_trilha(self):
        r1 = Recurso(trilha_id="trilha_1", tipo="video", titulo="Video 1", ordem=1, duracao_min=20)
        r2 = Recurso(trilha_id="trilha_1", tipo="artigo", titulo="Artigo 1", ordem=2, duracao_min=15)
        trilha = Trilha(
            id="trilha_1",
            titulo="Trilha 1",
            habilidade="programacao",
            recursos=[r1, r2],
        )
        self.banco.salvar_trilha(trilha)

        carregada = self.banco.obter_trilha("trilha_1")
        self.assertIsNotNone(carregada)
        self.assertEqual(carregada.titulo, "Trilha 1")
        self.assertEqual(len(carregada.recursos), 2)
        self.assertEqual(carregada.recursos[0].titulo, "Video 1")
        self.assertEqual(carregada.recursos[1].duracao_min, 15)

    def test_salvar_e_listar_planos(self):
        plano = Plano(trilha_id="trilha_1", dias_semana=3, minutos_dia=40)
        self.banco.salvar_plano(plano)

        recuperado = self.banco.obter_plano(plano.id)
        self.assertIsNotNone(recuperado)
        self.assertEqual(recuperado.dias_semana, 3)
        self.assertEqual(recuperado.minutos_dia, 40)

        planos = self.banco.listar_planos(ativo_apenas=True)
        self.assertEqual(len(planos), 1)

    def test_acoes_e_pontuacao(self):
        acao = ProgressoAcao(
            plano_id="p1",
            recurso_id="r1",
            data="2026-11-08",
            estado="pendente",
        )
        self.banco.salvar_acao(acao)

        carregada = self.banco.obter_acao(acao.id)
        self.assertIsNotNone(carregada)
        self.assertEqual(carregada.estado, "pendente")

        # Atualiza acao para feita
        carregada.estado = "feito"
        carregada.pontos = 25
        self.banco.salvar_acao(carregada)
        atualizada = self.banco.obter_acao(acao.id)
        self.assertEqual(atualizada.estado, "feito")
        self.assertEqual(atualizada.pontos, 25)

        # Pontuacao
        pts = Pontuacao(plano_id="p1", xp_total=100, nivel=2, streak=3, ultima_data="2026-11-08")
        self.banco.salvar_pontuacao(pts)
        pts_carregados = self.banco.obter_pontuacao("p1")
        self.assertIsNotNone(pts_carregados)
        self.assertEqual(pts_carregados.xp_total, 100)
        self.assertEqual(pts_carregados.nivel, 2)
        self.assertEqual(pts_carregados.streak, 3)


if __name__ == "__main__":
    unittest.main()
