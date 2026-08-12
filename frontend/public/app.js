const API = {
  me: '/v1/auth/me',
  summary: '/v1/summary',
  incidents: '/v1/incidents',
  alerts: '/v1/alerts',
  events: '/v1/events',
  decisions: '/v1/decisions',
  systems: '/v1/contours',
  identities: '/v1/identities',
  health: '/health',
};

const NAV_ITEMS = [
  { id: 'overview', label: 'Сводка', group: 'УПРАВЛЕНИЕ' },
  { id: 'users', label: 'Пользователи' },
  { id: 'matrix', label: 'Матрица ответственности' },
  { id: 'systems', label: 'Системы' },
  { id: 'routing', label: 'Маршрутизация' },
  { id: 'roles', label: 'Роли и права доступа' },
  { id: 'sla', label: 'Политики SLA' },
  { id: 'integrations', label: 'Интеграции' },
  { id: 'audit', label: 'Аудит' },
  { id: 'incidents', label: 'Инциденты', group: 'МОНИТОРИНГ' },
  { id: 'alerts', label: 'Алерты' },
  { id: 'events', label: 'События' },
  { id: 'decisions', label: 'Решения корреляции' },
];

const DETAIL_VIEWS = ['profile', 'role-editor'];

const DEMO_USERS = [
  ['Алексей Смирнов', 'Эксплуатация / BRD-3', 'Сетевая служба, BRD-3', 'Инженер L2', 'Сетевая инфраструктура', '2 мин'],
  ['Иван Петров', 'Механическая служба', 'Старшие механики', 'Старший инженер', 'АСУ ТП', '8 мин'],
  ['Мария Соколова', 'NOC', 'NOC L2', 'Руководитель смены', 'Все критические системы', '12 мин'],
  ['Олег Кузнецов', 'Инфраструктура', 'Инфраструктура Windows', 'Инженер L2', 'Инфраструктура Windows', '1 ч'],
  ['Анна Морозова', 'Эксплуатация баз данных', 'Администраторы БД L2', 'Инженер L2', 'Платформа баз данных', '3 ч'],
  ['Сергей Волков', 'Безопасность', 'Аудит безопасности', 'Аудитор', 'Все системы', 'вчера'],
];

const state = {
  identity: null,
  health: null,
  currentView: location.hash.slice(1) || 'overview',
  query: '',
  theme: localStorage.getItem('spokukha-theme') || 'light',
  refreshTimer: null,
  requestController: null,
};

const content = document.getElementById('content');
const nav = document.getElementById('main-nav');
const search = document.getElementById('global-search');

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatNumber(value) {
  return new Intl.NumberFormat('ru-RU').format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
}

function shortId(value) {
  return value ? String(value).slice(0, 8) : '—';
}

function badge(value, label = value) {
  const variant = String(value || 'neutral').toLowerCase().replaceAll('_', '-');
  return `<span class="badge ${escapeHtml(variant)}">${escapeHtml(label || '—')}</span>`;
}

function roleLabel(role) {
  return { viewer: 'Наблюдатель', engineer: 'Инженер', admin: 'Администратор' }[role] || role;
}

function hasRole(...roles) {
  return Boolean(state.identity?.roles?.some((role) => roles.includes(role)));
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  if (response.status === 401) throw Object.assign(new Error('Требуется вход'), { status: 401 });
  if (response.status === 403) throw Object.assign(new Error('Недостаточно прав'), { status: 403 });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* response is not JSON */ }
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return response.json();
}

function page(title, subtitle, body) {
  return `<section class="page"><header class="page-head"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></header>${body}</section>`;
}

function designBanner(message = 'Экран собран по макету Figma. Настройки показаны в демонстрационном режиме до подключения административного API.') {
  return `<div class="mode-banner"><strong>Демонстрационные настройки</strong><span>${escapeHtml(message)}</span></div>`;
}

function viewTabs(items, active) {
  return `<div class="tabs">${items.map(([id, label]) => `<button type="button" class="tab ${id === active ? 'active' : ''}" data-view="${id}">${escapeHtml(label)}</button>`).join('')}</div>`;
}

function protectedButton(label, secondary = false) {
  return `<button class="button ${secondary ? 'secondary' : ''}" type="button" data-protected>${escapeHtml(label)}</button>`;
}

function loading() {
  content.innerHTML = '<div class="loading-page"><span class="spinner"></span><p>Загрузка данных…</p></div>';
}

function renderLogin() {
  const authAction = state.health?.auth === 'configured'
    ? '<a class="button" href="/v1/auth/login">Войти через TrueConf</a>'
    : '<button class="button" type="button" disabled>OAuth не настроен</button>';
  content.innerHTML = `<section class="page card login-state">
    <img class="login-logo" src="/assets/spokukha-logo.png" alt="">
    <h1>Войдите в платформу</h1>
    <p>Для просмотра живых событий, алертов и инцидентов нужна сессия TrueConf. Системное состояние доступно без входа.</p>
    <div>${authAction} <button class="button secondary" data-view="systems">Состояние систем</button></div>
  </section>`;
}

function renderError(error) {
  if (error.status === 401) return renderLogin();
  content.innerHTML = `<section class="page card error-state"><h2>Не удалось загрузить данные</h2><p>${escapeHtml(error.message)}</p><button class="button secondary" id="retry">Повторить</button></section>`;
  document.getElementById('retry').addEventListener('click', () => renderCurrentView());
}

function toast(message, type = '') {
  const item = document.createElement('div');
  item.className = `toast ${type}`;
  item.textContent = message;
  document.getElementById('toast-region').appendChild(item);
  setTimeout(() => item.remove(), 3600);
}

function renderNav() {
  const items = NAV_ITEMS;
  if (!items.some((item) => item.id === state.currentView) && !DETAIL_VIEWS.includes(state.currentView)) state.currentView = 'overview';
  const activeView = state.currentView === 'profile' ? 'users' : state.currentView === 'role-editor' ? 'roles' : state.currentView;
  nav.innerHTML = items.map((item) => `${item.group ? `<div class="nav-section">${escapeHtml(item.group)}</div>` : ''}<button class="nav-button ${item.id === activeView ? 'active' : ''}" data-view="${item.id}" type="button">${escapeHtml(item.label)}</button>`).join('');
  nav.querySelectorAll('.nav-button').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.view)));
  document.getElementById('nav-eyebrow').textContent = 'INCIDENT INTELLIGENCE';
}

function navigate(view) {
  state.currentView = view;
  history.replaceState(null, '', `#${view}`);
  state.query = '';
  search.value = '';
  document.getElementById('sidebar').classList.remove('open');
  renderNav();
  renderCurrentView();
}

async function renderOverview() {
  const [health, systems] = await Promise.all([api(API.health), api(API.systems)]);
  let live = true;
  let summary;
  let incidents = [];
  let alerts;
  try {
    [summary, alerts] = await Promise.all([api(API.summary), api(API.alerts)]);
  } catch (error) {
    if (![401, 403].includes(error.status)) throw error;
    live = false;
  }
  if (live) {
    // Kept out of the Promise.all above so an incident-projection failure
    // degrades to an empty "Требуют внимания" card rather than turning the
    // whole landing page into an error screen. 501 is still tolerated: an
    // older platform build behind this frontend answers that way.
    try {
      incidents = await api(API.incidents);
    } catch (error) {
      if (![401, 403, 501].includes(error.status)) throw error;
    }
  }
  if (!live) {
    summary = {
      window_limit: 1000,
      events_in_window: 18429,
      alerts_in_window: 127,
      open_incidents: 23,
      incidents_in_window: 31,
      alerts_by_severity: { critical: 7, high: 18, average: 43, warning: 36, info: 23 },
      decisions_by_type: { dedup: 72, suppress: 34 },
    };
    incidents = [
      { title: 'Недоступен контроллер буровой BRD-3', service: 'АСУ ТП', updated_at: new Date().toISOString(), alert_count: 8, severity: 'critical', status: 'open' },
      { title: 'Высокая задержка межсетевого шлюза', service: 'Сетевая инфраструктура', updated_at: new Date(Date.now() - 780000).toISOString(), alert_count: 4, severity: 'high', status: 'open' },
      { title: 'Заполнение tablespace APP_DATA', service: 'Платформа баз данных', updated_at: new Date(Date.now() - 2100000).toISOString(), alert_count: 3, severity: 'average', status: 'open' },
    ];
    alerts = [];
  }
  const criticalAlerts = summary.alerts_by_severity?.critical || 0;
  const correlated = (summary.decisions_by_type?.dedup || 0) + (summary.decisions_by_type?.suppress || 0);
  const correlationRate = summary.alerts_in_window ? Math.round((correlated / summary.alerts_in_window) * 100) : 0;
  const openIncidents = incidents.filter((item) => item.status === 'open');
  const attention = incidents.filter((item) => item.status !== 'resolved').slice(0, 5);
  const bars = Object.entries(summary.alerts_by_severity || {});
  const maxBar = Math.max(1, ...bars.map(([, value]) => value));

  content.innerHTML = page('Обзор эксплуатации', `Живое окно мониторинга · до ${formatNumber(summary.window_limit)} записей`, `
    ${live ? '' : designBanner('Операционные показатели показаны как макет Figma: TrueConf OAuth пока не настроен. Состояние платформы загружается с backend в реальном времени.')}
    <div class="kpi-grid">
      ${kpi('События', summary.events_in_window, 'В текущем окне')}
      ${kpi('Алерты', summary.alerts_in_window, `${criticalAlerts} критических`, criticalAlerts ? 'critical' : '')}
      ${kpi('Открытые инциденты', summary.open_incidents ?? openIncidents.length, `${summary.incidents_in_window ?? incidents.length} всего`, openIncidents.some((item) => item.severity === 'critical') ? 'critical' : '')}
      ${kpi('Корреляция', `${correlationRate}%`, `${correlated} объединено`, 'success')}
      ${kpi('Состояние платформы', health.status === 'ok' ? 'Исправно' : 'Ошибка', `Kafka: ${health.kafka}`, health.status === 'ok' ? 'success' : 'critical')}
    </div>
    <div class="overview-grid">
      <article class="card"><h2>Алерты по критичности</h2>${bars.length ? `<div class="bar-chart">${bars.map(([label, value]) => `<div class="bar-column"><span class="bar-value">${formatNumber(value)}</span><span class="bar" style="height:${Math.max(4, Math.round(value / maxBar * 88))}px"></span><span>${escapeHtml(label)}</span></div>`).join('')}</div>` : emptyInline('Пока нет алертов в живом окне.')}</article>
      <article class="card"><h2>Состояние платформы</h2><ul class="health-list">${healthRows(health, systems)}</ul></article>
      <article class="card full"><h2>Требуют внимания</h2>${attention.length ? `<ul class="attention-list">${attention.map((item) => `<li class="attention-row"><div class="attention-copy"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(incidentScope(item))} · ${formatDate(item.updated_at)} · ${item.alert_count} алерт(а)${item.status === 'acknowledged' ? ` · принят: ${escapeHtml(item.acknowledged_by_label || item.acknowledged_by)}` : ''}</span></div>${badge(item.severity)}</li>`).join('')}</ul>` : emptyInline('Открытых инцидентов сейчас нет.')}</article>
      <article class="card full"><h2>Последние алерты</h2>${alerts.length ? compactAlerts(alerts.slice(0, 5)) : emptyInline('Алерты появятся после поступления данных мониторинга.')}</article>
    </div>
    <div class="page-actions"><span class="refresh-meta">Обновлено ${new Date().toLocaleTimeString('ru-RU')}</span><button class="button secondary" id="refresh-view">Обновить</button></div>
  `);
  document.getElementById('refresh-view').addEventListener('click', renderCurrentView);
}

function kpi(label, value, meta, tone = '') {
  return `<article class="kpi-card"><div class="kpi-label">${escapeHtml(label)}</div><div class="kpi-value">${typeof value === 'number' ? formatNumber(value) : escapeHtml(value)}</div><div class="kpi-meta ${tone}">${escapeHtml(meta)}</div></article>`;
}

function healthRows(health, contours) {
  const rows = [
    ['API', health.status],
    ['Kafka', health.kafka],
    ['База идентификаций', health.identity_db],
    ['Проекция алертов', contours.alerts],
    ['Маршрутизация', contours.routing],
  ];
  return rows.map(([label, value]) => {
    const healthy = /ok|connected|active|wired/i.test(String(value));
    return `<li class="health-row"><span>${escapeHtml(label)}</span>${badge(healthy ? 'healthy' : 'warning', healthy ? 'Исправно' : String(value))}</li>`;
  }).join('');
}

function emptyInline(message) {
  return `<p class="refresh-meta">${escapeHtml(message)}</p>`;
}

function compactAlerts(items) {
  return `<div class="table-scroll"><table><thead><tr><th>Время</th><th>Критичность</th><th>Правило</th><th>Источник</th><th>Значение</th></tr></thead><tbody>${items.map((message) => {
    const item = message.data || {};
    return `<tr><td>${formatDate(message.occurred_at)}</td><td>${badge(item.severity)}</td><td class="cell-title">${escapeHtml(item.rule)}</td><td>${escapeHtml(item.source)}</td><td>${escapeHtml(item.value)} / ${escapeHtml(item.threshold)}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

/** Service label, falling back to the correlation key it was grouped on.
 *  An alert without a `service` label still forms an incident — keyed on
 *  (source, metric) — and showing "null" for it would be worse than showing
 *  the key the correlator actually used. */
function incidentScope(item) {
  return item.service || item.correlation_key || '—';
}

async function renderIncidents() {
  const items = await api(API.incidents);
  renderDataTable({
    title: 'Инциденты',
    subtitle: 'Сгруппированные алерты, требующие реакции оператора',
    cardTitle: `${items.length} инцидентов в живом окне`,
    filters: [{ key: 'status', label: 'Статус', values: ['', 'open', 'acknowledged'] }, { key: 'severity', label: 'Критичность', values: ['', 'critical', 'high', 'average', 'warning', 'info'] }],
    items,
    searchFields: (item) => [item.title, item.service, item.incident_id, item.correlation_key, item.page_reason],
    columns: ['Инцидент', 'Статус', 'Критичность', 'Система', 'Алерты', 'Уведомлений', 'Обновлён', 'Действие'],
    row: (item) => [
      // The reason line is the point of the screen: it is the correlator's own
      // explanation of why this incident exists, quoted rather than restated.
      `<span class="cell-title">${escapeHtml(item.title)}</span><span class="cell-subtitle mono">INC-${shortId(item.incident_id)}</span>${item.page_reason ? `<span class="cell-subtitle">${escapeHtml(item.page_reason)}</span>` : ''}`,
      item.status === 'acknowledged'
        ? `${badge('acknowledged', 'Принят')}<span class="cell-subtitle">${escapeHtml(item.acknowledged_by_label || item.acknowledged_by || '')}</span>`
        : badge(item.status, { open: 'Открыт' }[item.status] || item.status),
      badge(item.severity), escapeHtml(incidentScope(item)), formatNumber(item.alert_count), formatNumber(item.notification_count), formatDate(item.updated_at),
      item.status === 'open' && hasRole('engineer', 'admin') ? `<button class="button small" data-ack="${escapeHtml(item.incident_id)}">Принять</button>` : '—',
    ],
  });
  content.querySelectorAll('[data-ack]').forEach((button) => button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await api(`${API.incidents}/${button.dataset.ack}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: null }),
      });
      toast('Инцидент принят в работу');
      renderCurrentView();
    } catch (error) { button.disabled = false; toast(error.message, 'error'); }
  }));
}

async function renderAlerts() {
  const items = await api(API.alerts);
  renderDataTable({
    title: 'Алерты', subtitle: 'Нормализованные сигналы от подключённых источников', cardTitle: `${items.length} алертов`,
    filters: [{ key: 'severity', label: 'Критичность', values: ['', 'critical', 'high', 'average', 'warning', 'info', 'resolved'] }, { key: 'source', label: 'Источник', values: ['', ...unique(items.map((x) => x.data?.source))] }],
    items, searchFields: (message) => [message.data?.rule, message.data?.source, message.data?.metric, message.correlation_id],
    filterData: (message) => message.data || {}, columns: ['Время', 'Критичность', 'Правило', 'Источник', 'Метрика', 'Значение', 'Корреляция'],
    row: (message) => { const item = message.data || {}; return [formatDate(message.occurred_at), badge(item.severity), `<span class="cell-title">${escapeHtml(item.rule)}</span>`, escapeHtml(item.source), escapeHtml(item.metric), `${escapeHtml(item.value)} / ${escapeHtml(item.threshold)}`, `<span class="mono">${shortId(message.correlation_id)}</span>`]; },
  });
}

async function renderEvents() {
  const items = await api(API.events);
  renderDataTable({
    title: 'События', subtitle: 'Необработанный поток наблюдений из систем мониторинга', cardTitle: `${items.length} событий`,
    filters: [{ key: 'status', label: 'Статус', values: ['', ...unique(items.map((x) => x.data?.status))] }, { key: 'source', label: 'Источник', values: ['', ...unique(items.map((x) => x.data?.source))] }],
    items, searchFields: (message) => [message.data?.source, message.data?.metric, message.data?.status, message.correlation_id],
    filterData: (message) => message.data || {}, columns: ['Время', 'Статус', 'Источник', 'Метрика', 'Значение', 'Корреляция'],
    row: (message) => { const item = message.data || {}; return [formatDate(message.occurred_at), badge(item.status), `<span class="cell-title">${escapeHtml(item.source)}</span>`, escapeHtml(item.metric || '—'), escapeHtml(item.value ?? '—'), `<span class="mono">${shortId(message.correlation_id)}</span>`]; },
  });
}

async function renderDecisions() {
  const items = await api(API.decisions);
  renderDataTable({
    title: 'Решения корреляции', subtitle: 'Решения движка по объединению, маршрутизации и подавлению шума', cardTitle: `${items.length} решений`,
    filters: [{ key: 'decision_type', label: 'Тип', values: ['', 'route', 'dedup', 'suppress'] }],
    items, searchFields: (item) => [item.decision_type, item.action, item.reason, item.alert_id, item.policy_id], columns: ['Тип', 'Действие', 'Причина', 'Алерт', 'Политика'],
    row: (item) => [badge(item.decision_type), `<span class="cell-title">${escapeHtml(item.action)}</span>`, escapeHtml(item.reason), `<span class="mono">${shortId(item.alert_id)}</span>`, escapeHtml(item.policy_id || '—')],
  });
}

async function renderSystems() {
  const [health, contours] = await Promise.all([api(API.health), api(API.systems)]);
  const rows = flattenContours(contours);
  const catalog = [
    ['АСУ ТП — Буровые установки', 'Промышленная АСУ', 'Zabbix', 'BRD-3', 'Критическая', 'Старшие механики / NOC L2', 'P0'],
    ['Сетевая инфраструктура', 'Инфраструктура', 'Zabbix', 'Все площадки', 'Высокая', 'Сетевая служба / NOC L1', 'P1'],
    ['Платформа баз данных', 'Базы данных', 'Zabbix', 'ЦОД', 'Высокая', 'Администраторы БД L2', 'P1'],
    ['Инфраструктура Windows', 'Инфраструктура', 'Zabbix', 'ЦОД', 'Средняя', 'Инфраструктура Windows', 'P2'],
  ];
  content.innerHTML = page('Системы', 'Каталог систем, критичность, владельцы и источники мониторинга', `
    <div class="kpi-grid">
      ${kpi('API', health.status === 'ok' ? 'Исправно' : 'Ошибка', 'Проверка /health', health.status === 'ok' ? 'success' : 'critical')}
      ${kpi('Kafka', health.kafka, 'Транспорт событий', /connected/i.test(health.kafka) ? 'success' : 'critical')}
      ${kpi('База идентификаций', health.identity_db, 'Пользователи и роли', /connected/i.test(health.identity_db) ? 'success' : 'critical')}
      ${kpi('Контуры', rows.length, 'Заявлено backend')}
    </div>
    ${designBanner('Каталог систем воспроизведен из Figma; верхние показатели и технические компоненты загружаются с backend в реальном времени.')}
    <article class="card table-card"><div class="table-heading"><h2>Каталог систем</h2>${protectedButton('Добавить систему')}</div><div class="table-scroll"><table><thead><tr><th>Система</th><th>Тип</th><th>Источник</th><th>Контур</th><th>Критичность</th><th>Ответственные</th><th>SLA</th><th>Статус</th></tr></thead><tbody>${catalog.map((row) => `<tr data-view="routing" class="clickable-row">${row.map((cell, index) => `<td class="${index === 0 ? 'cell-title' : ''}">${escapeHtml(cell)}</td>`).join('')}<td>${badge('healthy', 'Активна')}</td></tr>`).join('')}</tbody></table></div></article>
    <article class="card table-card"><div class="table-heading"><h2>Компоненты платформы</h2><span class="refresh-meta">Данные backend /v1/contours</span></div><div class="table-scroll"><table><thead><tr><th>Контур</th><th>Компонент</th><th>Состояние</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${escapeHtml(row.area)}</td><td class="cell-title">${escapeHtml(row.component)}</td><td>${badge(row.healthy ? 'healthy' : 'warning', row.value)}</td></tr>`).join('')}</tbody></table></div></article>
  `);
}

function flattenContours(contours) {
  const rows = [];
  Object.entries(contours).forEach(([area, value]) => {
    if (Array.isArray(value)) value.forEach((item) => rows.push({ area, component: item, value: 'Подключён', healthy: true }));
    else if (value && typeof value === 'object') Object.entries(value).forEach(([component, nested]) => rows.push({ area, component, value: String(nested), healthy: /active|connected|wired|pass-through/i.test(String(nested)) }));
    else rows.push({ area, component: area, value: String(value), healthy: /active|connected|wired|pass-through/i.test(String(value)) });
  });
  return rows;
}

async function renderUsers() {
  let items = [];
  let live = true;
  try { items = await api(API.identities); } catch (error) {
    if (![401, 403].includes(error.status)) throw error;
    live = false;
  }
  if (!live) {
    content.innerHTML = page('Пользователи', 'Учетные записи, группы, роли и область ответственности', `
      ${designBanner('Пользователи из макета доступны для просмотра. Редактирование включится после настройки TrueConf OAuth и входа администратора.')}
      <div class="card filters"><label class="field grow"><span>Поиск</span><input class="control" placeholder="Имя, подразделение или группа"></label><label class="field"><span>Статус</span><select class="control"><option>Все</option><option>Активен</option></select></label>${protectedButton('Добавить пользователя')}</div>
      <article class="card table-card"><div class="table-heading"><h2>${DEMO_USERS.length} пользователей</h2><span class="refresh-meta">Макет Figma</span></div><div class="table-scroll"><table><thead><tr><th>Пользователь</th><th>Подразделение</th><th>Группы</th><th>Роль</th><th>Ответственность</th><th>Статус</th><th>Последняя активность</th></tr></thead><tbody>${DEMO_USERS.map((item, index) => `<tr class="clickable-row" ${index === 0 ? 'data-view="profile"' : ''}><td class="cell-title">${escapeHtml(item[0])}</td><td>${escapeHtml(item[1])}</td><td>${escapeHtml(item[2])}</td><td>${escapeHtml(item[3])}</td><td>${escapeHtml(item[4])}</td><td>${badge('healthy', 'Активен')}</td><td>${escapeHtml(item[5])}</td></tr>`).join('')}</tbody></table></div></article>
    `);
    return;
  }
  renderDataTable({
    title: 'Пользователи и группы', subtitle: 'Учётные записи TrueConf, роли и атрибуты синтетического AD', cardTitle: `${items.length} пользователей`,
    filters: [{ key: 'role', label: 'Роль', values: ['', 'viewer', 'engineer', 'admin'] }], items,
    searchFields: (item) => [item.display_label, item.ad_login, item.department, item.team, ...(item.roles || [])],
    predicate: (item, filters) => !filters.role || item.roles?.includes(filters.role),
    columns: ['Имя', 'Подразделение', 'Группа', 'Роли', 'AD login', 'Назначить роль'],
    row: (item) => [
      `<button class="text-link" data-view="profile">${escapeHtml(item.display_label)}</button><span class="cell-subtitle mono">${shortId(item.identity_id)}</span>`, escapeHtml(item.department || '—'), escapeHtml(item.team || '—'), (item.roles || []).map((role) => badge(role, roleLabel(role))).join(' '), escapeHtml(item.ad_login || '—'),
      `<div style="display:flex;gap:6px"><select class="control" data-role-for="${escapeHtml(item.identity_id)}" style="width:140px;height:30px"><option value="viewer">Наблюдатель</option><option value="engineer">Инженер</option><option value="admin">Администратор</option></select><button class="button small secondary" data-save-role="${escapeHtml(item.identity_id)}">Добавить</button></div>`,
    ],
  });
  content.querySelectorAll('[data-save-role]').forEach((button) => button.addEventListener('click', async () => {
    const select = content.querySelector(`[data-role-for="${CSS.escape(button.dataset.saveRole)}"]`);
    button.disabled = true;
    try {
      await api(`${API.identities}/${button.dataset.saveRole}/roles`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role_id: select.value }) });
      toast('Роль добавлена');
      renderCurrentView();
    } catch (error) { button.disabled = false; toast(error.message, 'error'); }
  }));
}

function renderRouting() {
  content.innerHTML = page('АСУ ТП — Буровые установки', 'Маршрутизация уведомлений и правила эскалации', `
    ${designBanner()}
    ${viewTabs([['systems', 'Сводка'], ['routing', 'Получатели'], ['matrix', 'Правила маршрутизации'], ['audit', 'Активность']], 'routing')}
    <div class="split-grid">
      <article class="card"><div class="table-heading compact"><h2>Получатели уведомлений</h2>${protectedButton('Добавить', true)}</div>
        <div class="stack-list">
          <div class="stack-row"><div><strong>Старшие механики</strong><span>Группа · 8 пользователей</span></div>${badge('healthy', 'Основной')}</div>
          <div class="stack-row"><div><strong>NOC L2</strong><span>Группа · 12 пользователей</span></div>${badge('info', 'Эскалация')}</div>
          <div class="stack-row"><div><strong>Мария Соколова</strong><span>Руководитель смены</span></div>${badge('warning', 'P0')}</div>
        </div>
      </article>
      <article class="card"><h2>Правило маршрутизации</h2>
        <div class="form-grid"><label class="field"><span>Критичность</span><select class="control"><option>P0 — Критическая</option></select></label><label class="field"><span>Источник</span><select class="control"><option>Zabbix</option></select></label><label class="field wide"><span>Условие</span><input class="control" value="system = BRD-* AND severity ≥ high"></label><label class="field"><span>Первичный получатель</span><select class="control"><option>Старшие механики</option></select></label><label class="field"><span>Эскалация через</span><input class="control" value="15 минут"></label></div>
        <div class="page-actions"><span class="refresh-meta">Правило приоритета 100</span><div>${protectedButton('Проверить правило', true)} ${protectedButton('Сохранить')}</div></div>
      </article>
    </div>
  `);
}

function renderMatrix() {
  const rows = [
    ['АСУ ТП — Буровые установки', 'Старшие механики', 'NOC L2', 'Мария Соколова'],
    ['Сетевая инфраструктура', 'Сетевая служба', 'NOC L1', 'Алексей Смирнов'],
    ['Платформа баз данных', 'Администраторы БД L2', 'NOC L2', 'Анна Морозова'],
    ['Инфраструктура Windows', 'Инфраструктура Windows', 'NOC L1', 'Олег Кузнецов'],
  ];
  content.innerHTML = page('Матрица ответственности', 'Кто отвечает за системы, сервисы и критические инциденты', `
    ${designBanner()}
    <div class="warning-card"><strong>Проверьте незакрытые области ответственности</strong><span>Для двух некритичных сервисов не назначен резервный получатель.</span></div>
    <article class="card table-card"><div class="table-heading"><h2>Ответственные команды</h2>${protectedButton('Изменить матрицу')}</div><div class="table-scroll"><table><thead><tr><th>Система / сервис</th><th>Основная команда</th><th>Резервная команда</th><th>Владелец</th><th>P0</th><th>P1</th></tr></thead><tbody>${rows.map((row) => `<tr><td class="cell-title">${escapeHtml(row[0])}</td><td>${escapeHtml(row[1])}</td><td>${escapeHtml(row[2])}</td><td>${escapeHtml(row[3])}</td><td>${badge('healthy', 'R')}</td><td>${badge('info', 'A')}</td></tr>`).join('')}</tbody></table></div></article>
    <div class="legend"><span>${badge('healthy', 'R')} Исполнитель</span><span>${badge('info', 'A')} Ответственный</span><span>${badge('warning', 'C')} Консультант</span><span>${badge('neutral', 'I')} Информируемый</span></div>
  `);
}

function renderProfile() {
  content.innerHTML = page('Алексей Смирнов', 'Инженер L2 · Эксплуатация / BRD-3', `
    ${designBanner('Профиль соответствует макету Figma. Данные будут заменены атрибутами TrueConf/AD после настройки OAuth.')}
    ${viewTabs([['profile', 'Профиль'], ['roles', 'Роли'], ['role-editor', 'Разрешения'], ['matrix', 'Ответственность'], ['audit', 'Активность']], 'profile')}
    <div class="split-grid">
      <article class="card"><h2>Учетная запись</h2><dl class="detail-list"><div><dt>Полное имя</dt><dd>Алексей Смирнов</dd></div><div><dt>Логин</dt><dd class="mono">a.smirnov</dd></div><div><dt>Email</dt><dd>alexey.smirnov@example.ru</dd></div><div><dt>Подразделение</dt><dd>Эксплуатация / BRD-3</dd></div><div><dt>Статус</dt><dd>${badge('healthy', 'Активен')}</dd></div></dl></article>
      <article class="card"><h2>Ответственность</h2><div class="stack-list"><div class="stack-row"><div><strong>Сетевая инфраструктура</strong><span>Основной ответственный</span></div>${badge('healthy', 'R')}</div><div class="stack-row"><div><strong>АСУ ТП — Буровые установки</strong><span>Резервный инженер</span></div>${badge('info', 'A')}</div></div></article>
      <article class="card full"><h2>Эффективные права</h2><div class="chip-list"><span class="chip">Просмотр инцидентов</span><span class="chip">Принятие в работу</span><span class="chip">Управление подписками</span><span class="chip">Просмотр систем</span></div><div class="page-actions"><span class="refresh-meta">Роль: Инженер L2 · Группа: Сетевая служба</span>${protectedButton('Редактировать пользователя')}</div></article>
    </div>
  `);
}

function renderRoles() {
  const roles = [
    ['Администратор', 'Полный доступ к конфигурации платформы', '6', '12'],
    ['Руководитель смены', 'Управление инцидентами и эскалациями', '14', '9'],
    ['Инженер L2', 'Работа с назначенными инцидентами', '34', '8'],
    ['Наблюдатель', 'Просмотр доступных объектов', '21', '4'],
    ['Аудитор', 'Чтение конфигурации и журнала аудита', '3', '5'],
  ];
  content.innerHTML = page('Роли и права доступа', 'Каталог ролей и наборов разрешений', `
    ${designBanner()}
    <div class="page-actions"><span class="refresh-meta">${roles.length} системных ролей</span><div>${protectedButton('Дублировать', true)} ${protectedButton('Создать роль')}</div></div>
    <article class="card table-card"><div class="table-scroll"><table><thead><tr><th>Роль</th><th>Описание</th><th>Пользователи</th><th>Разрешения</th><th>Статус</th></tr></thead><tbody>${roles.map((role, index) => `<tr class="clickable-row" data-view="role-editor"><td class="cell-title">${escapeHtml(role[0])}</td><td>${escapeHtml(role[1])}</td><td>${role[2]}</td><td>${role[3]}</td><td>${badge(index < 4 ? 'healthy' : 'info', index < 4 ? 'Активна' : 'Системная')}</td></tr>`).join('')}</tbody></table></div></article>
  `);
}

function renderRoleEditor() {
  const group = (title, rows) => `<section class="permission-group"><h3>${escapeHtml(title)}</h3>${rows.map(([name, enabled]) => `<label class="permission-row"><input type="checkbox" ${enabled ? 'checked' : ''} disabled><span><strong>${escapeHtml(name)}</strong><small>Доступ определяется ролью и областью ответственности</small></span></label>`).join('')}</section>`;
  content.innerHTML = page('Роль: Инженер L2', 'Настройка разрешений и области действия роли', `
    ${designBanner()}
    ${viewTabs([['role-editor', 'Разрешения'], ['users', 'Пользователи'], ['audit', 'История изменений']], 'role-editor')}
    <div class="split-grid wide-left"><article class="card permission-grid">${group('Инциденты', [['Просмотр инцидентов', true], ['Принятие в работу', true], ['Закрытие инцидента', false], ['Изменение приоритета', false]])}${group('Подписки', [['Просмотр подписок', true], ['Управление своими подписками', true], ['Управление подписками команды', false]])}${group('Администрирование', [['Управление пользователями', false], ['Управление интеграциями', false], ['Просмотр аудита', true]])}</article>
      <aside class="card"><h2>Область действия</h2><label class="field"><span>Системы</span><select class="control"><option>По матрице ответственности</option></select></label><label class="field"><span>Критичность</span><select class="control"><option>P0–P3</option></select></label><label class="field"><span>Команды</span><select class="control"><option>Назначенные группы</option></select></label><div class="page-actions">${protectedButton('Отмена', true)} ${protectedButton('Сохранить')}</div></aside></div>
  `);
}

function renderSla() {
  const policies = [['P0 — Критическая', '5 мин', '30 мин', '24×7'], ['P1 — Высокая', '15 мин', '2 ч', '24×7'], ['P2 — Средняя', '1 ч', '8 ч', 'Рабочее время'], ['P3 — Низкая', '4 ч', '24 ч', 'Рабочее время']];
  content.innerHTML = page('Политики SLA', 'Сроки реакции, устранения и эскалации', `
    ${designBanner()}
    <div class="split-grid wide-left"><article class="card table-card"><div class="table-heading"><h2>Политики</h2>${protectedButton('Создать', true)}</div><div class="table-scroll"><table><thead><tr><th>Политика</th><th>Реакция</th><th>Решение</th><th>Календарь</th></tr></thead><tbody>${policies.map((item, index) => `<tr class="${index === 0 ? 'selected-row' : ''}"><td class="cell-title">${item[0]}</td><td>${item[1]}</td><td>${item[2]}</td><td>${item[3]}</td></tr>`).join('')}</tbody></table></div></article>
      <article class="card"><h2>P0 — Критическая</h2><div class="form-grid"><label class="field"><span>Подтверждение</span><input class="control" value="5 минут"></label><label class="field"><span>Устранение</span><input class="control" value="30 минут"></label><label class="field"><span>Календарь</span><select class="control"><option>24×7</option></select></label><label class="field"><span>Пауза SLA</span><select class="control"><option>Только ожидание внешней стороны</option></select></label><label class="field wide"><span>Эскалация</span><input class="control" value="NOC L2 → Руководитель смены → Директор ИТ"></label></div><div class="page-actions">${protectedButton('Дублировать', true)} ${protectedButton('Сохранить')}</div></article></div>
  `);
}

function renderIntegrations() {
  const integrations = [['Zabbix', 'Мониторинг', 'Подключено', 'сейчас'], ['SolarWinds', 'Мониторинг', 'Отключено', '—'], ['TrueConf', 'Идентификация', 'Требует настройки', '—'], ['LDAP / AD', 'Каталог пользователей', 'Демо-контур', '5 мин'], ['CMDB', 'Каталог систем', 'Демо-контур', '12 мин']];
  content.innerHTML = page('Интеграции', 'Источники мониторинга, идентификация и синхронизация справочников', `
    ${designBanner('Статус Zabbix и платформы проверяется backend. Остальные подключения показаны по макету до ввода учетных данных.')}
    <article class="card table-card"><div class="table-heading"><h2>Подключения</h2>${protectedButton('Добавить интеграцию')}</div><div class="table-scroll"><table><thead><tr><th>Интеграция</th><th>Назначение</th><th>Состояние</th><th>Последняя синхронизация</th><th>Действия</th></tr></thead><tbody>${integrations.map((item, index) => `<tr><td class="cell-title">${item[0]}</td><td>${item[1]}</td><td>${badge(index === 0 ? 'healthy' : index === 2 ? 'warning' : 'info', item[2])}</td><td>${item[3]}</td><td>${protectedButton(index === 0 ? 'Обновить' : 'Открыть', true)}</td></tr>`).join('')}</tbody></table></div></article>
    <article class="card integration-detail"><div><h2>Zabbix</h2><p>Основной источник событий и проблем мониторинга.</p></div><dl class="detail-list horizontal"><div><dt>Endpoint</dt><dd class="mono">/api_jsonrpc.php</dd></div><div><dt>Синхронизация</dt><dd>каждые 60 секунд</dd></div><div><dt>Последний результат</dt><dd>${badge('healthy', 'Успешно')}</dd></div></dl></article>
  `);
}

function renderAudit() {
  const rows = [
    ['сегодня, 14:32', 'Мария Соколова', 'Изменила правило маршрутизации', 'АСУ ТП — Буровые установки', 'Успешно'],
    ['сегодня, 13:18', 'Алексей Смирнов', 'Принял инцидент в работу', 'INC-2841', 'Успешно'],
    ['сегодня, 11:46', 'Администратор', 'Назначил роль Инженер L2', 'Олег Кузнецов', 'Успешно'],
    ['вчера, 18:02', 'Система', 'Синхронизация Zabbix', '127 алертов', 'Успешно'],
    ['вчера, 16:41', 'Сергей Волков', 'Экспортировал журнал аудита', 'CSV', 'Успешно'],
  ];
  content.innerHTML = page('Аудит', 'Неизменяемый журнал действий пользователей и системных процессов', `
    ${designBanner()}
    <div class="card filters"><label class="field"><span>Период</span><select class="control"><option>Последние 7 дней</option></select></label><label class="field"><span>Тип действия</span><select class="control"><option>Все действия</option></select></label><label class="field grow"><span>Пользователь или объект</span><input class="control" placeholder="Поиск по журналу"></label>${protectedButton('Экспорт CSV', true)}</div>
    <article class="card table-card"><div class="table-heading"><h2>События аудита</h2><span class="refresh-meta">Хранение: 365 дней</span></div><div class="table-scroll"><table><thead><tr><th>Время</th><th>Инициатор</th><th>Действие</th><th>Объект</th><th>Результат</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell, index) => `<td class="${index === 2 ? 'cell-title' : ''}">${index === 4 ? badge('healthy', cell) : escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></article>
  `);
}

function renderDataTable(config) {
  const filterState = {};
  const renderRows = () => {
    const query = state.query.toLowerCase().trim();
    const items = config.items.filter((item) => {
      const data = config.filterData ? config.filterData(item) : item;
      const baseMatch = !query || config.searchFields(item).some((value) => String(value ?? '').toLowerCase().includes(query));
      const filterMatch = (config.filters || []).every((filter) => !filterState[filter.key] || String(data[filter.key] ?? '').toLowerCase() === filterState[filter.key].toLowerCase());
      return baseMatch && filterMatch && (!config.predicate || config.predicate(item, filterState));
    });
    const tbody = document.getElementById('data-rows');
    const empty = document.getElementById('table-empty');
    tbody.innerHTML = items.map((item) => `<tr>${config.row(item).map((value) => `<td>${value}</td>`).join('')}</tr>`).join('');
    empty.hidden = items.length > 0;
    document.getElementById('result-count').textContent = `${items.length} из ${config.items.length}`;
  };

  const filters = (config.filters || []).map((filter) => `<label class="field"><span>${escapeHtml(filter.label)}</span><select class="control" data-filter="${escapeHtml(filter.key)}">${filter.values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value || 'Все')}</option>`).join('')}</select></label>`).join('');
  content.innerHTML = page(config.title, config.subtitle, `
    ${filters ? `<div class="card filters">${filters}<button class="button secondary" id="clear-filters">Сбросить</button></div>` : ''}
    <article class="card table-card"><div class="table-heading"><h2>${escapeHtml(config.cardTitle)}</h2><span class="refresh-meta" id="result-count"></span></div><div class="table-scroll"><table><thead><tr>${config.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody id="data-rows"></tbody></table><div class="empty-state" id="table-empty" hidden><p>По выбранным условиям ничего не найдено.</p></div></div></article>
  `);
  content.querySelectorAll('[data-filter]').forEach((select) => select.addEventListener('change', () => { filterState[select.dataset.filter] = select.value; renderRows(); }));
  const clear = document.getElementById('clear-filters');
  if (clear) clear.addEventListener('click', () => { content.querySelectorAll('[data-filter]').forEach((select) => { select.value = ''; filterState[select.dataset.filter] = ''; }); renderRows(); });
  renderRows();
  content._rerenderRows = renderRows;
}

function unique(values) {
  return [...new Set(values.filter(Boolean).map(String))].sort();
}

const renderers = {
  overview: renderOverview,
  users: renderUsers,
  profile: renderProfile,
  matrix: renderMatrix,
  systems: renderSystems,
  routing: renderRouting,
  roles: renderRoles,
  'role-editor': renderRoleEditor,
  sla: renderSla,
  integrations: renderIntegrations,
  audit: renderAudit,
  incidents: renderIncidents,
  alerts: renderAlerts,
  events: renderEvents,
  decisions: renderDecisions,
};

async function renderCurrentView(silent = false) {
  clearTimeout(state.refreshTimer);
  content._rerenderRows = null;
  if (!silent) loading();
  try {
    await (renderers[state.currentView] || renderOverview)();
  } catch (error) {
    renderError(error);
  }
  content.querySelectorAll('[data-view]').forEach((element) => element.addEventListener('click', () => navigate(element.dataset.view)));
  content.querySelectorAll('[data-protected]').forEach((button) => button.addEventListener('click', () => {
    toast(state.identity ? 'Функция ожидает административный API' : 'Войдите через TrueConf для изменения настроек', 'error');
  }));
  if (['overview', 'incidents', 'alerts', 'events', 'decisions', 'systems'].includes(state.currentView)) {
    state.refreshTimer = setTimeout(() => renderCurrentView(true), 15000);
  }
}

async function updateIdentity() {
  try {
    state.identity = await api(API.me);
  } catch (error) {
    state.identity = null;
  }
}

async function updateConnection() {
  const dot = document.getElementById('connection-dot');
  const label = document.getElementById('connection-label');
  try {
    const health = await api(API.health);
    state.health = health;
    dot.className = `status-dot ${health.status === 'ok' ? 'ok' : 'error'}`;
    label.textContent = health.status === 'ok' ? 'Платформа доступна' : 'Платформа недоступна';
  } catch (_) {
    state.health = null;
    dot.className = 'status-dot error';
    label.textContent = 'Нет связи с платформой';
  }
}

function updateAccount() {
  const authLink = document.getElementById('auth-link');
  const accountMeta = document.getElementById('account-meta');
  authLink.onclick = null;
  if (state.identity) {
    accountMeta.textContent = (state.identity.roles || []).map(roleLabel).join(' · ') || 'Без роли';
    authLink.textContent = state.identity.display_label || 'Профиль';
    authLink.href = '#logout';
    authLink.onclick = async (event) => {
      event.preventDefault();
      await api('/v1/auth/logout', { method: 'POST' });
      location.reload();
    };
  } else if (state.health?.auth === 'configured') {
    accountMeta.textContent = 'Гостевой режим';
    authLink.textContent = 'Войти';
    authLink.href = '/v1/auth/login';
  } else {
    accountMeta.textContent = 'OAuth не настроен';
    authLink.textContent = 'Вход недоступен';
    authLink.href = '#auth-not-configured';
    authLink.onclick = (event) => {
      event.preventDefault();
      toast('Администратор должен настроить TrueConf OAuth', 'error');
    };
  }
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
  document.querySelector('meta[name="theme-color"]').content = state.theme === 'dark' ? '#0f172a' : '#f8fafc';
  document.getElementById('theme-button').textContent = state.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема';
}

document.getElementById('theme-button').addEventListener('click', () => {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('spokukha-theme', state.theme);
  applyTheme();
});

document.getElementById('menu-button').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
search.addEventListener('input', () => {
  state.query = search.value;
  if (typeof content._rerenderRows === 'function') content._rerenderRows();
});

window.addEventListener('hashchange', () => {
  const view = location.hash.slice(1);
  if (view && view !== state.currentView) navigate(view);
});

async function bootstrap() {
  applyTheme();
  await Promise.all([updateIdentity(), updateConnection()]);
  updateAccount();
  renderNav();
  renderCurrentView();
}

bootstrap();
