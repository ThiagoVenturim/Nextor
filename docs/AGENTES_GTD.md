# Conexao de Agentes e Habilidades ao Painel GTD

O Nextor permite que assistentes externos e agentes autonomos (como Claude Code, agy, agentes do Maestri ou rotinas agendadas no Windows) interajam diretamente com o painel de produtividade pessoal.

## Formas de Integracao

### 1. Ferramentas MCP (Model Context Protocol)
O modulo `nextor.mcp_server` expoe as seguintes ferramentas para agentes compativeis:
- `gtd_capturar`: adiciona uma nova ideia ou tarefa na caixa de entrada.
- `gtd_dia`: consulta o resumo inteligente do dia (agenda Google + tarefas prioritarias + meta de leitura).
- `gtd_processar`: muda o destino de uma tarefa (proxima acao, projeto, leitura, algum dia, feito ou lixo).
- `gtd_trocar_metodo`: altera dinamicamente o metodo ativo (gtd, para, eisenhower, kanban).
- `pomodoro_iniciar`, `pomodoro_parar`, `pomodoro_estado`: gerenciam sessoes de foco pomodoro.
- `leitura_progresso`: registra paginas lidas e atualiza o progresso da meta diaria.
- `notificacao_teste`: despacha notificacoes de teste pelos canais ativos (Telegram, Discord, WhatsApp, Web Push ou Voz).

Para configurar o servidor MCP em clientes stdio:
```json
{
  "mcpServers": {
    "nextor": {
      "command": "python",
      "args": ["-m", "nextor.mcp_server"],
      "cwd": "C:/Users/thiag/projetos-oss/Nextor"
    }
  }
}
```

### 2. API HTTP Local Protegida
Os agentes tambem podem se comunicar pelas rotas HTTP locais do servico Nextor (`http://localhost:5005` ou via VPN):
- `GET /gtd/itens`: lista tarefas com filtros de estado e contexto.
- `POST /gtd/capturar`: captura para o inbox.
- `POST /gtd/processar`: move de estado ou converte em projeto/leitura.
- `GET /gtd/hoje`: retorna agenda e proximas acoes.
- `GET /gtd/revisao`: diagnostico da revisao semanal (projetos sem proxima acao e itens parados).
- `GET/PUT /gtd/config`: consulta e atualizacao de configuracoes do framework.

Todas as rotas exigem autenticacao estrita via cabecalho:
`X-Nextor-Token: <NEXTOR_TOKEN>` ou `Authorization: Bearer <NEXTOR_TOKEN>`.

## Exemplos de Agentes e Acoes

### Agente de Triagem de Inbox
- **Objetivo**: Ler periodicamente itens com estado `inbox` e sugerir classificacao.
- **Fluxo**:
  1. Chama `GET /gtd/itens?estado=inbox`.
  2. Analisa o texto do item usando o modelo de linguagem configurado.
  3. Identifica contexto apropriado (@faculdade, @trabalho, @casa, @academia, @leitura) e se e acao unica ou projeto.
  4. Chama `POST /gtd/processar` definindo o novo contexto e estado `proxima` (ou `projeto`).

### Agente de Revisao Semanal
- **Objetivo**: Conduzir o ritual de revisao semanal do GTD sem atritos.
- **Fluxo**:
  1. Chama `GET /gtd/revisao`.
  2. Encontra projetos ativos que nao possuem nenhuma proxima acao cadastrada.
  3. Formula uma mensagem de resumo alertando os gargalos.
  4. Despacha a mensagem pelo canal configurado (Telegram ou Discord) ou fala diretamente no Google Nest.

### Agente de Planejamento Matinal
- **Objetivo**: Integrar com a rotina matinal (`nextor/rotina.py`).
- **Fluxo**:
  1. Consulta `GET /gtd/hoje`.
  2. Ajusta a ordem sugerida do dia com base nos compromissos de hora marcada da agenda.
  3. Notifica o usuario no celular com o plano do dia.
