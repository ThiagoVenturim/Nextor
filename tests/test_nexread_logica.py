"""Testes unitarios offline da logica do NexRead: extracao, traducao, marcacao, gravacao, estudos e IA (Issue #55)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, estudos
from nextor.nexread import (
    ArmazenamentoNexRead,
    conversar_sobre_artigo,
    extrair_blocos_html,
    extrair_blocos_pdf,
    gravar_nota_leitura,
    marcar_trecho,
    salvar_na_biblioteca_estudos,
    traduzir_pagina_ao_vivo,
)


class TestNexReadLogica(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_nexread = self.base_path / "test_nexread.db"
        self.estudos_dir = self.base_path / "estudos"
        self.estudos_db = self.estudos_dir / "indice_estudos.db"

        self.patch_nr_db = mock.patch.object(config, "NEXREAD_DB", self.db_nexread)
        self.patch_est_dir = mock.patch.object(config, "ESTUDOS_DIR", self.estudos_dir)
        self.patch_est_db = mock.patch.object(config, "ESTUDOS_DB", self.estudos_db)
        self.patch_nr_db.start()
        self.patch_est_dir.start()
        self.patch_est_db.start()

        self.banco = ArmazenamentoNexRead(self.db_nexread)

    def tearDown(self):
        self.patch_nr_db.stop()
        self.patch_est_dir.stop()
        self.patch_est_db.stop()
        self.temp_dir.cleanup()

    def test_extrair_html_preserva_layout_e_remove_scripts(self):
        html_exemplo = """
        <html lang="en">
        <head>
            <title>Attention Mechanism in Deep Learning</title>
            <meta name="author" content="Ada Lovelace, Alan Turing">
            <script>alert('xss');</script>
        </head>
        <body>
            <article>
                <h1>Introduction to Neural Networks</h1>
                <p>Deep learning models use attention mechanism for better performance.</p>
                <blockquote>Research shows significant results in natural language processing.</blockquote>
                <ul>
                    <li>Fast training on parallel data</li>
                </ul>
            </article>
        </body>
        </html>
        """
        extraido = extrair_blocos_html(html_exemplo)
        self.assertEqual(extraido["titulo"], "Attention Mechanism in Deep Learning")
        self.assertEqual(extraido["autor"], "Ada Lovelace, Alan Turing")
        self.assertEqual(extraido["idioma_origem"], "en")

        blocos = extraido["blocos"]
        self.assertEqual(len(blocos), 4)
        self.assertEqual([b.tag for b in blocos], ["h1", "p", "blockquote", "li"])
        self.assertNotIn("alert", " ".join(b.texto_original for b in blocos))

    def test_recusa_pagina_nao_aberta_pelo_usuario(self):
        with self.assertRaises(ValueError) as ctx:
            traduzir_pagina_ao_vivo(
                texto="Artigo em background",
                aberta_pelo_usuario=False,
                db=self.banco,
            )
        self.assertIn("abriu", str(ctx.exception))

    def test_traducao_ao_vivo_mantendo_layout_e_marcacoes(self):
        html_artigo = """
        <article>
            <h1>Machine Learning Study</h1>
            <p>This paper presents a neural network model for data analysis.</p>
        </article>
        """
        # Simula modelo local traduzindo
        def fake_tradutor(texto: str, destino: str) -> str:
            if "Machine Learning Study" in texto:
                return "Estudo de Aprendizado de Maquina"
            return "Este artigo apresenta um modelo de rede neural para analise de dados."

        artigo = traduzir_pagina_ao_vivo(
            conteudo_html=html_artigo,
            url="https://arxiv.org/abs/2611.00001",
            autor="Grace Hopper",
            modo_layout="bilingue",
            tradutor_fn=fake_tradutor,
            db=self.banco,
        )

        self.assertEqual(artigo.motor_traducao, "local")
        self.assertEqual(len(artigo.blocos), 2)
        self.assertEqual(artigo.blocos[0].tag, "h1")
        self.assertEqual(artigo.blocos[1].tag, "p")
        self.assertIn("nexread-bilingue", artigo.html_traduzido)

        # Marca trecho e adiciona anotacao
        marc = marcar_trecho(
            artigo_id=artigo.id,
            trecho="neural network model",
            nota="Arquitetura central do artigo",
            cor="verde",
            db=self.banco,
        )
        self.assertEqual(marc.bloco_id, "b-2")

        artigo_atualizado = self.banco.obter_artigo(artigo.id)
        self.assertIn('<mark class="nexread-mark cor-verde"', artigo_atualizado.html_traduzido)
        self.assertIn("Arquitetura central do artigo", artigo_atualizado.html_traduzido)

    def test_gravar_e_salvar_na_biblioteca_de_estudos_fts5(self):
        with mock.patch("nextor.cerebro._chamar_ollama", side_effect=OSError("offline")):
            artigo = traduzir_pagina_ao_vivo(
                conteudo_html="<h1>Introduction</h1><p>Deep learning and neural networks in research.</p>",
                titulo="Deep Learning Paper",
                autor="Geoffrey Hinton",
                url="https://arxiv.org/abs/2611.12345",
                db=self.banco,
            )
        marcar_trecho(
            artigo_id=artigo.id,
            trecho="Deep learning",
            nota="Importante para a prova de IA",
            cor="amarelo",
            db=self.banco,
        )
        gravar_nota_leitura(
            artigo_id=artigo.id,
            titulo="Explicacao em voz",
            transcricao="O autor destaca que redes neurais profundas escalam bem com dados.",
            duracao_seg=18,
            db=self.banco,
        )

        res_estudos = salvar_na_biblioteca_estudos(
            artigo_id=artigo.id,
            disciplina_nome="Inteligencia Artificial",
            db=self.banco,
            base_dir_estudos=self.estudos_dir,
            caminho_db_estudos=self.estudos_db,
        )

        self.assertTrue(res_estudos["ok"])
        self.assertIn("HINTON, Geoffrey", res_estudos["referencia_abnt"])
        self.assertEqual(res_estudos["total_marcacoes"], 1)
        self.assertEqual(res_estudos["total_gravacoes"], 1)

        # Confirma indexacao no SQLite FTS5 do modo estudante
        busca = estudos.buscar_materiais(
            "escalam",
            disciplina_nome="Inteligencia Artificial",
            caminho_db=self.estudos_db,
        )
        self.assertEqual(len(busca), 1)
        self.assertIn("NexRead", busca[0]["titulo"])

    def test_conversar_sobre_artigo_com_fontes_do_texto_e_artigos_cientificos(self):
        artigo = traduzir_pagina_ao_vivo(
            conteudo_html=(
                "<h1>Transformer Architecture</h1>"
                "<p>The attention mechanism replaces recurrence completely.</p>"
                "<p>Results show faster training on translation benchmarks.</p>"
            ),
            titulo="Transformer Architecture",
            tradutor_fn=lambda t, _d: (
                "O mecanismo de atencao substitui a recorrencia completamente."
                if "recurrence" in t
                else "Resultados mostram treinamento mais rapido em benchmarks de traducao."
            ),
            db=self.banco,
        )

        fake_openalex_json = '{"results": [{"id": "https://openalex.org/W1", "title": "Attention Is All You Need", "publication_year": 2017, "authorships": [{"author": {"display_name": "Ashish Vaswani"}}], "abstract_inverted_index": {"Transformers": [0], "use": [1], "attention.": [2]}}]}'
        fake_arxiv_xml = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

        def fake_http_artigos(url: str, _headers: dict) -> str:
            if "openalex" in url:
                return fake_openalex_json
            return fake_arxiv_xml

        res_chat = conversar_sobre_artigo(
            artigo_id=artigo.id,
            pergunta="Como o mecanismo de atencao funciona segundo o texto?",
            acao="perguntar",
            buscar_fontes_cientificas=True,
            cerebro_fn=lambda prompt, _sis: "Segundo o Bloco 2 do texto, o mecanismo de atencao substitui a recorrencia.",
            http_client_artigos=fake_http_artigos,
            db=self.banco,
        )

        self.assertTrue(res_chat["ok"])
        self.assertIn("substitui a recorrencia", res_chat["resposta"])
        self.assertTrue(any("Bloco 2" in f for f in res_chat["fontes"]))
        self.assertTrue(any("VASWANI, Ashish" in f for f in res_chat["fontes"]))
        self.assertEqual(len(res_chat["artigos_relacionados"]), 1)

        historico = self.banco.listar_mensagens_chat(artigo.id)
        self.assertEqual(len(historico), 2)

    def test_extrair_blocos_pdf_com_validacao_segura(self):
        pdf_falso = self.base_path / "artigo_teste.pdf"
        pdf_falso.write_bytes(b"%PDF-1.4 fake content")
        with mock.patch("nextor.estudos.extrair_texto_pdf", return_value="# Titulo do PDF\n\nParagrafo extraido do PDF."):
            res = extrair_blocos_pdf(pdf_falso, pastas_autorizadas=[self.base_path])
            self.assertEqual(res["tipo_origem"], "pdf")
            self.assertTrue(len(res["blocos"]) >= 1)


if __name__ == "__main__":
    unittest.main()
