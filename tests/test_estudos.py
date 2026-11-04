"""Testes da biblioteca de materias de estudos, extratores e busca FTS5. Sem rede."""
import io
import os
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, estudos, roteador, servico


class TestSlugENomes(unittest.TestCase):
    def test_normalizar_slug(self):
        casos = {
            "Cálculo Numérico II": "calculo_numerico_ii",
            "Física 1 - Mecânica!": "fisica_1_mecanica",
            "Álgebra Linear & Geometria": "algebra_linear_geometria",
            "  Estruturas   de Dados  ": "estruturas_de_dados",
            "!!!": "sem_nome",
            "": "sem_nome",
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(estudos.normalizar_slug(entrada), esperado)

    def test_obter_pasta_disciplina(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            pasta = estudos.obter_pasta_disciplina("Cálculo 1", base_dir=base)
            self.assertTrue(pasta.exists())
            self.assertTrue(pasta.is_dir())
            self.assertEqual(pasta.name, "calculo_1")


class TestDisciplinasDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_estudos.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_criar_disciplina_e_obter(self):
        res = estudos.criar_disciplina("Cálculo Diferencial", base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertTrue(res["ok"])
        self.assertEqual(res["nome"], "Cálculo Diferencial")
        self.assertEqual(res["slug"], "calculo_diferencial")

        disc_slug = estudos.obter_disciplina("calculo_diferencial", caminho_db=self.db_path)
        self.assertIsNotNone(disc_slug)
        self.assertEqual(disc_slug["nome"], "Cálculo Diferencial")

        disc_nome = estudos.obter_disciplina("Cálculo Diferencial", caminho_db=self.db_path)
        self.assertIsNotNone(disc_nome)
        self.assertEqual(disc_nome["id"], disc_slug["id"])

    def test_criar_disciplina_nome_vazio(self):
        res = estudos.criar_disciplina("   ", base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertFalse(res["ok"])
        self.assertIn("vazio", res["erro"])

    def test_criar_disciplina_duplicada_atualiza(self):
        res1 = estudos.criar_disciplina("Algebra", base_dir=self.base_dir, caminho_db=self.db_path)
        res2 = estudos.criar_disciplina("Álgebra", base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertTrue(res1["ok"])
        self.assertTrue(res2["ok"])
        self.assertEqual(res1["id"], res2["id"])
        disciplinas = estudos.listar_disciplinas(caminho_db=self.db_path)
        self.assertEqual(len(disciplinas), 1)

    def test_listar_disciplinas_ordenadas(self):
        estudos.criar_disciplina("Física", base_dir=self.base_dir, caminho_db=self.db_path)
        estudos.criar_disciplina("Algoritmos", base_dir=self.base_dir, caminho_db=self.db_path)
        estudos.criar_disciplina("Cálculo", base_dir=self.base_dir, caminho_db=self.db_path)

        lista = estudos.listar_disciplinas(caminho_db=self.db_path)
        nomes = [d["nome"] for d in lista]
        self.assertEqual(nomes, ["Algoritmos", "Cálculo", "Física"])

    def test_resumo_disciplinas(self):
        self.assertIn("nao cadastrou nenhuma", estudos.resumo_disciplinas(caminho_db=self.db_path))

        estudos.criar_disciplina("Calculo", base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertEqual(
            estudos.resumo_disciplinas(caminho_db=self.db_path),
            "Voce tem 1 disciplina cadastrada: Calculo."
        )

        estudos.criar_disciplina("Algebra", base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertEqual(
            estudos.resumo_disciplinas(caminho_db=self.db_path),
            "Voce tem 2 disciplinas: Algebra e Calculo."
        )


class TestExtratores(unittest.TestCase):
    def test_extrair_texto_arquivo_plano(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p_utf8 = Path(tmpdir) / "notas_utf8.txt"
            p_utf8.write_text("Introdução à Cinemática e Vetores", encoding="utf-8")
            self.assertEqual(estudos.extrair_texto_arquivo_plano(p_utf8), "Introdução à Cinemática e Vetores")

            p_lat = Path(tmpdir) / "notas_lat.txt"
            p_lat.write_bytes("Acentuação em Latin-1: maçã e coração".encode("latin-1"))
            self.assertEqual(estudos.extrair_texto_arquivo_plano(p_lat), "Acentuação em Latin-1: maçã e coração")

    def test_extrair_texto_docx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p_docx = Path(tmpdir) / "aula.docx"
            xml_content = (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b'<w:body>'
                b'<w:p><w:r><w:t>Primeiro paragrafo de calculo.</w:t></w:r></w:p>'
                b'<w:p><w:r><w:t>Segundo paragrafo: limites e derivadas.</w:t></w:r></w:p>'
                b'</w:body>'
                b'</w:document>'
            )
            with zipfile.ZipFile(p_docx, "w") as z:
                z.writestr("word/document.xml", xml_content)

            texto = estudos.extrair_texto_docx(p_docx)
            self.assertIn("Primeiro paragrafo de calculo.", texto)
            self.assertIn("Segundo paragrafo: limites e derivadas.", texto)

    def test_extrair_texto_docx_corrompido(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p_bad = Path(tmpdir) / "invalido.docx"
            p_bad.write_text("isto nao e um zip", encoding="utf-8")
            self.assertEqual(estudos.extrair_texto_docx(p_bad), "")

    def test_extrair_texto_pdf_com_mock(self):
        fake_page = mock.Mock()
        fake_page.extract_text.return_value = "Teorema Fundamental do Calculo"
        fake_reader = mock.Mock()
        fake_reader.pages = [fake_page]

        with mock.patch.object(estudos, "pypdf") as mock_pypdf:
            mock_pypdf.PdfReader.return_value = fake_reader
            texto = estudos.extrair_texto_pdf(Path("dummy.pdf"))
            self.assertEqual(texto, "Teorema Fundamental do Calculo")

    def test_extrair_texto_pdf_sem_pypdf(self):
        with mock.patch.object(estudos, "pypdf", None):
            self.assertEqual(estudos.extrair_texto_pdf(Path("dummy.pdf")), "")

    def test_extrair_texto_html(self):
        html_doc = """
        <html>
            <head>
                <title>Aula de Geometria Analitica</title>
                <style>body { font-size: 14px; }</style>
                <script>alert('teste');</script>
            </head>
            <body>
                <h1>Vetores no Espaco</h1>
                <p>O produto escalar &amp; produto vetorial sao fundamentais.</p>
            </body>
        </html>
        """
        titulo, texto = estudos.extrair_texto_html(html_doc)
        self.assertEqual(titulo, "Aula de Geometria Analitica")
        self.assertNotIn("alert", texto)
        self.assertNotIn("font-size", texto)
        self.assertIn("Vetores no Espaco", texto)
        self.assertIn("produto escalar & produto vetorial", texto)

    def test_baixar_link_offline(self):
        fake_html = b"<html><head><title>Artigo Cientifico</title></head><body>Resumo do estudo</body></html>"
        fake_resp = mock.MagicMock()
        fake_resp.headers.get.side_effect = lambda k, d=None: {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(fake_html)),
        }.get(k, d)
        fake_resp.headers.get_content_charset.return_value = "utf-8"
        fake_resp.read.side_effect = [fake_html, b""]
        fake_resp.__enter__.return_value = fake_resp

        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]), \
             mock.patch("urllib.request.urlopen", return_value=fake_resp):
            titulo, texto = estudos.baixar_link("https://exemplo.org/artigo")
            self.assertEqual(titulo, "Artigo Cientifico")
            self.assertIn("Resumo do estudo", texto)


class TestMateriaisEBuscaFTS5(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "test_estudos.db"
        self.p_env_importar = mock.patch.dict(os.environ, {"NEXTOR_ESTUDOS_IMPORTAR_DE": str(self.tmp.name)})
        self.p_env_importar.start()
        estudos.criar_disciplina("Fisica", base_dir=self.base_dir, caminho_db=self.db_path)

    def tearDown(self):
        self.p_env_importar.stop()
        self.tmp.cleanup()

    def test_importar_material_txt_e_copia_para_pasta(self):
        origem = Path(self.tmp.name) / "cinematica.txt"
        origem.write_text("Movimento retilineo uniforme e aceleracao da gravidade.", encoding="utf-8")

        res = estudos.importar_material(
            "Fisica",
            origem,
            titulo="Cinematica Basica",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["disciplina"], "Fisica")
        self.assertEqual(res["tipo"], "txt")
        self.assertTrue(Path(res["caminho"]).exists())

        materiais = estudos.listar_materiais("Fisica", caminho_db=self.db_path)
        self.assertEqual(len(materiais), 1)
        self.assertEqual(materiais[0]["titulo"], "Cinematica Basica")

    def test_importar_material_inexistente(self):
        res = estudos.importar_material(
            "Fisica",
            Path(self.tmp.name) / "fantasma.pdf",
            base_dir=self.base_dir,
            caminho_db=self.db_path,
        )
        self.assertFalse(res["ok"])
        self.assertIn("Arquivo nao encontrado", res["erro"])

    def test_importar_material_link(self):
        with mock.patch.object(estudos, "baixar_link", return_value=("Leis de Newton", "Primeira e segunda lei de Newton")):
            res = estudos.importar_material(
                "Fisica",
                "https://fisica.exemplo.com/newton",
                base_dir=self.base_dir,
                caminho_db=self.db_path,
            )
        self.assertTrue(res["ok"])
        self.assertEqual(res["tipo"], "link")
        self.assertEqual(res["titulo"], "Leis de Newton")
        self.assertTrue(Path(res["caminho"]).exists())

    def test_resumo_materiais(self):
        self.assertEqual(estudos.resumo_materiais("Quimica", caminho_db=self.db_path), "A disciplina Quimica ainda nao existe.")
        self.assertEqual(estudos.resumo_materiais("Fisica", caminho_db=self.db_path), "Nenhum material encontrado para Fisica.")

        origem1 = Path(self.tmp.name) / "m1.txt"
        origem1.write_text("texto 1", encoding="utf-8")
        estudos.importar_material("Fisica", origem1, titulo="Termodinamica", base_dir=self.base_dir, caminho_db=self.db_path)
        self.assertEqual(estudos.resumo_materiais("Fisica", caminho_db=self.db_path), "Na disciplina Fisica voce tem 1 material: Termodinamica.")

        origem2 = Path(self.tmp.name) / "m2.txt"
        origem2.write_text("texto 2", encoding="utf-8")
        estudos.importar_material("Fisica", origem2, titulo="Optica", base_dir=self.base_dir, caminho_db=self.db_path)
        resumo = estudos.resumo_materiais("Fisica", caminho_db=self.db_path)
        self.assertTrue(resumo.startswith("Na disciplina Fisica voce tem 2 materiais:"))
        self.assertIn("Optica", resumo)
        self.assertIn("Termodinamica", resumo)

    def test_busca_fts5_geral_e_por_disciplina(self):
        estudos.criar_disciplina("Calculo", base_dir=self.base_dir, caminho_db=self.db_path)

        arq_fis = Path(self.tmp.name) / "ondas.txt"
        arq_fis.write_text("Estudo da propagacao de ondas eletromagneticas e frequencia ressonante.", encoding="utf-8")
        estudos.importar_material("Fisica", arq_fis, titulo="Ondas", base_dir=self.base_dir, caminho_db=self.db_path)

        arq_calc = Path(self.tmp.name) / "series.txt"
        arq_calc.write_text("Analise de Fourier e frequencia em series trigonometricas.", encoding="utf-8")
        estudos.importar_material("Calculo", arq_calc, titulo="Series de Fourier", base_dir=self.base_dir, caminho_db=self.db_path)

        res_geral = estudos.buscar_materiais("frequencia", caminho_db=self.db_path)
        self.assertEqual(len(res_geral), 2)
        titulos = {r["titulo"] for r in res_geral}
        self.assertEqual(titulos, {"Ondas", "Series de Fourier"})

        res_filtrado = estudos.buscar_materiais("frequencia", disciplina_nome="Calculo", caminho_db=self.db_path)
        self.assertEqual(len(res_filtrado), 1)
        self.assertEqual(res_filtrado[0]["titulo"], "Series de Fourier")

        res_vazio = estudos.buscar_materiais("inexistente_termo_xyz", caminho_db=self.db_path)
        self.assertEqual(res_vazio, [])

        res_sem_termo = estudos.buscar_materiais("   ", caminho_db=self.db_path)
        self.assertEqual(res_sem_termo, [])

    def test_resumo_busca(self):
        arq = Path(self.tmp.name) / "vetores.txt"
        arq.write_text("Grandeza vetorial e produto escalar.", encoding="utf-8")
        estudos.importar_material("Fisica", arq, titulo="Vetores", base_dir=self.base_dir, caminho_db=self.db_path)

        resumo1 = estudos.resumo_busca("vetorial", disciplina_nome="Fisica", caminho_db=self.db_path)
        self.assertEqual(resumo1, "Encontrei 1 material sobre vetorial em Fisica: Vetores.")

        resumo_nenhum = estudos.resumo_busca("relatividade", disciplina_nome="Fisica", caminho_db=self.db_path)
        self.assertEqual(resumo_nenhum, "Nao encontrei nenhum material sobre relatividade em Fisica.")


class TestSegurancaEstudos(unittest.TestCase):
    """Testes de seguranca essenciais: mitigacao de Path Traversal e SSRF."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta_autorizada = Path(self.tmp.name) / "autorizada"
        self.pasta_autorizada.mkdir(parents=True, exist_ok=True)
        self.pasta_externa = Path(self.tmp.name) / "externa"
        self.pasta_externa.mkdir(parents=True, exist_ok=True)
        self.base_estudos = Path(self.tmp.name) / "dados_estudos"
        self.db_path = self.base_estudos / "seguranca.db"

        self.p_env = mock.patch.dict(os.environ, {"NEXTOR_ESTUDOS_IMPORTAR_DE": str(self.pasta_autorizada)})
        self.p_env.start()
        estudos.criar_disciplina("Seguranca", base_dir=self.base_estudos, caminho_db=self.db_path)

    def tearDown(self):
        self.p_env.stop()
        self.tmp.cleanup()

    def test_recusa_arquivos_env_e_sensiveis(self):
        # Arquivo .env
        env_file = self.pasta_autorizada / ".env"
        env_file.write_text("SEGREDO=123", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            estudos.validar_caminho_local(env_file, pastas_autorizadas=[self.pasta_autorizada])
        self.assertIn("ocultos nao sao permitidos", str(ctx.exception))

        # Arquivo .env.prod
        env_prod = self.pasta_autorizada / ".env.prod"
        env_prod.write_text("TOKEN=xyz", encoding="utf-8")
        with self.assertRaises(ValueError):
            estudos.validar_caminho_local(env_prod, pastas_autorizadas=[self.pasta_autorizada])

        # Arquivo sensivel com extensao proibida
        pem_file = self.pasta_autorizada / "chave.pem"
        pem_file.write_text("CERT", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx_pem:
            estudos.validar_caminho_local(pem_file, pastas_autorizadas=[self.pasta_autorizada])
        self.assertIn("Extensao '.pem' nao permitida", str(ctx_pem.exception))

        # Arquivo sensivel chamado secret.txt
        sec_file = self.pasta_autorizada / "secret.txt"
        sec_file.write_text("senhas", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx_sec:
            estudos.validar_caminho_local(sec_file, pastas_autorizadas=[self.pasta_autorizada])
        self.assertIn("recusado por regras de seguranca", str(ctx_sec.exception))

    def test_recusa_arquivo_fora_de_pastas_autorizadas(self):
        fora = self.pasta_externa / "material_fora.txt"
        fora.write_text("Conteudo de fora.", encoding="utf-8")

        # Tentar validar caminho fora das pastas autorizadas
        with self.assertRaises(ValueError) as ctx:
            estudos.validar_caminho_local(fora, pastas_autorizadas=[self.pasta_autorizada])
        self.assertIn("fora das pastas autorizadas", str(ctx.exception))

        # Tentar importar via importar_material
        res = estudos.importar_material(
            "Seguranca",
            fora,
            base_dir=self.base_estudos,
            caminho_db=self.db_path,
            pastas_autorizadas=[self.pasta_autorizada],
        )
        self.assertFalse(res["ok"])
        self.assertIn("fora das pastas autorizadas", res["erro"])

    def test_recusa_path_traversal_com_pontos(self):
        # Criar arquivo fora da pasta autorizada
        externo = self.pasta_externa / "privado.txt"
        externo.write_text("privado", encoding="utf-8")

        # Construir caminho com traversal relativo a partir da pasta autorizada
        caminho_traversal = self.pasta_autorizada / ".." / "externa" / "privado.txt"
        with self.assertRaises(ValueError) as ctx:
            estudos.validar_caminho_local(caminho_traversal, pastas_autorizadas=[self.pasta_autorizada])
        self.assertIn("fora das pastas autorizadas", str(ctx.exception))

    def test_recusa_ssrf_ips_privados_e_loopback(self):
        urls_proibidas = [
            "http://127.0.0.1/admin",
            "http://127.0.0.1:8000/api",
            "http://localhost:5005/notas",
            "http://localhost.localdomain/info",
            "http://192.168.1.1/config",
            "http://192.168.0.254/router",
            "http://10.0.0.1/intranet",
            "http://172.16.0.1/dashboard",
            "http://169.254.169.254/latest/meta-data/",
            "ftp://exemplo.com/arquivo.txt",
        ]
        for url in urls_proibidas:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    estudos.validar_url_segura(url)

    def test_recusa_ssrf_resolucao_dns_privada(self):
        # Simula dominio aparentemente externo que resolve para 127.0.0.1 (DNS rebinding / SSRF)
        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaises(ValueError) as ctx:
                estudos.validar_url_segura("http://meu-host-interno.com/api")
            self.assertIn("Acesso bloqueado ao IP 127.0.0.1", str(ctx.exception))

        # Simula resolucao para 192.168.1.50
        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80))]):
            with self.assertRaises(ValueError) as ctx:
                estudos.validar_url_segura("http://servidor-rede-local.com/api")
            self.assertIn("Acesso bloqueado ao IP 192.168.1.50", str(ctx.exception))

    def test_download_acima_de_10mb_content_length(self):
        fake_resp = mock.MagicMock()
        fake_resp.headers.get.side_effect = lambda k, d=None: {
            "Content-Type": "text/html",
            "Content-Length": str(15 * 1024 * 1024),
        }.get(k, d)
        fake_resp.read.return_value = b""
        fake_resp.__enter__.return_value = fake_resp

        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]), \
             mock.patch("urllib.request.urlopen", return_value=fake_resp):
            with self.assertRaises(ValueError) as ctx:
                estudos.baixar_link("https://exemplo.org/grande.html")
            self.assertIn("excede o limite de 10 MB", str(ctx.exception))

    def test_download_acima_de_10mb_streaming_chunks(self):
        # Sem header Content-Length, mas enviando mais de 10 MB em blocos
        fake_resp = mock.MagicMock()
        fake_resp.headers.get.side_effect = lambda k, d=None: {
            "Content-Type": "text/html",
        }.get(k, d)
        fake_resp.headers.get_content_charset.return_value = "utf-8"
        # 11 blocos de 1 MB
        bloco = b"X" * (1024 * 1024)
        fake_resp.read.side_effect = [bloco] * 11 + [b""]
        fake_resp.__enter__.return_value = fake_resp

        with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]), \
             mock.patch("urllib.request.urlopen", return_value=fake_resp):
            with self.assertRaises(ValueError) as ctx:
                estudos.baixar_link("https://exemplo.org/stream.html")
            self.assertIn("Download interrompido: o conteudo excedeu o limite maximo de 10 MB", str(ctx.exception))

    def test_canal_remoto_recusa_caminho_local(self):
        arquivo = self.pasta_autorizada / "aula.txt"
        arquivo.write_text("aula", encoding="utf-8")

        # Via importar_material
        res = estudos.importar_material(
            "Seguranca",
            arquivo,
            canal="remoto",
            base_dir=self.base_estudos,
            caminho_db=self.db_path,
        )
        self.assertFalse(res["ok"])
        self.assertIn("Canal remoto aceita apenas links", res["erro"])

        # Canal remoto com link e aceito
        with mock.patch.object(estudos, "baixar_link", return_value=("Titulo Web", "Conteudo Web")):
            res_link = estudos.importar_material(
                "Seguranca",
                "https://exemplo.org/aula",
                canal="remoto",
                base_dir=self.base_estudos,
                caminho_db=self.db_path,
            )
        self.assertTrue(res_link["ok"])


class TestRoteadorEstudos(unittest.TestCase):
    def test_rotear_criar_disciplina(self):
        with mock.patch("nextor.roteador._fazer_estudos_criar_disciplina", return_value="Disciplina Calculo criada.") as m:
            r = roteador.rotear("nova disciplina Calculo 1")
            self.assertEqual(r["intencao"], "estudos_criar_disciplina")
            self.assertEqual(r["resposta"], "Disciplina Calculo criada.")
            m.assert_called_once_with("Calculo 1")

    def test_rotear_adicionar_material(self):
        with mock.patch("nextor.roteador._fazer_estudos_adicionar", return_value="Material adicionado.") as m:
            r = roteador.rotear("adicionar notas.txt em Calculo")
            self.assertEqual(r["intencao"], "estudos_adicionar")
            self.assertEqual(r["resposta"], "Material adicionado.")
            m.assert_called_once_with("Calculo", "notas.txt")

    def test_rotear_adicionar_material_canal_remoto(self):
        with mock.patch("nextor.roteador._fazer_estudos_adicionar", return_value="Canal remoto aceita apenas links.") as m:
            r = roteador.rotear("adicionar notas.txt em Calculo", canal="remoto")
            self.assertEqual(r["intencao"], "estudos_adicionar")
            m.assert_called_once_with("Calculo", "notas.txt", canal="remoto")

    def test_rotear_listar_materiais(self):
        with mock.patch("nextor.roteador._fazer_estudos_listar_materiais", return_value="Na disciplina Calculo voce tem 1 material.") as m:
            r = roteador.rotear("o que tenho de material de Calculo")
            self.assertEqual(r["intencao"], "estudos_listar_materiais")
            m.assert_called_once_with("Calculo")

    def test_rotear_listar_disciplinas(self):
        with mock.patch("nextor.roteador._fazer_estudos_listar_disciplinas", return_value="Voce tem 2 disciplinas.") as m:
            r = roteador.rotear("minhas disciplinas")
            self.assertEqual(r["intencao"], "estudos_listar_disciplinas")
            m.assert_called_once()

    def test_rotear_buscar(self):
        with mock.patch("nextor.roteador._fazer_estudos_buscar", return_value="Encontrei 1 material.") as m:
            r = roteador.rotear("busca material sobre derivadas em Calculo")
            self.assertEqual(r["intencao"], "estudos_buscar")
            m.assert_called_once_with("derivadas", "Calculo")


class TestServicoEstudosEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name) / "estudos"
        self.db_path = self.base_dir / "servico_estudos.db"
        self.pasta_autorizada = Path(self.tmp.name) / "autorizada"
        self.pasta_autorizada.mkdir(parents=True, exist_ok=True)

        self.p_token = mock.patch.object(config, "TOKEN", "token-teste")
        self.p_dir = mock.patch.object(config, "ESTUDOS_DIR", self.base_dir)
        self.p_db = mock.patch.object(config, "ESTUDOS_DB", self.db_path)
        self.p_edir = mock.patch.object(estudos.config, "ESTUDOS_DIR", self.base_dir)
        self.p_edb = mock.patch.object(estudos.config, "ESTUDOS_DB", self.db_path)
        self.p_env_importar = mock.patch.dict(os.environ, {"NEXTOR_ESTUDOS_IMPORTAR_DE": str(self.pasta_autorizada)})

        self.p_token.start()
        self.p_dir.start()
        self.p_db.start()
        self.p_edir.start()
        self.p_edb.start()
        self.p_env_importar.start()

        self.client = servico.app.test_client()
        self.headers = {"X-Nextor-Token": "token-teste"}

    def tearDown(self):
        self.p_env_importar.stop()
        self.p_edb.stop()
        self.p_edir.stop()
        self.p_db.stop()
        self.p_dir.stop()
        self.p_token.stop()
        self.tmp.cleanup()

    def test_endpoints_exigem_token(self):
        self.assertEqual(self.client.get("/estudos/disciplinas").status_code, 401)
        self.assertEqual(self.client.post("/estudos/disciplinas").status_code, 401)
        self.assertEqual(self.client.get("/estudos/disciplinas/calculo/materiais").status_code, 401)
        self.assertEqual(self.client.get("/estudos/buscar?q=algo").status_code, 401)

    def test_criar_e_listar_disciplinas_api(self):
        r_post = self.client.post(
            "/estudos/disciplinas",
            json={"nome": "Algoritmos e Estruturas"},
            headers=self.headers,
        )
        self.assertEqual(r_post.status_code, 200)
        self.assertTrue(r_post.get_json()["ok"])
        self.assertEqual(r_post.get_json()["slug"], "algoritmos_e_estruturas")

        r_get = self.client.get("/estudos/disciplinas", headers=self.headers)
        self.assertEqual(r_get.status_code, 200)
        dados = r_get.get_json()
        self.assertTrue(dados["ok"])
        self.assertEqual(len(dados["disciplinas"]), 1)
        self.assertEqual(dados["disciplinas"][0]["nome"], "Algoritmos e Estruturas")

    def test_criar_disciplina_invalida_api(self):
        r = self.client.post("/estudos/disciplinas", json={"nome": ""}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        self.assertIn("erro", r.get_json())

    def test_importar_material_json_api(self):
        self.client.post("/estudos/disciplinas", json={"nome": "Redes"}, headers=self.headers)

        origem = self.pasta_autorizada / "tcp_ip.txt"
        origem.write_text("Camada de transporte e protocolo TCP/IP.", encoding="utf-8")

        r = self.client.post(
            "/estudos/disciplinas/Redes/materiais",
            json={"origem": str(origem), "titulo": "Protocolo TCP"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(r.get_json()["titulo"], "Protocolo TCP")

        r_list = self.client.get("/estudos/disciplinas/Redes/materiais", headers=self.headers)
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(len(r_list.get_json()["materiais"]), 1)

    def test_importar_material_canal_remoto_recusa_local_api(self):
        self.client.post("/estudos/disciplinas", json={"nome": "Redes"}, headers=self.headers)

        # Requisicao com canal remoto enviando caminho local
        r_json = self.client.post(
            "/estudos/disciplinas/Redes/materiais",
            json={"origem": "C:/documentos/teste.txt", "canal": "remoto"},
            headers=self.headers,
        )
        self.assertEqual(r_json.status_code, 400)
        self.assertIn("Canal remoto aceita apenas links", r_json.get_json()["erro"])

        # Requisicao com header X-Nextor-Canal: remoto e upload multipart
        arquivo_bytes = io.BytesIO(b"conteudo")
        r_upload = self.client.post(
            "/estudos/disciplinas/Redes/materiais",
            data={"arquivo": (arquivo_bytes, "remoto.txt")},
            content_type="multipart/form-data",
            headers={**self.headers, "X-Nextor-Canal": "remoto"},
        )
        self.assertEqual(r_upload.status_code, 400)
        self.assertIn("canal remoto nao permite upload", r_upload.get_json()["erro"])

    def test_importar_material_upload_arquivo_api(self):
        self.client.post("/estudos/disciplinas", json={"nome": "Sistemas Operacionais"}, headers=self.headers)

        arquivo_bytes = io.BytesIO(b"Processos, threads e escalonamento preemptivo.")
        r = self.client.post(
            "/estudos/disciplinas/sistemas_operacionais/materiais",
            data={
                "arquivo": (arquivo_bytes, "escalonamento.txt"),
                "titulo": "Resumo Escalonamento",
            },
            content_type="multipart/form-data",
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(r.get_json()["titulo"], "Resumo Escalonamento")

    def test_buscar_materiais_api(self):
        self.client.post("/estudos/disciplinas", json={"nome": "Estatistica"}, headers=self.headers)

        arquivo_bytes = io.BytesIO(b"Distribuicao normal, variancia e desvio padrao.")
        self.client.post(
            "/estudos/disciplinas/Estatistica/materiais",
            data={"arquivo": (arquivo_bytes, "normal.txt")},
            content_type="multipart/form-data",
            headers=self.headers,
        )

        r_sem_q = self.client.get("/estudos/buscar", headers=self.headers)
        self.assertEqual(r_sem_q.status_code, 400)

        r_busca = self.client.get("/estudos/buscar?q=variancia", headers=self.headers)
        self.assertEqual(r_busca.status_code, 200)
        res = r_busca.get_json()
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["resultados"]), 1)
        self.assertEqual(res["resultados"][0]["disciplina"], "Estatistica")
