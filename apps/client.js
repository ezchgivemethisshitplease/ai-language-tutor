/* Shared same-origin transport. Pending results survive reload until acknowledged. */
(() => {
  const nativeFetch = window.fetch.bind(window);
  let session;
  const ready = nativeFetch('/api/session').then(async response => {
    if (!response.ok) throw new Error('Local server unavailable');
    session = await response.json();
    document.documentElement.lang = session.locale || 'ru';
    return session;
  });
  const keyFor = path => `tutor:${location.origin}:${session.namespace}:${path}`;
  async function request(path, options = {}) {
    await ready;
    const response = await nativeFetch(path, {...options, headers: {
      ...options.headers, 'X-Tutor-Token': session.token, 'X-Tutor-Namespace': session.namespace
    }});
    if (!response.ok) { const error = new Error(`HTTP ${response.status}`); error.status = response.status; throw error; }
    return response;
  }
  function status(message, retry, id = 'save-status') {
    let box = document.getElementById(id);
    if (!box) {
      box = document.createElement('div'); box.id = id;
      box.setAttribute('role', 'status'); box.style.cssText = 'padding:12px;text-align:center;background:var(--surface-2);font:14px system-ui';
      document.body.prepend(box);
    }
    box.replaceChildren(document.createTextNode(message));
    if (retry) {
      const button = document.createElement('button'); button.textContent = 'Повторить';
      button.style.marginLeft = '12px'; button.onclick = retry; box.append(button);
    }
  }
  async function post(path, payload) {
    await ready;
    const body = {...payload, batch_id: payload.batch_id || crypto.randomUUID()};
    const key = keyFor(path) + ':' + body.batch_id;
    localStorage.setItem(key, JSON.stringify(body));
    const response = await request(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (result.ok !== true) throw new Error('Save not acknowledged');
    localStorage.removeItem(key);
    const backupUnavailable = ['warning', 'unavailable'].includes(result.backup?.status);
    status('Сохранено');
    if (backupUnavailable) {
      status('Ответ сохранён. Резервная копия недоступна: проверьте подключение диска и настройку копирования.', undefined, 'backup-status');
    } else if (result.backup && result.backup.status !== 'disabled') {
      document.getElementById('backup-status')?.remove();
    }
    return result;
  }
  async function flush() {
    await ready;
    let conflicts = 0;
    for (const path of ['/api/deck', '/api/deck/complete', '/api/quiz', '/api/text']) {
      const prefix = keyFor(path) + ':';
      const keys = Object.keys(localStorage).filter(key => key.startsWith(prefix));
      for (const key of keys) {
        const body = JSON.parse(localStorage.getItem(key));
        if (body) {
          try { await post(path, body); }
          catch (error) {
            if ([400, 409].includes(error.status)) {
              conflicts++;
              status('Старый результат требует разбора с преподавателем. Он сохранён в очереди браузера.');
            } else { throw error; }
          }
        }
      }
    }
    return {conflicts};
  }
  async function audioUrl(text) {
    await ready;
    return '/api/tts?text=' + encodeURIComponent(text) + '&token=' + encodeURIComponent(session.token);
  }
  const escape = value => { const node = document.createElement('span'); node.textContent = value ?? ''; return node.innerHTML; };
  window.Tutor = {ready, request, post, flush, audioUrl, status, escape};
  // Existing read-only app fetches share the authenticated transport.
  window.fetch = (path, options) => String(path).startsWith('/api/') ? request(path, options) : nativeFetch(path, options);
  ready.catch(() => status('Сервер недоступен. Запустите его и обновите страницу.', () => location.reload()));
})();
