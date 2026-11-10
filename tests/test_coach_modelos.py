"""Testes unitarios offline dos modelos de dados do Coach de Estudos (Issue #57)."""
import os
import unittest

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor.coach.modelos import (
    Plano,
    Pontuacao,
    ProgressoAcao,
    Recurso,
    Trilha,
    calcular_bonus_streak,
    calcular_nivel,
)


class TestCoachModelos(unittest.TestCase):
    def test_calcular_nivel(self):
        self.assertEqual(calcular_nivel(0), 1)
        self.assertEqual(calcular_nivel(50), 1)
        self.assertEqual(calcular_nivel(99), 1)
        self.assertEqual(calcular_nivel(100), 2)
        self.assertEqual(calcular_nivel(199), 2)
        self.assertEqual(calcular_nivel(200), 3)
        self.assertEqual(calcular_nivel(550), 6)

    def test_calcular_bonus_streak(self):
        self.assertEqual(calcular_bonus_streak(0), 0)
        self.assertEqual(calcular_bonus_streak(1), 0)
        self.assertEqual(calcular_bonus_streak(2), 10)
        self.assertEqual(calcular_bonus_streak(5), 25)
        self.assertEqual(calcular_bonus_streak(10), 50)
        self.assertEqual(calcular_bonus_streak(20), 50)  # Teto maximo de 50

    def test_recurso_criacao_e_serializacao(self):
        rec = Recurso(
            trilha_id="t1",
            tipo="video",
            titulo="Video Introdutorio",
            ordem=1,
            duracao_min=15,
            dominio_publico=True,
            url="https://archive.org/video",
        )
        d = rec.to_dict()
        self.assertEqual(d["titulo"], "Video Introdutorio")
        self.assertEqual(d["tipo"], "video")
        self.assertTrue(d["dominio_publico"])

        restaurado = Recurso.from_dict(d)
        self.assertEqual(restaurado.id, rec.id)
        self.assertEqual(restaurado.titulo, rec.titulo)

    def test_trilha_com_recursos(self):
        r1 = Recurso(trilha_id="t1", tipo="aula", titulo="Aula 1", ordem=1)
        r2 = Recurso(trilha_id="t1", tipo="exercicio", titulo="Exercicio 1", ordem=2)
        trilha = Trilha(
            id="t1",
            titulo="Trilha Teste",
            habilidade="logica",
            nivel="iniciante",
            recursos=[r1, r2],
        )
        d = trilha.to_dict()
        self.assertEqual(len(d["recursos"]), 2)
        restaurada = Trilha.from_dict(d)
        self.assertEqual(len(restaurada.recursos), 2)
        self.assertEqual(restaurada.recursos[0].titulo, "Aula 1")

    def test_plano_ritmo(self):
        plano = Plano(trilha_id="t1", dias_semana=5, minutos_dia=45)
        self.assertEqual(plano.ritmo, {"dias_semana": 5, "minutos_dia": 45})
        d = plano.to_dict()
        self.assertEqual(d["ritmo"]["dias_semana"], 5)
        restaurado = Plano.from_dict(d)
        self.assertEqual(restaurado.dias_semana, 5)
        self.assertEqual(restaurado.minutos_dia, 45)

    def test_progresso_acao_e_pontuacao(self):
        acao = ProgressoAcao(plano_id="p1", recurso_id="r1", data="2026-11-08")
        self.assertEqual(acao.estado, "pendente")
        self.assertEqual(acao.pontos, 0)
        d_acao = acao.to_dict()
        self.assertEqual(d_acao["data"], "2026-11-08")

        pontos = Pontuacao(plano_id="p1", xp_total=120)
        self.assertEqual(pontos.nivel, 2)
        d_pontos = pontos.to_dict()
        self.assertEqual(d_pontos["xp_total"], 120)


if __name__ == "__main__":
    unittest.main()
