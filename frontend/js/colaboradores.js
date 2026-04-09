// colaboradores.js — Módulo Colaboradores (import de planilha + listagem)

const ColaboradoresModule = (() => {
  // ── Estado ───────────────────────────────────────────────────────────────────
  const state = {
    lista:         [],
    loadingLista:  false,
    loadingImport: false,
    importResult:  null,
    selectedFile:  null,
    erro:          null,
  };

  // ── setState + render ────────────────────────────────────────────────────────
  function setState(patch) {
    Object.assign(state, patch);
    render();
  }

  // ── Render (puro — somente DOM output, sem side effects) ─────────────────────
  function render() {
    document.getElementById('panel-colaboradores').innerHTML = `
      <div class="section-card">
        <h2>Importar Planilha de Colaboradores</h2>
        ${buildImportSection()}
      </div>
      <div class="section-card">
        <h2>Colaboradores Cadastrados</h2>
        ${buildListSection()}
      </div>
    `;
  }

  function buildImportSection() {
    const fileName = state.selectedFile
      ? `<p class="dz-file">📄 ${state.selectedFile}</p>`
      : '';

    const btnLabel = state.loadingImport
      ? `<span class="spinner"></span> Importando...`
      : 'Importar Planilha';

    let resultHtml = '';
    if (state.importResult) {
      const r = state.importResult;
      const alertas = (r.alertas_salario || [])
        .map(a => `<li>${a.nome || ''}: ${fmtBRL(a.salario_anterior)} → ${fmtBRL(a.salario_novo)}</li>`)
        .join('');
      const erros = (r.erros || [])
        .map(e => `<li>${e}</li>`)
        .join('');

      resultHtml = `
        <div class="alert-box alert-info" style="margin-top:1rem">
          <strong>Resultado da importação:</strong>
          ${r.inseridos} inserido(s) · ${r.atualizados} atualizado(s) ·
          ${r.ignorados_outros_contratos || 0} ignorado(s) (outro contrato)
          ${erros   ? `<ul style="margin:.5rem 0 0 1.25rem">${erros}</ul>` : ''}
          ${alertas ? `<p style="margin:.5rem 0 0"><strong>Alertas de salário:</strong></p><ul style="margin:.25rem 0 0 1.25rem">${alertas}</ul>` : ''}
        </div>`;
    }

    return `
      <div class="drop-zone" id="colab-dropzone">
        <input type="file" id="colab-file-input" accept=".xls,.xlsx">
        <div class="dz-icon">📂</div>
        <p class="dz-label">Arraste a planilha aqui ou clique para selecionar</p>
        <p class="dz-hint">Formatos aceitos: .xls, .xlsx — Contratos Correios CEINT / CLI</p>
        ${fileName}
      </div>
      <div style="margin-top:1rem">
        <button class="btn btn-primary" data-action="importar"
          ${!state.selectedFile || state.loadingImport ? 'disabled' : ''}>${btnLabel}</button>
      </div>
      ${resultHtml}`;
  }

  function buildListSection() {
    if (state.loadingLista) {
      return `<div class="loading-state"><span class="spinner spinner-dark"></span> Carregando colaboradores...</div>`;
    }
    if (!state.lista.length) {
      return `
        <div class="empty-state">
          <p>Nenhum colaborador cadastrado.</p>
          <p style="font-size:.8rem">Importe a planilha para começar.</p>
        </div>`;
    }

    const rows = state.lista.map(e => `
      <tr>
        <td>${e.nome}</td>
        <td style="font-family:monospace;font-size:.8rem">${e.cpf}</td>
        <td>${e.funcao}</td>
        <td style="text-align:right">${fmtBRL(e.salario)}</td>
        <td>${e.contrato || '—'}</td>
        <td>${fmtData(e.data_admissao)}</td>
        <td><span class="badge badge-${e.status}">${fmtStatus(e.status)}</span></td>
      </tr>`).join('');

    return `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.75rem">
        <span style="font-size:.85rem;color:var(--kway-muted)">${state.lista.length} colaborador(es)</span>
        <button class="btn btn-ghost btn-sm" data-action="atualizar-lista">↻ Atualizar</button>
      </div>
      <div style="overflow-x:auto">
        <table class="fgi-table">
          <thead>
            <tr>
              <th>Nome</th>
              <th>CPF</th>
              <th>Função</th>
              <th style="text-align:right">Salário</th>
              <th>Contrato</th>
              <th>Admissão</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // ── Ações ────────────────────────────────────────────────────────────────────
  async function importar() {
    const input = document.getElementById('colab-file-input');
    if (!input || !input.files[0]) return;

    const form = new FormData();
    form.append('file', input.files[0]);
    setState({ loadingImport: true, importResult: null, erro: null });

    try {
      const result = await API.colaboradores.importar(form);
      setState({ loadingImport: false, importResult: result, selectedFile: null });
      toast(`Importado: ${result.inseridos} novos, ${result.atualizados} atualizados`);
      carregarLista();
    } catch (e) {
      setState({ loadingImport: false, erro: e.message });
      toast(e.isApiError ? e.message : 'Erro inesperado ao importar.', 'error');
      if (!e.isApiError) console.error('[Colaboradores importar]', e);
    }
  }

  async function carregarLista() {
    setState({ loadingLista: true, erro: null });
    try {
      const lista = await API.colaboradores.listar('ativo');
      setState({ loadingLista: false, lista });
    } catch (e) {
      setState({ loadingLista: false, erro: e.message });
      toast(e.isApiError ? e.message : 'Erro ao carregar colaboradores.', 'error');
      if (!e.isApiError) console.error('[Colaboradores lista]', e);
    }
  }

  // ── Event delegation (bind UMA VEZ em init) ───────────────────────────────────
  function setupEvents() {
    const panel = document.getElementById('panel-colaboradores');

    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (!btn || (btn.tagName === 'BUTTON' && btn.disabled)) return;
      if (btn.dataset.action === 'importar')       importar();
      if (btn.dataset.action === 'atualizar-lista') carregarLista();
    });

    panel.addEventListener('change', e => {
      if (e.target.id === 'colab-file-input' && e.target.files[0]) {
        setState({ selectedFile: e.target.files[0].name });
      }
    });
  }

  // ── Init (chamado uma vez quando a aba é ativada pela primeira vez) ───────────
  function init() {
    render();
    setupEvents();
    carregarLista();
  }

  return { init };
})();
