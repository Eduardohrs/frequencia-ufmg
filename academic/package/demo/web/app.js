// A interface apenas envia ações e apresenta resultados. As regras e cálculos
// de frequência pertencem às classes Python usadas pela interface local.
const ui = {
  state: { disciplinas: [], atividades: [] },
  selected: sessionStorage.getItem("demo.selectedCourse"),
  view: "disciplinas",
  dates: [],
  refreshAfterDialog: false,
  hasLoaded: false,
  toastTimer: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const dateLabel = (iso) => {
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
};
const shortMonth = (iso) => new Intl.DateTimeFormat("pt-BR", { month: "short" })
  .format(new Date(`${iso}T12:00:00`)).replace(".", "");
const statusLabel = {
  pendente: "Pendente", presente: "Presente", ausente: "Ausente",
  atrasado: "Atraso", "saiu mais cedo": "Saída antecipada",
  cancelada: "Cancelada", "sem chamada": "Sem chamada",
};

function notice(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.hidden = false;
  clearTimeout(ui.toastTimer);
  ui.toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}

function applyState(body) {
  ui.state = body;
  if (!body.disciplinas.some((course) => course.codigo === ui.selected)) {
    ui.selected = body.disciplinas[0]?.codigo || null;
  }
  if (ui.selected) sessionStorage.setItem("demo.selectedCourse", ui.selected);
  else sessionStorage.removeItem("demo.selectedCourse");
  render();
}

async function load() {
  const retry = $('#load-error [data-action="retry-load"]');
  retry.disabled = true;
  try {
    const response = await fetch("/api/estado", { cache: "no-store" });
    let body;
    try { body = await response.json(); } catch { throw Error("Resposta inválida do servidor local."); }
    if (!response.ok) throw Error(body.erro || "Não foi possível carregar os dados.");
    ui.hasLoaded = true;
    $("#load-error").hidden = true;
    $(".shell").classList.remove("load-failed");
    applyState(body);
  } catch (error) {
    const message = error instanceof TypeError
      ? "O servidor local não respondeu. Verifique o terminal e tente novamente."
      : error.message.replace(/^Não foi possível carregar os dados:\s*/, "");
    $("#load-error-title").textContent = ui.hasLoaded
      ? "Não foi possível atualizar" : "Não foi possível carregar a demo";
    $("#load-error-message").textContent = ui.hasLoaded
      ? `${message.replace(/[.!?]$/, "")}. Os dados abaixo são da última leitura.` : message;
    $("#load-error").hidden = false;
    $(".shell").classList.toggle("load-failed", !ui.hasLoaded);
  } finally {
    retry.disabled = false;
  }
}

async function send(route, payload) {
  const response = await fetch(route, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let body;
  try { body = await response.json(); } catch { throw Error("Resposta inválida do servidor local."); }
  if (!response.ok) throw Error(body.erro || "Não foi possível salvar.");
  applyState(body);
}

const validViews = new Set(["disciplinas", "agenda", "ajustes"]);

function switchView(name, updateHash = true) {
  if (!validViews.has(name)) name = "disciplinas";
  ui.view = name;
  $$(".view").forEach((panel) => { panel.hidden = panel.id !== `view-${name}`; });
  $$(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
    button.setAttribute("aria-current", button.dataset.view === name ? "page" : "false");
  });
  if (updateHash && location.hash !== `#${name}`) location.hash = name;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function render() {
  const courses = ui.state.disciplinas;
  const picker = $("#mobile-course-picker");
  picker.hidden = courses.length <= 1;
  $("#mobile-course-select").innerHTML = courses.map((course) =>
    `<option value="${escapeHtml(course.codigo)}">${escapeHtml(course.nome)} · ${escapeHtml(course.codigo)}</option>`
  ).join("");
  $("#mobile-course-select").value = ui.selected || "";
  $(".course-layout").classList.toggle("no-courses", courses.length === 0);
  $("#course-count").textContent = courses.length;
  $("#course-list").innerHTML = courses.length ? courses.map((course) => {
    const pending = course.resumo.pendentes;
    return `<button type="button" class="course-choice ${course.codigo === ui.selected ? "active" : ""}" data-course="${escapeHtml(course.codigo)}" aria-pressed="${course.codigo === ui.selected}">
      <strong>${escapeHtml(course.nome)}</strong><small>${escapeHtml(course.codigo)}</small>
      <span class="course-meta"><i class="status-dot ${pending ? "warn" : ""}"></i>${pending ? `${pending} aula${pending === 1 ? "" : "s"} pendente${pending === 1 ? "" : "s"}` : "Registros em dia"}</span>
    </button>`;
  }).join("") : '<p class="muted">Nenhuma disciplina ainda.</p>';
  const selected = courses.find((course) => course.codigo === ui.selected);
  $("#course-detail").innerHTML = selected ? courseDetail(selected) : `
    <div class="surface empty"><span class="empty-icon">+</span><strong>Comece com uma disciplina</strong>
    <p>Adicione a grade para acompanhar presenças e faltas.</p>
    <div class="empty-actions"><button type="button" class="primary" data-action="criar">Criar disciplina</button>
    <button type="button" class="secondary" data-action="exemplo">Usar dados de exemplo</button></div></div>`;
  renderAgenda();
  const select = $("#activity-course");
  select.innerHTML = courses.map((course) => `<option value="${escapeHtml(course.codigo)}">${escapeHtml(course.nome)}</option>`).join("");
}

function courseDetail(course) {
  const summary = course.resumo;
  const total = summary.aulas || 1;
  const attended = Math.max(0, summary.aulas - summary.faltas - summary.pendentes);
  const activities = ui.state.atividades.filter((item) => item.codigo_disciplina === course.codigo);
  const percent = summary.frequencia === null ? "—" : `${Math.round(summary.frequencia)}%`;
  const lessons = course.registros[0]?.aulas || 0;
  const absenceValue = summary.limite ? `${summary.faltas}/${summary.limite}` : summary.faltas;
  const absenceLabel = summary.limite ? "faltas usadas" : "faltas usadas (limite 0)";
  return `<div class="surface">
    <div class="detail-top"><div><span class="detail-code">${escapeHtml(course.codigo)}</span>
      <h2 class="detail-title">${escapeHtml(course.nome)}</h2>
      <p class="muted">${course.chamadas === 1 ? "Uma chamada" : "Duas chamadas"} por encontro · ${lessons} aula${lessons === 1 ? "" : "s"} de 50 min</p></div>
      <button type="button" class="secondary" data-action="renomear">Renomear</button></div>
    <div class="summary-grid"><div class="stat"><strong>${absenceValue}</strong><span>${absenceLabel}</span></div>
      <div class="stat ${summary.excesso ? "over-limit" : ""}"><strong>${summary.excesso || summary.restantes}</strong><span>${summary.excesso ? "faltas acima do limite" : "faltas restantes"}</span></div>
      <div class="stat"><strong>${percent}</strong><span>${summary.pendentes ? "frequência pendente" : "frequência"}</span></div></div>
    <div class="frequency-heading"><span>Visão da grade</span><strong>${summary.aulas} aulas de 50 min</strong></div>
    <div class="frequency-track" role="img" aria-label="${attended} aulas sem falta, ${summary.pendentes} pendentes, ${summary.faltas} faltas">
      <span class="used" style="width:${attended / total * 100}%"></span><span class="pending" style="width:${summary.pendentes / total * 100}%"></span><span class="missing" style="width:${summary.faltas / total * 100}%"></span></div>
    <p class="frequency-legend">Verde: sem falta · cinza: pendente · vermelho: falta</p>
  </div>
  <div class="surface"><div class="section-heading"><h2>Encontros</h2><span class="badge">${course.registros.length}</span></div>
    <div class="meeting-list">${course.registros.map((item) => `<div class="meeting">
      <div class="meeting-date">${dateLabel(item.dia)}<small>${item.aulas} aula${item.aulas === 1 ? "" : "s"} de 50 min</small></div>
      <div class="meeting-right"><span class="meeting-state ${item.faltas ? "absent" : item.situacao === "presente" ? "present" : ""}">${statusLabel[item.situacao] || escapeHtml(item.situacao)}${item.faltas ? ` · ${item.faltas} falta${item.faltas === 1 ? "" : "s"}` : ""}</span>
        <button type="button" class="text-button" data-register="${escapeHtml(item.dia)}">${item.situacao === "pendente" ? "Registrar" : "Corrigir"}</button></div></div>`).join("")}</div>
  </div>
  <div class="surface"><div class="section-heading"><h2>Provas e trabalhos</h2><button type="button" class="text-button" data-action="atividade">Adicionar</button></div>
    ${activities.length ? `<div class="activity-list">${activities.map(activityItem).join("")}</div>` : '<p class="muted">Nenhuma atividade cadastrada.</p>'}</div>`;
}

function activityItem(activity) {
  return `<div class="activity-item"><span class="activity-date"><strong>${activity.dia.split("-")[2]}</strong><small>${shortMonth(activity.dia)}<br>${activity.dia.split("-")[0]}</small></span>
    <span class="activity-info"><strong>${escapeHtml(activity.titulo)}</strong><small>${escapeHtml(activity.tipo)} · ${escapeHtml(activity.nome_disciplina)}</small></span></div>`;
}

function renderAgenda() {
  const agenda = ui.state.atividades;
  const hasCourses = ui.state.disciplinas.length > 0;
  $("#agenda-list").innerHTML = agenda.length ? agenda.map(activityItem).join("") : `
    <div class="empty"><span class="empty-icon">▣</span><strong>Agenda vazia</strong>
      <p>${hasCourses ? "Adicione uma prova ou um trabalho." : "Crie uma disciplina para registrar provas e trabalhos."}</p></div>`;
  const button = $("#view-agenda .page-heading .primary");
  button.dataset.action = hasCourses ? "atividade" : "criar";
  button.textContent = hasCourses ? "Adicionar atividade" : "Criar disciplina";
}

function openDialog(id) {
  const dialog = $(`#${id}`);
  dialog.querySelector("form").reset();
  const error = $("[data-error]", dialog);
  error.hidden = true;
  if (id === "course-dialog") { ui.dates = []; renderDates(); syncCourseRules(); }
  if (id === "activity-dialog") {
    if (!ui.state.disciplinas.length) { notice("Crie uma disciplina antes de adicionar atividades.", true); return; }
    $("#activity-course").value = ui.selected || ui.state.disciplinas[0].codigo;
  }
  if (id === "rename-dialog") {
    const course = ui.state.disciplinas.find((item) => item.codigo === ui.selected);
    if (!course) return;
    $("#rename-context").textContent = course.nome;
    $('#rename-form [name="nome"]').value = course.nome;
    $('#rename-form button[type="submit"]').disabled = true;
  }
  dialog.showModal();
  $("input:not([type=hidden]),select", dialog)?.focus();
}

function renderDates() {
  $("#date-list").innerHTML = ui.dates.sort().map((iso) => `
    <span class="date-chip">${dateLabel(iso)}<button type="button" data-remove-date="${iso}" aria-label="Remover ${dateLabel(iso)}">×</button></span>`).join("");
}

function formError(form, message) {
  const element = $("[data-error]", form);
  element.textContent = message;
  element.hidden = false;
}

async function runTests(button) {
  const result = $("#test-result");
  const summary = $("#test-summary");
  result.hidden = false;
  summary.textContent = "Executando testes…";
  $("#test-details").textContent = "";
  button.disabled = true;
  try {
    const response = await fetch("/api/testes", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const body = await response.json();
    if (!response.ok) throw Error(body.erro || "Não foi possível executar os testes.");
    summary.textContent = body.ok
      ? `${body.quantidade} testes aprovados.` : "Alguns testes falharam. Veja os detalhes.";
    $("#test-details").textContent = body.detalhes;
  } catch (error) {
    summary.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function submit(form, route, payload, success) {
  const button = $('button[type="submit"]', form);
  button.disabled = true;
  try {
    await send(route, payload);
    form.closest("dialog").close();
    notice(success);
    return true;
  } catch (error) {
    formError(form, error.message);
    return false;
  } finally {
    button.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) { switchView(nav.dataset.view); return; }
  const courseButton = event.target.closest("[data-course]");
  if (courseButton) { selectCourse(courseButton.dataset.course); return; }
  const removeDate = event.target.closest("[data-remove-date]");
  if (removeDate) { ui.dates = ui.dates.filter((date) => date !== removeDate.dataset.removeDate); renderDates(); return; }
  if (event.target.closest("[data-close]")) { event.target.closest("dialog").close(); return; }
  const register = event.target.closest("[data-register]");
  if (register) {
    const course = ui.state.disciplinas.find((item) => item.codigo === ui.selected);
    const record = course.registros.find((item) => item.dia === register.dataset.register);
    const correcting = record.situacao !== "pendente";
    const options = ["presente", "ausente", "atrasado", "saiu mais cedo", "cancelada", "sem chamada"];
    const box = document.createElement("dialog");
    box.className = "modal small-modal";
    box.innerHTML = `<form class="form-card"><div class="modal-header"><div><p class="eyebrow">FREQUÊNCIA</p><h2>${correcting ? "Corrigir registro" : "Registrar presença"}</h2></div><button type="button" class="icon-button" data-close aria-label="Fechar">×</button></div>
      <p class="modal-context">${escapeHtml(course.nome)} · ${dateLabel(record.dia)}</p><label>Situação
      <select name="situacao">${options.map((value) => `<option value="${value}" ${value === record.situacao ? "selected" : ""}>${statusLabel[value]}</option>`).join("")}</select></label>
      <p class="field-error" data-error hidden></p><div class="form-actions"><button type="button" class="quiet-button" data-close>Cancelar</button><button type="submit" class="primary" ${correcting ? "disabled" : ""}>Salvar registro</button></div></form>`;
    document.body.append(box);
    box.addEventListener("close", () => box.remove(), { once: true });
    if (correcting) {
      $('[name="situacao"]', box).addEventListener("change", (changeEvent) => {
        $('button[type="submit"]', box).disabled = changeEvent.target.value === record.situacao;
      });
    }
    $("form", box).addEventListener("submit", (submitEvent) => {
      submitEvent.preventDefault();
      submit($("form", box), "/api/registros", {
        codigo: course.codigo, dia: record.dia,
        situacao: $('[name="situacao"]', box).value, corrigir: correcting,
        versao: record.versao,
      }, correcting ? "Registro corrigido." : "Presença registrada.");
    });
    box.showModal();
    return;
  }
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "retry-load") { load(); return; }
  if (action === "exemplo") {
    const button = event.target.closest("[data-action]");
    button.disabled = true;
    send("/api/exemplo", {}).then(() => notice("Dados de exemplo adicionados."))
      .catch((error) => { button.disabled = false; notice(error.message, true); });
    return;
  }
  if (action === "testes") { runTests(event.target.closest("[data-action]")); return; }
  if (action) openDialog({ criar: "course-dialog", atividade: "activity-dialog", renomear: "rename-dialog", reset: "reset-dialog" }[action]);
});

function selectCourse(code) {
  ui.selected = code;
  sessionStorage.setItem("demo.selectedCourse", code);
  render();
}

$("#mobile-course-select").addEventListener("change", (event) => selectCourse(event.target.value));

$('#rename-form [name="nome"]').addEventListener("input", (event) => {
  const course = ui.state.disciplinas.find((item) => item.codigo === ui.selected);
  $('#rename-form button[type="submit"]').disabled = event.target.value.trim() === course?.nome;
  $('#rename-form [data-error]').hidden = true;
});


function syncCourseRules() {
  const form = $("#course-form");
  const calls = $('[name="chamadas"]', form);
  const lessons = $('[name="aulas"]', form);
  calls.querySelector('option[value="2"]').disabled = lessons.value === "1";
  lessons.querySelector('option[value="1"]').disabled = calls.value === "2";
  $("#course-rule-hint").hidden = lessons.value !== "1";
}

$('[name="chamadas"]', $("#course-form")).addEventListener("change", syncCourseRules);
$('[name="aulas"]', $("#course-form")).addEventListener("change", syncCourseRules);

$("#add-date").addEventListener("click", () => {
  const input = $("#course-date");
  if (!input.value) { input.reportValidity(); notice("Escolha uma data primeiro.", true); return; }
  if (ui.dates.includes(input.value)) { notice("Essa data já está na lista.", true); return; }
  ui.dates.push(input.value);
  input.value = "";
  renderDates();
});

$("#course-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const dates = [...ui.dates];
  const typedDate = $("#course-date").value;
  if (typedDate && dates.includes(typedDate)) {
    formError(form, "Essa data já está na lista.");
    return;
  }
  if (typedDate) dates.push(typedDate);
  if (!dates.length) { formError(form, "Escolha ao menos uma data de encontro."); return; }
  const data = Object.fromEntries(new FormData(form));
  const newCode = data.codigo.trim().toUpperCase();
  submit(form, "/api/disciplinas", {
    codigo: data.codigo, nome: data.nome, chamadas: Number(data.chamadas),
    aulas: Number(data.aulas), datas: dates,
  }, "Disciplina criada.").then((saved) => {
    if (saved) {
      ui.selected = newCode;
      sessionStorage.setItem("demo.selectedCourse", newCode);
      render();
      switchView("disciplinas");
    }
  });
});
$("#activity-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, "/api/atividades", Object.fromEntries(new FormData(form)), "Atividade adicionada.");
});
$("#rename-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, "/api/renomear", { codigo: ui.selected, nome: new FormData(form).get("nome") }, "Nome atualizado.");
});
$("#reset-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, "/api/reset", Object.fromEntries(new FormData(form)), "Dados da demo apagados.").then((saved) => {
    if (saved) switchView("disciplinas");
  });
});
window.addEventListener("hashchange", () => switchView(location.hash.slice(1), false));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if ($("dialog[open]")) ui.refreshAfterDialog = true;
  else load();
});
document.addEventListener("close", () => {
  if (ui.refreshAfterDialog && !$("dialog[open]")) {
    ui.refreshAfterDialog = false;
    load();
  }
}, true);
load().then(() => switchView(location.hash.slice(1), false));
