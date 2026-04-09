// atestados.js — Módulo Atestados (OCR state machine + lista)

const AtestadosModule = (() => {
  // ── Máquina de estados OCR ────────────────────────────────────────────────────
  const OCR_STEP = {
    IDLE:      'idle',
    UPLOADING: 'uploading',
    REVIEWING: 'reviewing',
    SAVING:    'saving',
  };

  const _OCR_TRANSITIONS = {
    idle:      ['uploading'],
    uploading: ['reviewing', 'idle'],
    reviewing: ['saving',    'idle'],
    saving:    ['idle'],
  };

  function ocrTransition(next) {
    if (!_OCR_TRANSITIONS[state.ocrStep]?.includes(next)) {
      console.warn(`[Atestados] Transição OCR inválida: ${state.ocrStep} → ${next}`);
      return false;
    }
    // Não chama setState para evitar loop — ocrStep será atualizado pelo chamador
    return true;
  }

  // ── Estado ───────────────────────────────────────────────────────────────────
  const state = {
    // OCR flow
    ocrStep:          OCR_STEP.IDLE,
    ocrAtestado:      null,     // resposta completa do POST /upload
    ocrForm:          {},       // campos editáveis pelo operador
    ocrSelectedFile:  null,

    // Lista
    lista:            [],
    loadingLista:     false,
    filtros: {
      mes:    new Date().getMonth() + 1,
      ano:    new Date().getFullYear(),
      status: '',
    },

    // Vincular inline na tabela
    vinculandoId:        null,
    candidatosVincular:  [],
    loadingVincular:     false,
  };

  // ── setState + render ────────────────────────────────────────────────────────
  function setState(patch) {
    Object.assign(state, patch);
    render();
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  function render() {
    document.getElementById('panel-atestados').innerHTML = `
      <div class="section-card">
        <h2>Subir Atestado (OCR)</h2>
        ${buildOcrSection()}
      </div>
      <div class="section-card">
        <h2>Atestados do Período</h2>
        ${buildListSection()}
      </div>
    `;
  }

  function buildOcrSection() {
    switch (state.ocrStep) {
      case OCR_STEP.IDLE:      return buildOcrIdle();
      case OCR_STEP.UPLOADING: return buildOcrUploading();
      case OCR_STEP.REVIEWING: return buildOcrReviewing(false);
      case OCR_STEP.SAVING:    return buildOcrReviewing(true);
      default:                 return buildOcrIdle();
    }
  }

  function buildOcrIdle() {
    const fileName = state.ocrSelectedFile
      ? `<p class="dz-file">📄 ${state.ocrSelectedFile}</p>`
      : '';
    return `
      <div class="drop-zone">
        <input type="file" id="ocr-file-input" accept=".pdf">
        <div class="dz-icon">📋</div>
        <p class="dz-label">Arraste o PDF do atestado ou clique para selecionar</p>
        <p class="dz-hint">Suporta PDFs digitais e escaneados (OCR automático)</p>
        ${fileName}
      </div>
      <div style="margin-top:1rem">
        <button class="btn btn-primary" data-action="ocr-upload"
          ${!state.ocrSelectedFile ? 'disabled' : ''}>Processar OCR</button>
      </div>`;
  }

  function buildOcrUploading() {
    return `
      <div class="ocr-loading">
        <div class="spinner-large"></div>
        <p><strong>Processando OCR...</strong></p>
        <p>Isso pode levar alguns segundos. Não feche esta aba.</p>
      </div>`;
  }

  function buildOcrReviewing(saving) {
    const r = state.ocrAtestado;
    const f = state.ocrForm;
    const candidatos = r.candidatos_colaborador || [];
    const avisos     = r.avisos || [];

    const avisosHtml = avisos.length ? `
      <div class="alert-box alert-warn">
        <strong>Avisos do OCR — revise os campos abaixo:</strong>
        <ul style="margin:.4rem 0 0 1.25rem">${avisos.map(a => `<li>${a}</li>`).join('')}</ul>
      </div>` : '';

    const candidatosOptions = candidatos
      .map(c => `<option value="${c.id}" ${f.colaborador_id == c.id ? 'selected' : ''}>
        ${c.nome} — CPF ${c.cpf} (${Math.round((c.score || 0) * 100)}% similar)
      </option>`)
      .join('');

    const colaboradorField = candidatos.length
      ? `<select data-field="colaborador_id">
           <option value="">— selecione o colaborador —</option>
           ${candidatosOptions}
         </select>`
      : `<input type="text" placeholder="Nenhum candidato identificado — vincule pela lista abaixo"
           readonly style="background:#f9fafb;color:var(--kway-muted)">`;

    const btnConfirmar = saving
      ? `<button class="btn btn-primary" disabled><span class="spinner"></span> Confirmando...</button>`
      : `<button class="btn btn-primary" data-action="ocr-confirmar">Confirmar atestado</button>`;

    return `
      ${avisosHtml}
      <div class="form-grid" style="margin-bottom:1rem">
        <div class="form-group">
          <label>Data de início</label>
          <input type="date" data-field="data_inicio" value="${f.data_inicio || ''}" ${saving ? 'disabled' : ''}>
        </div>
        <div class="form-group">
          <label>Dias de afastamento</label>
          <input type="number" min="0" max="365" data-field="dias"
            value="${f.dias !== undefined && f.dias !== '' ? f.dias : ''}" placeholder="0" ${saving ? 'disabled' : ''}>
        </div>
        <div class="form-group">
          <label>Horas declaradas (HH:MM)</label>
          <input type="text" placeholder="ex: 04:00" data-field="horas_declaradas"
            value="${f.horas_declaradas || ''}" ${saving ? 'disabled' : ''}>
        </div>
        <div class="form-group">
          <label>CID</label>
          <input type="text" placeholder="ex: J11.0" data-field="cid"
            value="${f.cid || ''}" ${saving ? 'disabled' : ''}>
        </div>
      </div>
      <div class="form-group" style="margin-bottom:1rem">
        <label>Colaborador</label>
        ${colaboradorField}
      </div>
      <div style="display:flex;gap:.75rem;flex-wrap:wrap">
        ${btnConfirmar}
        <button class="btn btn-danger" data-action="ocr-rejeitar" ${saving ? 'disabled' : ''}>Rejeitar</button>
        <button class="btn btn-ghost"  data-action="ocr-cancelar" ${saving ? 'disabled' : ''}>Cancelar</button>
      </div>`;
  }

  function buildListSection() {
    const { mes, ano, status } = state.filtros;
    const nomeMeses = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];

    const mesOpts = nomeMeses
      .map((m, i) => `<option value="${i + 1}" ${mes == i + 1 ? 'selected' : ''}>${m}</option>`)
      .join('');

    const statusOpts = [
      ['', 'Todos'],
      ['pendente_validacao', 'Pendente'],
      ['sem_vinculo',        'Sem vínculo'],
      ['confirmado',         'Confirmado'],
      ['rejeitado',          'Rejeitado'],
    ].map(([v, l]) => `<option value="${v}" ${status === v ? 'selected' : ''}>${l}</option>`).join('');

    const filtros = `
      <div style="display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:1rem;align-items:flex-end">
        <div class="form-group" style="margin:0">
          <label>Mês</label>
          <select data-filter="mes">${mesOpts}</select>
        </div>
        <div class="form-group" style="margin:0">
          <label>Ano</label>
          <input type="number" data-filter="ano" value="${ano}" style="width:90px">
        </div>
        <div class="form-group" style="margin:0">
          <label>Status</label>
          <select data-filter="status">${statusOpts}</select>
        </div>
        <button class="btn btn-ghost btn-sm" data-action="filtrar-lista" style="align-self:flex-end">↻ Filtrar</button>
      </div>`;

    if (state.loadingLista) {
      return filtros + `<div class="loading-state"><span class="spinner spinner-dark"></span> Carregando atestados...</div>`;
    }
    if (!state.lista.length) {
      return filtros + `<div class="empty-state"><p>Nenhum atestado encontrado para este período.</p></div>`;
    }

    const rows = state.lista.map(a => {
      const nomeColaborador = a.nome_ocr || (a.colaborador_id ? `ID ${a.colaborador_id}` : '—');
      return `<tr>
        <td>${nomeColaborador}</td>
        <td>${fmtData(a.data_inicio)}</td>
        <td style="text-align:center">${a.dias || '—'}</td>
        <td style="text-align:center">${a.horas_declaradas_raw || '—'}</td>
        <td>${a.cid || '—'}</td>
        <td><span class="badge badge-${a.status}">${fmtStatus(a.status)}</span></td>
        <td style="font-size:.78rem;color:var(--kway-muted)">${a.origem}</td>
        <td>${buildAcoesAtestado(a)}</td>
      </tr>`;
    }).join('');

    return filtros + `
      <div style="overflow-x:auto">
        <table class="fgi-table">
          <thead>
            <tr>
              <th>Colaborador</th><th>Data</th><th>Dias</th><th>Horas</th>
              <th>CID</th><th>Status</th><th>Origem</th><th>Ações</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function buildAcoesAtestado(a) {
    if (a.status === 'sem_vinculo') {
      if (state.vinculandoId === a.id) {
        const opts = (state.candidatosVincular || [])
          .map(c => `<option value="${c.id}">${c.nome} (${c.cpf})</option>`)
          .join('');
        const btnOk = state.loadingVincular
          ? `<button class="btn btn-primary btn-sm" disabled><span class="spinner"></span></button>`
          : `<button class="btn btn-primary btn-sm" data-action="vincular-confirmar" data-id="${a.id}">OK</button>`;
        return `
          <div style="display:flex;gap:.4rem;align-items:center;flex-wrap:wrap">
            <select id="vincular-select-${a.id}" style="font-size:.8rem;padding:.3rem;border:1px solid var(--kway-border);border-radius:var(--radius)">
              <option value="">— colaborador —</option>${opts}
            </select>
            ${btnOk}
            <button class="btn btn-ghost btn-sm" data-action="vincular-cancelar">✕</button>
          </div>`;
      }
      return `<button class="btn btn-outline btn-sm" data-action="vincular-iniciar"
        data-id="${a.id}" data-nome="${(a.nome_ocr || '').replace(/"/g, '&quot;')}">Vincular</button>`;
    }

    if (a.status === 'pendente_validacao') {
      return `<button class="btn btn-danger btn-sm" data-action="rejeitar" data-id="${a.id}">Rejeitar</button>`;
    }

    return '';
  }

  // ── Ações OCR ────────────────────────────────────────────────────────────────
  async function handleUpload() {
    const input = document.getElementById('ocr-file-input');
    if (!input || !input.files[0]) return;
    if (!ocrTransition(OCR_STEP.UPLOADING)) return;

    const form = new FormData();
    form.append('file', input.files[0]);
    setState({ ocrStep: OCR_STEP.UPLOADING });

    try {
      const result = await API.atestados.upload(form);
      const a = result.atestado;
      const o = result.ocr || {};

      setState({
        ocrStep:     OCR_STEP.REVIEWING,
        ocrAtestado: result,
        ocrForm: {
          colaborador_id:    a.colaborador_id || null,
          data_inicio:       a.data_inicio ? String(a.data_inicio).substring(0, 10) : '',
          dias:              (a.dias > 0 ? a.dias : null) ?? o.dias ?? '',
          horas_declaradas:  o.horas || a.horas_declaradas_raw || '',
          cid:               o.cid   || a.cid || '',
        },
      });
    } catch (e) {
      setState({ ocrStep: OCR_STEP.IDLE, ocrSelectedFile: null });
      toast(e.isApiError ? e.message : 'Erro inesperado ao processar OCR.', 'error');
      if (!e.isApiError) console.error('[Atestados OCR upload]', e);
    }
  }

  async function confirmar() {
    if (!ocrTransition(OCR_STEP.SAVING)) return;
    const id = state.ocrAtestado.atestado.id;

    const dados = {
      usuario: 'operador',
    };
    if (state.ocrForm.colaborador_id)   dados.colaborador_id    = Number(state.ocrForm.colaborador_id);
    if (state.ocrForm.data_inicio)      dados.data_inicio        = state.ocrForm.data_inicio;
    if (state.ocrForm.dias !== '')      dados.dias               = Number(state.ocrForm.dias) || 0;
    if (state.ocrForm.horas_declaradas) dados.horas_declaradas   = state.ocrForm.horas_declaradas;
    if (state.ocrForm.cid)              dados.cid                = state.ocrForm.cid;

    setState({ ocrStep: OCR_STEP.SAVING });

    try {
      await API.atestados.confirmar(id, dados);
      setState({
        ocrStep: OCR_STEP.IDLE,
        ocrAtestado: null,
        ocrForm: {},
        ocrSelectedFile: null,
      });
      toast('Atestado confirmado com sucesso.', 'success');
      carregarLista();
    } catch (e) {
      setState({ ocrStep: OCR_STEP.REVIEWING });
      toast(e.isApiError ? e.message : 'Erro ao confirmar atestado.', 'error');
      if (!e.isApiError) console.error('[Atestados confirmar]', e);
    }
  }

  async function rejeitarOcr() {
    if (!state.ocrAtestado) return;
    const id = state.ocrAtestado.atestado.id;
    try {
      await API.atestados.rejeitar(id);
      setState({ ocrStep: OCR_STEP.IDLE, ocrAtestado: null, ocrForm: {}, ocrSelectedFile: null });
      toast('Atestado rejeitado.', 'warn');
      carregarLista();
    } catch (e) {
      toast(e.isApiError ? e.message : 'Erro ao rejeitar.', 'error');
    }
  }

  async function rejeitarDaLista(id) {
    try {
      await API.atestados.rejeitar(id);
      toast('Atestado rejeitado.', 'warn');
      carregarLista();
    } catch (e) {
      toast(e.isApiError ? e.message : 'Erro ao rejeitar.', 'error');
    }
  }

  // ── Ações de vínculo ─────────────────────────────────────────────────────────
  async function vincularIniciar(id, nomeOcr) {
    setState({ vinculandoId: id, candidatosVincular: [], loadingVincular: false });
    if (nomeOcr && nomeOcr.length >= 3) {
      try {
        const candidatos = await API.atestados.buscaNome(nomeOcr);
        setState({ candidatosVincular: candidatos });
      } catch (_) {
        // Ignora — operador pode selecionar manualmente se a busca falhar
      }
    }
  }

  async function vincularConfirmar(id) {
    const select = document.getElementById(`vincular-select-${id}`);
    const colaborador_id = select ? Number(select.value) : 0;
    if (!colaborador_id) { toast('Selecione um colaborador.', 'warn'); return; }

    setState({ loadingVincular: true });
    try {
      await API.atestados.vincular(id, colaborador_id);
      setState({ vinculandoId: null, loadingVincular: false });
      toast('Colaborador vinculado com sucesso.', 'success');
      carregarLista();
    } catch (e) {
      setState({ loadingVincular: false });
      toast(e.isApiError ? e.message : 'Erro ao vincular.', 'error');
    }
  }

  // ── Ação de lista ────────────────────────────────────────────────────────────
  async function carregarLista() {
    setState({ loadingLista: true, vinculandoId: null });
    try {
      const lista = await API.atestados.listar(state.filtros);
      setState({ loadingLista: false, lista });
    } catch (e) {
      setState({ loadingLista: false });
      toast(e.isApiError ? e.message : 'Erro ao carregar atestados.', 'error');
      if (!e.isApiError) console.error('[Atestados lista]', e);
    }
  }

  // ── Event delegation (bind UMA VEZ em init) ───────────────────────────────────
  function setupEvents() {
    const panel = document.getElementById('panel-atestados');

    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (!btn || (btn.tagName === 'BUTTON' && btn.disabled)) return;
      const id = btn.dataset.id ? Number(btn.dataset.id) : null;

      switch (btn.dataset.action) {
        case 'ocr-upload':        handleUpload(); break;
        case 'ocr-confirmar':     confirmar(); break;
        case 'ocr-rejeitar':      rejeitarOcr(); break;
        case 'ocr-cancelar':
          setState({ ocrStep: OCR_STEP.IDLE, ocrAtestado: null, ocrForm: {}, ocrSelectedFile: null });
          break;
        case 'filtrar-lista':     carregarLista(); break;
        case 'vincular-iniciar':  vincularIniciar(id, btn.dataset.nome || ''); break;
        case 'vincular-confirmar':vincularConfirmar(id); break;
        case 'vincular-cancelar': setState({ vinculandoId: null }); break;
        case 'rejeitar':          rejeitarDaLista(id); break;
      }
    });

    panel.addEventListener('change', e => {
      // Arquivo OCR
      if (e.target.id === 'ocr-file-input' && e.target.files[0]) {
        setState({ ocrSelectedFile: e.target.files[0].name });
        return;
      }

      // Campos do formulário OCR — atualiza sem re-render para preservar foco
      if (e.target.dataset.field) {
        state.ocrForm[e.target.dataset.field] = e.target.value;
        return;
      }

      // Filtros da lista
      if (e.target.dataset.filter) {
        state.filtros[e.target.dataset.filter] = e.target.value;
        return;
      }
    });
  }

  // ── Init ─────────────────────────────────────────────────────────────────────
  function init() {
    render();
    setupEvents();
    carregarLista();
  }

  return { init };
})();
