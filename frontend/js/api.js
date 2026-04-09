// api.js — Camada HTTP pura. Nenhuma lógica de UI aqui.

class ApiError extends Error {
  constructor(detail, status) {
    super(detail);
    this.name   = 'ApiError';
    this.status = status;
    this.isApiError = true;
  }
}

const API = (() => {
  async function req(method, path, { body, form, params } = {}) {
    let url = path;
    if (params) {
      const q = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '')
      );
      if (q.toString()) url += '?' + q;
    }

    const opts = { method };
    if (form) {
      opts.body = form; // multipart — browser define Content-Type
    } else if (body !== undefined) {
      opts.body = JSON.stringify(body);
      opts.headers = { 'Content-Type': 'application/json' };
    }

    let res;
    try {
      res = await fetch(url, opts);
    } catch (_) {
      throw new ApiError('Sem conexão com o servidor.', 0);
    }

    if (!res.ok) {
      let detail = `Erro ${res.status}`;
      try { const json = await res.json(); detail = json.detail || detail; } catch (_) {}
      throw new ApiError(detail, res.status);
    }

    return res;
  }

  return {
    colaboradores: {
      importar: (form)   => req('POST', '/employees/import', { form }).then(r => r.json()),
      listar:   (status) => req('GET',  '/employees', { params: { status } }).then(r => r.json()),
    },

    atestados: {
      upload:    (form)      => req('POST', '/atestados/upload', { form }).then(r => r.json()),
      listar:    (p)         => req('GET',  '/atestados', { params: p }).then(r => r.json()),
      vincular:  (id, cid)   => req('PATCH', `/atestados/${id}/vincular`, { body: { colaborador_id: cid } }).then(r => r.json()),
      confirmar: (id, dados) => req('PATCH', `/atestados/${id}/confirmar`, { body: dados }).then(r => r.json()),
      rejeitar:  (id)        => req('PATCH',  `/atestados/${id}/rejeitar`).then(r => r.json()),
      excluir:   (id)        => req('DELETE', `/atestados/${id}`),
      buscaNome: (nome)      => req('GET',    '/atestados/busca-nome', { params: { nome } }).then(r => r.json()),
    },

    relatorio: {
      preview:  (ano, mes) => req('GET',  `/reports/${ano}/${mes}/preview`).then(r => r.json()),
      gerar:    (ano, mes) => req('POST', `/reports/${ano}/${mes}/generate`).then(r => r.json()),
      download: (ano, mes) => req('GET',  `/reports/${ano}/${mes}/download`),
    },
  };
})();
