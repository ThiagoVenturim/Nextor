"""Modulo NexRead: tradutor de artigo/pagina ao vivo com marcacao, gravacao e conversa com IA (Issue #55)."""
from .armazenamento import ArmazenamentoNexRead
from .estudo import (
    conversar_sobre_artigo,
    gravar_nota_leitura,
    marcar_trecho,
    salvar_na_biblioteca_estudos,
)
from .extrator import (
    extrair_blocos_html,
    extrair_blocos_pdf,
    extrair_blocos_texto,
    extrair_pagina_aberta,
    validar_pagina_aberta_pelo_usuario,
)
from .modelos import (
    CORES_MARCACAO,
    MODOS_LAYOUT,
    TAGS_BLOCO_PERMITIDAS,
    ArtigoLido,
    BlocoPagina,
    GravacaoLeitura,
    Marcacao,
    MensagemChatArtigo,
)
from .tradutor import (
    MOTORES_SUPORTADOS,
    reconstruir_html_layout,
    traduzir_pagina_ao_vivo,
    traduzir_texto_bloco,
)

__all__ = [
    "ArmazenamentoNexRead",
    "ArtigoLido",
    "BlocoPagina",
    "CORES_MARCACAO",
    "GravacaoLeitura",
    "MODOS_LAYOUT",
    "MOTORES_SUPORTADOS",
    "Marcacao",
    "MensagemChatArtigo",
    "TAGS_BLOCO_PERMITIDAS",
    "conversar_sobre_artigo",
    "extrair_blocos_html",
    "extrair_blocos_pdf",
    "extrair_blocos_texto",
    "extrair_pagina_aberta",
    "gravar_nota_leitura",
    "marcar_trecho",
    "reconstruir_html_layout",
    "salvar_na_biblioteca_estudos",
    "traduzir_pagina_ao_vivo",
    "traduzir_texto_bloco",
    "validar_pagina_aberta_pelo_usuario",
]
