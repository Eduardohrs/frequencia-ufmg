const screens = [...document.querySelectorAll('[data-screen]')];
const routeButtons = [...document.querySelectorAll('[data-route]')];
const app = document.querySelector('#app');
const appShell = document.querySelector('.app-shell');
const sheet = document.querySelector('.sheet');
const scrim = document.querySelector('.scrim');
const toast = document.querySelector('.toast');
let lastFocus = null;
let selectedStatus = 'Presente';

function showScreen(name, { updateUrl = true } = {}) {
  if (!screens.some((screen) => screen.dataset.screen === name)) name = 'home';
  screens.forEach((screen) => screen.classList.toggle('active', screen.dataset.screen === name));
  routeButtons.forEach((button) => {
    const active = button.dataset.route === name || (name === 'course' && button.dataset.route === 'home') || (name === 'materials' && button.dataset.route === 'home');
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  if (updateUrl) history.replaceState(null, '', `?screen=${name}`);
  app.focus({ preventScroll: true });
}

routeButtons.forEach((button) => button.addEventListener('click', () => showScreen(button.dataset.route)));
document.querySelectorAll('[data-open-course]').forEach((button) => button.addEventListener('click', () => showScreen('course')));
document.querySelectorAll('[data-show-materials]').forEach((button) => button.addEventListener('click', () => showScreen('materials')));

function openSheet(trigger) {
  lastFocus = trigger;
  appShell.inert = true;
  sheet.hidden = false;
  scrim.hidden = false;
  requestAnimationFrame(() => sheet.querySelector('[role="radio"]').focus());
}
function closeSheet() {
  sheet.hidden = true;
  scrim.hidden = true;
  appShell.inert = false;
  lastFocus?.focus();
}
document.querySelector('[data-open-attendance]').addEventListener('click', (event) => openSheet(event.currentTarget));
document.querySelector('.close-sheet').addEventListener('click', closeSheet);
scrim.addEventListener('click', closeSheet);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !sheet.hidden) closeSheet();
  if (event.key !== 'Tab' || sheet.hidden) return;
  const focusable = [...sheet.querySelectorAll('button:not([disabled])')];
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

document.querySelectorAll('.attendance-options button').forEach((button) => button.addEventListener('click', () => {
  selectedStatus = button.dataset.status;
  document.querySelectorAll('.attendance-options button').forEach((option) => option.setAttribute('aria-checked', String(option === button)));
}));

document.querySelector('.save-attendance').addEventListener('click', () => {
  closeSheet();
  document.querySelector('.primary-action').hidden = true;
  toast.querySelector('span').textContent = `Frequência salva como ${selectedStatus.toLowerCase()}.`;
  toast.hidden = false;
  setTimeout(() => { toast.hidden = true; }, 5000);
});
toast.querySelector('button').addEventListener('click', () => {
  document.querySelector('.primary-action').hidden = false;
  toast.hidden = true;
});

document.querySelectorAll('[data-download]').forEach((button) => button.addEventListener('click', () => {
  if (button.disabled) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = 'Preparando…';
  setTimeout(() => { button.textContent = 'Baixando 42%'; }, 450);
  setTimeout(() => { button.textContent = 'Offline ✓'; button.classList.add('saved'); }, 1250);
  button.setAttribute('aria-label', `${original} ${button.dataset.download}`);
}));

showScreen(new URLSearchParams(location.search).get('screen') || 'home', { updateUrl: false });
