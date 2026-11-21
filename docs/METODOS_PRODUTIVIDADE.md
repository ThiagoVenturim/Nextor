# Metodos de produtividade intercambiaveis

O painel de tarefas (`/gtd`) mostra os mesmos itens com o metodo que voce escolher, e voce
pode trocar de metodo a qualquer hora. Existe um unico modelo de dados (`Item`, em
`nextor/gtd/modelos.py`). Cada metodo e uma visao sobre ele.

| Metodo | Slug | Colunas | Onde guarda a classificacao |
|--------|------|---------|-----------------------------|
| GTD ("A Arte de Fazer Acontecer") | `gtd` | Caixa de Entrada, Proximas Acoes, Aguardando, Algum Dia, Concluido | `estado` do item |
| PARA (Tiago Forte) | `para` | Entrada, Projetos, Areas, Recursos, Arquivos | `metadados.balde_para` |
| Matriz de Eisenhower | `eisenhower` | Fazer, Agendar, Delegar, Eliminar, Concluido | `metadados.quadrante`, `urgente`, `importante` |
| Kanban Pessoal | `kanban` | A Fazer, Fazendo (com limite de WIP), Feito | `metadados.coluna_kanban` |

O Pomodoro e um timer por cima de qualquer metodo. Ele conta os ciclos concluidos em
`metadados.pomodoros_concluidos` da tarefa associada.

## Trocar de metodo sem perder dados

Cada metodo escreve so nos seus proprios campos. Mover um item no Kanban nao muda o balde
PARA nem o quadrante de Eisenhower. Trocar o metodo ativo so muda a visao. A unica
informacao compartilhada e "concluido": concluir um item em qualquer metodo grava
`estado = feito`, e todos os metodos passam a mostra-lo na coluna de conclusao (no PARA, em
Arquivos). Reabrir o item devolve-o para a coluna que ele tinha antes em cada metodo.

Quando o PARA nao tem um balde escolhido para o item, ele infere um a partir do projeto e do
contexto. O Eisenhower faz o mesmo com o prazo, a energia e o contexto.

## Configuracao

Os ajustes ficam no `config.json` local (veja `nextor/gtd/configuracao.py`) e podem ser
alterados na aba Ajustes do painel ou por `PUT /gtd/config`:

| Chave | Padrao | Efeito |
|-------|--------|--------|
| `metodo_ativo` | `gtd` | metodo exibido na aba Visao; precisa estar registrado |
| `kanban_wip_limite` | `3` | quantos itens cabem em "Fazendo" (1 a 50) |
| `pomodoro_ativo` | `true` | mostra o timer; desligado, `iniciar` e `retomar` respondem 409 |
| `pomodoro_duracao_min` | `25` | duracao padrao do foco (1 a 180 minutos) |

## Rotas HTTP

Todas exigem o token mestre no cabecalho `X-Nextor-Token`.

| Rota | Uso |
|------|-----|
| `GET /gtd/metodos` | catalogo dos metodos registrados (colunas, campos, regras) e o metodo ativo |
| `GET /gtd/visao?metodo=` | itens agrupados nas colunas do metodo ativo (ou do informado) |
| `POST /gtd/visao/mover` | `{"item_id", "coluna", "metodo"?}` move o item segundo as regras do metodo |
| `POST /gtd/pomodoro/iniciar` | `{"item_id"?, "duracao_min"?, "modo"?}` |
| `POST /gtd/pomodoro/pausar`, `/retomar`, `/parar`, `/concluir` | controle do timer |

`POST /gtd/visao/mover` responde 400 para coluna ou metodo inexistente, 404 para item
inexistente e 409 com `codigo = limite_wip` quando a coluna "Fazendo" do Kanban esta cheia.

No MCP, `gtd_trocar_metodo` troca o metodo ativo e `gtd_mover_item` move uma tarefa (aceita o
inicio do id).

## Adicionar um metodo novo

Crie um modulo com uma subclasse de `Metodo` e registre-a. Nada mais precisa mudar: o metodo
aparece em `GET /gtd/metodos`, nas abas e nos seletores do painel, e pode virar o
`metodo_ativo`. O painel usa uma visao generica por colunas para metodos que ele nao conhece.

```python
from nextor.gtd.metodos import Metodo, registrar_metodo


class MetodoTresTarefas(Metodo):
    nome = "Tres Tarefas"
    slug = "tres_tarefas"
    descricao = "Escolha tres tarefas para hoje."

    def colunas(self):
        return [
            {"id": "espera", "titulo": "Espera", "descricao": "Fora do dia"},
            {"id": "hoje", "titulo": "Hoje", "descricao": "As tres do dia"},
            {"id": "feito", "titulo": "Feito", "descricao": "Concluidas"},
        ]

    def classificar(self, item):
        if item.estado == "feito":
            return "feito"
        return item.obter_meta("coluna_tres_tarefas") or "espera"


registrar_metodo(MetodoTresTarefas)
```

O que cada metodo pode definir:

- `colunas()` e `classificar(item)`: obrigatorios.
- `mover(item, coluna, itens)`: o padrao grava `metadados["coluna_<slug>"]` e conclui ou
  reabre o item. Sobrescreva para gravar em outro campo ou aplicar regras; levante
  `LimiteWIPExcedido` ou outra `ErroMovimento` para recusar o movimento.
- `coluna_concluida`: coluna que marca o item como feito (`None` se nao houver).
- `campos_extra()`: campos de `metadados` que o metodo usa, para o painel.
- `regras()`: valores que o painel deve conhecer, como o limite de WIP.
- `configurar(cfg)`: devolve uma instancia ajustada ao `config.json`.
- `visao_dia(itens, agenda)`: acrescente chaves proprias (por exemplo `foco_hoje`).

Para que o metodo seja registrado quando o Nextor sobe, importe o modulo em
`nextor/gtd/metodos/registro.py` ou em qualquer modulo carregado na inicializacao.
