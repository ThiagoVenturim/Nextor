"""Adaptador da Alexa para o Nextor.

Permite interagir com o Nextor atraves de uma custom skill da Amazon Alexa.
Implementa:
- Verificacao rigorosa de assinatura da requisicao da Alexa:
  * URL do certificado (SignatureCertChainUrl): protocolo HTTPS, host s3.amazonaws.com,
    porta 443, caminho iniciando com /echo.api/
  * Validacao do certificado X.509: periodo de validade e SAN contendo echo-api.amazon.com
  * Validacao do timestamp da requisicao (tolerancia maxima de 150 segundos)
  * Verificacao criptografica RSA com padding PKCS1v15 e SHA-1 (com suporte a SHA-256)
- Validacao de Application ID (Skill ID)
- Validacao opcional de token do adaptador via query/header
- Despacho de LaunchRequest, IntentRequest (livre e padrao) e SessionEndedRequest
  para o endpoint /v1/assistente do Nextor
"""
import base64
from datetime import datetime, timezone
import hmac
import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import ExtensionOID, NameOID

from . import config

log = logging.getLogger("nextor.alexa")

# Cache em memoria para certificados baixados: url -> x509.Certificate
_CERTIFICADOS_CACHE: Dict[str, x509.Certificate] = {}

# Tolerancia de timestamp recomendada pela Amazon (em segundos)
TOLERANCIA_TIMESTAMP_SEGUNDOS = 150


def limpar_cache_certificados() -> None:
    """Limpa o cache em memoria de certificados."""
    _CERTIFICADOS_CACHE.clear()


def validar_url_certificado(url: str) -> bool:
    """Valida se a URL do certificado cumpre estritamente os requisitos da Amazon:
    - Esquema https (case-insensitive)
    - Hostname s3.amazonaws.com (case-insensitive)
    - Caminho iniciando com /echo.api/ (case-sensitive)
    - Porta 443 se especificada
    - Sem caminhos relativos ou transversais
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    if parsed.scheme.lower() != "https":
        return False

    hostname = (parsed.hostname or "").lower()
    if hostname != "s3.amazonaws.com":
        return False

    if parsed.port not in (None, 443):
        return False

    caminho = parsed.path
    if not caminho.startswith("/echo.api/"):
        return False

    if "/../" in caminho or caminho.endswith("/.."):
        return False

    return True


def baixar_certificado(url: str, timeout: float = 5.0) -> bytes:
    """Baixa o conteudo PEM do certificado X.509 da URL fornecida."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Nextor-Alexa-Adapter/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def obter_certificado(
    url: str,
    baixador: Optional[Callable[[str], bytes]] = None,
    timeout: float = 5.0,
) -> x509.Certificate:
    """Obtem o certificado X.509 a partir da URL, utilizando cache em memoria."""
    if url in _CERTIFICADOS_CACHE:
        return _CERTIFICADOS_CACHE[url]

    func_baixar = baixador or (lambda u: baixar_certificado(u, timeout=timeout))
    pem_bytes = func_baixar(url)
    cert = x509.load_pem_x509_certificate(pem_bytes)
    _CERTIFICADOS_CACHE[url] = cert
    return cert


def validar_certificado(cert: x509.Certificate, agora: Optional[datetime] = None) -> bool:
    """Valida periodo de vigencia e presenca de echo-api.amazon.com no certificado."""
    if agora is None:
        agora = datetime.now(timezone.utc)
    elif agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)

    # Validacao de datas
    try:
        inicio = getattr(cert, "not_valid_before_utc", None)
        fim = getattr(cert, "not_valid_after_utc", None)
        if inicio is None or fim is None:
            inicio = cert.not_valid_before.replace(tzinfo=timezone.utc)
            fim = cert.not_valid_after.replace(tzinfo=timezone.utc)
        if not (inicio <= agora <= fim):
            log.warning("Certificado expirado ou ainda nao vigente (%s a %s, agora %s)", inicio, fim, agora)
            return False
    except Exception as e:
        log.warning("Falha ao checar vigencia do certificado: %s", e)
        return False

    # Validacao de Subject Alternative Name (SAN)
    san_valido = False
    try:
        ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        nomes_dns = ext.value.get_values_for_type(x509.DNSName)
        if "echo-api.amazon.com" in nomes_dns:
            san_valido = True
    except Exception:
        san_valido = False

    if not san_valido:
        # Fallback para CN caso nao haja SAN
        try:
            cns = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            for attr in cns:
                if attr.value == "echo-api.amazon.com":
                    san_valido = True
                    break
        except Exception:
            pass

    if not san_valido:
        log.warning("Certificado nao contem echo-api.amazon.com no SAN ou CN")
        return False

    return True


def validar_timestamp(
    timestamp_str: str,
    agora: Optional[datetime] = None,
    tolerancia_segundos: int = TOLERANCIA_TIMESTAMP_SEGUNDOS,
) -> bool:
    """Valida se o timestamp da requisicao esta dentro da janela de tolerancia permitida."""
    if not timestamp_str or not isinstance(timestamp_str, str):
        return False

    try:
        # Formato esperado: ISO-8601 (ex: 2019-05-13T12:34:56Z)
        limpo = timestamp_str.strip().replace("Z", "+00:00")
        dt_req = datetime.fromisoformat(limpo)
        if dt_req.tzinfo is None:
            dt_req = dt_req.replace(tzinfo=timezone.utc)
    except Exception:
        return False

    if agora is None:
        agora = datetime.now(timezone.utc)
    elif agora.tzinfo is None:
        agora = agora.replace(tzinfo=timezone.utc)

    diferenca = abs((agora - dt_req).total_seconds())
    if diferenca > tolerancia_segundos:
        log.warning("Timestamp fora de tolerancia: %s s (maximo %s s)", diferenca, tolerancia_segundos)
        return False

    return True


def validar_assinatura_requisicao(
    raw_body: bytes,
    signature_b64: str,
    cert_url: str,
    agora: Optional[datetime] = None,
    baixador_cert: Optional[Callable[[str], bytes]] = None,
) -> Tuple[bool, str]:
    """Verifica integralmente a assinatura criptografica da requisicao da Alexa.
    Retorna tupla (sucesso, motivo_erro).
    """
    if not validar_url_certificado(cert_url):
        return False, "url_certificado_invalida"

    try:
        cert = obter_certificado(cert_url, baixador=baixador_cert)
    except Exception as e:
        log.warning("Erro ao obter certificado: %s", e)
        return False, "erro_download_certificado"

    if not validar_certificado(cert, agora=agora):
        return False, "certificado_invalido_ou_expirado"

    try:
        sig_bytes = base64.b64decode(signature_b64)
    except Exception:
        return False, "assinatura_base64_invalida"

    pub_key = cert.public_key()
    # Tenta verificacao com SHA-1 (padrao da Alexa) e fallback para SHA-256
    verificado = False
    for hash_algo in (hashes.SHA1(), hashes.SHA256()):
        try:
            pub_key.verify(sig_bytes, raw_body, padding.PKCS1v15(), hash_algo)
            verificado = True
            break
        except Exception:
            continue

    if not verificado:
        return False, "falha_verificacao_assinatura"

    return True, ""


def extrair_application_id(dados: dict) -> str:
    """Extrai o application ID da requisicao da Alexa."""
    if not isinstance(dados, dict):
        return ""
    app_id = (
        dados.get("session", {}).get("application", {}).get("applicationId")
        or dados.get("context", {}).get("System", {}).get("application", {}).get("applicationId")
        or ""
    )
    return str(app_id).strip()


def validar_application_id(dados: dict, app_id_esperado: Optional[str] = None) -> bool:
    """Valida se o Application ID corresponde ao configurado."""
    esperado = (app_id_esperado if app_id_esperado is not None else (os.getenv("ALEXA_SKILL_ID", "") or config.ALEXA_SKILL_ID)).strip()
    if not esperado:
        return True  # Nao configurado restritivamente

    recebido = extrair_application_id(dados)
    if not recebido:
        return False
    return hmac.compare_digest(recebido, esperado)


def obter_token_adaptador() -> str:
    """Obtem o token do adaptador Alexa para chamar /v1/assistente."""
    try:
        from . import adaptadores
        return adaptadores.obter_token_adaptador(
            "alexa",
            "Skill Alexa",
            env_var="ALEXA_ADAPTADOR_TOKEN",
        )
    except Exception as e:
        log.warning("Nao foi possivel obter token de adaptador automatico para Alexa: %s", e)
        return os.getenv("ALEXA_ADAPTADOR_TOKEN", "") or config.ALEXA_ADAPTADOR_TOKEN or config.TOKEN


def chamar_assistente(
    texto: str,
    token_adaptador: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Despacha uma mensagem de texto para o endpoint unificado /v1/assistente do Nextor."""
    from . import adaptadores
    return adaptadores.chamar_assistente(
        texto=texto,
        id_adaptador="alexa",
        nome_adaptador="Skill Alexa",
        env_var="ALEXA_ADAPTADOR_TOKEN",
        token_adaptador=token_adaptador,
        base_url=base_url,
        urlopen_fn=urllib.request.urlopen,
        tratar_erro_http=False,
    )


def construir_resposta_alexa(
    texto: str,
    should_end_session: bool = True,
    reprompt: Optional[str] = None,
) -> dict:
    """Constroi a resposta JSON no formato compativel com o Alexa Skills Kit."""
    resp: Dict[str, Any] = {
        "outputSpeech": {
            "type": "PlainText",
            "text": texto,
        },
        "shouldEndSession": should_end_session,
    }
    if reprompt:
        resp["reprompt"] = {
            "outputSpeech": {
                "type": "PlainText",
                "text": reprompt,
            }
        }
    return {
        "version": "1.0",
        "response": resp,
    }


def extrair_frase_slots(request_dict: dict) -> str:
    """Extrai o texto livre dos slots de uma intencao."""
    intent = request_dict.get("intent", {})
    slots = intent.get("slots", {})
    if not isinstance(slots, dict):
        return ""

    # Prioridade para nomes de slot conhecidos
    for chave in ("comando", "frase", "pergunta", "texto", "termo", "query", "mensagem"):
        if chave in slots and isinstance(slots[chave], dict):
            val = slots[chave].get("value")
            if val and str(val).strip():
                return str(val).strip()

    # Fallback: pega o primeiro slot com valor preenchido
    for s_info in slots.values():
        if isinstance(s_info, dict):
            val = s_info.get("value")
            if val and str(val).strip():
                return str(val).strip()

    return ""


def processar_requisicao_alexa(
    dados: dict,
    raw_body: Optional[bytes] = None,
    headers: Optional[dict] = None,
    verificar_assinatura: Optional[bool] = None,
    agora: Optional[datetime] = None,
    baixador_cert: Optional[Callable[[str], bytes]] = None,
    token_esperado: Optional[str] = None,
) -> Tuple[dict, int]:
    """Processa a requisicao da Alexa e retorna tupla (resposta_json, status_code)."""
    headers = headers or {}
    deve_verificar = (
        verificar_assinatura
        if verificar_assinatura is not None
        else (os.getenv("ALEXA_VERIFICAR_ASSINATURA", "1").strip().lower() not in ("0", "false", "nao"))
    )

    # 1. Validacao de token por adaptador (hmac.compare_digest) e revogacao
    from . import adaptadores

    disp_alexa = adaptadores.buscar_por_id("alexa")
    if disp_alexa and not disp_alexa.get("ativo", True):
        log.warning("Acesso negado: adaptador Alexa esta revogado")
        return {"ok": False, "erro": "adaptador_revogado"}, 403

    token_conf = (token_esperado or os.getenv("ALEXA_ADAPTADOR_TOKEN", "") or config.ALEXA_ADAPTADOR_TOKEN).strip()
    token_recebido = adaptadores.extrair_token_requisicao(headers=headers)
    if token_conf:
        valido_conf = bool(token_recebido and hmac.compare_digest(token_recebido, token_conf))
        if not valido_conf and token_recebido:
            adp_tk = adaptadores.buscar_por_token(token_recebido)
            if adp_tk and hmac.compare_digest(str(adp_tk.get("id", "")), "alexa") and adp_tk.get("ativo", True):
                valido_conf = True
        if not valido_conf:
            log.warning("Acesso negado: token do adaptador Alexa ausente ou divergente")
            return {"ok": False, "erro": "token_invalido"}, 401
    elif token_recebido:
        adp_tk = adaptadores.buscar_por_token(token_recebido)
        if not adp_tk:
            log.warning("Acesso negado: token do adaptador Alexa invalido")
            return {"ok": False, "erro": "token_invalido"}, 401
        if not adp_tk.get("ativo", True):
            return {"ok": False, "erro": "adaptador_revogado"}, 403

    # 2. Verificacao de assinatura Amazon (obrigatoria em producao)
    if deve_verificar:
        if raw_body is None:
            return {"ok": False, "erro": "corpo_bruto_ausente"}, 400

        cert_url = (
            headers.get("SignatureCertChainUrl")
            or headers.get("signaturecertchainurl")
            or headers.get("SIGNATURECERTCHAINURL")
            or ""
        )
        signature = (
            headers.get("Signature")
            or headers.get("signature")
            or headers.get("SIGNATURE")
            or ""
        )

        if not cert_url or not signature:
            log.warning("Cabecalhos de assinatura ausentes na requisicao da Alexa")
            return {"ok": False, "erro": "cabecalhos_assinatura_ausentes"}, 400

        ok_sig, erro_sig = validar_assinatura_requisicao(
            raw_body=raw_body,
            signature_b64=signature,
            cert_url=cert_url,
            agora=agora,
            baixador_cert=baixador_cert,
        )
        if not ok_sig:
            log.warning("Assinatura da Alexa invalida: %s", erro_sig)
            return {"ok": False, "erro": erro_sig}, 400

    # 3. Validacao de Application ID (Skill ID)
    if not validar_application_id(dados):
        log.warning("Application ID da Alexa divergente do configurado")
        return {"ok": False, "erro": "application_id_invalido"}, 400

    # 4. Validacao do Timestamp
    req_dict = dados.get("request", {}) if isinstance(dados, dict) else {}
    ts = req_dict.get("timestamp", "")
    if deve_verificar and ts:
        if not validar_timestamp(ts, agora=agora):
            log.warning("Timestamp da requisicao expirado: %s", ts)
            return {"ok": False, "erro": "timestamp_expirado"}, 400

    tipo = req_dict.get("type", "")

    # 5. Tratamento de tipos de requisicao
    if tipo == "LaunchRequest":
        texto = f"{config.NOME or 'Nextor'} pronto. Como posso ajudar?"
        reprompt = "O que voce gostaria de fazer?"
        return construir_resposta_alexa(texto, should_end_session=False, reprompt=reprompt), 200

    if tipo == "SessionEndedRequest":
        return construir_resposta_alexa("", should_end_session=True), 200

    if tipo == "IntentRequest":
        intent = req_dict.get("intent", {})
        intent_nome = intent.get("name", "")

        if intent_nome == "AMAZON.HelpIntent":
            ajuda = (
                "Voce pode me fazer perguntas, pedir a agenda do dia dizendo o que tenho hoje, "
                "ou pedir para anotar algo. Como posso ajudar?"
            )
            return construir_resposta_alexa(ajuda, should_end_session=False, reprompt="Como posso ajudar?"), 200

        if intent_nome in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
            return construir_resposta_alexa("Ate logo.", should_end_session=True), 200

        if intent_nome == "AMAZON.FallbackIntent":
            return (
                construir_resposta_alexa(
                    "Nao compreendi o comando. Pode repetir?",
                    should_end_session=False,
                    reprompt="Pode repetir seu pedido?",
                ),
                200,
            )

        # Intencao personalizada (ex: ComandoLivreIntent ou qualquer outra)
        frase = extrair_frase_slots(req_dict)
        if not frase:
            frase = intent_nome.replace("Intent", "")

        resposta_nextor = chamar_assistente(frase)
        return construir_resposta_alexa(resposta_nextor, should_end_session=True), 200

    # Tipo nao reconhecido
    return (
        construir_resposta_alexa("Tipo de requisicao nao reconhecido.", should_end_session=True),
        200,
    )
