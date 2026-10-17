/* Honest practice evidence, with separate language domains and no inferred XP. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const count = value => Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
  const node = (tag, className, value) => { const item = document.createElement(tag); item.className = className || ''; if (value !== undefined) item.textContent = value; return item; };
  function render(status) {
    const summary = status.platform_summary || status.platform || {};
    $('service-status').textContent = status.auth?.status === 'chatgpt' ? 'Преподаватель подключён' : status.auth?.status === 'unavailable' ? 'Преподаватель недоступен' : 'Вход через ChatGPT';
    $('service-status').className = 'service-status' + (status.auth?.status === 'chatgpt' ? ' connected' : '');
    if (status.auth?.status === 'unavailable') { $('page-error').hidden = false; $('page-error-text').textContent = 'Не удалось подключить преподавателя. Открой занятие, чтобы проверить подключение.'; }
    $('progress-attempts').textContent = count(summary.observation_count);
    $('progress-sessions').textContent = count(summary.completed_sessions);
    $('progress-due').textContent = count(summary.due_count);
    const unassessed = !summary.proficiency_status || ['unassessed','legacy_unverified'].includes(summary.proficiency_status);
    $('progress-level').textContent = unassessed ? 'Уровень ещё не оценён' : `${summary.working_level || ''} · рабочий ориентир`;
    $('progress-level-description').textContent = unassessed ? 'Начальная отметка в профиле не заменяет диагностику. Разберёмся, что уже получается, на нескольких заданиях.' : 'Этот ориентир относится к учебным материалам. Навыки уточняются по ответам, а не по времени в приложении.';
    const names = {reading:'Чтение',writing:'Письмо',listening:'Аудирование',speaking:'Устная речь'};
    $('skill-list').replaceChildren(...Object.entries(names).map(([key,name]) => {
      const card = node('article','skill-card'); const domain = summary.domains?.[key] || {};
      const eligible = count(domain.eligible_attempts);
      let description = eligible ? `Самостоятельных попыток в текущей выборке: ${eligible}. Выводы остаются предварительными.` : 'Пока недостаточно самостоятельных ответов для оценки. Учебная практика сохраняется в общей истории.';
      if (!eligible && ['listening','speaking'].includes(key)) description = key === 'speaking' ? 'Текстовый чат и расшифровка речи не проверяют произношение. Нужен отдельный разбор реальной речи.' : 'Для оценки нужен ответ после реального прослушивания. Прочитанный текст не заменяет аудирование.';
      card.append(node('h3','',name), node('p','',description)); return card;
    }));
    const activity = Array.isArray(summary.recent_activity) ? summary.recent_activity.slice(-14).reverse() : [];
    $('activity-history').replaceChildren(...(activity.length ? activity.map(day => {
      const item = node('div','history-day'); const date = new Date(day.date + 'T12:00:00');
      item.append(node('b','',Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('ru',{day:'numeric',month:'long'}).format(date) : 'День практики'),node('span','',`${count(day.attempts)} ответов`)); return item;
    }) : [node('p','empty-copy','История начнётся с первого сохранённого ответа.')]));
    $('pending-review-copy').textContent = count(summary.pending_review_count) ? `${count(summary.pending_review_count)} ответов пока ждут разбора. Попроси преподавателя вернуться к ним.` : 'Сохранённые ответы остаются в истории даже после подсказок и исправлений.';
  }
  async function load() {
    $('page-error').hidden = true;
    try { const response = await Tutor.request('/api/web/status',{cache:'no-store'}); render(await response.json()); }
    catch { $('page-error').hidden = false; $('page-error-text').textContent = 'Не удалось загрузить прогресс. Данные не изменены; проверь сервер и повтори.'; }
  }
  $('reload-page').addEventListener('click',load);
  $('date-label').textContent = 'МОЙ ПРОГРЕСС';
  window.TutorProgressReady = Tutor.ready.then(load);
})();
