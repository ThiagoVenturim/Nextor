"""Testes unitarios offline do fluxo GTD (A Arte de Fazer Acontecer)."""
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from nextor import config
from nextor.gtd import capturar, processar, listar_por_contexto, agenda_do_dia, revisao_semanal
from nextor.gtd.armazenamento import ArmazenamentoGTD
from nextor.gtd.modelos import Item, Projeto, Leitura


class TestLogicaGTD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.caminho_db = Path(self.tmp.name) / "teste_logica.db"
        self.banco = ArmazenamentoGTD(self.caminho_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_captura_adiciona_ao_inbox(self):
        item = capturar(
            titulo="Pesquisar jurisprudencia sobre contratos",
            nota="Para o artigo da pos",
            contexto="@faculdade",
            db=self.banco,
        )
        self.assertEqual(item.estado, "inbox")
        self.assertEqual(item.contexto, "@faculdade")
        self.assertEqual(item.titulo, "Pesquisar jurisprudencia sobre contratos")

        # Verifica persistencia
        salvo = self.banco.obter_item(item.id)
        self.assertIsNotNone(salvo)
        self.assertEqual(salvo.estado, "inbox")

    def test_processar_move_para_proxima_acao(self):
        item = capturar("Enviar email para orientador", db=self.banco)
        processado = processar(
            item_id=item.id,
            novo_estado="proxima",
            novo_contexto="@faculdade",
            prazo="2026-11-09",
            energia="baixa",
            db=self.banco,
        )
        self.assertIsNotNone(processado)
        self.assertEqual(processado.estado, "proxima")
        self.assertEqual(processado.contexto, "@faculdade")
        self.assertEqual(processado.prazo, "2026-11-09")
        self.assertEqual(processado.energia, "baixa")

    def test_processar_transforma_em_projeto(self):
        item = capturar("Redigir artigo cientifico sobre IA e Direito", db=self.banco)
        processado = processar(
            item_id=item.id,
            novo_estado="projeto",
            db=self.banco,
        )
        self.assertIsNotNone(processado)
        self.assertEqual(processado.estado, "feito")
        self.assertIsNotNone(processado.projeto_id)

        proj = self.banco.obter_projeto(processado.projeto_id)
        self.assertIsNotNone(proj)
        self.assertEqual(proj.nome, "Redigir artigo cientifico sobre IA e Direito")

    def test_processar_transforma_em_leitura(self):
        item = capturar("Ler livro Como Fazer Amigos", nota="https://livros.exemplo.com/1", db=self.banco)
        processado = processar(
            item_id=item.id,
            novo_estado="leitura",
            db=self.banco,
        )
        self.assertIsNotNone(processado)
        self.assertEqual(processado.estado, "feito")

        leituras = self.banco.listar_leituras()
        self.assertEqual(len(leituras), 1)
        self.assertEqual(leituras[0].titulo, "Ler livro Como Fazer Amigos")
        self.assertEqual(leituras[0].estado, "quero_ler")

    def test_processar_descarta_lixo(self):
        item = capturar("Nota qualquer sem valor", db=self.banco)
        resultado = processar(item_id=item.id, novo_estado="lixo", db=self.banco)
        self.assertIsNone(resultado)
        self.assertIsNone(self.banco.obter_item(item.id))

    def test_listar_por_contexto(self):
        capturar("Comprar suplemento", contexto="@academia", db=self.banco)
        it1 = capturar("Treinar perna", contexto="@academia", db=self.banco)
        it2 = capturar("Estudar processo civil", contexto="@faculdade", db=self.banco)

        processar(it1.id, "proxima", db=self.banco)
        processar(it2.id, "proxima", db=self.banco)

        academia = listar_por_contexto("@academia", db=self.banco)
        self.assertEqual(len(academia), 1)
        self.assertEqual(academia[0].titulo, "Treinar perna")

    def test_agenda_do_dia_agrega_tres_fontes(self):
        hoje = date.today().isoformat()
        ontem = (date.today() - timedelta(days=1)).isoformat()

        # 1. Tarefa atrasada e tarefa para hoje
        it_atrasado = capturar("Pagar conta de luz", prazo=ontem, db=self.banco)
        processar(it_atrasado.id, "proxima", db=self.banco)

        it_hoje = capturar("Reuniao de alinhamento", prazo=hoje, db=self.banco)
        processar(it_hoje.id, "proxima", db=self.banco)

        # 2. Leitura e progresso
        livro = Leitura(titulo="Deep Work", estado="lendo", paginas_total=250)
        self.banco.salvar_leitura(livro)
        self.banco.registrar_progresso_leitura(livro.id, 15, hoje)

        # 3. Mock da Google Agenda
        eventos_falsos = [
            {"titulo": "Audiencia Virtual", "inicio": datetime(2026, 11, 8, 14, 0), "dia_inteiro": False}
        ]

        with mock.patch("nextor.agenda.eventos_hoje", return_value=eventos_falsos), \
             mock.patch.object(config, "LEITURA_META_DIARIA", 20):
            res = agenda_do_dia(db=self.banco)

            self.assertEqual(len(res["eventos_agenda"]), 1)
            self.assertEqual(res["eventos_agenda"][0]["titulo"], "Audiencia Virtual")
            self.assertGreaterEqual(len(res["proximas_acoes"]), 2)
            self.assertEqual(res["leitura"]["paginas_lidas_hoje"], 15)
            self.assertEqual(res["leitura"]["faltam_paginas"], 5)
            self.assertFalse(res["leitura"]["meta_atingida"])
            self.assertTrue("compromisso" in res["resumo_falado"] or "Audiencia" in res["resumo_falado"])

    def test_revisao_semanal_acha_projetos_sem_proxima_acao(self):
        # Projeto 1: tem proxima acao vinculada
        p1 = Projeto(nome="Sistema de IA", estado="ativo")
        self.banco.salvar_projeto(p1)
        it1 = capturar("Escrever testes do backend", projeto_id=p1.id, db=self.banco)
        processar(it1.id, "proxima", db=self.banco)

        # Projeto 2: ativo, mas nao tem nenhuma proxima acao
        p2 = Projeto(nome="Reforma do Escritorio", estado="ativo")
        self.banco.salvar_projeto(p2)

        rev = revisao_semanal(db=self.banco)
        self.assertEqual(rev["projetos_ativos_total"], 2)
        sem_acao = rev["projetos_sem_proxima_acao"]
        self.assertEqual(len(sem_acao), 1)
        self.assertEqual(sem_acao[0]["nome"], "Reforma do Escritorio")


if __name__ == "__main__":
    unittest.main()
