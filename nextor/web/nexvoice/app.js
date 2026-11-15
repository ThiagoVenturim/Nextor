(() => {
  let sessaoAtual = null;

  const elToken = document.getElementById("input-token");
  const elModo = document.getElementById("select-modo");
  const elFonte = document.getElementById("select-fonte");
  const elTitulo = document.getElementById("input-titulo");
  const elIdiomaMeu = document.getElementById("select-idioma-meu");
  const elIdiomaOutro = document.getElementById("select-idioma-outro");
  const elCheckConsentimento = document.getElementById("check-consentimento");
  const elParticipantes = document.getElementById("input-participantes");
  const elBtnIniciar = document.getElementById("btn-iniciar");
  const elBtnEncerrar = document.getElementById("btn-encerrar");
  const elStatus = document.getElementById("status-sessao");
  const elPainelLegendas = document.getElementById("painel-legendas");
  const elBadgeLatencia = document.getElementById("badge-latencia");
  const elInputFala = document.getElementById("input-fala");
  const elBtnOuvirOutro = document.getElementById("btn-ouvir-outro");
  const elBtnFalarMeu = document.getElementById("btn-falar-meu");
  const elInputDisciplina = document.getElementById("input-disciplina");
  const elBtnSalvarEstudos = document.getElementById("btn-salvar-estudos");
  const elBtnBaixarSrt = document.getElementById("btn-baixar-srt");
  const elResumoAta = document.getElementById("resumo-ata");

  function obterHeaders() {
    const tk = (elToken.value || sessionStorage.getItem("nextor_token") || "").trim();
    if (tk) {
      sessionStorage.setItem("nextor_token", tk);
    }
    return {
      "Content-Type": "application/json",
      "X-Nextor-Token": tk,
    };
  }

  function renderizarTrecho(trecho) {
    const placeholder = elPainelLegendas.querySelector(".placeholder-legenda");
    if (placeholder) {
      placeholder.remove();
    }
    const div = document.createElement("div");
    div.className = `item-legenda direcao-${trecho.direcao || "entrada"}`;

    const meta = document.createElement("div");
    meta.className = "legenda-meta";
    meta.textContent = `${trecho.legenda_formatada.split("]")[0]}] ${trecho.locutor} (${trecho.idioma_origem} -> ${trecho.idioma_destino}) | ${trecho.latencia_ms} ms`;

    const trad = document.createElement("div");
    trad.className = "legenda-traduzida";
    trad.textContent = trecho.texto_traduzido;

    const orig = document.createElement("div");
    orig.className = "legenda-original";
    orig.textContent = `Original: ${trecho.texto_original}`;

    div.appendChild(meta);
    div.appendChild(trad);
    div.appendChild(orig);
    elPainelLegendas.appendChild(div);
    elPainelLegendas.scrollTop = elPainelLegendas.scrollHeight;

    elBadgeLatencia.textContent = `${trecho.latencia_ms} ms | TTS: ${trecho.motor_tts}`;
  }

  async function iniciarSessao() {
    try {
      const resp = await fetch("/nexvoice/sessoes", {
        method: "POST",
        headers: obterHeaders(),
        body: JSON.stringify({
          titulo: elTitulo.value || "Sessao NexVoice",
          modo: elModo.value,
          fonte: elFonte.value,
          idioma_meu: elIdiomaMeu.value,
          idioma_outro: elIdiomaOutro.value,
          consentimento_confirmado: elCheckConsentimento.checked,
          consentimento_participantes: elParticipantes.value,
          disciplina: elInputDisciplina.value,
        }),
      });
      const dados = await resp.json();
      if (!resp.ok || !dados.ok) {
        elStatus.textContent = dados.mensagem || dados.erro || "Erro ao iniciar sessao.";
        return;
      }
      sessaoAtual = dados.sessao;
      elPainelLegendas.innerHTML = "";
      elBtnEncerrar.disabled = false;
      elStatus.textContent = `Sessao ativa (${sessaoAtual.modo}): ${sessaoAtual.titulo}`;
    } catch (err) {
      elStatus.textContent = `Falha de conexao: ${err.message}`;
    }
  }

  async function enviarTrecho(direcao) {
    if (!sessaoAtual) {
      elStatus.textContent = "Inicie uma sessao antes de traduzir.";
      return;
    }
    const texto = (elInputFala.value || "").trim();
    if (!texto) {
      return;
    }
    try {
      const resp = await fetch("/nexvoice/trechos", {
        method: "POST",
        headers: obterHeaders(),
        body: JSON.stringify({
          sessao_id: sessaoAtual.id,
          texto_fala: texto,
          direcao: direcao,
        }),
      });
      const dados = await resp.json();
      if (!resp.ok || !dados.ok) {
        elStatus.textContent = dados.mensagem || dados.erro || "Erro ao processar trecho.";
        return;
      }
      elInputFala.value = "";
      renderizarTrecho(dados.trecho);
    } catch (err) {
      elStatus.textContent = `Erro ao traduzir trecho: ${err.message}`;
    }
  }

  async function encerrarSessao() {
    if (!sessaoAtual) return;
    try {
      const resp = await fetch("/nexvoice/encerrar", {
        method: "POST",
        headers: obterHeaders(),
        body: JSON.stringify({
          sessao_id: sessaoAtual.id,
          gerar_ata: true,
          salvar_estudos: Boolean(elInputDisciplina.value.trim()),
          disciplina: elInputDisciplina.value.trim(),
        }),
      });
      const dados = await resp.json();
      if (resp.ok && dados.ok) {
        elBtnEncerrar.disabled = true;
        elStatus.textContent = "Sessao encerrada.";
        if (dados.ata_reuniao) {
          elResumoAta.textContent = dados.ata_reuniao.resumo || "";
        }
      }
    } catch (err) {
      elStatus.textContent = `Erro ao encerrar: ${err.message}`;
    }
  }

  async function salvarEstudos() {
    if (!sessaoAtual) return;
    const disc = elInputDisciplina.value.trim();
    if (!disc) {
      elStatus.textContent = "Informe o nome da disciplina.";
      return;
    }
    const resp = await fetch("/nexvoice/salvar-estudos", {
      method: "POST",
      headers: obterHeaders(),
      body: JSON.stringify({ sessao_id: sessaoAtual.id, disciplina: disc }),
    });
    const dados = await resp.json();
    elStatus.textContent = dados.aviso || dados.erro || "Salvo.";
  }

  async function exportarSrt() {
    if (!sessaoAtual) return;
    const resp = await fetch(`/nexvoice/sessoes/${encodeURIComponent(sessaoAtual.id)}/legendas.srt`, {
      headers: obterHeaders(),
    });
    if (resp.ok) {
      const srt = await resp.text();
      elResumoAta.textContent = srt || "Nenhum trecho disponivel.";
    }
  }

  if (elBtnIniciar) elBtnIniciar.addEventListener("click", iniciarSessao);
  if (elBtnEncerrar) elBtnEncerrar.addEventListener("click", encerrarSessao);
  if (elBtnOuvirOutro) elBtnOuvirOutro.addEventListener("click", () => enviarTrecho("entrada"));
  if (elBtnFalarMeu) elBtnFalarMeu.addEventListener("click", () => enviarTrecho("saida"));
  if (elBtnSalvarEstudos) elBtnSalvarEstudos.addEventListener("click", salvarEstudos);
  if (elBtnBaixarSrt) elBtnBaixarSrt.addEventListener("click", exportarSrt);

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/nexvoice/sw.js").catch(() => {});
  }
})();
