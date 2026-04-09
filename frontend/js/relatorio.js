// relatorio.js — Módulo Relatório (preview + gerar + baixar Excel)

const RelatorioModule = (() => {
  // ── Estado ───────────────────────────────────────────────────────────────────
  const state = {
    ano:     new Date().getFullYear(),
    mes:     new Date().getMonth() + 1,
    preview: null,
    loading: false,
    gerado:  false,
    erro:    null,
  };

  // ── setState + render ────────────────────────────────────────────────────────
  function setState(patch) {
    Object.assign(state, patch);
    render();
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  function render() {
    document.getElementById('panel-relatorio').innerHTML = `
      <div class="section-card">
        <h2>Selecionar Período</h2>
        ${buildSeletorHtml()}
      </div>
      ${state.preview ? buildPreviewHtml() : ''}
    `;
  }

  function buildSeletorHtml() {
    const nomeMeses = [
      'Janeiro','Fevereiro','Março','Abril','Maio','Junho',
      'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro',
    ];
    const mesOpts = nomeMeses
      .map((m, i) => `<option value="${i + 1}" ${state.mes == i + 1 ? 'selected' : ''}>${m}</option>`)
      .join('');

    const btnLabel = state.loading
      ? `<span class="spinner"></span> Carregando...`
      : 'Carregar Prévia';

    return `
      <div style="display:flex;gap:1rem;flex-wrap:wrap;align-items:flex-end">
        <div class="form-group" style="margin:0">
          <label>Mês</label>
          <select data-rel="mes">${mesOpts}</select>
        </div>
        <div class="form-group" style="margin:0">
          <label>Ano</label>
          <input type="number" data-rel="ano" value="${state.ano}" style="width:90px" min="2020" max="2099">
        </div>
        <button class="btn btn-primary" data-action="carregar-preview"
          ${state.loading ? 'disabled' : ''}>${btnLabel}</button>
      </div>`;
  }

  function buildPreviewHtml() {
    const p = state.preview;
    const t = p.totais || {};

    const alertasHtml = (p.alertas || []).length ? `
      <div class="section-card">
        <h2>⚠ Alertas Internos (não aparecem no Excel)</h2>
        <div class="alert-box alert-warn" style="margin:0">
          <ul style="margin:0;padding-left:1.25rem">
            ${p.alertas.map(a => `<li>${a.mensagem}</li>`).join('')}
          </ul>
        </div>
      </div>` : '';

    const pendenciasHtml = (p.pendencias || []).length ? `
      <div class="alert-box alert-erro" style="margin-bottom:1rem">
        <strong>Pendências que bloqueiam a geração do Excel:</strong>
        <ul style="margin:.4rem 0 0 1.25rem">
          ${p.pendencias.map(x => `<li>${x}</li>`).join('')}
        </ul>
      </div>` : '';

    const rows = (p.linhas || []).map(l => `
      <tr>
        <td>${l.nome}</td>
        <td style="font-size:.8rem;color:var(--kway-muted)">${l.funcao}</td>
        <td style="text-align:center">${l.dias_atestado}</td>
        <td style="text-align:center">${l.horas_declaradas_raw || '—'}</td>
        <td style="text-align:right">${fmtBRL(l.total_fgi)}</td>
        <td style="text-align:right">${fmtBRL(l.com_encargos)}</td>
        <td style="text-align:right;font-weight:600;color:var(--kway-red)">${fmtBRL(l.total_final)}</td>
      </tr>`).join('');

    const btnGerar = state.loading
      ? `<button class="btn btn-primary" disabled><span class="spinner"></span> Gerando...</button>`
      : `<button class="btn btn-primary" data-action="gerar-excel" ${!p.pode_gerar ? 'disabled' : ''}>
           Gerar Excel
         </button>`;

    const btnBaixar = `
      <button class="btn btn-outline" data-action="baixar-excel" ${!state.gerado ? 'disabled' : ''}>
        Baixar Excel (.xlsx)
      </button>`;

    const statusBadge = `<span class="badge badge-${p.status_periodo}" style="margin-left:.5rem;font-size:.75rem">${p.status_periodo}</span>`;

    return `
      ${alertasHtml}
      <div class="section-card">
        <h2>Prévia — ${p.mes}/${p.ano} ${statusBadge}</h2>

        <div class="totais-grid">
          <div class="total-card">
            <div class="label">Total FGI</div>
            <div class="value">${fmtBRL(t.total_fgi)}</div>
          </div>
          <div class="total-card">
            <div class="label">Com Encargos</div>
            <div class="value">${fmtBRL(t.total_com_encargos)}</div>
          </div>
          <div class="total-card destaque">
            <div class="label">Total Final</div>
            <div class="value">${fmtBRL(t.total_final)}</div>
          </div>
        </div>

        ${pendenciasHtml}

        <div style="overflow-x:auto;margin-bottom:1.5rem">
          <table class="fgi-table">
            <thead>
              <tr>
                <th>Colaborador</th>
                <th>Função</th>
                <th style="text-align:center">Dias</th>
                <th style="text-align:center">Horas</th>
                <th style="text-align:right">FGI</th>
                <th style="text-align:right">C/ Encargos</th>
                <th style="text-align:right">Total Final</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
            <tfoot>
              <tr>
                <td colspan="4">
                  <strong>${t.num_colaboradores || 0} colaborador(es)</strong>
                </td>
                <td style="text-align:right">${fmtBRL(t.total_fgi)}</td>
                <td style="text-align:right">${fmtBRL(t.total_com_encargos)}</td>
                <td style="text-align:right;color:var(--kway-red)">${fmtBRL(t.total_final)}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <div style="display:flex;gap:.75rem;flex-wrap:wrap">
          ${btnGerar}
          ${btnBaixar}
        </div>
      </div>`;
  }

  // ── Ações ────────────────────────────────────────────────────────────────────
  async function carregarPreview() {
    setState({ loading: true, preview: null, erro: null, gerado: false });
    try {
      const preview = await API.relatorio.preview(state.ano, state.mes);
      setState({ loading: false, preview });
    } catch (e) {
      setState({ loading: false, erro: e.message });
      toast(e.isApiError ? e.message : 'Erro ao carregar prévia.', 'error');
      if (!e.isApiError) console.error('[Relatorio preview]', e);
    }
  }

  async function gerarExcel() {
    setState({ loading: true });
    try {
      await API.relatorio.gerar(state.ano, state.mes);
      // Atualiza preview para refletir novo status do período
      const preview = await API.relatorio.preview(state.ano, state.mes);
      setState({ loading: false, gerado: true, preview });
      toast('Excel gerado com sucesso. Clique em "Baixar Excel".', 'success');
    } catch (e) {
      setState({ loading: false });
      toast(e.isApiError ? e.message : 'Erro ao gerar Excel.', 'error');
      if (!e.isApiError) console.error('[Relatorio gerar]', e);
    }
  }

  async function baixarExcel() {
    try {
      const res = await API.relatorio.download(state.ano, state.mes);
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      const mes  = String(state.mes).padStart(2, '0');
      a.href     = url;
      a.download = `FGI_CEINT_${state.ano}${mes}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(e.isApiError ? e.message : 'Erro ao baixar Excel.', 'error');
      if (!e.isApiError) console.error('[Relatorio download]', e);
    }
  }

  // ── Event delegation (bind UMA VEZ em init) ───────────────────────────────────
  function setupEvents() {
    const panel = document.getElementById('panel-relatorio');

    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (!btn || (btn.tagName === 'BUTTON' && btn.disabled)) return;
      switch (btn.dataset.action) {
        case 'carregar-preview': carregarPreview(); break;
        case 'gerar-excel':      gerarExcel();      break;
        case 'baixar-excel':     baixarExcel();     break;
      }
    });

    panel.addEventListener('change', e => {
      if (e.target.dataset.rel) {
        // Atualiza state sem render — período só muda ao clicar "Carregar Prévia"
        state[e.target.dataset.rel] = Number(e.target.value);
      }
    });
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  function init() {
    render();
    setupEvents();
  }

  return { init };
})();
