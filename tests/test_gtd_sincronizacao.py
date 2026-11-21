"""Testes offline da sincronizacao do GTD com Notion, GitHub e anotacoes do Nextor (Issue #42).

Todas as APIs sao simuladas em memoria: nenhum teste abre conexao de rede.
"""
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

os.environ["NEXTOR_VOZ_SAIDA"] = "nenhuma"

from nextor import config, servico  # noqa: E402
from nextor.gtd.armazenamento import ArmazenamentoGTD  # noqa: E402
from nextor.gtd.configuracao import carregar_config, normalizar_sincronizacao, salvar_config  # noqa: E402
from nextor.gtd.integracoes import sincronizar_notion, sincronizar_tudo, tarefas_do_github  # noqa: E402
from nextor.gtd.modelos import Item, Leitura  # noqa: E402
from nextor.gtd.notion import ClienteNotion  # noqa: E402
from nextor.gtd.sync_github import aplicar_evento_webhook, sincronizar_github  # noqa: E402
from nextor.gtd.sync_nextor import sincronizar_nextor  # noqa: E402

TOKEN_NOTION = "secret_notion_teste_nao_vazar_123"

ESQUEMA_TAREFAS = {
    "Tarefa": {"type": "title", "title": {}},
    "Status": {"type": "status", "status": {"options": [
        {"name": "Nao iniciado"}, {"name": "Em andamento"}, {"name": "Concluido"}, {"name": "Aguardando"},
    ]}},
    "Contexto": {"type": "select", "select": {"options": []}},
    "Prazo": {"type": "date", "date": {}},
    "Projeto": {"type": "relation", "relation": {}},
}
ESQUEMA_PROJETOS = {
    "Nome": {"type": "title", "title": {}},
    "Estado": {"type": "select", "select": {"options": [{"name": "Ativo"}, {"name": "Concluido"}]}},
}
ESQUEMA_LEITURAS = {
    "Titulo": {"type": "title", "title": {}},
    "Lido": {"type": "checkbox", "checkbox": {}},
    "Autor": {"type": "rich_text", "rich_text": {}},
    "Paginas": {"type": "number", "number": {}},
}


def _valor_para_prop(defn, valor):
    tipo = defn["type"]
    if tipo == "title":
        return {"type": "title", "title": [{"plain_text": valor}]}
    if tipo == "rich_text":
        return {"type": "rich_text", "rich_text": [{"plain_text": valor}]}
    if tipo == "status":
        return {"type": "status", "status": {"name": valor}}
    if tipo == "select":
        return {"type": "select", "select": {"name": valor} if valor else None}
    if tipo == "date":
        return {"type": "date", "date": {"start": valor} if valor else None}
    if tipo == "relation":
        return {"type": "relation", "relation": [{"id": i} for i in valor]}
    if tipo == "checkbox":
        return {"type": "checkbox", "checkbox": bool(valor)}
    if tipo == "number":
        return {"type": "number", "number": valor}
    raise AssertionError(tipo)


class NotionFalso:
    """Simula as rotas da API do Notion usadas pelo ClienteNotion."""

    def __init__(self, esquemas, tamanho_pagina=100):
        self.esquemas = esquemas
        self.paginas = {db: {} for db in esquemas}
        self.relogio = 0
        self.chamadas = []
        self.tamanho_pagina = tamanho_pagina
        self.headers_vistos = []

    def _carimbo(self):
        self.relogio += 1
        return f"2026-11-20T10:{self.relogio:02d}:00.000Z"

    def adicionar(self, db, page_id, valores, arquivada=False):
        esquema = self.esquemas[db]
        # Como no Notion real, a pagina traz todas as propriedades da base (vazias se nao preenchidas).
        props = {nome: _valor_vazio(defn) for nome, defn in esquema.items()}
        props.update({nome: _valor_para_prop(esquema[nome], v) for nome, v in valores.items()})
        self.paginas[db][page_id] = {"id": page_id, "properties": props, "archived": arquivada,
                                     "last_edited_time": self._carimbo(), "_db": db}
        return self.paginas[db][page_id]

    def editar(self, db, page_id, valores):
        pag = self.paginas[db][page_id]
        for nome, v in valores.items():
            pag["properties"][nome] = _valor_para_prop(self.esquemas[db][nome], v)
        pag["last_edited_time"] = self._carimbo()

    def escritas(self):
        return [c for c in self.chamadas if c[0] in ("POST", "PATCH") and not c[1].endswith("/query")]

    def __call__(self, url, metodo, dados, headers):
        self.headers_vistos.append(headers)
        caminho = url.replace("https://api.notion.com/v1", "")
        self.chamadas.append((metodo, caminho, dados))
        partes = caminho.strip("/").split("/")
        if partes[0] == "databases" and len(partes) == 3 and partes[2] == "query":
            todas = list(self.paginas[partes[1]].values())
            inicio = int((dados or {}).get("start_cursor") or 0)
            fatia = todas[inicio:inicio + self.tamanho_pagina]
            mais = inicio + self.tamanho_pagina < len(todas)
            return 200, {"results": fatia, "has_more": mais,
                         "next_cursor": str(inicio + self.tamanho_pagina) if mais else None}
        if partes[0] == "databases" and len(partes) == 2 and metodo == "GET":
            return 200, {"properties": self.esquemas[partes[1]]}
        if caminho == "/pages" and metodo == "POST":
            db = dados["parent"]["database_id"]
            page_id = f"pag-nova-{len(self.paginas[db]) + 1}-{db}"
            props = {}
            for nome, p in dados["properties"].items():
                tipo = self.esquemas[db][nome]["type"]
                props[nome] = dict(p, type=tipo)
            pag = {"id": page_id, "properties": props, "archived": False,
                   "last_edited_time": self._carimbo(), "_db": db}
            self.paginas[db][page_id] = pag
            return 200, pag
        if partes[0] == "pages" and metodo == "PATCH":
            for db, pags in self.paginas.items():
                if partes[1] in pags:
                    pag = pags[partes[1]]
                    for nome, p in dados["properties"].items():
                        pag["properties"][nome] = dict(p, type=self.esquemas[db][nome]["type"])
                    pag["last_edited_time"] = self._carimbo()
                    return 200, pag
            return 404, {}
        return 404, {}


def _valor_vazio(defn):
    tipo = defn["type"]
    vazios = {"title": [], "rich_text": [], "status": None, "select": None, "date": None,
              "relation": [], "checkbox": False, "number": None}
    return {"type": tipo, tipo: vazios[tipo]}


def _texto(prop):
    chave = prop["type"]
    if chave in ("title", "rich_text"):
        return "".join(t.get("plain_text") or t.get("text", {}).get("content", "") for t in prop[chave])
    return prop.get(chave)


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.banco = ArmazenamentoGTD(Path(self.tmp.name) / "sync.db")

    def tearDown(self):
        self.tmp.cleanup()


class TestNotionMaoDupla(BaseBanco):
    def _cliente(self, falso, tarefas="db-t", projetos="", leituras=""):
        return ClienteNotion(token=TOKEN_NOTION, db_tarefas=tarefas, db_projetos=projetos,
                             db_leituras=leituras, http_client=falso)

    def test_importa_tarefas_com_estado_contexto_prazo_e_projeto(self):
        falso = NotionFalso({"db-t": ESQUEMA_TAREFAS, "db-p": ESQUEMA_PROJETOS})
        falso.adicionar("db-p", "proj-1", {"Nome": "TCC", "Estado": "Ativo"})
        falso.adicionar("db-t", "t-1", {"Tarefa": "Escrever introducao", "Status": "Em andamento",
                                        "Contexto": "@faculdade", "Prazo": "2026-11-30", "Projeto": ["proj-1"]})
        falso.adicionar("db-t", "t-2", {"Tarefa": "Entregar resumo", "Status": "Concluido"})
        falso.adicionar("db-t", "t-3", {"Tarefa": "Arquivada"}, arquivada=True)

        res = sincronizar_notion(db=self.banco, cliente=self._cliente(falso, projetos="db-p"))

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tarefas_puxadas"], 2)
        self.assertEqual(res["projetos_sincronizados"], 1)
        itens = {i.titulo: i for i in self.banco.listar_itens()}
        self.assertEqual(set(itens), {"Escrever introducao", "Entregar resumo"})
        intro = itens["Escrever introducao"]
        self.assertEqual(intro.estado, "proxima")
        self.assertEqual(intro.contexto, "@faculdade")
        self.assertEqual(intro.prazo, "2026-11-30")
        projeto = self.banco.listar_projetos()[0]
        self.assertEqual(projeto.nome, "TCC")
        self.assertEqual(intro.projeto_id, projeto.id)
        self.assertEqual(itens["Entregar resumo"].estado, "feito")
        self.assertIsNotNone(itens["Entregar resumo"].concluido_em)
        # Importar nao escreve nada no Notion quando nada mudou localmente.
        self.assertEqual(falso.escritas(), [])

    def test_mudanca_remota_atualiza_local_e_segunda_rodada_e_idempotente(self):
        falso = NotionFalso({"db-t": ESQUEMA_TAREFAS})
        falso.adicionar("db-t", "t-1", {"Tarefa": "Ler capitulo 3", "Status": "Nao iniciado"})
        cliente = self._cliente(falso)
        sincronizar_notion(db=self.banco, cliente=cliente)

        falso.editar("db-t", "t-1", {"Tarefa": "Ler capitulo 3 e 4", "Status": "Concluido"})
        res = sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(res["detalhes"]["tarefas"]["atualizadas_local"], 1)
        item = self.banco.listar_itens()[0]
        self.assertEqual(item.titulo, "Ler capitulo 3 e 4")
        self.assertEqual(item.estado, "feito")

        res3 = sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(res3["sincronizados"], 0)
        self.assertEqual(falso.escritas(), [])

    def test_mudanca_local_e_enviada_com_tipos_da_base(self):
        falso = NotionFalso({"db-t": ESQUEMA_TAREFAS})
        falso.adicionar("db-t", "t-1", {"Tarefa": "Revisar slides", "Status": "Nao iniciado"})
        cliente = self._cliente(falso)
        sincronizar_notion(db=self.banco, cliente=cliente)

        item = self.banco.listar_itens()[0]
        item.estado = "feito"
        item.prazo = "2026-12-01"
        self.banco.salvar_item(item)

        res = sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(res["detalhes"]["tarefas"]["atualizadas_remoto"], 1)
        metodo, caminho, dados = falso.escritas()[-1]
        self.assertEqual((metodo, caminho), ("PATCH", "/pages/t-1"))
        # Status do tipo "status" usa a opcao existente equivalente a "feito".
        self.assertEqual(dados["properties"]["Status"], {"status": {"name": "Concluido"}})
        self.assertEqual(dados["properties"]["Prazo"], {"date": {"start": "2026-12-01"}})
        # A edicao que o proprio Nextor fez nao volta como mudanca remota.
        res2 = sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(res2["sincronizados"], 0)

    def test_conflito_respeita_politica(self):
        for politica, titulo_esperado in (("remoto", "Titulo do Notion"), ("local", "Titulo do painel")):
            with self.subTest(politica=politica):
                banco = ArmazenamentoGTD(Path(self.tmp.name) / f"conf-{politica}.db")
                falso = NotionFalso({"db-t": ESQUEMA_TAREFAS})
                falso.adicionar("db-t", "t-1", {"Tarefa": "Original", "Status": "Nao iniciado"})
                cliente = self._cliente(falso)
                sincronizar_notion(db=banco, cliente=cliente)

                falso.editar("db-t", "t-1", {"Tarefa": "Titulo do Notion"})
                item = banco.listar_itens()[0]
                item.titulo = "Titulo do painel"
                banco.salvar_item(item)

                res = sincronizar_notion(db=banco, cliente=cliente, politica=politica)
                self.assertEqual(res["conflitos"], 1)
                self.assertEqual(banco.listar_itens()[0].titulo, titulo_esperado)
                self.assertEqual(_texto(falso.paginas["db-t"]["t-1"]["properties"]["Tarefa"]), titulo_esperado)

    def test_direcao_importar_nunca_escreve_e_exportar_nunca_altera_local(self):
        falso = NotionFalso({"db-t": ESQUEMA_TAREFAS})
        falso.adicionar("db-t", "t-1", {"Tarefa": "Do Notion", "Status": "Nao iniciado"})
        self.banco.salvar_item(Item(titulo="Do painel", estado="proxima"))
        cliente = self._cliente(falso)

        sincronizar_notion(db=self.banco, cliente=cliente, direcao="importar")
        self.assertEqual(falso.escritas(), [])
        self.assertEqual(len(self.banco.listar_itens()), 2)

        outro = ArmazenamentoGTD(Path(self.tmp.name) / "exportar.db")
        outro.salvar_item(Item(titulo="So local", estado="proxima"))
        falso2 = NotionFalso({"db-t": ESQUEMA_TAREFAS})
        falso2.adicionar("db-t", "t-9", {"Tarefa": "Nao deve vir", "Status": "Nao iniciado"})
        res = sincronizar_notion(db=outro, cliente=self._cliente(falso2), direcao="exportar")
        self.assertEqual(res["tarefas_empurradas"], 1)
        self.assertEqual([i.titulo for i in outro.listar_itens()], ["So local"])

    def test_item_local_novo_e_criado_com_esquema_da_base(self):
        falso = NotionFalso({"db-t": ESQUEMA_TAREFAS})
        self.banco.salvar_item(Item(titulo="Comprar livro", contexto="@casa", estado="proxima"))
        sincronizar_notion(db=self.banco, cliente=self._cliente(falso))

        metodo, caminho, dados = falso.escritas()[0]
        self.assertEqual((metodo, caminho), ("POST", "/pages"))
        props = dados["properties"]
        self.assertEqual(props["Tarefa"]["title"][0]["text"]["content"], "Comprar livro")
        self.assertEqual(props["Contexto"], {"select": {"name": "@casa"}})
        self.assertEqual(props["Status"], {"status": {"name": "Nao iniciado"}})
        # Segunda rodada: ja mapeado, nao cria de novo.
        sincronizar_notion(db=self.banco, cliente=self._cliente(falso))
        self.assertEqual(len([c for c in falso.escritas() if c[1] == "/pages"]), 1)

    def test_paginacao_da_consulta(self):
        falso = NotionFalso({"db-t": ESQUEMA_TAREFAS}, tamanho_pagina=2)
        for n in range(5):
            falso.adicionar("db-t", f"t-{n}", {"Tarefa": f"Tarefa {n}", "Status": "Nao iniciado"})
        res = sincronizar_notion(db=self.banco, cliente=self._cliente(falso), direcao="importar")
        self.assertEqual(res["tarefas_puxadas"], 5)
        consultas = [c for c in falso.chamadas if c[1].endswith("/query")]
        self.assertEqual(len(consultas), 3)

    def test_leituras_mao_dupla_com_checkbox(self):
        falso = NotionFalso({"db-l": ESQUEMA_LEITURAS})
        falso.adicionar("db-l", "l-1", {"Titulo": "Dom Casmurro", "Lido": False, "Autor": "Machado de Assis",
                                        "Paginas": 256})
        self.banco.salvar_leitura(Leitura(titulo="Sapiens", autor="Harari", paginas_total=400))
        cliente = self._cliente(falso, tarefas="", leituras="db-l")

        sincronizar_notion(db=self.banco, cliente=cliente)
        leituras = {le.titulo: le for le in self.banco.listar_leituras()}
        self.assertEqual(leituras["Dom Casmurro"].autor, "Machado de Assis")
        self.assertEqual(leituras["Dom Casmurro"].paginas_total, 256)
        criada = [c for c in falso.escritas() if c[1] == "/pages"][0][2]["properties"]
        self.assertEqual(criada["Lido"], {"checkbox": False})
        self.assertEqual(criada["Paginas"], {"number": 400})

        falso.editar("db-l", "l-1", {"Lido": True})
        sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(self.banco.obter_leitura(leituras["Dom Casmurro"].id).estado, "lido")

    def test_token_nao_aparece_em_logs_nem_repr(self):
        def http_quebrado(url, metodo, dados, headers):
            raise RuntimeError("falha simulada " + headers["Authorization"])

        cliente = ClienteNotion(token=TOKEN_NOTION, db_tarefas="db-t", http_client=http_quebrado)
        self.assertNotIn(TOKEN_NOTION, repr(cliente))
        with self.assertLogs("nextor.gtd", level=logging.WARNING) as logs:
            res = sincronizar_notion(db=self.banco, cliente=cliente)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(all(TOKEN_NOTION not in linha for linha in logs.output))


class GitHubFalso:
    """Simula a API REST do GitHub para issues e PRs."""

    def __init__(self):
        self.issues = {}
        self.chamadas = []
        self.recusar_escrita = False

    def adicionar(self, repo, numero, titulo, pr=False, estado="open"):
        tipo = "pull" if pr else "issues"
        elem = {"id": numero * 10, "number": numero, "title": titulo, "state": estado,
                "html_url": f"https://github.com/{repo}/{tipo}/{numero}", "_repo": repo}
        if pr:
            elem["pull_request"] = {"url": "x"}
        self.issues[(repo, numero)] = elem
        return elem

    def escritas(self):
        return [c for c in self.chamadas if c[1] != "GET"]

    def __call__(self, path, metodo="GET", dados=None, token=None, handler_requisicao=None):
        self.chamadas.append((path, metodo, dados))
        if path.startswith("/issues?"):
            return 200, [dict(e) for e in self.issues.values() if e["state"] == "open"]
        partes = path.split("?")[0].strip("/").split("/")
        if partes[0] == "repos" and len(partes) == 4 and partes[3] == "issues":
            repo = f"{partes[1]}/{partes[2]}"
            if metodo == "POST":
                if self.recusar_escrita:
                    return 403, {}
                numero = 100 + len(self.issues)
                return 201, dict(self.adicionar(repo, numero, dados["title"]))
            return 200, [dict(e) for (r, _), e in self.issues.items() if r == repo and e["state"] == "open"]
        if partes[0] == "repos" and len(partes) == 5:
            chave = (f"{partes[1]}/{partes[2]}", int(partes[4]))
            if chave not in self.issues:
                return 404, {}
            if metodo == "PATCH":
                if self.recusar_escrita:
                    return 403, {}
                self.issues[chave].update(dados)
            return 200, dict(self.issues[chave])
        return 404, {}


class TestGitHubMaoDupla(BaseBanco):
    def test_importa_issues_e_prs_e_fechamento_remoto_conclui(self):
        gh = GitHubFalso()
        gh.adicionar("ThiagoVenturim/Nextor", 42, "Integracoes do GTD")
        gh.adicionar("ThiagoVenturim/Nextor", 70, "PR integracoes", pr=True)

        novas = tarefas_do_github(db=self.banco, cliente_requisicao=gh)
        self.assertEqual(len(novas), 2)
        pr = [i for i in novas if "/pull/" in i.ref_externa][0]
        self.assertTrue(pr.nota.startswith("GitHub PR #70"))

        gh.issues[("ThiagoVenturim/Nextor", 42)]["state"] = "closed"
        res = sincronizar_github(self.banco, direcao="importar", requisicao=gh)
        self.assertEqual(res["atualizadas_local"], 1)
        issue = self.banco.buscar_item_por_ref("https://github.com/ThiagoVenturim/Nextor/issues/42")
        self.assertEqual(issue.estado, "feito")
        self.assertEqual(gh.escritas(), [])

        gh.issues[("ThiagoVenturim/Nextor", 42)]["state"] = "open"
        sincronizar_github(self.banco, direcao="importar", requisicao=gh)
        self.assertEqual(self.banco.obter_item(issue.id).estado, "proxima")

    def test_concluir_local_fecha_issue_so_em_mao_dupla_e_nunca_fecha_pr(self):
        gh = GitHubFalso()
        gh.adicionar("ThiagoVenturim/Nextor", 42, "Integracoes do GTD")
        gh.adicionar("ThiagoVenturim/Nextor", 70, "PR integracoes", pr=True)
        sincronizar_github(self.banco, direcao="importar", requisicao=gh)
        for item in self.banco.listar_itens():
            item.estado = "feito"
            self.banco.salvar_item(item)

        sincronizar_github(self.banco, direcao="importar", requisicao=gh)
        self.assertEqual(gh.escritas(), [])

        res = sincronizar_github(self.banco, direcao="bidirecional", requisicao=gh)
        self.assertEqual(res["atualizadas_remoto"], 1)
        self.assertEqual(gh.escritas(), [("/repos/ThiagoVenturim/Nextor/issues/42", "PATCH", {"state": "closed"})])
        self.assertEqual(gh.issues[("ThiagoVenturim/Nextor", 70)]["state"], "open")

        # Reabrir no painel reabre a issue.
        issue = self.banco.buscar_item_por_ref("https://github.com/ThiagoVenturim/Nextor/issues/42")
        issue.estado = "proxima"
        self.banco.salvar_item(issue)
        sincronizar_github(self.banco, direcao="bidirecional", requisicao=gh)
        self.assertEqual(gh.issues[("ThiagoVenturim/Nextor", 42)]["state"], "open")

    def test_tarefa_local_com_repo_vira_issue(self):
        gh = GitHubFalso()
        item = Item(titulo="Documentar webhook", nota="detalhes", estado="proxima")
        item.definir_meta("github_repo", "Nextor")
        self.banco.salvar_item(item)

        sincronizar_github(self.banco, direcao="importar", requisicao=gh)
        self.assertEqual(gh.escritas(), [])

        res = sincronizar_github(self.banco, direcao="bidirecional", requisicao=gh)
        self.assertEqual(res["issues_criadas"], 1)
        salvo = self.banco.obter_item(item.id)
        self.assertTrue(salvo.ref_externa.startswith("https://github.com/ThiagoVenturim/Nextor/issues/"))
        # Na rodada seguinte a issue aberta nao vira tarefa duplicada.
        sincronizar_github(self.banco, direcao="bidirecional", requisicao=gh)
        self.assertEqual(len(self.banco.listar_itens()), 1)

    def test_repo_invalido_e_falha_de_escrita_contam_erro(self):
        gh = GitHubFalso()
        gh.recusar_escrita = True
        item = Item(titulo="X", estado="proxima")
        item.definir_meta("github_repo", "../../etc")
        self.banco.salvar_item(item)
        res = sincronizar_github(self.banco, direcao="bidirecional", requisicao=gh)
        self.assertEqual(res["erros"], 1)
        self.assertEqual(gh.escritas(), [])

    def test_evento_webhook_atualiza_e_cria_tarefa(self):
        gh = GitHubFalso()
        elem = gh.adicionar("ThiagoVenturim/Nextor", 42, "Integracoes")
        sincronizar_github(self.banco, direcao="importar", requisicao=gh)

        fechado = dict(elem, state="closed")
        res = aplicar_evento_webhook(self.banco, "issues", {"action": "closed", "issue": fechado})
        self.assertTrue(res["aplicado"])
        self.assertEqual(self.banco.buscar_item_por_ref(elem["html_url"]).estado, "feito")

        pr = {"number": 71, "title": "Novo PR", "state": "open",
              "html_url": "https://github.com/ThiagoVenturim/Nextor/pull/71",
              "assignees": [{"login": "ThiagoVenturim"}]}
        res2 = aplicar_evento_webhook(self.banco, "pull_request", {"action": "assigned", "pull_request": pr},
                                      usuario="ThiagoVenturim")
        self.assertEqual(res2["acao"], "criado")
        self.assertEqual(self.banco.buscar_item_por_ref(pr["html_url"]).contexto, "@trabalho")

        res3 = aplicar_evento_webhook(self.banco, "issues", {"action": "closed", "issue": fechado},
                                      direcao="desligado")
        self.assertFalse(res3["aplicado"])


class TestAnotacoesNextor(BaseBanco):
    def setUp(self):
        super().setUp()
        self.arquivo = Path(self.tmp.name) / "anotacoes.md"
        self.arquivo.write_text(
            "# Anotacoes\n- [2026-11-21] Ligar para o dentista\n- Comprar cafe\n- [x] Pagar boleto\n",
            encoding="utf-8",
        )

    def test_importa_pendentes_e_conclusao_anda_nos_dois_sentidos(self):
        res = sincronizar_nextor(self.banco, caminho_anotacoes=self.arquivo)
        self.assertEqual(res["novas"], 2)
        itens = {i.titulo: i for i in self.banco.listar_itens()}
        self.assertEqual(set(itens), {"Ligar para o dentista", "Comprar cafe"})
        self.assertEqual(itens["Ligar para o dentista"].prazo, "2026-11-21")
        self.assertEqual(itens["Comprar cafe"].origem, "nextor")

        # Concluir no painel marca [x] na anotacao.
        cafe = itens["Comprar cafe"]
        cafe.estado = "feito"
        self.banco.salvar_item(cafe)
        res = sincronizar_nextor(self.banco, caminho_anotacoes=self.arquivo)
        self.assertEqual(res["atualizadas_remoto"], 1)
        self.assertIn("- [x] Comprar cafe", self.arquivo.read_text(encoding="utf-8"))

        # Marcar [x] na anotacao (com linhas inseridas antes) conclui no painel.
        texto = self.arquivo.read_text(encoding="utf-8")
        texto = texto.replace("- [2026-11-21] Ligar", "- Nova nota\n- [x] [2026-11-21] Ligar")
        self.arquivo.write_text(texto, encoding="utf-8")
        res = sincronizar_nextor(self.banco, caminho_anotacoes=self.arquivo)
        self.assertEqual(res["atualizadas_local"], 1)
        self.assertEqual(res["novas"], 1)
        self.assertEqual(self.banco.obter_item(itens["Ligar para o dentista"].id).estado, "feito")

        # Reabrir no painel desmarca a anotacao.
        cafe = self.banco.obter_item(cafe.id)
        cafe.estado = "proxima"
        self.banco.salvar_item(cafe)
        sincronizar_nextor(self.banco, caminho_anotacoes=self.arquivo)
        self.assertIn("- [ ] Comprar cafe", self.arquivo.read_text(encoding="utf-8"))

    def test_importar_nao_altera_arquivo(self):
        sincronizar_nextor(self.banco, caminho_anotacoes=self.arquivo)
        for item in self.banco.listar_itens():
            item.estado = "feito"
            self.banco.salvar_item(item)
        antes = self.arquivo.read_text(encoding="utf-8")
        sincronizar_nextor(self.banco, direcao="importar", caminho_anotacoes=self.arquivo)
        self.assertEqual(self.arquivo.read_text(encoding="utf-8"), antes)


class TestConfiguracaoSincronizacao(BaseBanco):
    def test_salvar_valida_direcoes_conflito_e_repos(self):
        caminho = Path(self.tmp.name) / "config.json"
        cfg = salvar_config({"sincronizacao": {
            "notion": "importar", "github": "apagar-tudo", "nextor": "DESLIGADO",
            "conflito": "local", "github_repos": ["Nextor", "dono/repo", "../x", "a b", 3],
        }}, caminho_customizado=caminho)
        sinc = cfg["sincronizacao"]
        self.assertEqual(sinc["notion"], "importar")
        self.assertEqual(sinc["github"], "importar")  # valor invalido mantem o padrao
        self.assertEqual(sinc["nextor"], "desligado")
        self.assertEqual(sinc["conflito"], "local")
        self.assertEqual(sinc["github_repos"], ["Nextor", "dono/repo", "3"])
        self.assertEqual(carregar_config(caminho)["sincronizacao"], sinc)

    def test_padrao_github_so_importa(self):
        self.assertEqual(normalizar_sincronizacao(None)["github"], "importar")

    def test_sincronizar_tudo_respeita_painel_e_falta_de_token(self):
        cfg = {"integracoes": {"notion": False, "github": True, "nextor": True},
               "sincronizacao": {"notion": "bidirecional", "github": "bidirecional", "nextor": "desligado"}}
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": ""}), mock.patch.object(config, "GITHUB_TOKEN", ""):
            res = sincronizar_tudo(db=self.banco, cfg=cfg)
        self.assertEqual(res["notion"]["status"], "desligado")
        self.assertEqual(res["nextor"]["status"], "desligado")
        self.assertEqual(res["github"]["motivo"], "github_token_nao_configurado")

        gh = GitHubFalso()
        gh.adicionar("ThiagoVenturim/Nextor", 1, "Uma issue")
        res = sincronizar_tudo(db=self.banco, cfg=cfg, fontes=["github"], requisicao_github=gh)
        self.assertEqual(res["github"]["novas_tarefas"], 1)
        self.assertEqual(res["github_novas_tarefas"], 1)
        self.assertNotIn("notion", res)


class TestRotasIntegracao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = "nxt_mestre_seguro_123456789012345"
        self.segredo = "segredo-webhook-de-teste"
        self.patches = [
            mock.patch.object(config, "TOKEN", self.token),
            mock.patch.object(config, "GTD_DB", Path(self.tmp.name) / "rotas.db"),
            mock.patch.object(config, "GITHUB_WEBHOOK_SECRET", self.segredo),
            mock.patch.dict(os.environ, {"NEXTOR_GTD_CONFIG_JSON": str(Path(self.tmp.name) / "cfg.json")}),
        ]
        for p in self.patches:
            p.start()
        self.client = servico.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _assinar(self, corpo: bytes) -> str:
        return "sha256=" + hmac.new(self.segredo.encode(), corpo, hashlib.sha256).hexdigest()

    def test_sincronizar_valida_fontes(self):
        h = {"X-Nextor-Token": self.token}
        self.assertEqual(self.client.post("/gtd/sincronizar", json={"fontes": "notion"}, headers=h).status_code, 400)
        with mock.patch("nextor.gtd.integracoes.sincronizar_tudo", return_value={"github_novas_tarefas": 0}) as m:
            res = self.client.post("/gtd/sincronizar", json={"fontes": ["nextor"]}, headers=h)
        self.assertEqual(res.status_code, 200)
        m.assert_called_once_with(fontes=["nextor"])

    def test_webhook_exige_assinatura_valida(self):
        corpo = json.dumps({"action": "closed", "issue": {
            "html_url": "https://github.com/ThiagoVenturim/Nextor/issues/42", "state": "closed", "title": "x"}}).encode()
        base = {"X-GitHub-Event": "issues", "Content-Type": "application/json"}

        sem = self.client.post("/gtd/webhook/github", data=corpo, headers=base)
        self.assertEqual(sem.status_code, 401)
        errada = self.client.post("/gtd/webhook/github", data=corpo,
                                  headers=dict(base, **{"X-Hub-Signature-256": "sha256=" + "0" * 64}))
        self.assertEqual(errada.status_code, 401)
        ok = self.client.post("/gtd/webhook/github", data=corpo,
                              headers=dict(base, **{"X-Hub-Signature-256": self._assinar(corpo)}))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.get_json()["motivo"], "sem_tarefa_local")

    def test_webhook_desligado_sem_segredo(self):
        with mock.patch.object(config, "GITHUB_WEBHOOK_SECRET", ""):
            res = self.client.post("/gtd/webhook/github", data=b"{}", headers={"X-GitHub-Event": "ping"})
        self.assertEqual(res.status_code, 404)

    def test_criar_item_com_repo_github(self):
        res = self.client.post("/gtd/itens", json={"titulo": "Virar issue", "github_repo": "Nextor"},
                               headers={"X-Nextor-Token": self.token})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["item"]["metadados"]["github_repo"], "Nextor")


if __name__ == "__main__":
    unittest.main()
