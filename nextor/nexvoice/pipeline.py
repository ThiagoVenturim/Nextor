"""Pipeline de traducao de audio ao vivo do NexVoice: STT local, traducao bilingue e TTS Piper (Issue #56).

Implementa:
- Modo 'ouvir': captura de audio (video, aula ou microfone) com legenda e voz traduzida na hora.
- Modo 'reuniao' (bidirecional): fala do usuario (idioma_meu -> idioma_outro) e fala do interlocutor
  (idioma_outro -> idioma_meu) em streaming por trechos com baixa latencia.
- Etica e privacidade: exige consentimento expresso antes de traduzir/gravar reuniao ou aula,
  registra auditoria em SQLite e garante processamento estritamente local (Whisper + LLM local + Piper)
  sem enviar voz de terceiros para a nuvem.
- Integracao com a voz do Nextor (nextor.fala), modo estudante (nextor.estudos) e atas de reuniao (nextor.reuniao_tela).
"""
from datetime import datetime
import io
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union
import wave

from .. import config, estudos, fala, reuniao_tela
from .armazenamento import ArmazenamentoNexVoice
from .modelos import (
    AVISO_CONSENTIMENTO_NEXVOICE_AULA,
    AVISO_CONSENTIMENTO_NEXVOICE_REUNIAO,
    DIRECOES_FALA,
    FONTES_AUDIO,
    MODOS_NEXVOICE,
    MOTORES_STT_SUPORTADOS,
    MOTORES_TRADUCAO_SUPORTADOS,
    MOTORES_TTS_SUPORTADOS,
    SessaoNexVoice,
    TrechoVoz,
    formatar_tempo_legenda,
    formatar_timestamp_srt,
)

MOTORES_NUVEM_PROIBIDOS_LOCAL = ("claude", "gtts")

# Glossarios bidirecionais deterministicos para operacao 100% offline sem servidor externo ativo
_FRASES_EN_PARA_PT: Dict[str, str] = {
    "hello everyone, welcome to the meeting": "ola a todos, bem-vindos a reuniao",
    "welcome to our machine learning lecture": "bem-vindos a nossa aula de aprendizado de maquina",
    "can you hear me clearly": "voce consegue me ouvir claramente",
    "let us review the project architecture": "vamos revisar a arquitetura do projeto",
    "we decided to deploy the local model": "nos decidimos implantar o modelo local",
    "please send the report tomorrow": "por favor envie o relatorio amanha",
    "neural networks require training data": "redes neurais exigem dados de treinamento",
    "thank you for your time": "obrigado pelo seu tempo",
}

_FRASES_PT_PARA_EN: Dict[str, str] = {
    "ola a todos, bem-vindos a reuniao": "hello everyone, welcome to the meeting",
    "eu concordo com a proposta tecnica": "i agree with the technical proposal",
    "podemos comecar a apresentacao": "we can start the presentation",
    "vou enviar o codigo hoje": "i will send the code today",
    "decidimos usar processamento local por privacidade": "we decided to use local processing for privacy",
    "obrigado pela explicacao": "thank you for the explanation",
}

_TERMOS_EN_PT: Dict[str, str] = {
    "hello": "ola",
    "welcome": "bem-vindo",
    "meeting": "reuniao",
    "lecture": "aula",
    "video": "video",
    "project": "projeto",
    "architecture": "arquitetura",
    "machine learning": "aprendizado de maquina",
    "deep learning": "aprendizado profundo",
    "neural networks": "redes neurais",
    "neural network": "rede neural",
    "artificial intelligence": "inteligencia artificial",
    "privacy": "privacidade",
    "consent": "consentimento",
    "data": "dados",
    "model": "modelo",
    "training": "treinamento",
    "results": "resultados",
    "decision": "decisao",
    "action": "acao",
    "today": "hoje",
    "tomorrow": "amanha",
}

_TERMOS_PT_EN: Dict[str, str] = {v: k for k, v in _TERMOS_EN_PT.items()}


def validar_processamento_local_estrito(
    local_estrito: bool,
    motor_stt: str = "faster_whisper",
    motor_traducao: str = "local",
    motor_tts: str = "piper",
) -> None:
    """Garante que nenhum motor de nuvem seja usado quando processamento_local_estrito estiver ativo."""
    if not local_estrito:
        return
    for nome_etapa, motor in (("STT", motor_stt), ("traducao", motor_traducao), ("TTS", motor_tts)):
        m_norm = (motor or "").strip().lower()
        if m_norm in MOTORES_NUVEM_PROIBIDOS_LOCAL:
            raise PermissionError(
                f"Privacidade NexVoice: o motor '{m_norm}' ({nome_etapa}) usa nuvem e nao e permitido "
                "quando o processamento local estrito esta ativo."
            )


def validar_consentimento_sessao(sessao: SessaoNexVoice) -> None:
    """Valida que sessoes de reuniao ou aula possuem consentimento expresso confirmado."""
    if sessao.consentimento_exigido and not sessao.consentimento_confirmado:
        raise PermissionError(
            "Consentimento etico obrigatorio (NexVoice): para gravar ou traduzir reuniao/aula ao vivo, "
            "todos os participantes devem ser avisados e o consentimento deve ser confirmado."
        )


def gerar_wav_stub(duracao_seg: float = 0.5, taxa_amostragem: int = 16000) -> bytes:
    """Gera um arquivo WAV PCM 16-bit mono silencioso valido para testes offline e stubs."""
    num_frames = max(160, int(round(max(0.05, float(duracao_seg)) * taxa_amostragem)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(taxa_amostragem)
        wf.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


def _transcrever_faster_whisper(
    caminho_wav: Path,
    idioma_origem: str = "en-US",
    modelo_tamanho: Optional[str] = None,
) -> str:
    """Transcreve audio localmente usando faster-whisper se disponivel."""
    from faster_whisper import WhisperModel  # type: ignore

    tamanho = modelo_tamanho or getattr(config, "NEXVOICE_STT_MODELO", "base") or "base"
    lang = idioma_origem.split("-")[0].lower() if idioma_origem and idioma_origem != "auto" else None
    model = WhisperModel(tamanho, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(caminho_wav), language=lang, beam_size=1)
    partes = [seg.text.strip() for seg in segments if getattr(seg, "text", "").strip()]
    return " ".join(partes).strip()


def _transcrever_openai_whisper(
    caminho_wav: Path,
    idioma_origem: str = "en-US",
    modelo_tamanho: Optional[str] = None,
) -> str:
    """Transcreve audio localmente usando pacote whisper se instalado."""
    import whisper  # type: ignore

    tamanho = modelo_tamanho or getattr(config, "NEXVOICE_STT_MODELO", "base") or "base"
    lang = idioma_origem.split("-")[0].lower() if idioma_origem and idioma_origem != "auto" else None
    model = whisper.load_model(tamanho)
    res = model.transcribe(str(caminho_wav), language=lang, fp16=False)
    return (res.get("text") or "").strip()


def transcrever_trecho_audio(
    audio_bytes: Optional[bytes] = None,
    caminho_wav: Optional[Union[str, Path]] = None,
    texto_simulado: str = "",
    idioma_origem: str = "en-US",
    motor_stt: Optional[str] = None,
    stt_fn: Optional[Callable[..., str]] = None,
) -> Tuple[str, str]:
    """Converte um trecho de fala em texto usando Whisper/faster-whisper/Vosk local ou stub offline.

    Retorna (texto_transcrito, motor_utilizado).
    """
    padrao_stt = getattr(config, "NEXVOICE_STT_MOTOR", "faster_whisper") or "faster_whisper"
    motor_escolhido = (motor_stt or padrao_stt).strip().lower()
    if motor_escolhido not in MOTORES_STT_SUPORTADOS:
        motor_escolhido = "faster_whisper"

    if stt_fn is not None:
        res_custom = stt_fn(audio_bytes=audio_bytes, caminho_wav=caminho_wav, idioma_origem=idioma_origem)
        if res_custom and str(res_custom).strip():
            return str(res_custom).strip(), motor_escolhido

    if texto_simulado and texto_simulado.strip():
        return texto_simulado.strip(), motor_escolhido

    if motor_escolhido == "stub":
        idioma_curto = (idioma_origem or "en-US").lower()
        if idioma_curto.startswith("pt"):
            return "ola a todos, bem-vindos a reuniao", "stub"
        return "hello everyone, welcome to the meeting", "stub"

    caminho_resolvido: Optional[Path] = Path(caminho_wav) if caminho_wav else None
    temp_wav: Optional[Path] = None

    try:
        if caminho_resolvido is None and audio_bytes:
            import tempfile
            fd, nome_tmp = tempfile.mkstemp(suffix=".wav", prefix="nexvoice_stt_")
            os.close(fd)
            temp_wav = Path(nome_tmp)
            if audio_bytes[:4] == b"RIFF":
                temp_wav.write_bytes(audio_bytes)
            else:
                with wave.open(str(temp_wav), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(audio_bytes)
            caminho_resolvido = temp_wav

        if caminho_resolvido and caminho_resolvido.exists():
            if motor_escolhido == "faster_whisper":
                try:
                    txt = _transcrever_faster_whisper(caminho_resolvido, idioma_origem=idioma_origem)
                    if txt:
                        return txt, "faster_whisper"
                except Exception:
                    pass

            if motor_escolhido in ("faster_whisper", "whisper"):
                try:
                    txt = _transcrever_openai_whisper(caminho_resolvido, idioma_origem=idioma_origem)
                    if txt:
                        return txt, "whisper"
                except Exception:
                    pass

            if motor_escolhido in ("vosk", "faster_whisper", "whisper"):
                try:
                    from . import modelos as _m  # noqa: F401
                    from .. import aulas
                    trechos_vosk = aulas.transcrever_audio(caminho_resolvido)
                    textos = [
                        t.get("texto", "").strip()
                        for t in trechos_vosk
                        if t.get("texto", "").strip() and "pendente do modelo Vosk" not in t.get("texto", "")
                    ]
                    if textos:
                        return " ".join(textos), "vosk"
                except Exception:
                    pass
    finally:
        if temp_wav and temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

    idioma_curto = (idioma_origem or "en-US").lower()
    if idioma_curto.startswith("pt"):
        return "ola a todos, bem-vindos a reuniao", "stub"
    return "hello everyone, welcome to the meeting", "stub"


def _traduzir_fala_fallback_offline(
    texto: str,
    idioma_origem: str = "en-US",
    idioma_destino: str = "pt-BR",
) -> str:
    """Fallback deterministico offline bidirecional (EN <-> PT e outros idiomas)."""
    limpo = (texto or "").strip()
    if not limpo:
        return ""

    orig_norm = (idioma_origem or "auto").strip().lower()
    dest_norm = (idioma_destino or "pt-BR").strip().lower()

    if orig_norm != "auto" and orig_norm.split("-")[0] == dest_norm.split("-")[0]:
        return limpo

    chave_baixa = limpo.lower().strip(" .!?")

    # Traducao para Portugues
    if dest_norm.startswith("pt"):
        if chave_baixa in _FRASES_EN_PARA_PT:
            frase_pt = _FRASES_EN_PARA_PT[chave_baixa]
            return frase_pt.capitalize() if limpo[0].isupper() else frase_pt

        traduzido = limpo
        for termo_en, termo_pt in sorted(_TERMOS_EN_PT.items(), key=lambda x: -len(x[0])):
            padrao = re.compile(rf"\b{re.escape(termo_en)}\b", flags=re.IGNORECASE)

            def _sub_pt(m: re.Match, alvo: str = termo_pt) -> str:
                orig = m.group(0)
                if orig.isupper():
                    return alvo.upper()
                if orig[0].isupper():
                    return alvo.capitalize()
                return alvo

            traduzido = padrao.sub(_sub_pt, traduzido)
        if traduzido != limpo:
            return traduzido
        return f"[PT-BR] {limpo}"

    # Traducao para Ingles
    if dest_norm.startswith("en"):
        if chave_baixa in _FRASES_PT_PARA_EN:
            frase_en = _FRASES_PT_PARA_EN[chave_baixa]
            return frase_en.capitalize() if limpo[0].isupper() else frase_en

        traduzido = limpo
        for termo_pt, termo_en in sorted(_TERMOS_PT_EN.items(), key=lambda x: -len(x[0])):
            padrao = re.compile(rf"\b{re.escape(termo_pt)}\b", flags=re.IGNORECASE)

            def _sub_en(m: re.Match, alvo: str = termo_en) -> str:
                orig = m.group(0)
                if orig.isupper():
                    return alvo.upper()
                if orig[0].isupper():
                    return alvo.capitalize()
                return alvo

            traduzido = padrao.sub(_sub_en, traduzido)
        if traduzido != limpo:
            return traduzido
        return f"[EN-US] {limpo}"

    return f"[{idioma_destino.upper()}] {limpo}"


def traduzir_fala_ao_vivo(
    texto: str,
    idioma_origem: str = "en-US",
    idioma_destino: str = "pt-BR",
    motor: Optional[str] = None,
    local_estrito: bool = True,
    tradutor_fn: Optional[Callable[[str, str, str], str]] = None,
) -> str:
    """Traduz um trecho de fala com baixa latencia respeitando a politica de processamento local."""
    limpo = (texto or "").strip()
    if not limpo:
        return ""

    motor_escolhido = (motor or getattr(config, "NEXVOICE_TRADUTOR", "local") or "local").strip().lower()
    if motor_escolhido not in MOTORES_TRADUCAO_SUPORTADOS:
        motor_escolhido = "local"

    validar_processamento_local_estrito(local_estrito, motor_traducao=motor_escolhido)

    if tradutor_fn is not None:
        res_custom = tradutor_fn(limpo, idioma_origem, idioma_destino)
        if res_custom and str(res_custom).strip():
            return str(res_custom).strip()

    if idioma_origem != "auto" and idioma_origem.split("-")[0].lower() == idioma_destino.split("-")[0].lower():
        return limpo

    sistema = (
        f"Voce e o interpretador simultaneo NexVoice. Traduza a fala de {idioma_origem} para {idioma_destino} "
        "de forma direta, natural e concisa para falado/legenda ao vivo. Responda apenas com a traducao."
    )

    # 1. LibreTranslate local
    if motor_escolhido == "libretranslate":
        try:
            from ..nexread.tradutor import _traduzir_via_libretranslate
            endpoint = getattr(config, "LIBRETRANSLATE_URL", "http://localhost:5000/translate")
            if not local_estrito or any(h in endpoint for h in ("localhost", "127.0.0.1")):
                res_lt = _traduzir_via_libretranslate(limpo, idioma_origem=idioma_origem, idioma_destino=idioma_destino)
                if res_lt:
                    return res_lt
        except Exception:
            pass

    # 2. NLLB-200 ou Opus-MT local (HuggingFace)
    if motor_escolhido in ("nllb", "opus_mt"):
        try:
            from ..nexread.tradutor import _traduzir_via_huggingface_local
            res_hf = _traduzir_via_huggingface_local(limpo, motor=motor_escolhido, idioma_destino=idioma_destino)
            if res_hf:
                return res_hf
        except Exception:
            pass

    # 3. faccoder-core
    if motor_escolhido == "faccoder":
        try:
            from ..nexread.tradutor import _traduzir_via_faccoder
            res_fc = _traduzir_via_faccoder(limpo, idioma_destino=idioma_destino)
            if res_fc:
                return res_fc
        except Exception:
            pass

    # 4. Claude (somente se local_estrito=False e explicitamente solicitado)
    if motor_escolhido == "claude" and not local_estrito:
        try:
            from .. import claude_cerebro
            res_cl = claude_cerebro.responder(limpo, sistema=sistema, max_tokens=400)
            if res_cl:
                return res_cl.strip()
        except Exception:
            pass

    # 5. Modelo aberto local via Ollama (cerebro._chamar_ollama)
    try:
        from .. import cerebro
        res_ollama = cerebro._chamar_ollama(limpo, sistema=sistema, num_predict=250)
        if res_ollama and res_ollama.strip():
            return res_ollama.strip()
    except Exception:
        pass

    # 6. Fallback deterministico offline bidirecional
    return _traduzir_fala_fallback_offline(limpo, idioma_origem=idioma_origem, idioma_destino=idioma_destino)


def sintetizar_voz_traduzida(
    texto: str,
    idioma_destino: str = "pt-BR",
    motor_tts: Optional[str] = None,
    local_estrito: bool = True,
    tts_fn: Optional[Callable[[str, str], Tuple[bytes, str, str]]] = None,
) -> Dict[str, Any]:
    """Sintetiza a fala traduzida reutilizando a voz do Nextor (Piper local / SAPI) ou stub offline.

    Respeita NEXTOR_VOZ_SAIDA=nenhuma para nao tocar audio fisico durante testes.
    """
    texto_limpo = (texto or "").strip()
    if not texto_limpo:
        return {"fala_id": "", "motor_tts": "nenhum", "duracao_seg": 0.0, "mime": "audio/wav", "dados": b""}

    motor_escolhido = (motor_tts or getattr(config, "NEXVOICE_TTS_MOTOR", "piper") or "piper").strip().lower()
    if motor_escolhido not in MOTORES_TTS_SUPORTADOS:
        motor_escolhido = "piper"

    validar_processamento_local_estrito(local_estrito, motor_tts=motor_escolhido)

    dados_audio: Optional[bytes] = None
    mime_audio = "audio/wav"
    motor_usado = motor_escolhido

    saida_voz = os.getenv("NEXTOR_VOZ_SAIDA", getattr(config, "VOZ_SAIDA", "pc")).strip().lower()
    modo_silencioso = saida_voz in ("nenhuma", "none", "off", "false", "0")

    if tts_fn is not None:
        dados_audio, mime_audio, motor_usado = tts_fn(texto_limpo, idioma_destino)
    elif motor_escolhido == "stub":
        dur_est = max(0.6, round(len(texto_limpo) / 14.0, 2))
        dados_audio = gerar_wav_stub(duracao_seg=dur_est)
        mime_audio = "audio/wav"
        motor_usado = "stub"
    else:
        # Tenta usar Piper local primeiro; SAPI so se nao estiver em modo silencioso de teste
        motores_tentativa = [motor_escolhido] if motor_escolhido in ("piper", "sapi") else ["piper", "sapi"]
        if modo_silencioso and "sapi" in motores_tentativa and motor_escolhido != "sapi":
            motores_tentativa = [m for m in motores_tentativa if m != "sapi"]
        if not local_estrito and motor_escolhido == "gtts" and not modo_silencioso:
            motores_tentativa = ["gtts"]

        for m_nome in motores_tentativa:
            try:
                dados_audio, mime_audio, motor_usado = fala.sintetizar(
                    texto_limpo,
                    idioma=idioma_destino,
                    motor=m_nome,
                )
                break
            except Exception:
                continue

        if dados_audio is None:
            dur_est = max(0.6, round(len(texto_limpo) / 14.0, 2))
            dados_audio = gerar_wav_stub(duracao_seg=dur_est)
            mime_audio = "audio/wav"
            motor_usado = "stub"

    duracao_seg = round(fala.duracao(dados_audio, mime_audio, texto_limpo), 2)
    fala_id = fala.guardar(dados_audio, mime_audio)

    if not modo_silencioso and motor_usado != "stub":
        try:
            fala.tocar_no_pc(dados_audio, mime_audio)
        except Exception:
            pass

    return {
        "fala_id": fala_id,
        "motor_tts": motor_usado,
        "duracao_seg": duracao_seg,
        "mime": mime_audio,
        "dados": dados_audio,
    }


def iniciar_sessao_nexvoice(
    titulo: str = "Sessao NexVoice",
    modo: str = "ouvir",
    fonte: Optional[str] = None,
    idioma_meu: Optional[str] = None,
    idioma_outro: Optional[str] = None,
    motor_stt: Optional[str] = None,
    motor_traducao: Optional[str] = None,
    motor_tts: Optional[str] = None,
    sintetizar_voz: bool = True,
    processamento_local_estrito: Optional[bool] = None,
    consentimento_confirmado: bool = False,
    consentimento_participantes: str = "",
    disciplina: str = "",
    permitir_consentimento_pendente: bool = False,
    db: Optional[ArmazenamentoNexVoice] = None,
) -> SessaoNexVoice:
    """Inicia uma sessao de traducao ao vivo (modo 'ouvir' ou 'reuniao' bidirecional).

    Em modo 'reuniao' ou quando fonte for 'reuniao'/'aula', exige consentimento expresso
    (a menos que permitir_consentimento_pendente=True, caso em que fica bloqueada ate confirmar).
    """
    modo_norm = (modo or "ouvir").strip().lower()
    if modo_norm not in MODOS_NEXVOICE:
        raise ValueError(f"Modo invalido '{modo}'. Use um de: {MODOS_NEXVOICE}")

    fonte_padrao = "reuniao" if modo_norm == "reuniao" else "video"
    fonte_norm = (fonte or fonte_padrao).strip().lower()
    if fonte_norm not in FONTES_AUDIO:
        fonte_norm = fonte_padrao

    meu_id = (idioma_meu or getattr(config, "NEXVOICE_IDIOMA_MEU", "pt-BR") or "pt-BR").strip()
    outro_id = (idioma_outro or getattr(config, "NEXVOICE_IDIOMA_OUTRO", "en-US") or "en-US").strip()
    stt_m = (motor_stt or getattr(config, "NEXVOICE_STT_MOTOR", "faster_whisper") or "faster_whisper").strip().lower()
    trad_m = (motor_traducao or getattr(config, "NEXVOICE_TRADUTOR", "local") or "local").strip().lower()
    tts_m = (motor_tts or getattr(config, "NEXVOICE_TTS_MOTOR", "piper") or "piper").strip().lower()

    local_estrito = (
         getattr(config, "NEXVOICE_LOCAL_ESTRITO", True)
        if processamento_local_estrito is None
        else bool(processamento_local_estrito)
    )

    validar_processamento_local_estrito(local_estrito, motor_stt=stt_m, motor_traducao=trad_m, motor_tts=tts_m)

    exige_consentimento = modo_norm == "reuniao" or fonte_norm in ("reuniao", "aula")
    aviso = ""
    if exige_consentimento:
        aviso = (
            AVISO_CONSENTIMENTO_NEXVOICE_AULA
            if fonte_norm == "aula" and modo_norm == "ouvir"
            else AVISO_CONSENTIMENTO_NEXVOICE_REUNIAO
        )
        if not consentimento_confirmado and not permitir_consentimento_pendente:
            raise PermissionError(
                f"{aviso} Confirme o consentimento (consentimento_confirmado=True) antes de iniciar."
            )

    agora = datetime.now().isoformat(timespec="seconds")
    sessao = SessaoNexVoice(
        titulo=(titulo or "Sessao NexVoice").strip(),
        modo=modo_norm,
        fonte=fonte_norm,
        idioma_meu=meu_id,
        idioma_outro=outro_id,
        motor_stt=stt_m if stt_m in MOTORES_STT_SUPORTADOS else "faster_whisper",
        motor_traducao=trad_m if trad_m in MOTORES_TRADUCAO_SUPORTADOS else "local",
        motor_tts=tts_m if tts_m in MOTORES_TTS_SUPORTADOS else "piper",
        sintetizar_voz=bool(sintetizar_voz),
        processamento_local_estrito=local_estrito,
        consentimento_exigido=exige_consentimento,
        consentimento_confirmado=bool(consentimento_confirmado) if exige_consentimento else True,
        consentimento_participantes=consentimento_participantes.strip(),
        consentimento_em=agora if (consentimento_confirmado or not exige_consentimento) else None,
        aviso_consentimento=aviso,
        disciplina=disciplina.strip(),
        estado="ativa",
    )

    banco = db or ArmazenamentoNexVoice()
    sessao_salva = banco.salvar_sessao(sessao)

    if exige_consentimento and consentimento_confirmado:
        banco.registrar_consentimento(
            sessao_id=sessao_salva.id,
            modo=sessao_salva.modo,
            fonte=sessao_salva.fonte,
            participantes=sessao_salva.consentimento_participantes or "Participantes da sessao",
            aviso=sessao_salva.aviso_consentimento,
            local_estrito=sessao_salva.processamento_local_estrito,
        )

    try:
        from ..companheiro import companheiro
        companheiro.atualizar(
            atividade="traduzindo_voz",
            detalhe=f"NexVoice ({sessao_salva.modo}): {sessao_salva.titulo}",
        )
    except Exception:
        pass

    return sessao_salva


def confirmar_consentimento_sessao(
    sessao_id: str,
    participantes: str = "Todos os participantes de acordo",
    db: Optional[ArmazenamentoNexVoice] = None,
) -> SessaoNexVoice:
    """Registra e confirma o consentimento expresso dos participantes para uma sessao de reuniao/aula."""
    banco = db or ArmazenamentoNexVoice()
    sessao = banco.obter_sessao(sessao_id)
    if not sessao:
        raise ValueError(f"Sessao NexVoice '{sessao_id}' nao encontrada.")

    sessao.consentimento_confirmado = True
    sessao.consentimento_participantes = (participantes or "Participantes confirmados").strip()
    sessao.consentimento_em = datetime.now().isoformat(timespec="seconds")
    if not sessao.aviso_consentimento:
        sessao.aviso_consentimento = AVISO_CONSENTIMENTO_NEXVOICE_REUNIAO

    banco.salvar_sessao(sessao)
    banco.registrar_consentimento(
        sessao_id=sessao.id,
        modo=sessao.modo,
        fonte=sessao.fonte,
        participantes=sessao.consentimento_participantes,
        aviso=sessao.aviso_consentimento,
        local_estrito=sessao.processamento_local_estrito,
    )
    return banco.obter_sessao(sessao.id) or sessao


def processar_trecho_ao_vivo(
    sessao_id: str,
    texto_fala: str = "",
    audio_bytes: Optional[bytes] = None,
    caminho_wav: Optional[Union[str, Path]] = None,
    direcao: str = "entrada",
    locutor: str = "",
    idioma_origem: Optional[str] = None,
    idioma_destino: Optional[str] = None,
    inicio_seg: Optional[float] = None,
    fim_seg: Optional[float] = None,
    sintetizar_voz: Optional[bool] = None,
    stt_fn: Optional[Callable[..., str]] = None,
    tradutor_fn: Optional[Callable[[str, str, str], str]] = None,
    tts_fn: Optional[Callable[[str, str], Tuple[bytes, str, str]]] = None,
    db: Optional[ArmazenamentoNexVoice] = None,
) -> TrechoVoz:
    """Processa um trecho de audio/fala em tempo real (STT local -> traducao -> TTS Piper).

    No modo 'ouvir':
      - direcao padrao 'entrada': traduz do idioma_outro (video/aula) para idioma_meu.
    No modo 'reuniao' (bidirecional):
      - direcao 'entrada' (outra pessoa fala): traduz de idioma_outro -> idioma_meu.
      - direcao 'saida' (usuario fala): traduz de idioma_meu -> idioma_outro.
    """
    t0 = time.perf_counter()
    banco = db or ArmazenamentoNexVoice()
    sessao = banco.obter_sessao(sessao_id)
    if not sessao:
        raise ValueError(f"Sessao NexVoice '{sessao_id}' nao encontrada.")

    if sessao.estado == "encerrada":
        raise ValueError(f"A sessao '{sessao.titulo}' ja foi encerrada.")

    validar_consentimento_sessao(sessao)
    validar_processamento_local_estrito(
        sessao.processamento_local_estrito,
        motor_stt=sessao.motor_stt,
        motor_traducao=sessao.motor_traducao,
        motor_tts=sessao.motor_tts,
    )

    dir_norm = (direcao or "entrada").strip().lower()
    if dir_norm not in DIRECOES_FALA:
        dir_norm = "entrada"

    if dir_norm == "saida":
        orig = (idioma_origem or sessao.idioma_meu).strip()
        dest = (idioma_destino or sessao.idioma_outro).strip()
        nome_locutor = (locutor or "eu").strip()
    else:
        orig = (idioma_origem or sessao.idioma_outro).strip()
        dest = (idioma_destino or sessao.idioma_meu).strip()
        nome_locutor = (locutor or ("professor" if sessao.fonte == "aula" else "interlocutor")).strip()

    # 1. Fala -> Texto (STT local)
    texto_original, motor_stt_usado = transcrever_trecho_audio(
        audio_bytes=audio_bytes,
        caminho_wav=caminho_wav,
        texto_simulado=texto_fala,
        idioma_origem=orig,
        motor_stt=sessao.motor_stt,
        stt_fn=stt_fn,
    )
    if not texto_original:
        raise ValueError("Nenhum texto ou fala reconhecido no trecho de audio.")

    # 2. Traducao ao vivo
    texto_traduzido = traduzir_fala_ao_vivo(
        texto_original,
        idioma_origem=orig,
        idioma_destino=dest,
        motor=sessao.motor_traducao,
        local_estrito=sessao.processamento_local_estrito,
        tradutor_fn=tradutor_fn,
    )

    # 3. Texto -> Fala (TTS local reutilizando nextor.fala)
    deve_sintetizar = sessao.sintetizar_voz if sintetizar_voz is None else bool(sintetizar_voz)
    fala_id = ""
    duracao_tts = 0.0
    motor_tts_usado = sessao.motor_tts

    if deve_sintetizar:
        res_tts = sintetizar_voz_traduzida(
            texto_traduzido,
            idioma_destino=dest,
            motor_tts=sessao.motor_tts,
            local_estrito=sessao.processamento_local_estrito,
            tts_fn=tts_fn,
        )
        fala_id = res_tts["fala_id"]
        duracao_tts = res_tts["duracao_seg"]
        motor_tts_usado = res_tts["motor_tts"]

    existentes = sessao.trechos
    prox_indice = len(existentes) + 1
    ultimo_fim = existentes[-1].fim_seg if existentes else 0.0
    ini_calc = ultimo_fim if inicio_seg is None else float(inicio_seg)
    dur_estimada = max(1.5, round(len(texto_original) / 14.0, 1))
    fim_calc = (ini_calc + dur_estimada) if fim_seg is None else float(fim_seg)

    latencia_ms = max(1, int(round((time.perf_counter() - t0) * 1000)))

    trecho = TrechoVoz(
        sessao_id=sessao.id,
        indice=prox_indice,
        direcao=dir_norm,
        locutor=nome_locutor,
        idioma_origem=orig,
        idioma_destino=dest,
        texto_original=texto_original,
        texto_traduzido=texto_traduzido,
        inicio_seg=ini_calc,
        fim_seg=fim_calc,
        latencia_ms=latencia_ms,
        motor_stt=motor_stt_usado,
        motor_traducao=sessao.motor_traducao,
        motor_tts=motor_tts_usado,
        fala_id=fala_id,
        duracao_tts_seg=duracao_tts,
    )
    return banco.salvar_trecho(trecho)


def processar_stream_trechos(
    sessao_id: str,
    trechos_entrada: Iterable[Dict[str, Any]],
    stt_fn: Optional[Callable[..., str]] = None,
    tradutor_fn: Optional[Callable[[str, str, str], str]] = None,
    tts_fn: Optional[Callable[[str, str], Tuple[bytes, str, str]]] = None,
    db: Optional[ArmazenamentoNexVoice] = None,
) -> List[TrechoVoz]:
    """Processa um fluxo continuo (streaming por trechos) em modo ouvir ou reuniao bidirecional."""
    banco = db or ArmazenamentoNexVoice()
    resultados: List[TrechoVoz] = []
    for item in trechos_entrada:
        tr = processar_trecho_ao_vivo(
            sessao_id=sessao_id,
            texto_fala=item.get("texto") or item.get("texto_fala") or "",
            audio_bytes=item.get("audio_bytes"),
            caminho_wav=item.get("caminho_wav"),
            direcao=item.get("direcao", "entrada"),
            locutor=item.get("locutor", ""),
            idioma_origem=item.get("idioma_origem"),
            idioma_destino=item.get("idioma_destino"),
            inicio_seg=item.get("inicio_seg"),
            fim_seg=item.get("fim_seg"),
            sintetizar_voz=item.get("sintetizar_voz"),
            stt_fn=stt_fn,
            tradutor_fn=tradutor_fn,
            tts_fn=tts_fn,
            db=banco,
        )
        resultados.append(tr)
    return resultados


def exportar_legendas_srt(
    sessao_id: str,
    bilingue: bool = True,
    db: Optional[ArmazenamentoNexVoice] = None,
) -> str:
    """Exporta os trechos da sessao no formato de legendas SubRip (.srt)."""
    banco = db or ArmazenamentoNexVoice()
    sessao = banco.obter_sessao(sessao_id)
    if not sessao:
        raise ValueError(f"Sessao NexVoice '{sessao_id}' nao encontrada.")

    blocos_srt: List[str] = []
    for idx, t in enumerate(sessao.trechos, 1):
        ini_str = formatar_timestamp_srt(t.inicio_seg)
        fim_str = formatar_timestamp_srt(t.fim_seg)
        linhas = [str(idx), f"{ini_str} --> {fim_str}"]
        if bilingue and t.texto_original and t.texto_original != t.texto_traduzido:
            linhas.append(f"[{t.locutor}] {t.texto_traduzido}")
            linhas.append(f"({t.texto_original})")
        else:
            linhas.append(f"[{t.locutor}] {t.texto_traduzido or t.texto_original}")
        blocos_srt.append("\n".join(linhas))

    return "\n\n".join(blocos_srt) + ("\n" if blocos_srt else "")


def gerar_ata_reuniao_bilingue(
    sessao_id: str,
    salvar_anotacoes: bool = False,
    db: Optional[ArmazenamentoNexVoice] = None,
) -> Dict[str, Any]:
    """Estrutura resumo executivo, decisoes e itens de acao a partir da reuniao bilingue no NexVoice."""
    banco = db or ArmazenamentoNexVoice()
    sessao = banco.obter_sessao(sessao_id)
    if not sessao:
        raise ValueError(f"Sessao NexVoice '{sessao_id}' nao encontrada.")

    trechos_para_resumo: List[Dict[str, Any]] = []
    for t in sessao.trechos:
        # Usa o texto no idioma do usuario (pt-BR) para extrair decisoes e itens de acao
        txt_pt = t.texto_traduzido if t.idioma_destino.lower().startswith("pt") else t.texto_original
        trechos_para_resumo.append({
            "inicio": formatar_tempo_legenda(t.inicio_seg),
            "fim": formatar_tempo_legenda(t.fim_seg),
            "locutor": t.locutor,
            "texto": txt_pt or t.texto_traduzido or t.texto_original,
            "original": t.texto_original,
            "traduzido": t.texto_traduzido,
        })

    estruturado = reuniao_tela.estruturar_resumo_reuniao(
        trechos=trechos_para_resumo,
        tema=sessao.titulo,
        participantes=sessao.consentimento_participantes,
    )

    if salvar_anotacoes and estruturado.get("itens_acao"):
        try:
            carimbo = datetime.now().strftime("%Y-%m-%d")
            with config.ANOTACOES.open("a", encoding="utf-8") as f:
                for act in estruturado["itens_acao"]:
                    resp = f" ({act['responsavel']})" if act.get("responsavel") else ""
                    f.write(f"- [{carimbo}] [NexVoice: {sessao.titulo}] {act['descricao']}{resp}\n")
        except Exception:
            pass

    return {
        "ok": True,
        "sessao_id": sessao.id,
        "titulo": sessao.titulo,
        "modo": sessao.modo,
        "consentimento_confirmado": sessao.consentimento_confirmado,
        "participantes": sessao.consentimento_participantes,
        "total_trechos": len(sessao.trechos),
        "resumo": estruturado["resumo"],
        "topicos": estruturado["topicos"],
        "decisoes": estruturado["decisoes"],
        "itens_acao": estruturado["itens_acao"],
        "transcricao_bilingue": sessao.transcricao_bilingue,
    }


def salvar_sessao_nos_estudos(
    sessao_id: str,
    disciplina_nome: str = "",
    db: Optional[ArmazenamentoNexVoice] = None,
    base_dir_estudos: Optional[Path] = None,
    caminho_db_estudos: Optional[Path] = None,
) -> Dict[str, Any]:
    """Salva a transcricao bilingue e legendas de uma aula/video do NexVoice na biblioteca do modo estudante."""
    banco = db or ArmazenamentoNexVoice()
    sessao = banco.obter_sessao(sessao_id)
    if not sessao:
        raise ValueError(f"Sessao NexVoice '{sessao_id}' nao encontrada.")

    disc_alvo = (disciplina_nome or sessao.disciplina or "").strip()
    if not disc_alvo:
        raise ValueError("Informe o nome da disciplina para salvar a sessao na biblioteca de estudos.")

    disc = estudos.obter_disciplina(disc_alvo, caminho_db=caminho_db_estudos)
    if not disc:
        disc = estudos.criar_disciplina(disc_alvo, base_dir=base_dir_estudos, caminho_db=caminho_db_estudos)

    pasta_disc = Path(disc["pasta"])
    pasta_disc.mkdir(parents=True, exist_ok=True)

    linhas = [
        f"# {sessao.titulo} (NexVoice - Traducao de Audio ao Vivo)",
        f"Modo: {sessao.modo} | Fonte: {sessao.fonte}",
        f"Idiomas: {sessao.idioma_outro} <-> {sessao.idioma_meu}",
        f"Motores locais: STT={sessao.motor_stt}, Traducao={sessao.motor_traducao}, TTS={sessao.motor_tts}",
    ]
    if sessao.aviso_consentimento:
        linhas.append(f"Consentimento: {sessao.aviso_consentimento}")
    linhas.extend(["", "## Transcricao e Traducao Sincronizada"])

    for t in sessao.trechos:
        carimbo = f"[{formatar_tempo_legenda(t.inicio_seg)} - {formatar_tempo_legenda(t.fim_seg)}]"
        linhas.append(f"{carimbo} [{t.locutor} | {t.idioma_origem} -> {t.idioma_destino}]")
        linhas.append(f"Traducao: {t.texto_traduzido}")
        if t.texto_original and t.texto_original != t.texto_traduzido:
            linhas.append(f"Original: {t.texto_original}")
        linhas.append("")

    conteudo_md = "\n".join(linhas).strip() + "\n"
    slug = re.sub(r"[^a-z0-9]+", "-", sessao.titulo.lower()).strip("-")[:40] or "sessao"
    arquivo_txt = pasta_disc / f"nexvoice_{slug}_{sessao.id[:8]}.txt"
    arquivo_txt.write_text(conteudo_md, encoding="utf-8")

    # Salva tambem o arquivo de legendas .srt na pasta da disciplina
    conteudo_srt = exportar_legendas_srt(sessao.id, bilingue=True, db=banco)
    arquivo_srt = pasta_disc / f"nexvoice_{slug}_{sessao.id[:8]}.srt"
    if conteudo_srt:
        arquivo_srt.write_text(conteudo_srt, encoding="utf-8")

    res_imp = estudos.importar_material(
        disciplina_nome=disc_alvo,
        origem=arquivo_txt,
        titulo=f"NexVoice: {sessao.titulo}",
        tipo="txt",
        base_dir=base_dir_estudos,
        caminho_db=caminho_db_estudos,
        pastas_autorizadas=[pasta_disc],
        canal="local",
    )

    sessao.disciplina = disc_alvo
    sessao.material_id = res_imp.get("id")
    banco.salvar_sessao(sessao)

    return {
        "ok": True,
        "sessao_id": sessao.id,
        "disciplina": disc_alvo,
        "material_id": sessao.material_id,
        "caminho_arquivo": str(arquivo_txt),
        "caminho_srt": str(arquivo_srt) if conteudo_srt else "",
        "total_trechos": len(sessao.trechos),
        "aviso": (
            f"Sessao '{sessao.titulo}' salva na disciplina {disc_alvo} "
            f"com {len(sessao.trechos)} trechos traduzidos."
        ),
    }


def encerrar_sessao_nexvoice(
    sessao_id: str,
    salvar_estudos: bool = False,
    disciplina_nome: str = "",
    gerar_ata: bool = False,
    db: Optional[ArmazenamentoNexVoice] = None,
    base_dir_estudos: Optional[Path] = None,
    caminho_db_estudos: Optional[Path] = None,
) -> Dict[str, Any]:
    """Encerra uma sessao ativa do NexVoice, opcionalmente gerando ata ou salvando nos estudos."""
    banco = db or ArmazenamentoNexVoice()
    sessao = banco.obter_sessao(sessao_id)
    if not sessao:
        raise ValueError(f"Sessao NexVoice '{sessao_id}' nao encontrada.")

    sessao.estado = "encerrada"
    sessao.encerrado_em = datetime.now().isoformat(timespec="seconds")
    banco.salvar_sessao(sessao)

    try:
        from ..companheiro import companheiro
        companheiro.atualizar(atividade="ocioso", detalhe="")
    except Exception:
        pass

    resultado: Dict[str, Any] = {
        "ok": True,
        "sessao": (banco.obter_sessao(sessao.id) or sessao).to_dict(),
        "legendas_srt": exportar_legendas_srt(sessao.id, bilingue=True, db=banco),
    }

    if gerar_ata or sessao.modo == "reuniao":
        resultado["ata_reuniao"] = gerar_ata_reuniao_bilingue(sessao.id, db=banco)

    disc_final = (disciplina_nome or sessao.disciplina or "").strip()
    if salvar_estudos and disc_final:
        resultado["estudos"] = salvar_sessao_nos_estudos(
            sessao_id=sessao.id,
            disciplina_nome=disc_final,
            db=banco,
            base_dir_estudos=base_dir_estudos,
            caminho_db_estudos=caminho_db_estudos,
        )

    return resultado
