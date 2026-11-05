"""Testes unitarios offline do modulo de busca de artigos cientificos com ABNT (Issue #7)."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import artigos_cientificos, config, estudos, roteador, servico

# Fixture JSON simulando resposta da API do OpenAlex
MOCK_OPENALEX_JSON = json.dumps({
    "results": [
        {
            "id": "https://openalex.org/W2741809807",
            "doi": "https://doi.org/10.1038/nature14539",
            "title": "Deep Learning and Neural Representations",
            "publication_year": 2015,
            "authorships": [
                {"author": {"display_name": "Yann LeCun"}},
                {"author": {"display_name": "Yoshua Bengio"}},
                {"author": {"display_name": "Geoffrey Hinton"}},
            ],
            "abstract_inverted_index": {
                "Deep": [0],
                "learning": [1],
                "discovers": [2],
                "intricate": [3],
                "structures": [4],
                "in": [5],
                "data.": [6],
            },
            "primary_location": {
                "source": {"display_name": "Nature"},
                "landing_page_url": "https://www.nature.com/articles/nature14539",
                "pdf_url": "https://www.nature.com/articles/nature14539.pdf",
            },
            "open_access": {
                "oa_url": "https://www.nature.com/articles/nature14539.pdf",
            },
        },
        {
            "id": "https://openalex.org/W2000000002",
            "title": "Calculo Diferencial Avancado",
            "publication_year": 2020,
            "authorships": [
                {"author": {"display_name": "Jose Carlos Silva Junior"}},
            ],
            "abstract_inverted_index": None,
            "primary_location": {
                "source": {"display_name": "Revista Brasileira de Matematica"},
                "landing_page_url": "https://exemplo.org/calculo",
            },
            "open_access": {
                "oa_url": None,
            },
        },
    ]
})

# Fixture Atom XML simulando resposta da API do arXiv
MOCK_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v1</id>
    <published>2017-06-12T20:15:00Z</published>
    <title> Attention Is All You Need </title>
    <summary> The dominant sequence models are based on recurrent neural networks. </summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <author><name>Niki Parmar</name></author>
    <author><name>Jakob Uszkoreit</name></author>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/1706.03762v1"/>
    <link title="pdf" rel="related" type="application/pdf" href="http://arxiv.org/pdf/1706.03762v1"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2101.99999v1</id>
    <published>2021-01-10T10:00:00Z</published>
    <title> Quantum Computing Foundations </title>
    <summary> An introduction to qubits and quantum logic gates. </summary>
    <author><name>Richard Feynman</name></author>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2101.99999v1"/>
  </entry>
</feed>
"""


class BaseArtigosTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_artigos.db"
        self.token_teste = "token-artigos-mestre-super-seguro-com-mais-de-24-caracteres"

        self.p_dir = mock.patch.object(config, "ESTUDOS_DIR", self.base_dir)
        self.p_db = mock.patch.object(config, "ESTUDOS_DB", self.db_path)
        self.p_edir = mock.patch.object(estudos.config, "ESTUDOS_DIR", self.base_dir)
        self.p_edb = mock.patch.object(estudos.config, "ESTUDOS_DB", self.db_path)
        self.p_token = mock.patch.object(config, "TOKEN", self.token_teste)
        self.p_env_importar = mock.patch.dict(os.environ, {"NEXTOR_ESTUDOS_IMPORTAR_DE": str(self.tmp.name)})
        # Garante 100% offline bloqueando requisicoes HTTP globais de urllib
        self.p_http = mock.patch("nextor.artigos_cientificos._executar_requisicao", side_effect=RuntimeError("offline_sem_rede"))

        self.p_dir.start()
        self.p_db.start()
        self.p_edir.start()
        self.p_edb.start()
        self.p_token.start()
        self.p_env_importar.start()
        self.p_http.start()

        self.client = servico.app.test_client()
        self.headers = {"X-Nextor-Token": self.token_teste}

    def tearDown(self):
        self.p_http.stop()
        self.p_env_importar.stop()
        self.p_token.stop()
        self.p_edb.stop()
        self.p_edir.stop()
        self.p_db.stop()
        self.p_dir.stop()
        self.tmp.cleanup()


class TestFormatacaoABNT(unittest.TestCase):
    def test_formatar_autor_abnt_unico(self):
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Albert Einstein"), "EINSTEIN, Albert")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Alan Turing"), "TURING, Alan")

    def test_formatar_autor_abnt_multiplos_prenomes(self):
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Alan Mathison Turing"), "TURING, Alan Mathison")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Edsger Wybe Dijkstra"), "DIJKSTRA, Edsger Wybe")

    def test_formatar_autor_abnt_com_sufixos_sobrenome(self):
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Jose Silva Junior"), "SILVA JUNIOR, Jose")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Antonio Carlos Júnior"), "CARLOS JÚNIOR, Antonio")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Pedro Alvares Cabral Filho"), "CABRAL FILHO, Pedro Alvares")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Mario Mendes Neto"), "MENDES NETO, Mario")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Lucas Ferreira Sobrinho"), "FERREIRA SOBRINHO, Lucas")

    def test_formatar_autor_abnt_mononimo_e_vazio(self):
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("Platao"), "PLATAO")
        self.assertEqual(artigos_cientificos.formatar_autor_abnt("   "), "")

    def test_formatar_referencia_abnt_um_autor(self):
        dt = datetime(2026, 11, 4)
        ref = artigos_cientificos.formatar_referencia_abnt(
            autores=["Albert Einstein"],
            titulo="Zur Elektrodynamik bewegter Korper.",
            veiculo_ou_periodico="Annalen der Physik",
            ano=1905,
            url="https://example.org/einstein1905",
            data_acesso=dt,
        )
        esperado = (
            "EINSTEIN, Albert. Zur Elektrodynamik bewegter Korper. "
            "Annalen der Physik, 1905. "
            "Disponivel em: <https://example.org/einstein1905>. Acesso em: 4 nov. 2026."
        )
        self.assertEqual(ref, esperado)

    def test_formatar_referencia_abnt_dois_e_tres_autores(self):
        # 2 autores
        ref2 = artigos_cientificos.formatar_referencia_abnt(
            autores=["Alan Turing", "Alonzo Church"],
            titulo="Computabilidade e Funcoes Recursivas",
            veiculo_ou_periodico="Journal of Symbolic Logic",
            ano=1936,
        )
        self.assertTrue(ref2.startswith("TURING, Alan; CHURCH, Alonzo. Computabilidade e Funcoes Recursivas."))
        self.assertIn("Journal of Symbolic Logic, 1936.", ref2)

        # 3 autores
        ref3 = artigos_cientificos.formatar_referencia_abnt(
            autores=["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"],
            titulo="Deep Learning",
            veiculo_ou_periodico="Nature",
            ano=2015,
        )
        self.assertTrue(ref3.startswith("LECUN, Yann; BENGIO, Yoshua; HINTON, Geoffrey. Deep Learning."))

    def test_formatar_referencia_abnt_quatro_ou_mais_autores_et_al(self):
        autores = ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"]
        ref = artigos_cientificos.formatar_referencia_abnt(
            autores=autores,
            titulo="Attention Is All You Need",
            veiculo_ou_periodico="Advances in Neural Information Processing Systems",
            ano=2017,
        )
        self.assertTrue(ref.startswith("VASWANI, Ashish et al. Attention Is All You Need."))

    def test_formatar_referencia_abnt_autor_desconhecido_e_sem_url(self):
        ref = artigos_cientificos.formatar_referencia_abnt(
            autores=[],
            titulo="Manuscrito Anonimo de Geometria",
            veiculo_ou_periodico="Biblioteca Historica",
            ano=1890,
        )
        self.assertEqual(ref, "AUTOR DESCONHECIDO. Manuscrito Anonimo de Geometria. Biblioteca Historica, 1890.")
        self.assertNotIn("Disponivel em:", ref)


class TestAbstractInvertidoOpenAlex(unittest.TestCase):
    def test_reconstruir_abstract_ordenado(self):
        idx = {
            "linguagens": [2],
            "compiladores": [0],
            "e": [1],
            "otimizadas": [3],
        }
        res = artigos_cientificos.reconstruir_abstract_openalex(idx)
        self.assertEqual(res, "compiladores e linguagens otimizadas")

    def test_reconstruir_abstract_com_palavras_repetidas(self):
        idx = {
            "o": [0, 3],
            "limite": [1],
            "define": [2],
            "calculo": [4],
        }
        res = artigos_cientificos.reconstruir_abstract_openalex(idx)
        self.assertEqual(res, "o limite define o calculo")

    def test_reconstruir_abstract_vazio_ou_nulo(self):
        self.assertEqual(artigos_cientificos.reconstruir_abstract_openalex(None), "")
        self.assertEqual(artigos_cientificos.reconstruir_abstract_openalex({}), "")
        self.assertEqual(artigos_cientificos.reconstruir_abstract_openalex("invalido"), "")


class TestBuscaOpenAlexEArxiv(unittest.TestCase):
    def test_buscar_openalex_sucesso_com_mock_http(self):
        cliente_mock = lambda url, headers: MOCK_OPENALEX_JSON
        res = artigos_cientificos.buscar_openalex("deep learning", limite=2, http_client=cliente_mock)

        self.assertEqual(len(res), 2)
        primeiro = res[0]
        self.assertEqual(primeiro["fonte_api"], "OpenAlex")
        self.assertEqual(primeiro["titulo"], "Deep Learning and Neural Representations")
        self.assertEqual(primeiro["autores"], ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"])
        self.assertEqual(primeiro["ano"], 2015)
        self.assertEqual(primeiro["resumo"], "Deep learning discovers intricate structures in data.")
        self.assertEqual(primeiro["veiculo"], "Nature")
        self.assertEqual(primeiro["pdf_url"], "https://www.nature.com/articles/nature14539.pdf")
        self.assertIn("LECUN, Yann; BENGIO, Yoshua; HINTON, Geoffrey.", primeiro["referencia_abnt"])
        self.assertIn("Nature, 2015.", primeiro["referencia_abnt"])

        # Segundo item com abstract nulo
        segundo = res[1]
        self.assertEqual(segundo["resumo"], "Resumo nao disponibilizado pelo repositorio.")
        self.assertEqual(segundo["pdf_url"], "")

    def test_buscar_openalex_termo_vazio(self):
        res = artigos_cientificos.buscar_openalex("   ")
        self.assertEqual(res, [])

    def test_buscar_openalex_fallback_gracioso_em_erro(self):
        cliente_com_falha = lambda url, headers: (_ for _ in ()).throw(RuntimeError("HTTP 500 Server Error"))
        res = artigos_cientificos.buscar_openalex("deep learning", http_client=cliente_com_falha)
        self.assertEqual(res, [])

    def test_buscar_arxiv_sucesso_com_mock_http(self):
        cliente_mock = lambda url, headers=None: MOCK_ARXIV_XML
        res = artigos_cientificos.buscar_arxiv("transformer", limite=2, http_client=cliente_mock)

        self.assertEqual(len(res), 2)
        art1 = res[0]
        self.assertEqual(art1["fonte_api"], "arXiv")
        self.assertEqual(art1["titulo"], "Attention Is All You Need")
        self.assertEqual(art1["autores"], ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"])
        self.assertEqual(art1["ano"], 2017)
        self.assertEqual(art1["veiculo"], "arXiv")
        self.assertEqual(art1["pdf_url"], "http://arxiv.org/pdf/1706.03762v1")
        self.assertIn("VASWANI, Ashish et al.", art1["referencia_abnt"])

        # Artigo 2 sem link explicito de pdf, gerado automaticamente de /abs/
        art2 = res[1]
        self.assertEqual(art2["titulo"], "Quantum Computing Foundations")
        self.assertEqual(art2["pdf_url"], "http://arxiv.org/pdf/2101.99999v1")

    def test_buscar_arxiv_termo_vazio(self):
        res = artigos_cientificos.buscar_arxiv("   ")
        self.assertEqual(res, [])

    def test_buscar_arxiv_fallback_gracioso_em_erro(self):
        cliente_com_falha = lambda url, headers=None: (_ for _ in ()).throw(ValueError("XML corrompido"))
        res = artigos_cientificos.buscar_arxiv("algebra", http_client=cliente_com_falha)
        self.assertEqual(res, [])


class TestBuscaUnificada(unittest.TestCase):
    def test_buscar_artigos_fonte_openalex(self):
        with mock.patch("nextor.artigos_cientificos.buscar_openalex", return_value=[{"titulo": "Artigo OA"}]) as m_oa:
            with mock.patch("nextor.artigos_cientificos.buscar_arxiv") as m_ar:
                res = artigos_cientificos.buscar_artigos("redes neurais", fonte="openalex", limite=4)
                self.assertEqual(res, [{"titulo": "Artigo OA"}])
                m_oa.assert_called_once()
                m_ar.assert_not_called()

    def test_buscar_artigos_fonte_arxiv(self):
        with mock.patch("nextor.artigos_cientificos.buscar_arxiv", return_value=[{"titulo": "Artigo Arxiv"}]) as m_ar:
            with mock.patch("nextor.artigos_cientificos.buscar_openalex") as m_oa:
                res = artigos_cientificos.buscar_artigos("qubits", fonte="arxiv", limite=3)
                self.assertEqual(res, [{"titulo": "Artigo Arxiv"}])
                m_ar.assert_called_once()
                m_oa.assert_not_called()

    def test_buscar_artigos_fonte_todos_intercala_e_respeita_limite(self):
        lista_oa = [{"titulo": f"OA {i}"} for i in range(1, 4)]
        lista_ar = [{"titulo": f"AR {i}"} for i in range(1, 4)]

        with mock.patch("nextor.artigos_cientificos.buscar_openalex", return_value=lista_oa):
            with mock.patch("nextor.artigos_cientificos.buscar_arxiv", return_value=lista_ar):
                # Limite de 3: deve intercalar OA 1, AR 1, OA 2
                res = artigos_cientificos.buscar_artigos("calculo", fonte="todos", limite=3)
                self.assertEqual(len(res), 3)
                self.assertEqual([r["titulo"] for r in res], ["OA 1", "AR 1", "OA 2"])

    def test_resumo_artigos_falado(self):
        # 0 artigos
        fala_vazia = artigos_cientificos.resumo_artigos_falado([], "biologia quantica")
        self.assertIn("Nao encontrei artigos cientificos sobre biologia quantica", fala_vazia)

        # 1 artigo
        art_unico = [{
            "titulo": "Calculo Diferencial",
            "autores": ["Isaac Newton"],
            "ano": 1687,
        }]
        fala_1 = artigos_cientificos.resumo_artigos_falado(art_unico, "derivadas")
        self.assertIn("Encontrei 1 artigo sobre derivadas", fala_1)
        self.assertIn("Isaac Newton", fala_1)
        self.assertIn("1687", fala_1)

        # Multiplos artigos
        art_multiplos = [
            {"titulo": "Attention Is All You Need", "autores": ["Ashish Vaswani"], "ano": 2017},
            {"titulo": "BERT", "autores": ["Jacob Devlin"], "ano": 2018},
        ]
        fala_m = artigos_cientificos.resumo_artigos_falado(art_multiplos, "transformadores")
        self.assertIn("Encontrei 2 artigos sobre transformadores", fala_m)
        self.assertIn("Attention Is All You Need", fala_m)
        self.assertIn("Deseja que eu salve na sua biblioteca?", fala_m)


class TestSalvarArtigoNaDisciplina(BaseArtigosTestCase):
    def test_salvar_artigo_cria_txt_e_indexa_fts5(self):
        artigo = {
            "titulo": "Attention Is All You Need",
            "autores": ["Ashish Vaswani", "Noam Shazeer"],
            "ano": 2017,
            "veiculo": "NeurIPS",
            "url": "https://arxiv.org/abs/1706.03762",
            "pdf_url": "https://arxiv.org/pdf/1706.03762",
            "resumo": "Modelos baseados exclusivamente em mecanismos de atencao dispensam recorrencia.",
            "referencia_abnt": "VASWANI, Ashish; SHAZEER, Noam. Attention Is All You Need. NeurIPS, 2017.",
        }

        res = artigos_cientificos.salvar_artigo_na_disciplina(
            artigo=artigo,
            disciplina_nome="Inteligencia Artificial",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["disciplina"], "Inteligencia Artificial")
        self.assertEqual(res["titulo"], "Attention Is All You Need")
        self.assertIn("salvo com sucesso", res["aviso"])

        # Confirma que o arquivo .txt foi gravado
        caminho_arquivo = Path(res["caminho"])
        self.assertTrue(caminho_arquivo.exists())
        conteudo = caminho_arquivo.read_text(encoding="utf-8")
        self.assertIn("Artigo Cientifico: Attention Is All You Need", conteudo)
        self.assertIn("Referencia ABNT: VASWANI, Ashish; SHAZEER, Noam.", conteudo)
        self.assertIn("PDF Aberto: https://arxiv.org/pdf/1706.03762", conteudo)
        self.assertIn("Resumo (Abstract):", conteudo)

        # Confirma indexacao no SQLite FTS5
        disc = estudos.obter_disciplina("Inteligencia Artificial", caminho_db=self.db_path)
        materiais = estudos.listar_materiais(disc["nome"], caminho_db=self.db_path)
        self.assertEqual(len(materiais), 1)
        self.assertEqual(materiais[0]["tipo"], "artigo_cientifico")
        self.assertEqual(materiais[0]["titulo"], "Artigo: Attention Is All You Need")

        # Busca FTS5 por termos do artigo
        busca = estudos.buscar_materiais("mecanismos de atencao", caminho_db=self.db_path)
        self.assertTrue(len(busca) >= 1)
        self.assertEqual(busca[0]["titulo"], "Artigo: Attention Is All You Need")

    def test_salvar_artigo_cria_disciplina_automaticamente(self):
        artigo = {
            "titulo": "Principia Mathematica",
            "autores": ["Isaac Newton"],
            "ano": 1687,
            "resumo": "Leis do movimento e da gravitacao universal.",
        }
        res = artigos_cientificos.salvar_artigo_na_disciplina(
            artigo=artigo,
            disciplina_nome="Fisica Classica",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )
        self.assertTrue(res["ok"])
        disc = estudos.obter_disciplina("Fisica Classica", caminho_db=self.db_path)
        self.assertIsNotNone(disc)
        self.assertEqual(disc["nome"], "Fisica Classica")


class TestRoteadorArtigos(BaseArtigosTestCase):
    def test_rotear_gatilhos_busca_artigos(self):
        casos = [
            ("busca artigos sobre inteligencia artificial", "inteligencia artificial", ""),
            ("pesquisar artigos de redes neurais para Computacao", "redes neurais", "Computacao"),
            ("procurar artigo sobre calculo diferencial em Matematica", "calculo diferencial", "Matematica"),
            ("pesquisa artigo de mecânica quântica na disciplina Fisica", "mecânica quântica", "Fisica"),
        ]

        for frase, termo_esperado, disc_esperada in casos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_buscar_artigos", return_value="Resumo falado dos artigos.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_buscar_artigos")
                    self.assertEqual(r["resposta"], "Resumo falado dos artigos.")
                    m.assert_called_once()
                    args, kwargs = m.call_args
                    self.assertEqual(args[0], termo_esperado)
                    if disc_esperada:
                        self.assertEqual(kwargs.get("disciplina"), disc_esperada)

    def test_rotear_gatilhos_salvar_artigo(self):
        casos = [
            ("salvar artigo 1706.03762 na disciplina Computacao", "1706.03762", "Computacao"),
            ("salvar artigo Deep Learning em Inteligencia Artificial", "Deep Learning", "Inteligencia Artificial"),
            ("salvar artigo Teoria da Relatividade para Fisica", "Teoria da Relatividade", "Fisica"),
        ]

        for frase, art_esperado, disc_esperada in casos:
            with self.subTest(frase=frase):
                with mock.patch("nextor.roteador._fazer_estudos_salvar_artigo", return_value="Artigo salvo.") as m:
                    r = roteador.rotear(frase)
                    self.assertEqual(r["intencao"], "estudos_salvar_artigo")
                    self.assertEqual(r["resposta"], "Artigo salvo.")
                    m.assert_called_once_with(art_esperado, disc_esperada)

    def test_rotear_executa_busca_e_salvamento_com_mocks(self):
        fake_art = {
            "titulo": "Quantum Computing",
            "autores": ["David Deutsch"],
            "ano": 1985,
            "resumo": "Fundamentos da computacao quantica.",
        }

        with mock.patch("nextor.artigos_cientificos.buscar_artigos", return_value=[fake_art]):
            r_busca = roteador.rotear("busca artigos sobre computacao quantica")
            self.assertEqual(r_busca["intencao"], "estudos_buscar_artigos")
            self.assertIn("Quantum Computing", r_busca["resposta"])

        with mock.patch("nextor.artigos_cientificos.buscar_artigos", return_value=[fake_art]):
            with mock.patch("nextor.artigos_cientificos.salvar_artigo_na_disciplina", return_value={"ok": True, "aviso": "Artigo salvo com sucesso em Fisica."}):
                r_salva = roteador.rotear("salvar artigo Quantum Computing na disciplina Fisica")
                self.assertEqual(r_salva["intencao"], "estudos_salvar_artigo")
                self.assertIn("Artigo salvo com sucesso em Fisica.", r_salva["resposta"])


class TestServicoArtigosEndpoints(BaseArtigosTestCase):
    def test_buscar_artigos_sem_token_retorna_401(self):
        r_get = self.client.get("/estudos/artigos/buscar?termo=algebra")
        self.assertEqual(r_get.status_code, 401)

        r_post = self.client.post("/estudos/artigos/buscar", json={"termo": "algebra"})
        self.assertEqual(r_post.status_code, 401)

    def test_buscar_artigos_sem_termo_retorna_400(self):
        r = self.client.post("/estudos/artigos/buscar", json={"termo": "   "}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        self.assertIn("obrigatorio", r.get_json()["erro"])

    def test_buscar_artigos_sucesso(self):
        fake_arts = [
            {"titulo": "Artigo 1", "autores": ["Autor A"], "ano": 2021},
            {"titulo": "Artigo 2", "autores": ["Autor B"], "ano": 2022},
        ]
        with mock.patch("nextor.artigos_cientificos.buscar_artigos", return_value=fake_arts) as m_busca:
            r = self.client.post(
                "/estudos/artigos/buscar",
                json={"termo": "machine learning", "fonte": "openalex", "limite": 2},
                headers=self.headers,
            )
            self.assertEqual(r.status_code, 200)
            dados = r.get_json()
            self.assertTrue(dados["ok"])
            self.assertEqual(dados["termo"], "machine learning")
            self.assertEqual(dados["total"], 2)
            self.assertEqual(len(dados["artigos"]), 2)
            m_busca.assert_called_once_with("machine learning", fonte="openalex", limite=2)

    def test_salvar_artigo_sem_token_retorna_401(self):
        r = self.client.post("/estudos/artigos/salvar", json={"disciplina": "Matematica"})
        self.assertEqual(r.status_code, 401)

    def test_salvar_artigo_sem_disciplina_retorna_400(self):
        r = self.client.post("/estudos/artigos/salvar", json={"disciplina": "  "}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        self.assertIn("obrigatorio", r.get_json()["erro"])

    def test_salvar_artigo_com_artigo_dict_sucesso(self):
        artigo_dict = {
            "titulo": "Calculo Vetorial",
            "autores": ["Carl Friedrich Gauss"],
            "ano": 1830,
            "resumo": "Teorema da divergencia e fluxo.",
        }
        r = self.client.post(
            "/estudos/artigos/salvar",
            json={"disciplina": "Calculo III", "artigo": artigo_dict},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["disciplina"], "Calculo III")
        self.assertEqual(dados["titulo"], "Calculo Vetorial")
        self.assertIn("salvo com sucesso", dados["aviso"])

    def test_salvar_artigo_com_campos_soltos_sucesso(self):
        r = self.client.post(
            "/estudos/artigos/salvar",
            json={
                "disciplina": "Geometria",
                "titulo": "Elementos de Geometria",
                "autores": "Euclides de Alexandria, Arquimedes",
                "ano": 1500,
                "resumo": "Postulados fundamentais da geometria euclidiana.",
            },
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        dados = r.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["disciplina"], "Geometria")
        self.assertEqual(dados["titulo"], "Elementos de Geometria")


if __name__ == "__main__":
    unittest.main()
