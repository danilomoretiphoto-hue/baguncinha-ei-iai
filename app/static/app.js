/* ==========================================================
   Baguncinha Ei Iai · Painel Admin (JavaScript nativo ES6+)
   Visual Redesign em Alta Resolução (Light & Dark Mode)
   Preserva 100% das regras de negócio, integrações e rotas.
   ========================================================== */
"use strict";

const LS_KEY = "lb_admin_key";
const LS_API = "lb_api_base";
const LS_THEME = "lb_theme";
const LS_COLLAPSED = "lb_sidebar_collapsed";
const LS_SOUND = "lb_sound_alert";
const SISTEMA_IDS = new Set(["cliente-balcao", "despesas-internas"]);

const state = {
  adminKey: localStorage.getItem(LS_KEY) || "",
  apiBase: (localStorage.getItem(LS_API) || window.API_BASE_URL || "").replace(/\/+$/, ""),
  clientes: [],
  lancamentos: [],
  pendentes: [],
  arquivo: null,
  previewUrl: null,
  editando: null,
  somAtivo: localStorage.getItem(LS_SOUND) !== "0", // Padrão: ativado
};

/* ---------------- Utilitários ---------------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const money = (v) => brl.format(Number(v || 0));

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtData(iso, comHora = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  const opts = { day: "2-digit", month: "2-digit", year: "2-digit" };
  if (comHora) Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleString("pt-BR", opts);
}

function hojeISO() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

function dataAtualPorExtenso() {
  const d = new Date();
  const dias = ["Domingo", "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado"];
  const meses = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  return `${dias[d.getDay()]} • ${d.getDate()} de ${meses[d.getMonth()]} de ${d.getFullYear()}`;
}

function toast(msg, tipo = "ok", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${tipo}`;
  const icon = tipo === "err" ? "fa-circle-xmark" : (tipo === "warn" ? "fa-triangle-exclamation" : "fa-circle-check");
  el.innerHTML = `<i class="fa-solid ${icon} mr-1"></i> ${esc(msg)}`;
  const container = $("#toasts");
  if (container) container.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function setLoading(btn, on) {
  if (!btn) return;
  btn.classList.toggle("loading", on);
  btn.disabled = on;
}

const BADGE_TIPO = { PAGO: "b-pago", FIADO_A_RECEBER: "b-fiado", A_PAGAR: "b-pagar" };
const BADGE_STATUS = { APROVADO: "b-aprovado", PENDENTE_REVISAO: "b-pendente", REJEITADO: "b-rejeitado" };
const BADGE_CONF = { ALTO: "b-alto", MEDIO: "b-medio", BAIXO: "b-baixo" };
const ORIGEM_ICON = { TEXTO: "⌨️ Texto", IMAGEM_COMANDA: "📸 Imagem", AUDIO_WHATSAPP: "🎙️ Áudio" };
const badge = (txt, cls) => `<span class="badge ${cls || "b-neutro"}">${esc(txt)}</span>`;

function resumoItens(itens = []) {
  if (!itens || !itens.length) return "—";
  return itens.map((i) => `${Number(i.quantidade)}x ${i.descricao}`).join(", ");
}

/* ---------------- Web Audio API (Alerta Sonoro Discreto) ---------------- */
let audioCtx = null;

function obterAudioContext() {
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }
  return audioCtx;
}

// Desbloqueia contexto de áudio na primeira interação do usuário com a página
document.addEventListener("click", () => obterAudioContext(), { once: true });
document.addEventListener("keydown", () => obterAudioContext(), { once: true });

function tocarSomNotificacao() {
  if (!state.somAtivo) return;
  try {
    const ctx = obterAudioContext();
    if (!ctx) return;

    const agora = ctx.currentTime;

    // Tom 1 (D5: ~587.33 Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, agora);
    gain1.gain.setValueAtTime(0, agora);
    gain1.gain.linearRampToValueAtTime(0.18, agora + 0.03);
    gain1.gain.exponentialRampToValueAtTime(0.001, agora + 0.28);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(agora);
    osc1.stop(agora + 0.3);

    // Tom 2 (A5: 880 Hz) - harmônico agradável de campainha
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880, agora + 0.12);
    gain2.gain.setValueAtTime(0, agora + 0.12);
    gain2.gain.linearRampToValueAtTime(0.22, agora + 0.15);
    gain2.gain.exponentialRampToValueAtTime(0.001, agora + 0.55);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(agora + 0.12);
    osc2.stop(agora + 0.6);
  } catch (err) {
    // Falha silenciosa caso o navegador restrinja
  }
}

window.toggleSoundAlert = function () {
  state.somAtivo = !state.somAtivo;
  localStorage.setItem(LS_SOUND, state.somAtivo ? "1" : "0");
  atualizarIconeSom();
  if (state.somAtivo) {
    tocarSomNotificacao();
    toast("Som de notificações ativado 🔔");
  } else {
    toast("Som de notificações silenciado 🔕");
  }
};

function atualizarIconeSom() {
  const btn = $("#btn-sound-toggle");
  if (!btn) return;
  if (state.somAtivo) {
    btn.innerHTML = `<i class="fa-solid fa-bell"></i>`;
    btn.title = "Som de notificações: Ativado";
    btn.classList.remove("is-muted");
  } else {
    btn.innerHTML = `<i class="fa-solid fa-bell-slash"></i>`;
    btn.title = "Som de notificações: Silenciado";
    btn.classList.add("is-muted");
  }
}

function dispararAlertaConferencia(item) {
  // Alerta sonoro
  tocarSomNotificacao();

  // Alerta visual no card de conferência
  const cardSec = $("#sec-conferencia");
  if (cardSec) {
    cardSec.classList.remove("has-new-alert");
    void cardSec.offsetWidth; // Força reflow para reiniciar animação
    cardSec.classList.add("has-new-alert");
    setTimeout(() => cardSec.classList.remove("has-new-alert"), 5500);
  }

  // Notificação toast destacada
  const valorTxt = item && item.valor_total ? money(item.valor_total) : "";
  const clienteTxt = item && item.cliente_nome ? ` de ${item.cliente_nome}` : "";
  toast(`⚠️ Novo lançamento para conferência humana${clienteTxt} (${valorTxt})!`, "warn", 6000);
}

/* ---------------- API ---------------- */
async function api(path, { method = "GET", body, form, raw = false } = {}) {
  if (!state.adminKey) throw new Error("Informe a chave mestra (X-Admin-Key) no topo do painel.");
  const headers = { "X-Admin-Key": state.adminKey };
  let payload;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`${state.apiBase}${path}`, { method, headers, body: payload });
  } catch (err) {
    setConn(false);
    throw new Error("Não foi possível conectar à API. Verifique se o backend está no ar.");
  }
  if (!res.ok) {
    let msg = `Erro ${res.status}`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail)) msg = j.detail.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join(" | ");
      else msg = JSON.stringify(j);
    } catch (_) { /* resposta sem JSON */ }
    if (res.status === 401) setConn(false);
    throw new Error(msg);
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

function setConn(ok) {
  const el = $("#conn-status");
  if (!el) return;
  el.className = `pill ${ok ? "pill-on" : "pill-off"}`;
  el.innerHTML = ok
    ? `<i class="fa-solid fa-circle text-[8px] text-teal"></i> Conectado`
    : `<i class="fa-solid fa-circle text-[8px] text-coral"></i> Desconectado`;
}

/* ---------------- Carregamento Geral ---------------- */
async function carregarTudo() {
  if (!state.adminKey) return;
  const [dash, clientes, pend, lancs] = await Promise.allSettled([
    api("/v1/admin/dashboard"),
    api("/v1/admin/clientes"),
    api("/v1/admin/pendencias"),
    api("/v1/admin/lancamentos?limit=300"),
  ]);

  if (dash.status === "fulfilled") {
    setConn(true);
    renderKPIs(dash.value);
  } else {
    toast(dash.reason.message, "err");
    return;
  }

  if (clientes.status === "fulfilled") {
    state.clientes = clientes.value;
    renderClientes();
    popularSelects();
  }
  if (pend.status === "fulfilled") {
    state.pendentes = pend.value;
    renderPendencias();
  }
  if (lancs.status === "fulfilled") {
    state.lancamentos = lancs.value;
    renderLancamentos();
  }

  // Atualiza indicadores de rodapé e badges do header
  atualizarCardsResumo(dash.value);

  [clientes, pend, lancs].filter((r) => r.status === "rejected").forEach((r) => toast(r.reason.message, "err"));
}

/* ---------------- Polling Silencioso em Tempo Real (Sem F5) ---------------- */
let pollingEmExecucao = false;

async function pollingSilencioso() {
  if (pollingEmExecucao || !state.adminKey || document.visibilityState !== "visible") return;
  pollingEmExecucao = true;
  try {
    const [dash, pend, lancs] = await Promise.all([
      api("/v1/admin/dashboard"),
      api("/v1/admin/pendencias"),
      api("/v1/admin/lancamentos?limit=300"),
    ]);

    setConn(true);

    // Detecção de novos itens de conferência para acionar alerta visual e sonoro
    const idsAnteriores = new Set(state.pendentes.map((p) => p.id));
    const novosItensAlerta = pend.filter((p) => !idsAnteriores.has(p.id));

    state.pendentes = pend;
    state.lancamentos = lancs;

    renderKPIs(dash);
    renderPendencias();
    renderLancamentos();
    atualizarCardsResumo(dash);

    // Se surgiram novas pendências desde o último polling, toca a campainha e pisca o card
    if (novosItensAlerta.length > 0 && idsAnteriores.size > 0) {
      dispararAlertaConferencia(novosItensAlerta[0]);
    }
  } catch (err) {
    // Falha silenciosa em glitches transitórios de rede
  } finally {
    pollingEmExecucao = false;
  }
}

/* ---------------- Render: KPIs ---------------- */
function renderKPIs(k) {
  const elVendido = $("#kpi-vendido");
  const elVendidoSub = $("#kpi-vendido-sub");
  const elFiado = $("#kpi-fiado");
  const elFiadoSub = $("#kpi-fiado-sub");
  const elRecebido = $("#kpi-recebido");
  const elRecebidoSub = $("#kpi-recebido-sub");
  const elPend = $("#kpi-pendencias");
  const elSaldoCaixa = $("#kpi-saldo-caixa");
  const elSaldoSub = $("#kpi-saldo-sub");

  if (elVendido) elVendido.textContent = money(k.total_vendido_hoje);
  if (elVendidoSub) elVendidoSub.textContent = `${k.quantidade_transacoes_hoje} transações · fiado gerado hoje ${money(k.total_fiado_gerado_hoje)}`;

  if (elFiado) elFiado.textContent = money(k.total_fiado_a_receber);
  if (elFiadoSub) elFiadoSub.textContent = `${k.quantidade_clientes} clientes cadastrados`;

  if (elRecebido) elRecebido.textContent = money(k.total_recebido_fiado_hoje);
  if (elRecebidoSub) elRecebidoSub.textContent = `Despesas hoje ${money(k.total_despesas_hoje)} · Líquido ${money(k.saldo_liquido_hoje)}`;

  if (elPend) elPend.textContent = k.pendencias_conferencia;

  // Saldo em caixa real (Vendas à vista + recebimentos de fiado - despesas)
  const saldoCaixaEstimado = Math.max(0, (k.total_vendido_hoje || 0) + (k.total_recebido_fiado_hoje || 0) - (k.total_despesas_hoje || 0));
  if (elSaldoCaixa) elSaldoCaixa.textContent = money(saldoCaixaEstimado);
  if (elSaldoSub) elSaldoSub.textContent = `Líquido do dia: ${money(k.saldo_liquido_hoje)}`;

  // Notificações do Header
  const notifFiados = $("#notif-fiados");
  const notifPend = $("#notif-pendencias");
  if (notifPend) notifPend.textContent = k.pendencias_conferencia || 0;
  if (notifFiados) {
    const clientesComFiado = state.clientes.filter((c) => (c.saldo_fiado_atual || 0) > 0).length;
    notifFiados.textContent = clientesComFiado;
  }
}

/* ---------------- Render: Cards Resumo Inferiores ---------------- */
function atualizarCardsResumo(k) {
  const elTicket = $("#bottomTicketMedio");
  const elFiadosQuitados = $("#bottomFiadosQuitados");
  const elLancamentosHoje = $("#bottomLancamentosHoje");

  if (elFiadosQuitados && k) {
    elFiadosQuitados.textContent = money(k.total_recebido_fiado_hoje || 0);
  }

  if (state.lancamentos && state.lancamentos.length) {
    const vendas = state.lancamentos.filter((l) => l.tipo_operacao === "VENDA");
    const media = vendas.length > 0 ? (vendas.reduce((acc, v) => acc + (v.valor_total || 0), 0) / vendas.length) : 0;
    if (elTicket) elTicket.textContent = money(media);
    if (elLancamentosHoje) elLancamentosHoje.textContent = state.lancamentos.length;
  } else if (k) {
    if (elLancamentosHoje) elLancamentosHoje.textContent = k.quantidade_transacoes_hoje || 0;
  }
}

/* ---------------- Render: Clientes ---------------- */
function renderClientes() {
  const tbody = $("#tbody-clientes");
  if (!tbody) return;
  if (!state.clientes.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">Nenhum cliente cadastrado ainda.</td></tr>`;
    return;
  }
  const ordenados = [...state.clientes].sort((a, b) => (b.saldo_fiado_atual || 0) - (a.saldo_fiado_atual || 0));
  tbody.innerHTML = ordenados.map((c) => {
    const saldo = Number(c.saldo_fiado_atual || 0);
    const sistema = SISTEMA_IDS.has(c.id);
    return `
      <tr>
        <td>
          <strong>${esc(c.nome)}</strong>${sistema ? ` ${badge("sistema")}` : ""}<br>
          <span class="muted font-mono text-[11px]">${esc(c.id)}</span>
        </td>
        <td>${esc(c.telefone || "—")}</td>
        <td class="${saldo > 0 ? "saldo-pos" : "saldo-zero"} tabular-nums">${money(saldo)}</td>
        <td>${fmtData(c.criado_em, false)}</td>
        <td class="text-right">
          <div class="flex items-center justify-end gap-1.5">
            <button type="button" class="btn btn-teal btn-sm" data-acao="baixa" data-id="${esc(c.id)}" ${saldo > 0 ? "" : "disabled"} title="Registrar pagamento deste cliente">
              <i class="fa-solid fa-hand-holding-dollar"></i>
              <span>Baixa</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm" data-acao="cobrar" data-id="${esc(c.id)}" ${sistema ? "disabled" : ""} title="Gerar cobrança formatada para WhatsApp">
              <i class="fa-brands fa-whatsapp text-teal"></i>
              <span>Cobrar</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm" data-acao="chave" data-id="${esc(c.id)}" title="Copiar chave de acesso (X-API-Key) para o cliente">
              <i class="fa-solid fa-key"></i>
            </button>
          </div>
        </td>
      </tr>`;
  }).join("");
}

function popularSelects() {
  const opcoes = state.clientes
    .map((c) => `<option value="${esc(c.id)}">${esc(c.nome)}${c.saldo_fiado_atual > 0 ? ` (${money(c.saldo_fiado_atual)})` : ""}</option>`)
    .join("");
  const ingest = $("#ingest-cliente");
  if (ingest) {
    const atualIngest = ingest.value;
    ingest.innerHTML = `<option value="">🤖 Cliente detectado pela IA</option>${opcoes}`;
    ingest.value = atualIngest;
  }
  const baixaSelect = $("#baixa-cliente");
  if (baixaSelect) {
    baixaSelect.innerHTML = state.clientes
      .filter((c) => c.saldo_fiado_atual > 0)
      .map((c) => `<option value="${esc(c.id)}">${esc(c.nome)} — ${money(c.saldo_fiado_atual)}</option>`)
      .join("") || `<option value="">Nenhum cliente com saldo devedor</option>`;
  }
  const editSelect = $("#edit-cliente");
  if (editSelect) {
    editSelect.innerHTML = opcoes;
  }
}

/* ---------------- Render: Pendências (Conferência Humana) ---------------- */
function renderPendencias() {
  const box = $("#fila-conferencia");
  const countEl = $("#review-count");
  const secConf = $("#sec-conferencia");
  if (countEl) countEl.textContent = `${state.pendentes.length} pendente${state.pendentes.length === 1 ? "" : "s"}`;
  if (secConf) {
    secConf.classList.toggle("has-pending-cards", state.pendentes.length > 0);
  }
  if (!box) return;
  if (!state.pendentes.length) {
    box.innerHTML = `<p class="empty-state"><i class="fa-solid fa-circle-check text-teal"></i> <span>Nenhum lançamento aguardando conferência humana.</span></p>`;
    return;
  }
  box.innerHTML = state.pendentes.map((l) => `
    <article class="review-card ${l.confianca_extracao === "BAIXO" ? "baixo" : ""}" id="rev-${esc(l.id)}">
      <div class="review-attention-badge">
        <span class="beacon-dot-amber"></span>
        <span>Atenção: Conferência Humana Pendente</span>
      </div>
      <div class="review-top">
        <div>
          <strong>${esc(l.cliente_nome || l.cliente_id)}</strong>
          <div class="muted">${fmtData(l.data_hora)} • ${esc(ORIGEM_ICON[l.origem_dados] || l.origem_dados)}</div>
        </div>
        <span class="review-valor tabular-nums">${money(l.valor_total)}</span>
      </div>
      <div class="review-badges">
        ${badge(`Confiança ${l.confianca_extracao}`, BADGE_CONF[l.confianca_extracao])}
        ${badge(l.tipo_operacao)}
        ${badge(l.tipo_pagamento, BADGE_TIPO[l.tipo_pagamento])}
        ${badge(l.forma_pagamento)}
        ${l.divergencia_calculo ? badge("⚠ Divergência de cálculo", "b-div") : ""}
      </div>
      <ul class="review-itens">
        ${(l.itens || []).map((i) => `<li>${Number(i.quantidade)}x ${esc(i.descricao)} — ${money(i.valor_unitario)} = <strong>${money(i.valor_total_item)}</strong></li>`).join("") || "<li>Sem itens detalhados</li>"}
      </ul>
      ${l.transcricao_raw ? `<div class="review-raw">“${esc(l.transcricao_raw)}”</div>` : ""}
      ${l.observacoes ? `<div class="review-obs"><i class="fa-solid fa-note-sticky mr-1"></i> ${esc(l.observacoes)}</div>` : ""}
      <div class="review-actions">
        <button type="button" class="btn btn-warn btn-sm" data-acao="editar" data-id="${esc(l.id)}">
          <i class="fa-solid fa-pen-to-square"></i>
          <span>Editar / Rejeitar</span>
        </button>
        <button type="button" class="btn btn-teal btn-sm" data-acao="aprovar" data-id="${esc(l.id)}">
          <span class="spinner"></span>
          <i class="fa-solid fa-check"></i>
          <span class="btn-label">Aprovar Lançamento</span>
        </button>
      </div>
    </article>`).join("");
}

/* ---------------- Render: Lançamentos ---------------- */
function renderLancamentos() {
  const termoInput = $("#busca-cliente");
  const termo = termoInput ? termoInput.value.trim().toLowerCase() : "";
  const tipoSelect = $("#filtro-tipo");
  const tipo = tipoSelect ? tipoSelect.value : "";
  const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const lista = state.lancamentos.filter((l) =>
    (!tipo || l.tipo_pagamento === tipo) && (!termo || norm(l.cliente_nome).includes(norm(termo)) || norm(l.transcricao_raw).includes(norm(termo))));
  const tbody = $("#tbody-lancamentos");
  if (!tbody) return;
  if (!lista.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">Nenhum lançamento encontrado.</td></tr>`;
    return;
  }
  tbody.innerHTML = lista.map((l) => `
    <tr>
      <td class="tabular-nums font-medium whitespace-nowrap">${fmtData(l.data_hora)}</td>
      <td><strong>${esc(l.cliente_nome || l.cliente_id)}</strong></td>
      <td>${badge(l.tipo_operacao)}</td>
      <td>${badge(l.tipo_pagamento, BADGE_TIPO[l.tipo_pagamento])}</td>
      <td class="whitespace-nowrap">${esc(l.forma_pagamento)}</td>
      <td class="td-itens" title="${esc(l.observacoes || "")}">${esc(resumoItens(l.itens))}${l.divergencia_calculo ? ` ${badge("⚠ Divergência", "b-div")}` : ""}</td>
      <td class="text-right tabular-nums whitespace-nowrap font-bold">${money(l.valor_total)}</td>
      <td>${badge(l.status_validacao, BADGE_STATUS[l.status_validacao])}</td>
      <td class="whitespace-nowrap text-slate-500">${esc(ORIGEM_ICON[l.origem_dados] || l.origem_dados)}</td>
    </tr>`).join("");
}

/* ---------------- Ingestão Multimodal ---------------- */
function definirArquivo(file) {
  if (!file) return;
  const ok = /^(image|audio)\//.test(file.type) || file.type === "application/pdf" || /\.(ogg|opus|m4a|heic|webm)$/i.test(file.name);
  if (!ok) { toast("Formato de arquivo não suportado. Envie imagem, PDF ou áudio.", "err"); return; }
  if (file.size > 20 * 1024 * 1024) { toast("Arquivo excede o limite de 20 MB.", "err"); return; }
  limparArquivo();
  state.arquivo = file;
  state.previewUrl = URL.createObjectURL(file);
  const prev = $("#dz-preview");
  let midia = "";
  if (file.type.startsWith("image/")) midia = `<img src="${state.previewUrl}" alt="Prévia da comanda" />`;
  else if (file.type.startsWith("audio/") || /\.(ogg|opus|m4a|webm)$/i.test(file.name)) midia = `<audio controls src="${state.previewUrl}"></audio>`;
  else midia = `<div class="dz-icons-row"><i class="fa-solid fa-file-lines text-sky"></i></div>`;
  prev.innerHTML = `${midia}
    <div class="flex items-center gap-2 text-xs mt-1">
      <span class="font-medium">${esc(file.name)} (${(file.size / 1024).toFixed(0)} KB)</span>
      <button type="button" class="btn btn-ghost btn-sm" id="btn-remover-arquivo"><i class="fa-solid fa-xmark"></i> Remover</button>
    </div>`;
  prev.classList.remove("hidden");
  $("#dz-content").classList.add("hidden");
}

function limparArquivo() {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.arquivo = null;
  state.previewUrl = null;
  const input = $("#file-input");
  if (input) input.value = "";
  const prev = $("#dz-preview");
  if (prev) {
    prev.innerHTML = "";
    prev.classList.add("hidden");
  }
  const content = $("#dz-content");
  if (content) content.classList.remove("hidden");
}

/* ---------------- Câmera ao Vivo & Captura ---------------- */
let cameraStream = null;

window.iniciarCapturaFoto = async function () {
  const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (isMobile) {
    // No celular, aciona a câmera nativa do aparelho via input capture
    const camInput = $("#camera-input");
    if (camInput) camInput.click();
    return;
  }

  // No desktop, tenta abrir stream ao vivo no modal ou cai no seletor
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } }
      });
      const video = $("#camera-stream");
      if (video) {
        video.srcObject = cameraStream;
        abrirModal("#modal-camera");
      }
    } catch (err) {
      // Se permissão for negada ou sem câmera web, abre o seletor normal
      const camInput = $("#camera-input");
      if (camInput) camInput.click();
    }
  } else {
    const camInput = $("#camera-input");
    if (camInput) camInput.click();
  }
};

window.fecharModalCamera = function () {
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  const m = $("#modal-camera");
  if (m) m.classList.add("hidden");
};

window.capturarFotoDoStream = function () {
  const video = $("#camera-stream");
  const canvas = $("#camera-canvas");
  if (!video || !canvas) return;

  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => {
    if (blob) {
      const file = new File([blob], `foto_comanda_${Date.now()}.jpg`, { type: "image/jpeg" });
      definirArquivo(file);
      fecharModalCamera();
      toast("Foto capturada com sucesso!");
    }
  }, "image/jpeg", 0.9);
};

window.handleCameraCapture = function (ev) {
  if (ev.target && ev.target.files && ev.target.files[0]) {
    definirArquivo(ev.target.files[0]);
    toast("Foto da comanda pronta para o Agente!");
  }
};

/* ---------------- Gravação de Áudio com Microfone (MediaRecorder) ---------------- */
let mediaRecorder = null;
let audioChunks = [];
let audioStream = null;
let gravacaoInterval = null;
let segundosGravados = 0;

window.alternarGravacaoAudio = async function () {
  const btn = $("#btn-gravar-audio");
  const label = $("#label-audio-rec");
  const icon = $("#icon-mic-status");

  // Se já estiver gravando, parar a gravação
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    clearInterval(gravacaoInterval);
    if (btn) btn.classList.remove("is-recording");
    if (label) label.textContent = "Gravar Áudio";
    if (icon) icon.className = "fa-solid fa-microphone text-teal";
    return;
  }

  // Iniciar nova gravação
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    // Fallback: abre seletor de arquivo de áudio
    const fb = $("#audio-input-fallback");
    if (fb) fb.click();
    return;
  }

  try {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    segundosGravados = 0;

    let mimeType = "audio/webm";
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
      mimeType = "audio/webm;codecs=opus";
    } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
      mimeType = "audio/ogg;codecs=opus";
    } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
      mimeType = "audio/mp4";
    }

    mediaRecorder = new MediaRecorder(audioStream, { mimeType });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        audioChunks.push(e.data);
      }
    };

    mediaRecorder.onstop = () => {
      if (audioStream) {
        audioStream.getTracks().forEach((track) => track.stop());
        audioStream = null;
      }
      const ext = mimeType.includes("ogg") ? "ogg" : (mimeType.includes("mp4") ? "m4a" : "webm");
      const audioBlob = new Blob(audioChunks, { type: mimeType });
      const audioFile = new File([audioBlob], `pedido_audio_${Date.now()}.${ext}`, { type: mimeType });
      definirArquivo(audioFile);
      toast("Áudio gravado com sucesso! Pronto para mandar para o Agente.");
    };

    mediaRecorder.start(250);

    if (btn) btn.classList.add("is-recording");
    if (icon) icon.className = "fa-solid fa-circle-stop text-coral";
    if (label) label.textContent = "Parar (00:00)";

    gravacaoInterval = setInterval(() => {
      segundosGravados++;
      const m = String(Math.floor(segundosGravados / 60)).padStart(2, "0");
      const s = String(segundosGravados % 60).padStart(2, "0");
      if (label) label.textContent = `Parar (${m}:${s})`;
      // Limite máximo de 3 minutos de gravação contínua
      if (segundosGravados >= 180) {
        alternarGravacaoAudio();
      }
    }, 1000);

    toast("Microfone ativo! Fale o pedido e clique em 'Parar'.");
  } catch (err) {
    toast("Acesso ao microfone negado ou indisponível. Selecione um arquivo de áudio.", "warn");
    const fb = $("#audio-input-fallback");
    if (fb) fb.click();
  }
};

/* ---------------- Envio para o Agente (Ingestão) ---------------- */
async function processarIngestao() {
  const btn = $("#btn-processar");
  const textEl = $("#ingest-text");
  const texto = textEl ? textEl.value.trim() : "";
  const clienteId = $("#ingest-cliente") ? $("#ingest-cliente").value || null : null;
  const box = $("#ingest-result");
  if (!state.arquivo && !texto) {
    toast("Envie uma foto/áudio ou digite uma nota de balcão.", "warn");
    return;
  }

  setLoading(btn, true);
  if (box) {
    box.className = "ingest-result";
    box.innerHTML = `<i class="fa-solid fa-brain text-sky"></i> Agente Like Baguncinha 1.0 analisando e convertendo dados…`;
    box.classList.remove("hidden");
  }

  try {
    let r;
    if (state.arquivo) {
      const form = new FormData();
      form.append("arquivo", state.arquivo, state.arquivo.name);
      if (clienteId) form.append("cliente_id", clienteId);
      if (texto) form.append("texto_contexto", texto);
      r = await api("/v1/admin/ingestao/midia", { method: "POST", form });
    } else {
      r = await api("/v1/admin/ingestao/texto", { method: "POST", body: { texto, cliente_id: clienteId } });
    }
    const l = r.lancamento;
    const aprovado = l.status_validacao === "APROVADO";
    if (box) {
      box.className = `ingest-result ${aprovado ? "ok" : "warn"}`;
      box.innerHTML = `
        <div class="font-bold flex items-center gap-1.5">
          <i class="fa-solid ${aprovado ? "fa-circle-check" : "fa-triangle-exclamation"}"></i>
          <span>${esc(r.mensagem)}</span>
        </div>
        <div>Cliente: <strong>${esc(r.cliente_nome)}</strong> • Saldo devedor: <strong class="tabular-nums">${money(r.saldo_fiado_atual)}</strong></div>
        <div class="flex items-center gap-1 mt-1">
          ${badge(l.tipo_operacao)} ${badge(l.tipo_pagamento, BADGE_TIPO[l.tipo_pagamento])} ${badge(l.forma_pagamento)}
          ${badge(`Confiança ${l.confianca_extracao}`, BADGE_CONF[l.confianca_extracao])}
          ${l.divergencia_calculo ? badge("⚠ Divergência", "b-div") : ""}
        </div>
        <div class="muted mt-1">${esc(resumoItens(l.itens))} — <strong class="tabular-nums">${money(l.valor_total)}</strong></div>
        ${l.observacoes ? `<div class="review-obs mt-1"><i class="fa-solid fa-note-sticky mr-1"></i> ${esc(l.observacoes)}</div>` : ""}`;
    }

    // Se a confiança foi MÉDIA ou BAIXA, dispara o alerta visual e sonoro
    if (!aprovado) {
      dispararAlertaConferencia(l);
    } else {
      toast("Lançamento auditado e aprovado com sucesso!", "ok");
    }

    if (textEl) textEl.value = "";
    limparArquivo();
    await carregarTudo();
  } catch (err) {
    if (box) {
      box.className = "ingest-result err";
      box.innerHTML = `<i class="fa-solid fa-circle-xmark mr-1"></i> ${esc(err.message)}`;
    }
    toast(err.message, "err");
  } finally {
    setLoading(btn, false);
  }
}

/* ---------------- Testes Rápidos (Preenchimento 1-Clique) ---------------- */
window.preencherExemplo = function (tipo) {
  const input = $("#ingest-text");
  if (!input) return;
  if (tipo === "xsalada") {
    input.value = "Marcar pro João do Bar 1 x-salada 22 real, paga semana que vem";
  } else if (tipo === "marmita") {
    input.value = "Maria das Marmitas 69 real vai pagar dia 05 próximo";
  } else if (tipo === "cerveja") {
    input.value = "Anota 8 cerveja 12 real cada pro João do Bar, vai pagar amanhã";
  } else if (tipo === "despesa") {
    input.value = "Distribuidora de Gelo Bebedouro: entrega de gelo e carvão 110 reais a pagar em dinheiro";
  }
  input.focus();
  toast("Exemplo inserido! Clique em 'Mandar para o Agente'.");
};

/* ---------------- Conferência Humana ---------------- */
async function aprovarRapido(id, btn) {
  setLoading(btn, true);
  try {
    await api(`/v1/admin/lancamentos/${encodeURIComponent(id)}/validar`, { method: "PATCH", body: { status_validacao: "APROVADO" } });
    toast("Lançamento aprovado e integrado ao caixa!");
    await carregarTudo();
  } catch (err) {
    toast(err.message, "err");
    setLoading(btn, false);
  }
}

function linhaItem(item = { descricao: "", quantidade: 1, valor_unitario: 0 }) {
  const row = document.createElement("div");
  row.className = "item-row";
  row.innerHTML = `
    <input class="i-desc" type="text" placeholder="Descrição do item" value="${esc(item.descricao)}" required />
    <input class="i-qtd tabular-nums" type="number" step="0.001" min="0.001" value="${Number(item.quantidade) || 1}" required />
    <input class="i-vu tabular-nums" type="number" step="0.01" min="0" value="${Number(item.valor_unitario) || 0}" required />
    <span class="item-total tabular-nums">R$ 0,00</span>
    <button type="button" class="btn btn-danger btn-sm i-del" title="Remover item"><i class="fa-solid fa-xmark"></i></button>`;
  return row;
}

function recalcularTotalEdicao() {
  let total = 0;
  $$("#edit-itens .item-row").forEach((row) => {
    const q = parseFloat($(".i-qtd", row).value) || 0;
    const vu = parseFloat($(".i-vu", row).value) || 0;
    const t = Math.round(q * vu * 100) / 100;
    $(".item-total", row).textContent = money(t);
    total += t;
  });
  const totalEl = $("#edit-total");
  if (totalEl) totalEl.textContent = money(total);
}

function abrirEdicao(id) {
  const l = state.pendentes.find((p) => p.id === id) || state.lancamentos.find((p) => p.id === id);
  if (!l) return;
  state.editando = l;
  $("#edit-cliente").value = l.cliente_id;
  $("#edit-operacao").value = l.tipo_operacao;
  $("#edit-tipo").value = l.tipo_pagamento;
  $("#edit-forma").value = l.forma_pagamento;
  $("#edit-raw").textContent = l.transcricao_raw || "(sem transcrição original)";
  $("#edit-obs").value = l.observacoes || "";
  const box = $("#edit-itens");
  box.innerHTML = "";
  (l.itens && l.itens.length ? l.itens : [undefined]).forEach((i) => box.appendChild(linhaItem(i)));
  recalcularTotalEdicao();
  abrirModal("#modal-editar");
}

function coletarItensEdicao() {
  return $$("#edit-itens .item-row").map((row) => ({
    descricao: $(".i-desc", row).value.trim(),
    quantidade: parseFloat($(".i-qtd", row).value),
    valor_unitario: parseFloat($(".i-vu", row).value),
  })).filter((i) => i.descricao);
}

async function salvarEdicao(status, btn) {
  const l = state.editando;
  if (!l) return;
  const body = { status_validacao: status, observacoes: $("#edit-obs").value };
  if (status === "APROVADO") {
    const itens = coletarItensEdicao();
    if (!itens.length) { toast("Informe ao menos um item com descrição válida.", "warn"); return; }
    Object.assign(body, {
      itens,
      tipo_operacao: $("#edit-operacao").value,
      tipo_pagamento: $("#edit-tipo").value,
      forma_pagamento: $("#edit-forma").value,
      cliente_id: $("#edit-cliente").value || null,
    });
  }
  setLoading(btn, true);
  try {
    await api(`/v1/admin/lancamentos/${encodeURIComponent(l.id)}/validar`, { method: "PATCH", body });
    toast(status === "APROVADO" ? "Lançamento corrigido e aprovado." : "Lançamento rejeitado.", status === "APROVADO" ? "ok" : "warn");
    fecharModais();
    await carregarTudo();
  } catch (err) {
    toast(err.message, "err");
  } finally {
    setLoading(btn, false);
  }
}

/* ---------------- Baixa de Fiado ---------------- */
function abrirBaixa(clienteId) {
  const comSaldo = state.clientes.filter((c) => (c.saldo_fiado_atual || 0) > 0);
  if (!comSaldo.length) { toast("Nenhum cliente com saldo de fiado em aberto no momento.", "warn"); return; }
  const sel = $("#baixa-cliente");
  sel.value = clienteId && comSaldo.some((c) => c.id === clienteId) ? clienteId : comSaldo[0].id;
  atualizarSaldoBaixa();
  $("#baixa-obs").value = "";
  abrirModal("#modal-baixa");
  $("#baixa-valor").focus();
}

function atualizarSaldoBaixa() {
  const sel = $("#baixa-cliente");
  if (!sel) return;
  const c = state.clientes.find((x) => x.id === sel.value);
  const saldo = c ? Number(c.saldo_fiado_atual || 0) : 0;
  const saldoEl = $("#baixa-saldo");
  if (saldoEl) saldoEl.textContent = money(saldo);
  const valorInput = $("#baixa-valor");
  if (valorInput) {
    valorInput.max = saldo.toFixed(2);
    valorInput.value = saldo > 0 ? saldo.toFixed(2) : "";
  }
}

async function registrarBaixa(ev) {
  ev.preventDefault();
  const btn = $("#form-baixa button[type=submit]");
  setLoading(btn, true);
  try {
    const r = await api("/v1/admin/fiado/baixa", {
      method: "POST",
      body: {
        cliente_id: $("#baixa-cliente").value,
        valor_pago: parseFloat($("#baixa-valor").value),
        forma_pagamento: $("#baixa-forma").value,
        observacoes: $("#baixa-obs").value || null,
      },
    });
    toast(`${r.mensagem} Novo saldo: ${money(r.saldo_fiado_atual)}`);
    fecharModais();
    await carregarTudo();
  } catch (err) {
    toast(err.message, "err");
  } finally {
    setLoading(btn, false);
  }
}

/* ---------------- Cobrança via WhatsApp ---------------- */
async function abrirCobranca(clienteId) {
  try {
    const r = await api(`/v1/admin/clientes/${encodeURIComponent(clienteId)}/cobranca`);
    $("#cobranca-msg").value = r.mensagem;
    const link = $("#cobranca-link");
    if (r.whatsapp_link) {
      link.href = r.whatsapp_link;
      link.classList.remove("hidden");
    } else {
      link.classList.add("hidden");
    }
    abrirModal("#modal-cobranca");
  } catch (err) {
    toast(err.message, "err");
  }
}

async function copiarTexto(texto) {
  try {
    await navigator.clipboard.writeText(texto);
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = texto;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

/* ---------------- Cadastro de Cliente ---------------- */
async function cadastrarCliente(ev) {
  ev.preventDefault();
  const btn = $("#form-cliente button[type=submit]");
  const box = $("#cli-result");
  setLoading(btn, true);
  try {
    const c = await api("/v1/admin/clientes", {
      method: "POST",
      body: { nome: $("#cli-nome").value, telefone: $("#cli-tel").value, cpf_cnpj: $("#cli-doc").value || null },
    });
    box.className = "ingest-result ok";
    box.innerHTML = `<strong><i class="fa-solid fa-circle-check"></i> ${esc(c.nome)} cadastrado!</strong>
      <div>Chave do cliente (X-API-Key): <code class="font-mono bg-white/20 px-1 py-0.5 rounded text-[11px]">${esc(c.api_key)}</code></div>
      <div class="muted mt-1">Envie esta chave ao cliente para consulta no endpoint /v1/consulta/resumo.</div>`;
    box.classList.remove("hidden");
    $("#form-cliente").reset();
    await carregarTudo();
  } catch (err) {
    box.className = "ingest-result err";
    box.innerHTML = `<i class="fa-solid fa-circle-xmark mr-1"></i> ${esc(err.message)}`;
    box.classList.remove("hidden");
  } finally {
    setLoading(btn, false);
  }
}

/* ---------------- Exportação Fechamento .XLSX ---------------- */
async function exportarXlsx() {
  const data = $("#export-date").value || hojeISO();
  try {
    toast("Gerando planilha Excel de fechamento…", "ok", 2500);
    const res = await api(`/v1/admin/fechamento/exportar-xlsx?data=${encodeURIComponent(data)}`, { raw: true });
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^";]+)"?/i);
    const nome = match ? match[1] : `fechamento_like_baguncinha_${data}.xlsx`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
    toast("Fechamento .xlsx exportado com sucesso!");
  } catch (err) {
    toast(err.message, "err");
  }
}

/* ---------------- Modais & Sidebar Retrátil ---------------- */
function abrirModal(sel) {
  const el = $(sel);
  if (el) el.classList.remove("hidden");
}

function fecharModais() {
  $$(".modal").forEach((m) => m.classList.add("hidden"));
  state.editando = null;
  fecharModalCamera();
}

window.toggleSidebar = function () {
  const sb = $("#sidebar");
  const bd = $("#mobileBackdrop");
  if (!sb) return;
  sb.classList.toggle("open");
  if (bd) bd.classList.toggle("hidden");
};

window.toggleSidebarCollapse = function () {
  const sb = $("#sidebar");
  if (!sb) return;
  const isCollapsed = sb.classList.toggle("collapsed");
  document.documentElement.classList.toggle("sidebar-is-collapsed", isCollapsed);
  localStorage.setItem(LS_COLLAPSED, isCollapsed ? "1" : "0");
};

window.setActiveNav = function (el) {
  $$(".nav-item").forEach((item) => item.classList.remove("active"));
  if (el) el.classList.add("active");
  if (window.innerWidth < 992) {
    window.toggleSidebar();
  }
};

window.abrirModalInfoWebhook = function () {
  abrirModal("#modal-info-webhook");
};

/* ---------------- Modo Noturno Único ---------------- */
function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle("dark");
  localStorage.setItem(LS_THEME, isDark ? "dark" : "light");
  toast(isDark ? "Modo noturno ativado 🌙" : "Modo claro ativado ☀️", "ok", 2000);
}

/* ---------------- Registro de Eventos ---------------- */
function registrarEventos() {
  // Autenticação
  const authForm = $("#auth-form");
  if (authForm) {
    authForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      state.adminKey = $("#admin-key").value.trim();
      state.apiBase = $("#api-base").value.trim().replace(/\/+$/, "");
      localStorage.setItem(LS_KEY, state.adminKey);
      if (state.apiBase) localStorage.setItem(LS_API, state.apiBase);
      else localStorage.removeItem(LS_API);
      await carregarTudo();
    });
  }

  const btnLogout = $("#btn-logout");
  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      localStorage.removeItem(LS_KEY);
      state.adminKey = "";
      $("#admin-key").value = "";
      setConn(false);
      toast("Chave mestra removida deste navegador.", "warn");
    });
  }

  // Alternador de Modo Noturno Único (na barra lateral)
  const btnThemeSide = $("#btn-theme-toggle");
  if (btnThemeSide) btnThemeSide.addEventListener("click", toggleDarkMode);

  // Dropzone
  const dz = $("#dropzone");
  if (dz) {
    ["dragenter", "dragover"].forEach((e) => dz.addEventListener(e, (ev) => {
      ev.preventDefault();
      dz.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach((e) => dz.addEventListener(e, (ev) => {
      ev.preventDefault();
      dz.classList.remove("dragover");
    }));
    dz.addEventListener("drop", (ev) => definirArquivo(ev.dataTransfer.files[0]));
    dz.addEventListener("click", (ev) => {
      if (ev.target.closest("#btn-remover-arquivo")) {
        ev.preventDefault();
        limparArquivo();
      } else if (ev.target.closest("audio")) {
        ev.preventDefault();
      }
    });
  }

  const fileInput = $("#file-input");
  if (fileInput) {
    fileInput.addEventListener("change", (ev) => definirArquivo(ev.target.files[0]));
  }

  // Ingestão
  const btnProcessar = $("#btn-processar");
  if (btnProcessar) btnProcessar.addEventListener("click", processarIngestao);

  const ingestText = $("#ingest-text");
  if (ingestText) {
    ingestText.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) processarIngestao();
    });
  }

  // Fila de conferência
  const filaConf = $("#fila-conferencia");
  if (filaConf) {
    filaConf.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-acao]");
      if (!btn) return;
      if (btn.dataset.acao === "aprovar") aprovarRapido(btn.dataset.id, btn);
      if (btn.dataset.acao === "editar") abrirEdicao(btn.dataset.id);
    });
  }

  // Tabela de clientes
  const tbodyCli = $("#tbody-clientes");
  if (tbodyCli) {
    tbodyCli.addEventListener("click", async (ev) => {
      const btn = ev.target.closest("button[data-acao]");
      if (!btn) return;
      const id = btn.dataset.id;
      if (btn.dataset.acao === "baixa") abrirBaixa(id);
      if (btn.dataset.acao === "cobrar") abrirCobranca(id);
      if (btn.dataset.acao === "chave") {
        const c = state.clientes.find((x) => x.id === id);
        if (c) {
          await copiarTexto(c.api_key);
          toast(`Chave X-API-Key de ${c.nome} copiada com sucesso!`);
        }
      }
    });
  }

  const btnBaixaGeral = $("#btn-baixa-geral");
  if (btnBaixaGeral) btnBaixaGeral.addEventListener("click", () => abrirBaixa());

  const baixaCliSelect = $("#baixa-cliente");
  if (baixaCliSelect) baixaCliSelect.addEventListener("change", atualizarSaldoBaixa);

  const formBaixa = $("#form-baixa");
  if (formBaixa) formBaixa.addEventListener("submit", registrarBaixa);

  const btnNovoCli = $("#btn-novo-cliente");
  if (btnNovoCli) {
    btnNovoCli.addEventListener("click", () => {
      const resBox = $("#cli-result");
      if (resBox) resBox.classList.add("hidden");
      abrirModal("#modal-cliente");
      const nomeInput = $("#cli-nome");
      if (nomeInput) nomeInput.focus();
    });
  }

  const formCli = $("#form-cliente");
  if (formCli) formCli.addEventListener("submit", cadastrarCliente);

  const btnCopiar = $("#btn-copiar");
  if (btnCopiar) {
    btnCopiar.addEventListener("click", async () => {
      const msg = $("#cobranca-msg");
      if (msg) {
        await copiarTexto(msg.value);
        toast("Mensagem de cobrança copiada! Cole no WhatsApp do cliente.");
      }
    });
  }

  // Edição
  const btnAddItem = $("#btn-add-item");
  if (btnAddItem) {
    btnAddItem.addEventListener("click", () => {
      $("#edit-itens").appendChild(linhaItem());
      recalcularTotalEdicao();
    });
  }

  const editItens = $("#edit-itens");
  if (editItens) {
    editItens.addEventListener("input", recalcularTotalEdicao);
    editItens.addEventListener("click", (ev) => {
      if (ev.target.closest(".i-del")) {
        ev.target.closest(".item-row").remove();
        recalcularTotalEdicao();
      }
    });
  }

  const formEdit = $("#form-editar");
  if (formEdit) {
    formEdit.addEventListener("submit", (ev) => {
      ev.preventDefault();
      salvarEdicao("APROVADO", $("#form-editar button[type=submit]"));
    });
  }

  const btnRejeitar = $("#btn-rejeitar");
  if (btnRejeitar) {
    btnRejeitar.addEventListener("click", (ev) => {
      if (confirm("Deseja realmente rejeitar este lançamento? Ele será descartado do caixa e não contará no fiado.")) {
        salvarEdicao("REJEITADO", ev.currentTarget);
      }
    });
  }

  // Modais fechar
  $$(".modal").forEach((m) => m.addEventListener("click", (ev) => {
    if (ev.target === m || ev.target.closest("[data-close]")) fecharModais();
  }));
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") fecharModais();
  });

  // Filtros de Lançamentos
  const buscaCli = $("#busca-cliente");
  if (buscaCli) buscaCli.addEventListener("input", renderLancamentos);

  const filtroTipo = $("#filtro-tipo");
  if (filtroTipo) filtroTipo.addEventListener("change", renderLancamentos);

  const btnRefresh = $("#btn-refresh");
  if (btnRefresh) btnRefresh.addEventListener("click", carregarTudo);

  // Exportação
  const btnExport = $("#btn-export");
  if (btnExport) btnExport.addEventListener("click", exportarXlsx);

  const fabExport = $("#fab-export");
  if (fabExport) fabExport.addEventListener("click", exportarXlsx);
}

/* ---------------- Inicialização ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  const adminKeyInput = $("#admin-key");
  if (adminKeyInput) adminKeyInput.value = state.adminKey;

  const apiBaseInput = $("#api-base");
  if (apiBaseInput) apiBaseInput.value = localStorage.getItem(LS_API) || "";

  const exportDateInput = $("#export-date");
  if (exportDateInput) exportDateInput.value = hojeISO();

  const dataExtenso = $("#data-atual-extenso");
  if (dataExtenso) dataExtenso.textContent = dataAtualPorExtenso();

  // Aplica estado recolhido da sidebar se salvo
  if (localStorage.getItem(LS_COLLAPSED) === "1" && window.innerWidth >= 992) {
    const sb = $("#sidebar");
    if (sb) sb.classList.add("collapsed");
  }

  atualizarIconeSom();
  registrarEventos();

  if (state.adminKey) {
    carregarTudo();
  }

  // Atualização em tempo real (Polling leve a cada 4 segundos, sem F5)
  setInterval(() => {
    if (state.adminKey && document.visibilityState === "visible") {
      pollingSilencioso();
    }
  }, 4000);
});
