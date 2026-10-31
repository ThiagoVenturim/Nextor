# Home Assistant + Nextor

O Home Assistant (HA) e a ponte que faltava: ele recebe gatilhos (voz pelo Google,
webhooks, horarios) e chama o servico do Nextor, e vice-versa.

## 1. Subir o Home Assistant (container)

Pre-requisito: Docker Desktop aberto e rodando.

```
cd home_assistant
docker compose up -d
```

Abra http://localhost:8123 e faca o assistente inicial (cria sua conta, define casa e
fuso). Isso e feito uma vez, pelo navegador.

## 2. Ligar o pacote do Nextor

1. Pare o HA: `docker compose down` (ou edite com o HA no ar e recarregue depois).
2. Copie `packages/nextor.yaml` para `home_assistant/config/packages/nextor.yaml`.
3. No `home_assistant/config/configuration.yaml`, adicione (se ainda nao houver):

   ```
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Em `home_assistant/config/secrets.yaml`, adicione o token do Nextor (o mesmo do `.env`):

   ```
   nextor_token: "SEU-TOKEN"
   ```

5. Suba de novo (`docker compose up -d`) ou, com o HA no ar, use Ferramentas do
   desenvolvedor > YAML > Recarregar configuracao.

O servico do Nextor precisa estar rodando no Windows (porta 5005). O HA o alcanca por
`host.docker.internal`, ja configurado no pacote.

## 3. O que ja funciona (sem custo)

- Webhook: `POST http://<ip-do-HA>:8123/api/webhook/nextor_comando` com JSON
  `{"texto": "o que tenho amanha"}` faz o Nextor entender e falar no Nest.
- Rotina "bom dia" as 7h: Nextor fala agenda e noticias (ajuste o horario no pacote).

## 4. Gatilho de voz pelo Nest ("ei Nextor")

Para dizer um comando ao Nest e ele acionar o Nextor, o Google precisa enxergar um
dispositivo do HA. Caminhos:

- Nabu Casa (assinatura, mais simples): ative Configuracoes > Home Assistant Cloud,
  depois a integracao Google Assistant, e exponha o `input_boolean.nextor_gatilho`.
  No app Google Home, uma rotina com a frase "ativar Nextor" liga esse boolean; a
  automacao "gatilho de voz" do pacote chama o Nextor.
- Manual (sem assinatura, trabalhoso): dominio HTTPS publico + projeto no Google Cloud
  (Actions on Google / service account). Mais passos e manutencao.

Enquanto nao houver exposicao ao Google, use o webhook (celular/tablet) e as rotinas por
horario. Nunca abra porta do HA no roteador; fora de casa, use VPN privada (Tailscale).
