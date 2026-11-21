// A interface apenas envia ações e apresenta resultados. As regras e cálculos
// de frequência pertencem às classes Python, compartilhadas com o terminal.
const ui = {
  state: { disciplinas: [], atividades: [] },
  selected: sessionStorage.getItem("demo.selectedCourse"),
  view: "disciplinas",
  dates: [],
  reschedule: null,
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

async function load() {
  try {
    const response = await fetch("/api/estado", { cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw Error(body.erro || "Não foi possível carregar os dados.");
    ui.state = body;
    if (!body.disciplinas.some((course) => course.codigo === ui.selected)) {
      ui.selected = body.disciplinas[0]?.codigo || null;
    }
    if (ui.selected) sessionStorage.setItem("demo.selectedCourse", ui.selected);
    else sessionStorage.removeItem("demo.selectedCourse");
    render();
  } catch (error) {
    notice(error.message, true);
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
  ui.state = body;
  if (!body.disciplinas.some((course) => course.codigo === ui.selected)) {
    ui.selected = body.disciplinas[0]?.codigo || null;
  }
  render();
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
  $(".course-layout").classList.toggle("no-courses", courses.length === 0);
  $(".course-sidebar").classList.toggle("single-course", courses.length <= 1);
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
    <button type="button" class="primary" data-action="criar">Criar disciplina</button></div>`;
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
      <div class="meeting-date">${dateLabel(item.dia)}<small>${item.aulas} aula${item.aulas === 1 ? "" : "s"} de 50 min</small><button type="button" class="text-button date-edit" data-reschedule="${escapeHtml(item.dia)}">Corrigir data</button></div>
      <div class="meeting-right"><span class="meeting-state ${item.faltas ? "absent" : item.situacao === "presente" ? "present" : ""}">${statusLabel[item.situacao] || escapeHtml(item.situacao)}${item.faltas ? ` · ${item.faltas} falta${item.faltas === 1 ? "" : "s"}` : ""}</span>
        <button type="button" class="text-button" data-register="${escapeHtml(item.dia)}">${item.situacao === "pendente" ? "Registrar" : "Corrigir"}</button></div></div>`).join("")}</div>
  </div>
  <div class="surface"><div class="section-heading"><h2>Provas e trabalhos</h2><button type="button" class="text-button" data-action="atividade">Adicionar</button></div>
    ${activities.length ? `<div class="activity-list">${activities.map(activityItem).join("")}</div>` : '<p class="muted">Nenhuma atividade cadastrada.</p>'}</div>`;
}

function activityItem(activity) {
  return `<div class="activity-item"><span class="activity-date"><strong>${activity.dia.split("-")[2]}</strong><small>${shortMonth(activity.dia)}</small></span>
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
  }
  if (id === "reschedule-dialog") {
    const course = ui.state.disciplinas.find((item) => item.codigo === ui.selected);
    if (!course || !ui.reschedule) return;
    $("#reschedule-context").textContent = `${course.nome} · ${dateLabel(ui.reschedule)}`;
    $('#reschedule-form [name="novo_dia"]').value = ui.reschedule;
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
  if (courseButton) { ui.selected = courseButton.dataset.course; sessionStorage.setItem("demo.selectedCourse", ui.selected); render(); return; }
  const removeDate = event.target.closest("[data-remove-date]");
  if (removeDate) { ui.dates = ui.dates.filter((date) => date !== removeDate.dataset.removeDate); renderDates(); return; }
  if (event.target.closest("[data-close]")) { event.target.closest("dialog").close(); return; }
  const reschedule = event.target.closest("[data-reschedule]");
  if (reschedule) { ui.reschedule = reschedule.dataset.reschedule; openDialog("reschedule-dialog"); return; }
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
      <p class="field-error" data-error hidden></p><div class="form-actions"><button type="button" class="quiet-button" data-close>Cancelar</button><button type="submit" class="primary">Salvar registro</button></div></form>`;
    document.body.append(box);
    box.addEventListener("close", () => box.remove(), { once: true });
    $("form", box).addEventListener("submit", (submitEvent) => {
      submitEvent.preventDefault();
      submit($("form", box), "/api/registros", {
        codigo: course.codigo, dia: record.dia,
        situacao: $('[name="situacao"]', box).value, corrigir: correcting,
      }, correcting ? "Registro corrigido." : "Presença registrada.");
    });
    box.showModal();
    return;
  }
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action) openDialog({ criar: "course-dialog", atividade: "activity-dialog", renomear: "rename-dialog", reset: "reset-dialog" }[action]);
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
  if (typedDate && !dates.includes(typedDate)) dates.push(typedDate);
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
$("#reschedule-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, "/api/remarcar", {
    codigo: ui.selected,
    dia_anterior: ui.reschedule,
    novo_dia: new FormData(form).get("novo_dia"),
  }, "Data corrigida.");
});
$("#reset-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  submit(form, "/api/reset", Object.fromEntries(new FormData(form)), "Dados da demo apagados.").then((saved) => {
    if (saved) { sessionStorage.removeItem("demo.selectedCourse"); switchView("disciplinas"); }
  });
});
window.addEventListener("hashchange", () => switchView(location.hash.slice(1), false));
load().then(() => switchView(location.hash.slice(1), false));
