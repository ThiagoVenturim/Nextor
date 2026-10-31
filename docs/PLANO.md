# Estudo: deixar o Google Nest Mini mais inteligente

Data da pesquisa: 31/10/2026. Fase atual: somente pesquisa, nada instalado.

Aparelho do Thiago (confirmado em 31/10/2026):

| Campo | Valor |
|---|---|
| Modelo | Google Nest Mini (2a geracao) |
| Nome no Google Home | (definido no .env, campo NEXTOR_DISPOSITIVO) |
| Rede Wi-Fi | <SUA_REDE_WIFI> |
| IP | <IP_DO_NEST> (achado pelo notebook via tabela ARP; o app nao mostrava) |
| MAC | <MAC_DO_NEST> |
| Firmware do sistema | 540761 |
| Firmware do Google Cast | 20251119_1643_RC14 (canal estavel, sem atualizacao pendente) |
| Idioma | pt-BR |
| Notebook | <IP_DO_NOTEBOOK>, mesma rede |

Teste local feito: `http://<IP_DO_NEST>:8008/setup/eureka_info` responde (somente leitura), confirmando que o notebook alcanca o Nest e que a etapa 3 (Cast) e viavel.

Objetivo: controlar o alto-falante a partir do iPhone e do notebook Windows, via Wi-Fi e Bluetooth, e dar a ele mais "inteligencia" sem mexer em firmware nem burlar a conta Google.

---

## 1. Qual e o modelo exato

Existem dois aparelhos com o mesmo formato de "pedrinha":

| Item | Google Home Mini (1a geracao, 2017) | Google Nest Mini (2a geracao, 2019) |
|---|---|---|
| Alimentacao | Porta micro-USB | Conector redondo (barrel) proprio |
| Suporte de parede | Nao tem | Tem um encaixe na base para pendurar na parede |
| Microfones | 2 | 3 (melhor em ambiente barulhento) |
| Som | Mais fraco | Graves cerca de 2x mais fortes |
| Processamento | Tudo na nuvem | Chip de ML para parte do reconhecimento local; LEDs que acendem ao aproximar a mao |
| Nome no app Google Home | "Google Home Mini" | "Google Nest Mini" |

Como confirmar em casa, sem instalar nada:

1. Olhe a porta de energia: micro-USB = Home Mini (1a geracao); conector redondo = Nest Mini (2a geracao).
2. Vire o aparelho: o Nest Mini tem o furo/encaixe de parede na base de borracha.
3. App Google Home no iPhone: toque no dispositivo, depois em Configuracoes > Informacoes do dispositivo. Aparecem o modelo, o endereco IP e o MAC. Anote o IP; ele sera usado nas etapas de notebook.

O que muda na pratica para este estudo:

- Os dois falam o protocolo Google Cast, recebem audio por Bluetooth e funcionam como hub Matter por Wi-Fi.
- Gemini for Home: os dois recebem a versao gratuita. O Gemini Live (conversa continua, "Hey Google, let's chat") chegou primeiro ao Nest Mini e so em 23/07/2026 ao Home Mini de 1a geracao, e exige assinatura Google Home Premium.
- O Nest Mini responde melhor a comandos de voz (3 microfones), o que importa se ele for usado como "ouvido" de uma automacao.

Fontes:
- Android Central, Nest Mini vs Home Mini: https://androidcentral.com/nest-mini-vs-google-home-mini
- TechRadar, comparativo: https://www.techradar.com/news/google-nest-mini-vs-google-home-mini-whats-new-with-the-latest-google-smart-speaker
- Android Headlines, review do Nest Mini: https://www.androidheadlines.com/2019/10/nest-mini-review-higher-fidelity-same-great-price.html

---

## 2. O que e possivel hoje

### 2.1 Gemini for Home (no lugar do Google Assistente)

- O Google esta substituindo o Assistente pelo Gemini nos alto-falantes Nest. A camada basica (Gemini for Home) e gratuita; o Gemini Live (conversa natural, sem repetir "Hey Google") e pago (Google Home Premium).
- Em julho de 2026 o Gemini Live chegou tambem ao Home Mini de 1a geracao, junto com memoria de contexto de 15 minutos.
- Atencao: o lancamento comecou em ingles nos EUA e vem se expandindo por pais. Verificar no app Google Home (Configuracoes > Gemini / Acesso antecipado) se ja esta disponivel no Brasil e em portugues para a conta dele.

Fontes:
- Android Authority: https://www.androidauthority.com/gemini-live-expands-to-first-gen-google-speakers-3690874/
- Chrome Unboxed: https://chromeunboxed.com/google-brings-gemini-live-to-the-original-home-mini-and-nest-hub/
- TechRadar (acesso antecipado): https://techradar.com/home/smart-speakers/google-is-rolling-out-gemini-live-to-its-first-gen-smart-home-devices-and-its-great-news-if-your-home-mini-speaker-is-still-going-strong-heres-how-you-can-sign-up-to-early-access
- Tech Advisor (expansao para novos paises): https://www.techadvisor.com/article/3110206/gemini-for-google-home-launches-in-16-new-countries.html

### 2.2 Rotinas (automacoes) do app Google Home e editor de scripts

- Rotinas comuns: no app, aba Automacoes. Gatilho (frase de voz, horario, nascer/por do sol, estado de um dispositivo) + acoes (falar um texto, tocar musica, ajustar volume, ligar luz, transmitir aviso).
- Editor de scripts: em home.google.com (Google Home para web) ou no app. Usa YAML com blocos `metadata` e `automations` (starters, condition, actions), tem autocompletar e botao Validar. Permite logica que a interface simples nao oferece (varias condicoes, atrasos, combinacoes).
- E a forma oficial e mais segura de "programar" o Nest Mini sem instalar nada.

Fontes:
- Google, editor de scripts: https://support.google.com/googlehome/answer/13323253
- Google, escrever automacoes com script: https://support.google.com/googlehome/answer/13460475

### 2.3 Google Cast na rede local (notebook Windows)

O Nest Mini e um receptor Google Cast: qualquer programa na mesma rede Wi-Fi pode descobri-lo (mDNS) e mandar audio.

- pychromecast (biblioteca Python): descobre aparelhos, toca uma URL de audio, ajusta volume, pausa. Base de quase tudo nesta area. https://github.com/home-assistant-libs/pychromecast
- catt (Cast All The Things, linha de comando): `catt -d "Nome do Nest" cast arquivo.mp3`, `catt volume 40`, `catt stop`. Requer Python 3.11+ na versao atual. https://github.com/skorokithakis/catt e https://pypi.org/project/catt/
- "Falar texto" a partir do notebook: gerar um MP3 com um TTS (por exemplo gTTS, Piper local, ou TTS de um servico pago) e mandar o arquivo para o Nest via Cast. O Nest nao tem um comando "fale este texto" direto pelo Cast; ele so toca audio.
- Limite: o Cast so funciona na mesma rede, e o arquivo precisa ser servido por HTTP acessivel ao Nest (catt cuida disso para arquivos locais).

### 2.4 Home Assistant

Home Assistant (HA) e uma central de automacao de codigo aberto que roda em um computador sempre ligado (mini PC, Raspberry Pi, ou maquina virtual no notebook para testes).

- Integracao Google Cast: o Nest Mini vira um `media_player`. Da para tocar audio e usar `tts.speak` para falar qualquer texto, disparado por qualquer automacao do HA. Cuidado conhecido: o Cast exige que a URL do audio seja resolvivel pelo DNS publico do Google e, se HTTPS, com certificado valido; se o TTS "da certo" mas nao sai som, a causa costuma ser essa.
  - https://www.home-assistant.io/integrations/cast/
  - https://www.home-assistant.io/integrations/tts/
- Integracao Google Assistant SDK: o HA envia comandos de texto ao assistente da conta (`google_assistant_sdk.send_text_command`), por exemplo "broadcast jantar pronto", que vira um aviso nos alto-falantes sem interromper a musica. Exige criar credenciais OAuth no Google Cloud Console (projeto proprio, uso pessoal). Observacao: esse SDK foi feito para o Assistente; com a troca para Gemini, testar se continua funcionando na conta dele.
  - https://www.home-assistant.io/integrations/google_assistant_sdk/
  - Exemplo pratico: https://neilturner.me.uk/2024/05/06/
- Integracao Google Assistant (o contrario): expor dispositivos do HA para serem controlados por voz no Nest. Exige Nabu Casa (pago) ou configuracao manual com dominio HTTPS.

### 2.5 Bluetooth

Duas direcoes:

1. Nest como caixa de som Bluetooth: diga ao Nest "Ok Google, parear Bluetooth" (ou app Google Home > dispositivo > Configuracoes > Audio > Dispositivos Bluetooth pareados > Ativar modo de pareamento) e conecte pelo menu Bluetooth do celular ou do Windows. Funciona sem Wi-Fi do lado do celular, mas e so audio (sem controle).
2. Nest enviando audio para outra caixa Bluetooth maior: Configuracoes > Audio > Alto-falante padrao de musica.

Fonte: https://androidauthority.com/pair-google-nest-mini-with-bluetooth-850390

### 2.6 Matter

- Os alto-falantes Nest (incluindo Home Mini e Nest Mini) funcionam como hub/controlador Matter por Wi-Fi: dispositivos Matter (tomadas, lampadas) adicionados no app Google Home ficam controlaveis por voz e por rotinas, com controle local.
- Nenhum dos dois e Border Router Thread. Dispositivos Matter-sobre-Thread precisam de outro aparelho (Nest Hub 2a geracao, Nest Wifi Pro, ou um dongle Thread no Home Assistant).
- O proprio Nest Mini nao vira um dispositivo Matter controlavel pelo HA; ele e o controlador.

Fontes:
- Google, Matter e Thread: https://home.google.com/get-inspired/matter-and-thread/
- Matter Alpha, quais Nest sao hub: https://www.matteralpha.com/explainer/what-nest-devices-have-a-matter-hub-built-in

---

## 3. O que NAO e possivel (e alternativas realistas)

| Ideia | Por que nao | Alternativa realista |
|---|---|---|
| Trocar o firmware / instalar Linux proprio | Bootloader travado e firmware assinado pelo Google. Tentativas publicas exigem abrir o aparelho e mexer em hardware, com alto risco de inutilizar. Fora do escopo deste estudo. | Usar so as interfaces oficiais (Cast, app, SDK). |
| Root / acesso SSH ao aparelho | Nao existe acesso de shell oficial. | Ler informacoes publicas pela rede (descoberta Cast, `eureka_info` na porta 8008, que retorna nome e modelo). |
| Trocar o "Hey Google" por um LLM proprio (ChatGPT, Claude, modelo local) | A palavra de ativacao e o pipeline de voz sao fechados. O microfone do Nest nao e acessivel a terceiros. | Ver abaixo. |
| Ouvir o audio do microfone do Nest no notebook | Nao ha API para isso. | Microfone proprio no notebook, celular, ou satelite de voz. |
| Usar Bluetooth para controlar o Nest (volume, comandos) | O Bluetooth dele so transporta audio. | Controle via Cast (Wi-Fi). |

Alternativas realistas para ter um "assistente com LLM" usando o Nest:

1. Nest como alto-falante de saida + LLM no Home Assistant. O HA tem o Assist (assistente de voz proprio) e integracoes de conversa com LLM (OpenAI, Anthropic, Google Gemini API, ou Ollama local). O usuario fala no app Home Assistant do iPhone (ou pelo Siri via Atalhos) (ou em um satelite de voz como o Home Assistant Voice Preview Edition / ESP32), o LLM responde, e a resposta sai falada no Nest via `tts.speak`.
   - https://www.home-assistant.io/voice_control/
   - https://www.home-assistant.io/integrations/ollama/
2. Ponte de voz pelo proprio Nest: criar uma rotina no Google Home com frase de voz ("Hey Google, modo cinema") que liga um dispositivo virtual exposto pelo HA; o HA entao executa a logica (inclusive chamar um LLM) e responde no Nest. O Nest vira "microfone de comandos pre-definidos", nao de conversa livre.
3. Usar o proprio Gemini for Home / Gemini Live: e o caminho oficial para "mais inteligencia" sem infraestrutura propria, com o custo da assinatura e menos controle.

---

## 4. Plano de estudo em etapas

Cada etapa so comeca quando a anterior funcionar. Nada nesta lista modifica o aparelho de forma permanente; tudo e desfeito apagando a rotina, desinstalando o programa ou removendo a integracao.

### Etapa 0 - Inventario (15 min)
- Identificar o modelo (secao 1), anotar IP, MAC, versao de firmware.
- No roteador, reservar IP fixo (DHCP) para o Nest. Facilita tudo depois.
- Precisa: app Google Home no iPhone, acesso ao roteador.

### Etapa 1 - Recursos oficiais pelo celular (1 a 2 dias)
- Ativar e testar Bluetooth nos dois sentidos (celular -> Nest; Nest -> outra caixa).
- Criar 3 rotinas simples: bom dia (horario), frase de voz personalizada, aviso por broadcast.
- Verificar se o Gemini for Home ja esta disponivel para a conta (pt-BR) e testar.
- Precisa: so o celular.

### Etapa 2 - Editor de scripts (1 dia)
- Abrir home.google.com no notebook, recriar uma das rotinas em YAML e adicionar uma condicao (ex.: so dias uteis, so se alguem estiver em casa).
- Precisa: navegador no Windows.

### Etapa 3 - Controle pelo notebook via Google Cast (1 a 2 dias)
- Instalar Python 3.11+ e pipx; instalar `catt`.
- Descobrir o Nest (`catt scan`), tocar um MP3, mudar volume.
- Script Python com pychromecast + gTTS: gerar fala em portugues e tocar no Nest ("o build terminou", "lembrete de reuniao").
- Atencao no Windows: liberar o Python no Firewall para rede privada (descoberta mDNS) e garantir que o notebook esta na mesma rede/SSID do Nest.
- Precisa: notebook Windows, mesma rede Wi-Fi.

### Etapa 4 - Home Assistant (1 semana)
- Teste: instalar Home Assistant OS em maquina virtual (VirtualBox ou Hyper-V) no notebook. Definitivo: mini PC ou Raspberry Pi 4/5 sempre ligado.
- Adicionar integracao Google Cast (geralmente descoberta automaticamente) e testar `tts.speak` com Piper (TTS local) ou Google Translate TTS.
- Instalar o app Home Assistant Companion no iPhone (notificacoes, sensores do celular como gatilho).
- Opcional: integracao Google Assistant SDK para broadcasts e comandos de texto (criar projeto no Google Cloud Console).
- Precisa: maquina para o HA, conta Google, 1 a 2 horas para OAuth.

### Etapa 5 - Matter (opcional, quando houver dispositivo)
- Comprar uma tomada ou lampada Matter sobre Wi-Fi, adicionar pelo app Google Home e controlar por voz no Nest.
- Compartilhar o mesmo dispositivo com o Home Assistant (Matter multi-admin).
- Se quiser Thread: precisa de um Border Router (o Nest Mini nao serve).

### Etapa 6 - Assistente com LLM (avancado)
- No HA, configurar o Assist com um agente de conversa LLM:
  - Local: Ollama no notebook ou mini PC (precisa de GPU/RAM razoaveis; modelos de 3B a 8B parametros).
  - Pago: API da OpenAI, Anthropic ou Google Gemini (custo por uso, baixo para uso domestico).
- Fluxo: fala no app HA do iPhone, ou Siri via Atalhos (ou satelite de voz) -> STT (Whisper local ou nuvem) -> LLM -> TTS -> sai no Nest Mini.
- Ponte de voz com o proprio Nest: rotina Google Home com frase fixa -> dispositivo virtual do HA -> automacao no HA -> resposta falada no Nest.
- Precisa: HA funcionando (etapa 4), chave de API ou maquina para modelo local, opcionalmente um satelite de voz ESP32.

### Resumo do que comprar/ter
- Ja tem: Nest Mini, notebook Windows, iPhone, Wi-Fi.
- Gratis: app Google Home, Python, catt, pychromecast, Home Assistant (em VM).
- Recomendado para etapa 4 em diante: mini PC ou Raspberry Pi para o HA (24h ligado).
- Opcional: dispositivo Matter Wi-Fi; dongle Thread; satelite de voz; assinatura Google Home Premium (Gemini Live) ou chave de API de LLM.

---

## Pontos a verificar na proxima rodada
- Disponibilidade do Gemini for Home e Gemini Live em pt-BR no Brasil na conta do Thiago.
- Se o Google Assistant SDK ainda responde apos a migracao da conta para Gemini.
- Versao de firmware atual do aparelho dele e se o endpoint local `eureka_info` ainda responde.

---

## 5. Ideia do Thiago: um agente "tamagotchi" pessoal

Pedido (31/10/2026): um bichinho virtual que conversa com ele, guarda anotacoes, grava coisas, tem "vida" propria e ajuda a gerenciar o notebook e o iPhone, com o Google Home no centro.

### O que precisa mudar na ideia

- O Nest Mini nao pode ser o servidor: nao roda programas nossos, nao guarda arquivos e nao entrega o audio do microfone. Ele fica como **boca** (fala via Cast) e **gatilho** (frases fixas em rotinas).
- O **cerebro e a memoria** ficam no notebook (depois, num mini PC ou Raspberry Pi ligado 24h): um pequeno servico que guarda as anotacoes, o estado do bichinho e conversa com um modelo de IA.
- O **ouvido** para conversa livre e o iPhone: Siri + app Atalhos ditam o texto e mandam para o notebook pela rede de casa. Gravar audio tambem e pelo iPhone ou pelo microfone do notebook, com transcricao (Whisper).

### Arquitetura proposta

```
iPhone (Siri/Atalhos: "anotar", "conversar", gravar)
        |  HTTP na rede de casa (com token)
        v
Notebook: servico "bichinho"
  - memoria: anotacoes em Markdown + estado (humor, energia, fome) em arquivo/SQLite
  - IA: Claude/OpenAI/Gemini por API (pago, barato) ou Ollama local (gratis, precisa de RAM/GPU)
  - agenda: lembretes e "fome" que cresce com o tempo
  - comandos permitidos no notebook (lista fechada: abrir app, bateria, bloquear tela)
        |  Google Cast (pychromecast + TTS)
        v
Nest Mini <IP_DO_NEST>: fala respostas, avisos e "pedidos" do bichinho
        ^
Google Home: rotinas com frase fixa ("Ok Google, bom dia bichinho") -> via Home Assistant -> servico
```

### Limites honestos

- Conversa livre falando direto com o Nest nao da: o "Ok Google" sempre vai para o Gemini/Assistente. Com o Nest, so frases fixas viram gatilho.
- iPhone: o iOS nao deixa outro programa "gerenciar" o celular. Da para receber notificacoes (app Home Assistant ou ntfy), disparar Atalhos e usar automacoes pessoais do app Atalhos.
- Notebook desligado = bichinho dormindo. Para ficar 24h, precisa de um mini PC.
- Fora de casa: so com VPN privada (ex.: Tailscale). Nunca abrir porta no roteador.

### Versoes, da mais simples a mais completa

| Versao | O que faz | Depende de |
|---|---|---|
| V0 | Notebook faz o Nest falar um texto | Etapa 3 |
| V1 | Servico local com `/falar` e `/anotar`; Atalho no iPhone "Anotar no bichinho" salva a nota e o Nest confirma em voz | V0 |
| V2 | IA com personalidade e memoria (le as notas); Atalho "Conversar com bichinho" responde no iPhone e no Nest | V1 + chave de API ou Ollama |
| V3 | Modo tamagotchi: humor/energia/fome, avisos espontaneos no Nest ("faz tempo que voce nao me conta nada"), resumo do dia a noite | V2 |
| V4 | Gravacoes: audio do iPhone transcrito e guardado como nota | V2 + Whisper |
| V5 | Home Assistant: rotinas do Google Home disparam o bichinho; notificacoes no iPhone | Etapa 4 |
| V6 | Comandos no notebook por lista fechada, sempre com confirmacao | V2 |

### Decisoes pendentes com o Thiago
- Nome e personalidade do bichinho.
- IA paga por API (melhor qualidade, alguns reais por mes) ou local com Ollama (gratis, depende do hardware do notebook).
- Onde guardar a memoria: pasta local simples ou pasta sincronizada (OneDrive/Google Drive) para ler no iPhone.

---

## 6. Da para usar o processador do proprio Nest Mini?

Pergunta do Thiago (31/10/2026): se o Nest Mini tem processador, da para mudar o software dele e rodar o agente nele?

Resposta: nao, por dois motivos independentes.

1. **Bloqueio de software.** O Nest Mini so aceita firmware assinado pelo Google (inicializacao segura), atualiza sozinho e nao oferece acesso de terminal. Nao ha metodo publico e seguro para rodar codigo proprio nele; as tentativas conhecidas em aparelhos parecidos exigem abrir a placa e mexer em hardware, com risco real de inutilizar o aparelho e perder a garantia. Fica fora do escopo deste estudo.
2. **Mesmo que abrisse, nao serviria.** O processador e um ARM de 4 nucleos a 1,4 GHz, pensado para tocar audio e detectar o "Ok Google". O chip de ML dele e especializado nisso, nao em modelos de linguagem. A memoria e pequena (lojas citam cerca de 1 GB, sem confirmacao por desmontagem). Um modelo de linguagem minimo pelo Ollama ja pede 2 a 4 GB so para ele. O notebook e muito mais forte.

Fontes:
- Arm, caso do Nest Mini (CPU 64 bits de 4 nucleos + motor de ML): https://arm.com/company/success-library/arm-designs/google-nest-mini
- iFixit, pagina do Nest Mini 2a geracao: https://www.ifixit.com/Device/Google_Nest_Mini_%282nd_generation%29
- Liliputing, lancamento: https://liliputing.com/2019/10/google-nest-mini-is-small-smart-speaker-you-can-hang-on-the-wall.html

Conclusao: o Nest continua como boca e gatilho; o processamento fica no notebook.

## 7. Hardware do notebook (verificado em 31/10/2026)

| Item | Valor | Impacto |
|---|---|---|
| CPU | AMD Ryzen 5 3500U (4 nucleos / 8 threads) | Roda modelos pequenos so na CPU |
| RAM | cerca de 10 GB livres para o sistema | Modelos de ate 3-4 bilhoes de parametros |
| GPU | Radeon Vega 8 integrada | O Ollama no Windows praticamente nao usa; contar com CPU |
| Python | 3.13.5 instalado | Atende catt (3.11+) e pychromecast |
| Ollama | 0.24.0 instalado, nenhum modelo baixado; ha versao nova disponivel | Atualizar antes de usar |

Modelos sugeridos para o bichinho (pt-BR razoavel, leves): `qwen2.5:3b` ou `llama3.2:3b` (cerca de 2 GB cada). Respostas devem levar alguns segundos; frases curtas funcionam melhor. Se ficar lento demais, o plano B e uma API paga so para a conversa.

---

## 8. Referencias

Material de controle do Nest Mini pela rede local, uso legitimo, sem firmware/root/jailbreak. URLs verificadas em 31/10/2026.

## Bibliotecas e projetos (controle pela rede, Google Cast)

- pychromecast - https://github.com/home-assistant-libs/pychromecast
  Biblioteca Python que descobre e controla aparelhos Google Cast (tocar audio, volume, pausar). Base da integracao Cast do Home Assistant. Mantido (projeto da organizacao do Home Assistant).

- catt (Cast All The Things) - https://github.com/skorokithakis/catt
  Linha de comando que usa pychromecast para transmitir arquivos locais e URLs ao Nest. Mantido. Pacote: https://pypi.org/project/catt/ (requer Python 3.11+).

## Interface local do aparelho (:8008 / :8443) - somente leitura e controle, nao e firmware

- GHLocalApi (documentacao nao oficial) - https://rithvikvibhu.github.io/GHLocalApi/
  Documenta os endpoints locais que o proprio app Google Home usa: informacoes do aparelho (eureka_info), volume, alarmes/timers, reiniciar, Wi-Fi. Os endpoints atuais pedem HTTPS na porta 8443 em /setup/ com um token de autorizacao local; variantes antigas respondiam em HTTP 8008 sem token (foi o caso do teste que fizemos). Repositorio com scripts de apoio. Documentacao de referencia, nao e um produto mantido.

## Home Assistant - integracoes oficiais

- Google Cast - https://www.home-assistant.io/integrations/cast/
  Adiciona o Nest como media_player. Toca audio e fala texto via tts.speak. Mantida.

- Text-to-speech (TTS) - https://www.home-assistant.io/integrations/tts/
  Bloco de TTS; acao tts.speak fala um texto num media_player. Mantida.

- Google Translate text-to-speech - https://www.home-assistant.io/integrations/google_translate/
  Motor de TTS gratuito (voz do Google Translate) para falar no Nest. Mantida.

- Google Assistant SDK - https://www.home-assistant.io/integrations/google_assistant_sdk/
  Envia comandos de texto ao assistente da conta (google_assistant_sdk.send_text_command), inclusive broadcast nos alto-falantes. Exige credenciais OAuth proprias. Mantida.

- assistant-relay (greghesp) - https://github.com/greghesp/assistant-relay
  Servidor Node.js que expoe o Google Assistant como API REST (inclui broadcast). ARQUIVADO em 28/08/2025 (somente leitura); citar como historico, preferir o Google Assistant SDK do Home Assistant.

## Paginas e manuais oficiais do Google

- Especificacoes tecnicas do Nest Mini (Google Store) - https://store.google.com/product/google_nest_mini_specs
  Specs oficiais: 98 mm de diametro, 42 mm de altura, Wi-Fi 802.11 b/g/n/ac (2,4/5 GHz), Bluetooth 5.0, Chromecast e Matter, driver de 40 mm, 3 microfones, CPU ARM 64 bits quad-core 1,4 GHz, 5 anos de atualizacoes de seguranca.

- Especificacoes de aparelhos Nest e Home (Suporte Google) - https://support.google.com/googlenest/answer/7072284
  Tabela comparativa de varios aparelhos; conferir a coluna do Nest Mini (alguns valores na mesma tabela sao de outros modelos).

- Editor de scripts (automacoes avancadas) - https://support.google.com/googlehome/answer/13323253
  Como criar automacoes em YAML no Google Home para web. Oficial.

- Escrever automacoes com o editor de scripts - https://support.google.com/googlehome/answer/13460475
  Estrutura dos scripts (metadata, starters, condition, actions), validacao. Oficial.

- Matter e Thread no Google Home - https://home.google.com/get-inspired/matter-and-thread/
  O que e Matter/Thread e quais aparelhos Nest funcionam como hub. Oficial.

- Parear Bluetooth com o Nest Mini (Android Authority) - https://androidauthority.com/pair-google-nest-mini-with-bluetooth-850390
  Passo a passo de pareamento Bluetooth nos dois sentidos. Fonte terceira, atual.

---

## 9. Diario de construcao do Nestor

### V0 - concluida em 31/10/2026
- Ambiente Python isolado em .venv com gTTS (voz) e catt (envio via Cast).
- Script nestor.py: o notebook gera a fala em pt-BR e toca no Nest (<IP_DO_NEST>).
- Testado: o Nest falou a frase de apresentacao do Nestor. Som confirmado.
- Uso: `.venv/Scripts/python.exe nestor.py "texto"`.

### V1 - concluida em 31/10/2026
- Flask instalado no .venv.
- Servico nestor_service.py (porta 5005, token simples) com /anotar, /falar, /notas.
- Notas guardadas em anotacoes.md com data e hora.
- Testado local: nota salva e Nestor confirmou em voz ("Anotei: ...").
- Atalho do iPhone documentado em ATALHO_IPHONE.md ("Anotar no Nestor" via Siri).
- Pendencias: Thiago montar o atalho no iPhone e testar; reservar o IP do notebook
  (<IP_DO_NOTEBOOK>) no roteador; liberar o Python no Firewall do Windows se pedir.

### Proximo: V2 - personalidade e memoria (Ollama)
- Dar ao Nestor um modelo de IA local (qwen2.5:3b ou llama3.2:3b) que le as anotacoes
  e conversa. Endpoint /conversar: Thiago fala pelo iPhone, Nestor responde no Nest.

### V3 (parcial) - Google Agenda - 31/10/2026 (branch develop)
- Modulo nextor_agenda.py: le a Google Agenda por endereco privado iCal (sem Google Cloud),
  expande eventos repetidos, monta frase curta para falar.
- Endpoint /agenda (hoje / proximos) e agenda ligada ao cerebro (/conversar conhece a semana).
- Config por .env: NEXTOR_AGENDA_ICAL e NEXTOR_FUSO.
- Testado com a agenda real: Nextor falou os compromissos da semana no Nest.
- Pendencia: Thiago colar o endereco iCal privado no .env para o modo autonomo.

### V3 (continuacao) - noticias, nome, roteador - 31/10/2026 (develop)
- Nome do usuario no .env (NEXTOR_NOME) e setup de primeira vez (nextor_setup.py).
- Noticias: nextor_noticias.py (Google News RSS + resumo com IA local), endpoint /noticias.
- Roteador de intencoes: nextor_router.py decide anotar/agenda/noticias/conversar a partir de
  uma frase livre (tira saudacao e nome tipo "ei Nextor"); endpoint unico /comando. Log de
  comandos em comandos.log (ignorado no git) para analise de uso futura.
- Gatilho "ei Nextor" no Google Home: so chega ao servico via Home Assistant (webhook); a
  rotina do Google sozinha nao faz chamada HTTP. Por enquanto, gatilho pela Siri/iPhone.
- Reconhecer so a voz do dono: tratado como pesquisa; DTW nao e a tecnica certa (ver VISAO.md).

### V4 (inicio) - Home Assistant - 31/10/2026 (develop)
- Pasta home_assistant/: docker-compose.yml (HA em container), packages/nextor.yaml
  (rest_command para /comando, /agenda, /noticias; automacoes: gatilho de voz via
  input_boolean exposto ao Google, webhook para frase livre, rotina "bom dia" 7h) e HOWTO.md.
- config/ do HA fica fora do git (segredos). host.docker.internal liga o HA ao Nextor.
- Gatilho de voz pelo Nest exige expor o HA ao Google (Nabu Casa ou manual). Webhook e
  rotinas por horario ja funcionam sem custo.
- Docker Desktop estava instalado mas parado; iniciado nesta sessao, imagem do HA baixando.

### Rotina matinal configuravel - 31/10/2026 (develop)
- nextor_rotina.py: fala "bom dia" + agenda de hoje + resumo de noticias do assunto escolhido.
- Configuravel no .env/setup: NEXTOR_ROTINA_HORA (padrao 07:00) e NEXTOR_ROTINA_ASSUNTO.
- agendar_rotina.ps1: cria a tarefa diaria "NextorBomDia" no Windows na hora do .env (sem app,
  sem Home Assistant). A criacao da tarefa precisa ser rodada pelo Thiago (politica de seguranca
  bloqueia a persistencia a partir do agente).
- Robustez: nextor.py falar() agora limpa a sessao do Nest e tenta de novo se o cast falhar
  (o Nest travava preso em cast anterior).
- Descoberta: NAO era o Docker/Firewall; o Nest ficava preso em cast anterior. "catt stop" resolve.

### Reestruturacao em pacote + personas - 31/10/2026 (develop)
- Codigo virou o pacote nextor/ (config, personas, voz, cerebro, agenda, noticias, roteador,
  rotina, servico) com entrypoint python -m nextor. Scripts em scripts/, docs em docs/.
- Personas selecionaveis (NEXTOR_PERSONA): assistente, companheiro, profissional, amigo, coach.
- docs/ARQUITETURA.md explica a estrutura e como adicionar habilidades.
- Testado: pacote importa, rotas ok, /comando falou no Nest.

### Cerebro plugavel (local/Claude/agy) + servidor MCP - 31/10/2026 (develop)
- Cerebro escolhido por NEXTOR_CEREBRO: local (Ollama), claude (API, nextor/claude_cerebro.py,
  padrao claude-haiku-5-5) ou agy (nextor/agy_cerebro.py, via maestri ask). Cai para local se falhar.
- Chave do Claude em ANTHROPIC_API_KEY (.env, fora do git). Testado: modo claude sem chave cai
  para local sem quebrar.
- Servidor MCP (nextor/mcp_server.py, MCP 2.x / MCPServer) expoe anotar, listar_notas, agenda,
  noticias e falar para o Claude ou outro assistente se conectar. 5 ferramentas registradas.
- Noticias e conversa agora passam pelo cerebro escolhido (podem usar Claude).

### Perfis (agentes casa/escritorio) + verdade do "ei Nextor" - 31/10/2026 (develop)
- Perfis: cada .env.<nome> e um Nextor proprio (persona, cerebro, agenda, noticias, dispositivo).
  Ativo por NEXTOR_PERFIL ou pelo arquivo .perfil. Exemplos: .env.casa (companheiro),
  .env.escritorio (profissional). .env.* e .perfil ignorados; .env.example versionado.
- "ei Nextor" no Nest NAO e possivel (Google tranca a palavra de ativacao). Palavra propria so
  com satelite de voz (HA Voice/ESP32/openWakeWord). Documentado em docs/PERFIS_E_VOZ.md.

### Nosso "Home Assistant": automacoes + painel - 31/10/2026 (develop)
- nextor/automacoes.py: agendador proprio dentro do servico (thread, checa a cada 30s),
  automacoes por horario em automacoes.json (ignorado). Acoes: rotina, agenda, noticias,
  falar, comando. Semente: bom dia as 7h. Resolve o agendamento sem Agendador do Windows.
- servico.py: painel web /painel (falar, anotar, agenda, noticias, criar/remover automacoes)
  e API /automacoes (GET/POST/DELETE). Agendador inicia junto com o servico.
- Testado ao vivo: automacao criada para o minuto seguinte disparou sozinha e falou no Nest.
- Sem apps de terceiros (sem Docker/HA/Nabu Casa) para automacoes e painel.

### Skill de texto + pesquisa do gatilho Google Home - 31/10/2026 (develop)
- nextor/texto.py: traduzir, resumir e escrever usando o cerebro escolhido; salva o texto
  completo em arquivo (NEXTOR_TEXTOS_DIR, dica: cofre do Obsidian) e o Nest fala um aviso curto.
- Roteador entende "traduz ... para <idioma>", "resume ...", "escreve/conta uma historia ...".
  Endpoint /texto (acao=traduzir|resumir|escrever). Testado: poema escrito, salvo e falado.
- Cerebro.responder ganhou limite de tokens (textos longos). Pasta textos/ ignorada no git.
- Gatilho pelo Google Home: pesquisa confirmou que NAO e possivel acionar nosso servico por voz
  no Nest; o Google Assistente sera desligado em 04/09/2026. Caminho real para "ei Nextor":
  microfone proprio (notebook) com palavra de ativacao - proximo passo.
