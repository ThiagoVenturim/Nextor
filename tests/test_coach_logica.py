"""Testes unitarios offline da logica do Coach de Estudos (Issue #57)."""
from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor.coach.armazenamento import ArmazenamentoCoach
from nextor.coach.coach import acao_do_dia, concluir, criar_plano, dia_esta_cheio, resumo
from nextor.coach.modelos import Recurso, Trilha


class TestCoachLogica(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_coach.db"
        self.banco = ArmazenamentoCoach(self.db_path)

        # Monta trilha sintetica com 4 recursos: 2 curtos (15 min) e 2 longos (30 min)
        self.recursos = [
            Recurso(trilha_id="t_teste", tipo="video", titulo="Video Curto 1", ordem=1, duracao_min=15),
            Recurso(trilha_id="t_teste", tipo="aula", titulo="Aula Curta 2", ordem=2, duracao_min=15),
            Recurso(trilha_id="t_teste", tipo="livro", titulo="Leitura 3", ordem=3, duracao_min=30),
            Recurso(trilha_id="t_teste", tipo="teste", titulo="Quiz Final 4", ordem=4, duracao_min=30),
        ]
        self.trilha = Trilha(
            id="t_teste",
            titulo="Trilha de Testes",
            habilidade="estudos",
            recursos=self.recursos,
        )
        self.banco.salvar_trilha(self.trilha)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_criar_plano_distribui_recursos_respeitando_minutos_e_dias(self):
        # Ritmo: 30 minutos/dia, 5 dias/semana (seg a sex)
        hoje = date(2026, 11, 9)  # Segunda-feira
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco,
            integrar_gtd=False,
        )

        acoes = self.banco.listar_acoes(plano.id)
        self.assertEqual(len(acoes), 4)

        # Recurso 1 (15m) + Recurso 2 (15m) cabem ambos em 30m no dia 1 (2026-11-09)
        self.assertEqual(acoes[0].data, "2026-11-09")
        self.assertEqual(acoes[1].data, "2026-11-09")

        # Recurso 3 (30m) vai para o proximo dia de estudo (2026-11-10)
        self.assertEqual(acoes[2].data, "2026-11-10")

        # Recurso 4 (30m) vai para o proximo dia de estudo (2026-11-11)
        self.assertEqual(acoes[3].data, "2026-11-11")

    def test_acao_do_dia_pula_dia_cheio_na_agenda(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco,
            integrar_gtd=False,
        )

        # Em dia normal, retorna a primeira acao pendente
        with mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=False):
            acao = acao_do_dia(plano, data=hoje, db=self.banco)
            self.assertIsNotNone(acao)
            self.assertEqual(acao.recurso_id, self.recursos[0].id)

        # Em dia com agenda saturada / compromissos criticos, acao_do_dia pula o dia
        with mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=True):
            acao_cheio = acao_do_dia(plano, data=hoje, db=self.banco)
            self.assertIsNone(acao_cheio, "Em dia cheio, o coach deve pular e nao sobrecarregar o usuario.")

    def test_acao_do_dia_nao_repete_feito(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco,
            integrar_gtd=False,
        )

        # Conclui o primeiro recurso
        with mock.patch("nextor.coach.coach.dia_esta_cheio", return_value=False):
            acao1 = acao_do_dia(plano, data=hoje, db=self.banco)
            self.assertEqual(acao1.recurso_id, self.recursos[0].id)

            concluir(plano, recurso=acao1.recurso_id, data=hoje, db=self.banco)

            # Proxima consulta no mesmo dia deve trazer a proxima acao pendente, sem repetir a feita
            acao2 = acao_do_dia(plano, data=hoje, db=self.banco)
            self.assertIsNotNone(acao2)
            self.assertEqual(acao2.recurso_id, self.recursos[1].id)
            self.assertNotEqual(acao2.recurso_id, self.recursos[0].id)

    def test_concluir_soma_xp_mantem_ou_zera_streak_e_sobe_de_nivel(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 7, "minutos_dia": 60},
            data_inicio=hoje,
            db=self.banco,
            integrar_gtd=False,
        )

        # Dia 1 (2026-11-09): Conclui recurso 1 (video = 10 XP) -> streak 1
        res1 = concluir(plano, self.recursos[0].id, data=hoje, db=self.banco)
        self.assertEqual(res1["xp_ganho"], 10)
        self.assertEqual(res1["xp_total"], 10)
        self.assertEqual(res1["streak"], 1)
        self.assertEqual(res1["nivel"], 1)

        # Dia 2 consecutivo (2026-11-10): Conclui recurso 2 (aula = 20 XP + 10 bonus streak) -> streak 2
        dia2 = hoje + timedelta(days=1)
        res2 = concluir(plano, self.recursos[1].id, data=dia2, db=self.banco)
        self.assertEqual(res2["streak"], 2, "Streak deve incrementar em dias consecutivos.")
        self.assertEqual(res2["xp_ganho"], 30)  # 20 base + 10 bonus
        self.assertEqual(res2["xp_total"], 40)
        self.assertEqual(res2["nivel"], 1)

        # Pula um dia (quebra de streak): estuda em dia 4 (2026-11-12)
        dia4 = hoje + timedelta(days=3)
        res3 = concluir(plano, self.recursos[2].id, data=dia4, db=self.banco)
        self.assertEqual(res3["streak"], 1, "Streak deve resetar para 1 apos dia perdido.")
        self.assertEqual(res3["xp_ganho"], 15)  # livro base = 15, sem bonus
        self.assertEqual(res3["xp_total"], 55)

        # Conclui recurso 4 com bastante XP para ultrapassar 100 XP e subir de nivel
        # Forcamos pontuacao para testar a subida de nivel exatamente no limiar de 100 XP
        pts = self.banco.obter_pontuacao(plano.id)
        pts.xp_total = 90
        pts.ultima_data = (dia4 - timedelta(days=1)).isoformat()
        pts.streak = 1
        self.banco.salvar_pontuacao(pts)

        # Conclui recurso 4 (teste = 30 XP + 10 bonus) -> 90 + 40 = 130 XP -> Nivel 2
        res4 = concluir(plano, self.recursos[3].id, data=dia4, db=self.banco)
        self.assertTrue(res4["xp_total"] >= 100)
        self.assertEqual(res4["nivel"], 2, "Deve subir para nivel 2 ao atingir 100 XP.")
        self.assertTrue(res4["subiu_de_nivel"])

    def test_resumo_calcula_metricas_completas(self):
        hoje = date(2026, 11, 9)
        plano = criar_plano(
            trilha=self.trilha,
            ritmo={"dias_semana": 5, "minutos_dia": 30},
            data_inicio=hoje,
            db=self.banco,
            integrar_gtd=False,
        )

        concluir(plano, self.recursos[0].id, data=hoje, db=self.banco)
        r = resumo(plano, db=self.banco)

        self.assertEqual(r["total_acoes"], 4)
        self.assertEqual(r["concluidas"], 1)
        self.assertEqual(r["pendentes"], 3)
        self.assertEqual(r["percentual"], 25.0)
        self.assertTrue(len(r["proximos_passos"]) >= 1)
        self.assertEqual(r["proximos_passos"][0]["recurso_id"], self.recursos[1].id)


if __name__ == "__main__":
    unittest.main()
