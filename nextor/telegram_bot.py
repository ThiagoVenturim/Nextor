"""Adaptador do Telegram para o Nextor.

Permite interagir com o assistente por texto ou mensagem de voz (com transcricao local).
Filtra estritamente por IDs de usuarios autorizados (TELEGRAM_USUARIOS_AUTORIZADOS).
Integra os comandos /quiz, /resumo e /anotar ao modo estudante e despacha mensagens
para o endpoint /v1/assistente.
"""
from datetime import datetime
import hmac
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable, Optional, Set
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("nextor.telegram")


def _agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def obter_usuarios_autorizados() -> Set[str]:
    """Retorna conjunto de IDs de usuarios autorizados a partir da configuracao."""
    bruto = os.getenv("TELEGRAM_USUARIOS_AUTORIZADOS", "") or config.TELEGRAM_USUARIOS_AUTORIZADOS
    if not bruto:
        return set()
    separadores = [",", ";", " "]
    texto = bruto
    for s in separadores:
        texto = texto.replace(s, ",")
    return {p.strip() for p in texto.split(",") if p.strip()}


def usuario_autorizado(user_id: Any) -> bool:
    """Verifica em tempo constante se o ID do usuario do Telegram esta na lista de autorizados."""
    if user_id is None:
        return False
    candidato = str(user_id).strip()
    if not candidato:
        return False
    autorizados = obter_usuarios_autorizados()
    if not autorizados:
        return False
    encontrado = False
    for permitido in autorizados:
        if hmac.compare_digest(candidato.encode("utf-8"), permitido.encode("utf-8")):
            encontrado = True
    return encontrado


def obter_token_adaptador() -> str:
    """Obtem o token do adaptador do Telegram para chamar /v1/assistente."""
    try:
        from . import adaptadores
        return adaptadores.obter_token_adaptador(
            "telegram",
            "Bot Telegram",
            env_var="TELEGRAM_ADAPTADOR_TOKEN",
        )
    except Exception as e:
        log.warning("Nao foi possivel obter token de adaptador automatico: %s", e)
        return os.getenv("TELEGRAM_ADAPTADOR_TOKEN", "") or config.TELEGRAM_ADAPTADOR_TOKEN or config.TOKEN


def chamar_assistente(
    texto: str,
    token_adaptador: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Despacha uma mensagem de texto para o endpoint unificado /v1/assistente do Nextor."""
    from . import adaptadores
    return adaptadores.chamar_assistente(
        texto=texto,
        id_adaptador="telegram",
        nome_adaptador="Bot Telegram",
        env_var="TELEGRAM_ADAPTADOR_TOKEN",
        token_adaptador=token_adaptador,
        base_url=base_url,
        urlopen_fn=urllib.request.urlopen,
        tratar_erro_http=True,
    )


def transcrever_audio(caminho_ou_bytes: Path | str | bytes) -> str:
    """Transcreve audio localmente utilizando Vosk (offline)."""
    import wave

    caminho_wav = None
    arquivo_temp = None

    try:
        if isinstance(caminho_ou_bytes, bytes):
            arquivo_temp = tempfile.NamedTemporaryFile(suffix=".audio", delete=False)
            arquivo_temp.write(caminho_ou_bytes)
            arquivo_temp.close()
            caminho_entrada = Path(arquivo_temp.name)
        else:
            caminho_entrada = Path(caminho_ou_bytes)

        if not caminho_entrada.exists() or caminho_entrada.stat().st_size == 0:
            return ""

        # Converte para WAV 16kHz mono se nao for WAV nativo compativel
        caminho_wav = caminho_entrada.with_suffix(".pcm16.wav")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(caminho_entrada),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            str(caminho_wav),
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if res.returncode != 0:
                caminho_wav = caminho_entrada
        except Exception:
            caminho_wav = caminho_entrada

        try:
            import vosk
        except ImportError:
            return "Modulo Vosk de transcricao offline nao instalado."

        modelo_path = Path(config.VOSK_MODELO)
        if not modelo_path.exists():
            return "Modelo Vosk nao encontrado no caminho configurado."

        try:
            wf = wave.open(str(caminho_wav), "rb")
        except Exception:
            return "Formato de audio incompativel para transcricao."

        try:
            model = vosk.Model(str(modelo_path))
            rec = vosk.KaldiRecognizer(model, wf.getframerate())
            rec.SetWords(False)

            partes = []
            while True:
                dados = wf.readframes(4000)
                if len(dados) == 0:
                    break
                if rec.AcceptWaveform(dados):
                    resultado = json.loads(rec.Result())
                    t = resultado.get("text", "").strip()
                    if t:
                        partes.append(t)
            final = json.loads(rec.FinalResult())
            t_final = final.get("text", "").strip()
            if t_final:
                partes.append(t_final)
            return " ".join(partes).strip()
        finally:
            wf.close()
    except Exception as e:
        log.warning("Falha na transcricao do audio: %s", e)
        return ""
    finally:
        if arquivo_temp and Path(arquivo_temp.name).exists():
            try:
                Path(arquivo_temp.name).unlink()
            except Exception:
                pass
        if caminho_wav and caminho_wav != caminho_entrada and caminho_wav.exists():
            try:
                caminho_wav.unlink()
            except Exception:
                pass


def tratar_comando_quiz(disciplina: str = "") -> str:
    """Gera uma questao de quiz do modo estudante para a disciplina solicitada."""
    disc_limpa = disciplina.strip()
    try:
        from . import estudos
        disciplinas = estudos.listar_disciplinas()
        if not disciplinas:
            return "Nenhuma disciplina cadastrada ainda. Crie uma dizendo 'cria disciplina Direito', por exemplo."

        if not disc_limpa:
            nomes = ", ".join(d["nome"] for d in disciplinas)
            return f"Para iniciar o quiz, indique a disciplina: /quiz <disciplina>. Disciplinas disponiveis: {nomes}."

        alvo = None
        for d in disciplinas:
            if d["slug"] == disc_limpa.lower() or d["nome"].lower() == disc_limpa.lower():
                alvo = d
                break
        if not alvo:
            nomes = ", ".join(d["nome"] for d in disciplinas)
            return f"Disciplina '{disc_limpa}' nao encontrada. Disponiveis: {nomes}."

        materiais = estudos.listar_materiais(alvo["nome"])
        if not materiais:
            return f"A disciplina '{alvo['nome']}' ainda nao possui materiais importados. Adicione materiais para gerar o quiz."

        # Seleciona o material mais recente com conteudo
        material_escolhido = materiais[0]
        trecho = (material_escolhido.get("conteudo") or "")[:400].strip()
        titulo = material_escolhido.get("titulo", "Materia")

        # Tenta gerar pergunta com o cerebro configurado
        try:
            from . import cerebro
            prompt = (
                f"Voce e um tutor de estudos. Com base neste trecho do material '{titulo}' "
                f"da disciplina '{alvo['nome']}', formule uma questao de multipla escolha com 4 alternativas "
                f"(A, B, C, D) e indique a correta ao final com uma breve explicacao:\n\n{trecho}"
            )
            resposta = cerebro.conversar(prompt)
            if resposta and not resposta.startswith("Estou aqui, mas meu cerebro"):
                return f"[Quiz - {alvo['nome']}]\n{resposta}"
        except Exception:
            pass

        return (
            f"[Quiz - {alvo['nome']}]\n"
            f"Questao sobre '{titulo}':\n"
            f"Com base no material estudado: Qual o conceito central apresentado em '{trecho[:120]}...'?\n\n"
            f"A) Conceito introdutorio da materia\n"
            f"B) Excecao a regra geral\n"
            f"C) Jurisprudencia correlata\n"
            f"D) Nenhuma das anteriores\n\n"
            f"(Envie sua resposta para continuar)"
        )
    except Exception as e:
        return f"Nao consegui gerar o quiz de {disciplina or 'estudos'} agora ({e.__class__.__name__})."


def tratar_comando_resumo(termo: str = "") -> str:
    """Executa o comando /resumo ligado ao modo estudante ou skill de texto."""
    t = termo.strip()
    try:
        from . import estudos
        if not t:
            return estudos.resumo_disciplinas()

        # Verifica se corresponde a uma disciplina existente
        disciplinas = estudos.listar_disciplinas()
        for d in disciplinas:
            if d["slug"] == t.lower() or d["nome"].lower() == t.lower():
                return estudos.resumo_materiais(d["nome"])

        # Se nao for disciplina, verifica busca em materiais
        resultado_busca = estudos.buscar_materiais(t, "")
        if resultado_busca:
            return estudos.resumo_busca(t, "")

        # Fallback para resumir texto livre
        return chamar_assistente(f"resumir {t}")
    except Exception as e:
        return f"Nao foi possivel gerar o resumo: {e}"


def tratar_comando_anotar(texto: str) -> str:
    """Executa o comando /anotar salvando a nota via assistente."""
    if not texto.strip():
        return "Uso: /anotar <texto da anotacao>"
    return chamar_assistente(f"anota {texto.strip()}")


def tratar_comando_gtd_capturar(texto: str) -> str:
    """Captura diretamente uma ideia ou tarefa para a caixa de entrada GTD."""
    t = (texto or "").strip()
    if not t:
        return "Uso: /inbox <texto da tarefa>"
    try:
        from .gtd import capturar
        item = capturar(t)
        return f"Item adicionado ao inbox: {item.titulo}"
    except Exception as e:
        return f"Nao foi possivel adicionar ao inbox: {e}"


def tratar_comando_gtd_hoje() -> str:
    """Retorna o resumo da agenda do dia GTD."""
    try:
        from .gtd import agenda_do_dia
        res = agenda_do_dia()
        return res.get("resumo_falado", "Agenda do dia indisponivel.")
    except Exception as e:
        return f"Nao foi possivel carregar a agenda do dia: {e}"


def tratar_comando_gtd_leitura(arg: str) -> str:
    """Registra leitura diaria somando paginas ao livro atual ou meta."""
    try:
        num = int(arg.strip())
        if num <= 0:
            return "Informe um numero positivo de paginas: /li <n>"
        from .gtd import atualizar_progresso, listar_leituras
        leituras = listar_leituras(estado="lendo") or listar_leituras(estado="quero_ler")
        if not leituras:
            from .gtd.armazenamento import ArmazenamentoGTD
            banco = ArmazenamentoGTD()
            total = banco.registrar_progresso_leitura("geral", num)
            meta = getattr(config, "LEITURA_META_DIARIA", 20)
            status = "Meta batida!" if total >= meta else f"Faltam {max(0, meta - total)} paginas."
            return f"Registradas {num} paginas. Total hoje: {total}/{meta}. {status}"
        res = atualizar_progresso(leituras[0].id, num)
        status = "Meta batida!" if res["meta_atingida"] else f"Faltam {res['faltam_paginas']} paginas para a meta."
        return f"Registradas {num} paginas em '{res['leitura']['titulo']}'. Total hoje: {res['paginas_lidas_hoje']}/{res['meta_diaria']}. {status}"
    except ValueError:
        return "Informe um numero de paginas valido: /li <n>"
    except Exception as e:
        return f"Nao foi possivel registrar a leitura: {e}"


def tratar_comando(comando: str, argumento: str = "") -> str:
    """Roteia comandos iniciados por barra (/quiz, /resumo, /anotar, etc)."""
    cmd = comando.strip().lower()
    arg = argumento.strip()

    if cmd in ("/hoje", "/dia"):
        return tratar_comando_gtd_hoje()
    if cmd in ("/li", "/ler", "/leitura"):
        return tratar_comando_gtd_leitura(arg)
    if cmd in ("/inbox", "/capturar", "/tarefa"):
        return tratar_comando_gtd_capturar(arg)
    if cmd in ("/quiz", "/perguntas", "/teste"):
        return tratar_comando_quiz(arg)
    if cmd in ("/resumo", "/resumos", "/materiais"):
        return tratar_comando_resumo(arg)
    if cmd in ("/anotar", "/anote", "/nota"):
        return tratar_comando_anotar(arg)
    if cmd in ("/start", "/ajuda", "/help"):
        return (
            "Ola! Sou o Nextor no Telegram.\n\n"
            "Comandos de estudo disponiveis:\n"
            "- /quiz [disciplina] - Inicia uma questao de quiz\n"
            "- /resumo [disciplina] - Mostra o resumo das materias\n"
            "- /anotar [texto] - Salva um lembrete ou anotacao\n\n"
            "Voce tambem pode enviar qualquer pergunta em texto ou gravar uma mensagem de voz."
        )

    # Se for outro comando desconhecido, envia como texto para o assistente
    texto_total = f"{cmd} {arg}".strip()
    return chamar_assistente(texto_total)


def baixar_arquivo_telegram(file_id: str, bot_token: Optional[str] = None) -> bytes:
    """Obtem o arquivo de voz/audio a partir da API do Telegram."""
    token = bot_token or config.TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN nao configurado.")

    url_info = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
    req_info = urllib.request.Request(url_info, headers={"User-Agent": "NextorBot/1.0"})
    with urllib.request.urlopen(req_info, timeout=15) as resp:
        dados_info = json.loads(resp.read().decode("utf-8"))
        caminho_remoto = dados_info.get("result", {}).get("file_path", "")

    if not caminho_remoto:
        raise ValueError("Arquivo nao localizado no Telegram.")

    url_download = f"https://api.telegram.org/file/bot{token}/{caminho_remoto}"
    req_dl = urllib.request.Request(url_download, headers={"User-Agent": "NextorBot/1.0"})
    with urllib.request.urlopen(req_dl, timeout=30) as resp:
        return resp.read()


def enviar_mensagem_telegram(
    chat_id: int | str,
    texto: str,
    bot_token: Optional[str] = None,
) -> dict:
    """Envia uma mensagem de resposta via API HTTP do Telegram."""
    token = bot_token or config.TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "erro": "token_nao_configurado"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": texto,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning("Falha ao enviar mensagem ao Telegram: %s", e)
        return {"ok": False, "erro": str(e)}


def processar_update(
    update: dict,
    bot_token: Optional[str] = None,
    enviar_resposta: bool = True,
    baixador_audio: Optional[Callable[[str, Optional[str]], bytes]] = None,
    headers: Optional[dict] = None,
    token_esperado: Optional[str] = None,
) -> dict[str, Any]:
    """Processa um update de mensagem recebido do Telegram (via webhook ou polling)."""
    from . import adaptadores

    disp_tg = adaptadores.buscar_por_id("telegram")
    if disp_tg and not disp_tg.get("ativo", True):
        return {
            "ok": False,
            "autorizado": False,
            "erro": "adaptador_revogado",
            "resposta": "Adaptador do Telegram revogado.",
        }

    if headers is not None or token_esperado is not None:
        token_conf = (token_esperado or os.getenv("TELEGRAM_ADAPTADOR_TOKEN", "") or config.TELEGRAM_ADAPTADOR_TOKEN).strip()
        token_recebido = adaptadores.extrair_token_requisicao(headers=headers or {})
        if token_conf:
            valido = bool(token_recebido and hmac.compare_digest(token_recebido, token_conf))
            if not valido and token_recebido:
                adp_tk = adaptadores.buscar_por_token(token_recebido)
                if adp_tk and hmac.compare_digest(str(adp_tk.get("id", "")), "telegram") and adp_tk.get("ativo", True):
                    valido = True
            if not valido:
                return {"ok": False, "autorizado": False, "erro": "token_invalido"}
        elif token_recebido:
            adp_tk = adaptadores.buscar_por_token(token_recebido)
            if not adp_tk:
                return {"ok": False, "autorizado": False, "erro": "token_invalido"}
            if not adp_tk.get("ativo", True):
                return {"ok": False, "autorizado": False, "erro": "adaptador_revogado"}

    mensagem = update.get("message") or update.get("edited_message")
    if not mensagem:
        return {"ok": False, "motivo": "update_sem_mensagem"}

    remetente = mensagem.get("from") or {}
    user_id = remetente.get("id")
    chat = mensagem.get("chat") or {}
    chat_id = chat.get("id")

    # 1. Filtro estrito de autorizacao de usuario
    if not usuario_autorizado(user_id):
        log.warning("Acesso negado para usuario Telegram nao autorizado: %s (chat %s)", user_id, chat_id)
        resposta_negada = "Usuario nao autorizado."
        if enviar_resposta and chat_id and (bot_token or config.TELEGRAM_BOT_TOKEN):
            enviar_mensagem_telegram(chat_id, resposta_negada, bot_token=bot_token)
        return {
            "ok": False,
            "autorizado": False,
            "user_id": user_id,
            "chat_id": chat_id,
            "resposta": resposta_negada,
        }

    # 2. Processa conteudo da mensagem (texto ou voz)
    texto_processar = ""
    eh_audio = False

    if "voice" in mensagem or "audio" in mensagem:
        audio_info = mensagem.get("voice") or mensagem.get("audio") or {}
        file_id = audio_info.get("file_id")
        if file_id:
            eh_audio = True
            try:
                fn_baixar = baixador_audio or baixar_arquivo_telegram
                bytes_audio = fn_baixar(file_id, bot_token)
                texto_processar = transcrever_audio(bytes_audio)
                if not texto_processar:
                    texto_processar = ""
            except Exception as e:
                log.warning("Erro ao baixar/transcrever audio do Telegram: %s", e)
                texto_processar = ""
    else:
        texto_processar = (mensagem.get("text") or "").strip()

    if not texto_processar:
        if eh_audio:
            resposta = "Nao consegui compreender o audio."
        else:
            resposta = "Mensagem vazia."
        if enviar_resposta and chat_id and (bot_token or config.TELEGRAM_BOT_TOKEN):
            enviar_mensagem_telegram(chat_id, resposta, bot_token=bot_token)
        return {
            "ok": True,
            "autorizado": True,
            "user_id": user_id,
            "chat_id": chat_id,
            "resposta": resposta,
        }

    # 3. Execucao de comandos ou despacho para /v1/assistente
    if texto_processar.startswith("/"):
        partes = texto_processar.split(maxsplit=1)
        cmd = partes[0]
        arg = partes[1] if len(partes) > 1 else ""
        resposta = tratar_comando(cmd, arg)
    else:
        dono_chat = str(os.getenv("TELEGRAM_DONO_CHAT_ID", "") or getattr(config, "TELEGRAM_DONO_CHAT_ID", "")).strip()
        eh_dono = bool(
            dono_chat
            and (
                hmac.compare_digest(str(chat_id or "").strip(), dono_chat)
                or hmac.compare_digest(str(user_id or "").strip(), dono_chat)
            )
        )
        if eh_dono:
            resposta = tratar_comando_gtd_capturar(texto_processar)
        else:
            resposta = chamar_assistente(texto_processar)

    # 4. Envio de resposta
    if enviar_resposta and chat_id and (bot_token or config.TELEGRAM_BOT_TOKEN):
        enviar_mensagem_telegram(chat_id, resposta, bot_token=bot_token)

    return {
        "ok": True,
        "autorizado": True,
        "user_id": user_id,
        "chat_id": chat_id,
        "texto_entrada": texto_processar,
        "eh_audio": eh_audio,
        "resposta": resposta,
    }
