// app.js — Utilitários globais e inicialização de tabs (lazy).

// ── Formatadores ──────────────────────────────────────────────────────────────
function fmtBRL(v) {
  if (v === null || v === undefined) return '—';
  return Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function fmtData(iso) {
  if (!iso) return '—';
  const s = String(iso).substring(0, 10);
  const [y, m, d] = s.split('-');
  return `${d}/${m}/${y}`;
}

function fmtStatus(s) {
  const map = {
    pendente_validacao: 'Pendente',
    sem_vinculo:        'Sem vínculo',
    confirmado:         'Confirmado',
    rejeitado:          'Rejeitado',
    ativo:              'Ativo',
    inativo:            'Inativo',
  };
  return map[s] || s;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function toast(msg, tipo = 'success') {
  const el = document.createElement('div');
  el.className = `toast toast-${tipo}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 300);
  }, 3700);
}

// ── Tab manager com lazy init ─────────────────────────────────────────────────
const _tabInitialized = new Set();
const _tabModules = {};

function activateTab(tabName) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

  const panel = document.getElementById('panel-' + tabName);
  const btn   = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
  if (panel) panel.classList.remove('hidden');
  if (btn)   btn.classList.add('active');

  if (!_tabInitialized.has(tabName) && _tabModules[tabName]) {
    _tabInitialized.add(tabName);
    _tabModules[tabName].init();
  }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _tabModules.colaboradores = ColaboradoresModule;
  _tabModules.atestados     = AtestadosModule;
  _tabModules.relatorio     = RelatorioModule;

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => activateTab(btn.dataset.tab));
  });

  // Ativa primeira aba imediatamente
  activateTab('colaboradores');
});
