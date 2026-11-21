# Integracoes do GTD: Notion, GitHub e anotacoes do Nextor

O painel GTD (`/gtd`) sincroniza tarefas com tres fontes. Cada fonte tem uma direcao,
escolhida em Configuracoes > Integracoes no painel (ou em `~/.nextor/config.json`, secao
`sincronizacao`):

| Direcao        | O que faz                                              |
|----------------|--------------------------------------------------------|
| `bidirecional` | traz mudancas da fonte e leva as mudancas do painel    |
| `importar`     | so traz mudancas da fonte; nunca escreve nela          |
| `exportar`     | so leva mudancas do painel; nunca altera tarefas locais|
| `desligado`    | ignora a fonte                                         |

Padroes: Notion `bidirecional`, GitHub `importar`, Nextor `bidirecional`. O GitHub comeca
so importando porque escrever nele (fechar ou reabrir issue, criar issue) muda um sistema
compartilhado; escolher `bidirecional` ou `exportar` no painel vale como autorizacao.

Quando a mesma tarefa mudou nos dois lados desde o ultimo sincronismo, vale a politica
`conflito`: `remoto` (padrao, vence a fonte) ou `local` (vence o painel).

A sincronizacao roda pelo botao de sincronizar do painel, por `POST /gtd/sincronizar`
(corpo opcional `{"fontes": ["notion", "github", "nextor"]}`) ou pela ferramenta MCP
`gtd_sincronizar`. Nada e apagado em nenhum lado: tarefas removidas ou arquivadas numa
fonte continuam no painel.

## Credenciais

Tokens ficam so no `.env` do servidor (veja `.env.example`). Eles nunca vao para o git,
para o `config.json` nem para os logs: falhas de API registram so o codigo HTTP ou o tipo
do erro.

## Notion

Variaveis: `NOTION_TOKEN` (Internal Integration Secret) e os IDs das bases que voce quer
sincronizar, todos opcionais: `NOTION_DB_TAREFAS`, `NOTION_DB_PROJETOS`,
`NOTION_DB_LEITURAS`. Compartilhe cada base com a integracao no Notion.

As propriedades sao reconhecidas pelo tipo e por nomes comuns, sem esquema fixo:

- Tarefas: titulo (a propriedade do tipo title), `Status`/`Estado` (status, select ou
  checkbox), `Contexto` (select, ex.: `@trabalho`), `Prazo`/`Due` (date), `Projeto`
  (relation com a base de projetos).
- Projetos: titulo, `Status`/`Estado`, `Descricao`.
- Leituras: titulo, `Status`/`Estado` ou checkbox `Lido`, `Autor`, `Tipo` (Livro/Artigo),
  `Paginas`, `Lidas`, `URL`.

Estados sao traduzidos por sinonimos em portugues e ingles ("Concluido", "Done",
"Em andamento", "Aguardando", "Algum dia"...). Ao escrever, o Nextor usa a opcao ja
existente na base que equivale ao estado local.

Mudanca remota e detectada pelo `last_edited_time` da pagina; mudanca local, por um hash
dos campos sincronizados salvo no ultimo sincronismo. Tarefas criadas no painel viram
paginas novas na base de tarefas.

## GitHub (tarefas e PRs)

Variaveis: `GITHUB_TOKEN` (escopo minimo), `GITHUB_USUARIO`. Repositorios extras, alem das
issues atribuidas a voce, vao no campo "Repositorios GitHub extras" do painel.

- Issues e PRs abertos atribuidos a voce viram proximas acoes em `@trabalho`, sem
  duplicar (chave: URL da issue).
- Issue ou PR fechado no GitHub conclui a tarefa; reaberto volta para proxima.
- Com `bidirecional`/`exportar`: concluir a tarefa no painel fecha a issue e reabrir
  reabre. PRs nunca sao fechados pelo painel.
- Uma tarefa criada com `github_repo` (`POST /gtd/itens` com `{"titulo": ..., "github_repo": "Nextor"}`)
  vira issue nesse repositorio.

### Webhook (opcional)

Para atualizar o painel na hora, sem esperar o proximo sincronismo, configure um webhook
no repositorio apontando para `POST /gtd/webhook/github`, tipo `application/json`, eventos
"Issues" e "Pull requests", com um segredo gerado por voce e copiado para
`GITHUB_WEBHOOK_SECRET` no `.env`. O Nextor confere a assinatura `X-Hub-Signature-256`
(HMAC-SHA256) em tempo constante e recusa o pedido se ela nao bater. Sem segredo
configurado a rota responde 404. O webhook so traz mudancas do GitHub para o painel.

## Nextor (anotacoes)

As anotacoes feitas por voz, Telegram ou API (`anotacoes.md`, as mesmas que alimentam
`nextor.pendencias`) viram proximas acoes no painel. Marcar `[x]` numa anotacao conclui a
tarefa; concluir a tarefa no painel marca `[x]` na anotacao, e reabrir desmarca. Tarefas
criadas no painel nao sao copiadas para o arquivo, para nao duplicar a captura.
