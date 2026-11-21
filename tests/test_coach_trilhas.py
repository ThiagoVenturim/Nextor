"""Testes unitarios offline de trilhas embutidas e de usuario (Issue #57)."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor.coach.trilhas import (
    carregar_todas_trilhas,
    carregar_trilhas_embutidas,
    carregar_trilhas_usuario,
    criar_trilha,
    obter_trilha,
    salvar_trilha_usuario,
)


class TestCoachTrilhas(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pasta_usuario = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_trilha_ingles_embutida_carrega_e_apenas_dominio_publico_e_links(self):
        trilhas = carregar_trilhas_embutidas()
        self.assertTrue(len(trilhas) >= 1, "A trilha de ingles embutida deve carregar.")

        ingles = next((t for t in trilhas if t.id == "ingles_iniciante"), None)
        self.assertIsNotNone(ingles, "Trilha 'ingles_iniciante' deve estar disponivel.")
        self.assertEqual(ingles.habilidade, "ingles")
        self.assertTrue(len(ingles.recursos) >= 5, "Trilha de ingles deve ter recursos estruturados.")

        # Verifica conformidade etica e de direitos autorais:
        # Apenas dominio publico ou links; nenhum texto protegido por direitos autorais embutido
        for r in ingles.recursos:
            self.assertTrue(
                r.dominio_publico or (r.url and r.url.startswith("http")),
                f"Recurso '{r.titulo}' deve ser explicitamente de dominio publico ou conter link aberto.",
            )
            # Garantir que nao ha trechos longos de livros proprietarios embutidos
            self.assertTrue(len(r.descricao) < 500, "Sem textos longos de terceiros embutidos no codigo.")

    def test_criar_editar_e_carregar_trilha_do_usuario(self):
        # 1. Cria trilha
        recursos = [
            {"tipo": "video", "titulo": "Video Aula 1", "duracao_min": 20, "ordem": 1},
            {"tipo": "exercicio", "titulo": "Pratica 1", "duracao_min": 15, "ordem": 2},
        ]
        trilha = criar_trilha(
            id_trilha="minha_trilha",
            titulo="Minha Trilha de Python",
            habilidade="programacao",
            nivel="intermediario",
            descricao="Trilha focada em testes automatizados",
            recursos=recursos,
            pasta=self.pasta_usuario,
        )
        self.assertEqual(trilha.id, "minha_trilha")
        self.assertEqual(len(trilha.recursos), 2)

        # 2. Carrega da pasta do usuario
        usuario_trilhas = carregar_trilhas_usuario(self.pasta_usuario)
        self.assertEqual(len(usuario_trilhas), 1)
        self.assertEqual(usuario_trilhas[0].titulo, "Minha Trilha de Python")

        # 3. Edita a trilha adicionando um recurso e salva
        trilha.titulo = "Minha Trilha de Python Atualizada"
        trilha.recursos.append(
            trilha.recursos[0].__class__(
                trilha_id=trilha.id,
                tipo="revisao",
                titulo="Revisao Geral",
                ordem=3,
                duracao_min=30,
            )
        )
        salvar_trilha_usuario(trilha, pasta=self.pasta_usuario)

        # 4. Recarrega e valida atualizacao
        recarregada = obter_trilha("minha_trilha", pasta_usuario=self.pasta_usuario)
        self.assertIsNotNone(recarregada)
        self.assertEqual(recarregada.titulo, "Minha Trilha de Python Atualizada")
        self.assertEqual(len(recarregada.recursos), 3)

    def test_carregar_todas_trilhas_combina_embutidas_e_usuario(self):
        criar_trilha(
            id_trilha="trilha_custom",
            titulo="Trilha Custom",
            habilidade="musica",
            pasta=self.pasta_usuario,
        )
        todas = carregar_todas_trilhas(pasta_usuario=self.pasta_usuario)
        ids = [t.id for t in todas]
        self.assertIn("ingles_iniciante", ids)
        self.assertIn("trilha_custom", ids)


if __name__ == "__main__":
    unittest.main()
