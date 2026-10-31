# Referencias - estudo do Nest Mini

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
