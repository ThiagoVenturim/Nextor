(function () {
  const elUrl = document.getElementById('ext-url-servidor');
  const elToken = document.getElementById('ext-token');
  const elMotor = document.getElementById('ext-motor');
  const elDisciplina = document.getElementById('ext-disciplina');
  const elStatus = document.getElementById('ext-status');

  function enviarAcaoParaAbaAtiva(acao) {
    const cfg = {
      servidor: (elUrl && elUrl.value.trim()) || 'http://localhost:5005',
      token: (elToken && elToken.value.trim()) || '',
      motor: (elMotor && elMotor.value) || 'local',
      disciplina: (elDisciplina && elDisciplina.value.trim()) || 'Geral',
      acao: acao
    };
    if (typeof chrome !== 'undefined' && chrome.tabs) {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (!tabs || !tabs[0]) return;
        chrome.tabs.sendMessage(tabs[0].id, cfg, (resp) => {
          if (elStatus && resp && resp.mensagem) {
            elStatus.textContent = resp.mensagem;
          }
        });
      });
    }
  }

  document.getElementById('ext-btn-traduzir')?.addEventListener('click', () => enviarAcaoParaAbaAtiva('traduzir'));
  document.getElementById('ext-btn-marcar')?.addEventListener('click', () => enviarAcaoParaAbaAtiva('marcar'));
  document.getElementById('ext-btn-salvar')?.addEventListener('click', () => enviarAcaoParaAbaAtiva('salvar_estudos'));
  document.getElementById('ext-btn-painel')?.addEventListener('click', () => enviarAcaoParaAbaAtiva('abrir_ia'));
})();
