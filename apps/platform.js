/* A learning overview built from saved evidence, never simulated achievements. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const text = value => typeof value === 'string' ? value : '';
  const count = value => Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
  const element = (tag, className, value) => { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; };
  const contextUrl = id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(id) ? 'chat.html?conversation=' + encodeURIComponent(id) : 'chat.html';
  const defaults = [
    {id:'everyday', title:'Everyday English', description:'Small talk, планы и обычные ситуации.', symbol:'Hi'},
    {id:'work', title:'Английский для работы', description:'Объяснять свои идеи, обсуждать задачи и писать коллегам.', symbol:'↗'},
    {id:'travel', title:'Поездки и новые места', description:'Договориться, разобраться и почувствовать себя увереннее.', symbol:'↝'},
    {id:'interests', title:'Мои интересы', description:'Обсуждать музыку, игры и другие близкие тебе темы.', symbol:'✳'}
  ];
  function showError(message) { $('page-error').hidden = false; $('page-error-text').textContent = message; }
  function renderPreferences(personalization) {
    const preferences = personalization?.account_preferences || {};
    const dialects = {us:'American English', uk:'British English', international:'International English'};
    const registers = {informal:'Неформально', neutral:'Нейтрально', professional:'Для работы'};
    $('dialect-label').textContent = dialects[preferences.dialect] || 'American English';
    const labels = [registers[preferences.register] || 'Неформально', preferences.explanation_style === 'detailed' ? 'С подробностями' : 'По делу', preferences.grammar_terminology === 'standard' ? 'С терминами' : 'Без лишних терминов'];
    $('preference-tags').replaceChildren(...labels.map(label => element('span', '', label)));
    $('approach-title').textContent = preferences.register === 'professional' ? 'Уверенно в рабочих ситуациях.' : 'Разговорный английский.';
    $('approach-description').textContent = text(preferences.notes) || 'Твои предпочтения действуют во всех занятиях. Для отдельного направления их можно изменить.';
  }
  function renderDirections(personalization) {
    const available = Array.isArray(personalization?.directions) ? personalization.directions : [];
    const ordered = defaults.map(fallback => ({...fallback, ...available.find(item => item.id === fallback.id)}));
    $('direction-list').replaceChildren(...ordered.map(direction => {
      const card = element('a', 'direction-card');
      card.href = 'chat.html?new=1&direction=' + encodeURIComponent(direction.id);
      card.append(element('span', 'direction-symbol', direction.symbol), element('h3', '', text(direction.title)), element('p', '', text(direction.description)));
      const label = element('span', 'direction-link'); label.append(element('span', 'direction-verb', 'Выбрать направление'), element('span', '', '↗')); card.append(label);
      return card;
    }));
  }
  function renderRecent(conversations) {
    const recent = (Array.isArray(conversations) ? conversations : []).filter(item => typeof item?.id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(item.id)).slice(0, 4);
    if (!recent.length) { $('recent-conversations').replaceChildren(element('p', 'empty-copy', 'Здесь появятся твои занятия и сохранённые контексты. Выбери направление выше.')); return; }
    $('recent-conversations').replaceChildren(...recent.map(conversation => {
      const link = element('a', 'recent-item'); link.href = contextUrl(conversation.id);
      const body = element('div'); body.append(element('b', '', text(conversation.context?.title) || text(conversation.title) || 'Занятие английским'));
      const detail = text(conversation.context?.goal) || text(conversation.goal);
      const date = new Date(conversation.updated_at || '');
      body.append(element('small', '', detail || (Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('ru', {day:'numeric',month:'long'}).format(date) : 'Контекст сохранён')));
      link.append(element('span', 'recent-symbol', '◌'), body, element('span', 'recent-arrow', '↗')); return link;
    }));
  }
  const stepLabels = {srs_review:'Повторить знакомые слова',retrieval:'Вспомнить пройденное',practice:'Попробовать в деле',remediation:'Разобрать сложное место',new_material:'Новая тема',cumulative_review:'Закрепить пройденное',reflection:'Подвести итоги',speaking:'Разговорная практика',pronunciation:'Произношение'};
  function renderNext(status, platform) {
    const owner = platform.active_session_owner;
    const next = platform.next_action || {};
    const minutes = status.profile?.daily_minutes;
    $('daily-time').textContent = Number.isFinite(minutes) ? `${minutes} минут на занятие` : 'В твоём темпе';
    if (!status.initialized) {
      $('next-title').textContent = 'Сначала — твой подход'; $('next-description').textContent = 'Выбери удобное время и расскажи, зачем тебе английский. Предпочтения и контексты останутся с тобой.';
      $('next-action').textContent = 'Настроить обучение ↗'; $('next-action').href = 'chat.html?setup=1';
    } else if (owner?.conversation_id) {
      $('next-title').textContent = text(owner.title) || 'Продолжим с места остановки'; $('next-description').textContent = 'План и ответы сохранены. Вернись в своё занятие и продолжи следующий шаг.';
      $('next-action').textContent = 'Продолжить занятие ↗'; $('next-action').href = contextUrl(owner.conversation_id);
    } else if (status.session?.id && ['active','interrupted'].includes(status.session.status)) {
      $('next-title').textContent = 'Продолжим сохранённое занятие'; $('next-description').textContent = 'План уже начат. Открой беседу и подтверди, где его продолжить.';
      $('next-action').textContent = 'Открыть сохранённый план ↗'; $('next-action').href = contextUrl(next.conversation_id);
    } else if (next.kind === 'diagnostic' || ['unassessed','legacy_unverified'].includes(platform.proficiency_status) || !platform.proficiency_status) {
      $('next-title').textContent = 'Найдём твою отправную точку'; $('next-description').textContent = 'Короткая диагностика покажет, с какой сложности начать. Объяснения будут в твоём стиле.';
      $('next-action').textContent = 'Начать диагностику ↗'; $('next-action').href = 'chat.html?new=1&mode=diagnostic';
    } else {
      $('next-title').textContent = 'Немного практики сегодня'; $('next-description').textContent = 'Выбери близкую тему. Преподаватель учтёт прошлые ответы и то, что пора повторить.';
      $('next-action').textContent = text(next.label) || 'Начать занятие ↗'; $('next-action').href = next.conversation_id ? contextUrl(next.conversation_id) : 'chat.html?new=1&direction=everyday';
    }
    const session = status.session || status.plan;
    const steps = session?.plan?.steps || session?.steps;
    $('daily-route').replaceChildren();
    $('daily-route').hidden = !Array.isArray(steps) || !steps.length;
    if (Array.isArray(steps) && steps.length) {
      const completed = new Set(session.completed_steps || []);
      $('daily-route').replaceChildren(...steps.map((step,index) => { const done = completed.has(step.id); const item = element('li', done ? 'done' : ''); item.append(element('span','',done ? '✓' : String(index+1).padStart(2,'0')), element('b','',text(step.title) || text(step.unit_title) || stepLabels[step.type] || 'Практика')); return item; }));
    }
  }
  function render(status) {
    const platform = status.platform_summary || status.platform || {};
    const connected = status.auth?.status === 'chatgpt';
    $('service-status').textContent = connected ? 'Преподаватель подключён' : status.auth?.status === 'unavailable' ? 'Преподаватель недоступен' : 'Вход через ChatGPT';
    $('service-status').className = 'service-status' + (connected ? ' connected' : '');
    if (status.auth?.status === 'unavailable') showError('Не удалось подключить преподавателя. Открой занятие, чтобы проверить подключение.');
    renderPreferences(status.personalization); renderDirections(status.personalization); renderRecent(status.conversations); renderNext(status,platform);
    $('due-count').textContent = count(platform.due_count ?? status.progress?.due_count);
    $('due-description').textContent = 'карточек ждут повторения';
    $('attempt-count').textContent = count(platform.observation_count); $('session-count').textContent = count(platform.completed_sessions);
    $('level-status').textContent = ['unassessed','legacy_unverified'].includes(platform.proficiency_status) || !platform.proficiency_status ? 'Ещё знакомимся' : text(platform.working_level) + ' · рабочий ориентир';
  }
  async function load() {
    $('page-error').hidden = true;
    try { const response = await Tutor.request('/api/web/status', {cache:'no-store'}); render(await response.json()); }
    catch { showError('Не удалось загрузить обучение. Проверь, что локальный сервер работает, и повтори.'); }
  }
  $('reload-page').addEventListener('click', load);
  $('home-backup').addEventListener('click', async () => {
    const button = $('home-backup'); button.disabled = true;
    try { const response = await Tutor.request('/api/web/backup'); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = element('a'); link.href = url; link.download = 'tutor-backup.zip'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    catch { showError('Резервная копия не скачана. Учебные данные остаются на месте; попробуй ещё раз.'); }
    finally { button.disabled = false; }
  });
  $('date-label').textContent = new Intl.DateTimeFormat('ru', {weekday:'long',day:'numeric',month:'long'}).format(new Date());
  window.TutorPlatformReady = Tutor.ready.then(load);
})();
