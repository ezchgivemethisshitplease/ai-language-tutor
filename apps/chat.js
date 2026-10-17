/* Browser tutor. Chat requests are explicitly retried, never sent by the activity outbox. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {
    session: null, status: null, conversationId: null, messages: new Map(), messageNodes: new Map(), cursor: 0,
    active: false, sending: false, loading: false, pending: null, pollTimer: null,
    pollController: null, generation: 0, pollFailures: 0, loginWaiting: false,
    refreshPromise: null, replay: null, storageWarning: false, sessionBusy: false,
    speech: null, speakingMessageId: null, draftRevision: 0, draftSource: 'typed',
    personalization: null, personalizationRevision: null, context: {}, conversation: null,
    contextRevision: null, preferencesRevision: null, editingMemory: null, contextBusy: false, memoryBusy: false
  };
  const validText = value => typeof value === 'string' ? value : '';
  const storageKey = suffix => `tutor:${location.origin}:${state.session.namespace}:web:${suffix}`;
  const draftKey = () => storageKey(`draft:${state.conversationId || 'new'}`);
  const draftSourceKey = () => storageKey(`draft-source:${state.conversationId || 'new'}`);
  function storageWarning() {
    if (state.storageWarning) return;
    state.storageWarning = true;
    $('draft-status').textContent = 'Автосохранение недоступно. Не закрывайте страницу.';
    showNotice('Браузер не разрешил сохранить черновик. Не закрывайте страницу до подтверждения отправки.');
  }
  function stored(suffix) {
    try { return localStorage.getItem(storageKey(suffix)); }
    catch { storageWarning(); return null; }
  }
  function store(suffix, value) {
    try {
      if (value === null) localStorage.removeItem(storageKey(suffix));
      else localStorage.setItem(storageKey(suffix), value);
    } catch { storageWarning(); }
  }
  function saveDraft() {
    if (!state.session) return;
    if (!$('message-input').value) state.draftSource = 'typed';
    try {
      // Write the conservative provenance first; a storage failure must not
      // restore a transcript as an allegedly typed composition.
      if (state.draftSource === 'whisper_transcript') localStorage.setItem(draftSourceKey(), state.draftSource);
      localStorage.setItem(draftKey(), $('message-input').value);
      if (state.draftSource === 'typed') localStorage.removeItem(draftSourceKey());
      return true;
    }
    catch { storageWarning(); return false; }
  }
  function loadDraft() {
    try {
      $('message-input').value = localStorage.getItem(draftKey()) || '';
      state.draftSource = $('message-input').value && localStorage.getItem(draftSourceKey()) === 'whisper_transcript' ? 'whisper_transcript' : 'typed';
    }
    catch { $('message-input').value = ''; state.draftSource = 'typed'; storageWarning(); }
    state.draftRevision += 1;
    resizeInput();
  }
  function applySpeechDraft(text, {mode, snapshot} = {}) {
    const input = $('message-input');
    if (mode === 'if-empty' && (input.value !== '' || snapshot?.context !== (state.conversationId || 'new') || snapshot?.revision !== state.draftRevision)) return false;
    const result = mode === 'append' && input.value ? `${input.value}\n${text}` : text;
    if (result.length > 16000) return false;
    input.value = result; state.draftSource = 'whisper_transcript'; state.draftRevision += 1;
    saveDraft(); resizeInput(); input.focus(); return true;
  }
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }
  function showNotice(text, actions = [], kind = 'warning') {
    $('notice-text').textContent = text;
    $('notice').className = `notice ${kind}`;
    $('notice-actions').replaceChildren();
    for (const [label, handler] of actions) {
      const button = node('button', '', label);
      button.type = 'button'; button.addEventListener('click', handler);
      $('notice-actions').append(button);
    }
    $('notice').hidden = false;
  }
  function clearNotice() { $('notice').hidden = true; }
  function errorMessage(error) {
    if (error?.name === 'AbortError') return 'Сервер не подтвердил ответ вовремя. Отправка могла начаться: повторная попытка использует тот же номер сообщения.';
    if (typeof error?.detail === 'string' && error.detail.trim()) return error.detail;
    const known = {
      400: 'Не удалось выполнить действие. Проверьте введённые данные.',
      401: 'Войдите через ChatGPT, чтобы продолжить разговор.',
      403: 'Доступ к сессии изменился. Обновите страницу; черновик останется в браузере.',
      404: 'Сохранённый разговор или действие не найдены.',
      409: 'Действие пока недоступно. Проверьте текущее занятие и дождитесь окончания ответа.',
      413: 'Сообщение слишком длинное. Разделите его на несколько частей.',
      429: 'Достигнут лимит запросов. Повторите попытку позже.',
      503: 'Преподаватель пока недоступен. Проверьте подключение и вход в ChatGPT.'
    };
    return known[error?.status] || 'Связь с сервером потеряна. Проверьте подключение и повторите действие вручную.';
  }
  async function request(path, payload, {signal, timeout = 30000} = {}) {
    const controller = signal ? null : new AbortController();
    const timer = controller ? setTimeout(() => controller.abort(), timeout) : null;
    try {
      const options = {signal: signal || controller.signal, cache: 'no-store'};
      if (payload !== undefined) {
        options.method = 'POST'; options.headers = {'Content-Type': 'application/json'};
        options.body = JSON.stringify(payload);
      }
      const response = await Tutor.request(path, options);
      const result = await response.json();
      if (!result || typeof result !== 'object') throw new Error('Invalid server response');
      return result;
    } finally { if (timer !== null) clearTimeout(timer); }
  }
  function authReady() {
    return state.status?.auth?.status === 'chatgpt' && state.status?.initialized === true;
  }
  function updateControls() {
    const canWrite = authReady() && !state.loading;
    $('message-input').disabled = !canWrite;
    $('send-button').disabled = !canWrite || state.active || state.sending || !!state.pending || !$('message-input').value.trim();
    $('model-select').disabled = !canWrite || state.active || state.sending;
    $('stop-button').hidden = !state.active;
    $('stop-button').disabled = state.sending;
    $('send-button').hidden = state.active;
    $('retry-message').disabled = !authReady() || state.sending;
    $('new-conversation').disabled = !state.session || state.sending || state.loading || state.contextBusy;
    $('edit-context').disabled = state.sending || state.loading || state.contextBusy;
    $('messages').setAttribute('aria-busy', state.active ? 'true' : 'false');
    state.speech?.setComposerAvailable(canWrite && !state.sending);
  }
  function nearBottom() {
    const scroll = $('messages-scroll');
    return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
  }
  function scrollLatest(force = false) {
    if (force || nearBottom()) {
      $('messages-scroll').scrollTop = $('messages-scroll').scrollHeight;
      $('jump-latest').hidden = true;
    } else $('jump-latest').hidden = false;
  }
  function safeLink(value) {
    try {
      if (typeof value !== 'string' || value.length > 4096) return null;
      const explicit = /^https?:\/\//i.test(value);
      const url = new URL(value, location.href);
      const localPages = new Set(['/index.html', '/chat.html', '/dashboard.html', '/flashcards.html', '/quiz.html', '/reader.html', '/dictation.html']);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
      if (!explicit && (url.origin !== location.origin || !localPages.has(url.pathname))) return null;
      return url;
    } catch { return null; }
  }
  function renderAssistantText(container, text) {
    container.replaceChildren();
    const pattern = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|\[([^\]\n]{1,200})\]\(([^\s)]+)\)|https?:\/\/[^\s<>"`]+/g;
    let previous = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > previous) container.append(node('span', '', text.slice(previous, match.index)));
      if (match[1] !== undefined) container.append(node('code', '', match[1]));
      else if (match[2] !== undefined) container.append(node('strong', '', match[2]));
      else {
        const bare = !match[3];
        const raw = bare ? match[0].replace(/[.,;!?)]+$/, '') : match[4];
        const url = safeLink(raw);
        if (url) {
          const link = node('a', '', bare ? raw : match[3]); link.href = url.href;
          if (url.origin !== location.origin) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
          container.append(link);
          if (bare && raw.length < match[0].length) container.append(node('span', '', match[0].slice(raw.length)));
        } else container.append(node('span', '', match[0]));
      }
      previous = match.index + match[0].length;
    }
    if (previous < text.length) container.append(node('span', '', text.slice(previous)));
  }
  function renderMessages(forceScroll = false) {
    const shouldScroll = forceScroll || nearBottom();
    for (const [id, article] of state.messageNodes) {
      if (!state.messages.has(id)) { article.remove(); state.messageNodes.delete(id); }
    }
    for (const message of state.messages.values()) {
      let article = state.messageNodes.get(message.id);
      if (!article) {
        article = node('article');
        article.label = node('div', 'message-label'); article.body = node('div', 'message-body');
        article.copy = node('button', 'message-copy', 'Копировать'); article.copy.type = 'button';
        article.read = node('button', 'message-read', 'Озвучить'); article.read.type = 'button';
        article.actions = node('div', 'message-actions'); article.actions.append(article.copy, article.read);
        article.append(article.label, article.body, article.actions);
        state.messageNodes.set(message.id, article); $('messages').append(article);
        const id = message.id;
        const copy = article.copy;
        copy.addEventListener('click', async () => {
          try { await navigator.clipboard.writeText(state.messages.get(id)?.text || ''); copy.textContent = 'Скопировано'; }
          catch { showNotice('Не удалось скопировать автоматически. Можно выделить текст сообщения.'); }
        });
        article.read.addEventListener('click', () => {
          if (state.speakingMessageId === id) { state.speech?.stopSpeaking(); return; }
          state.speech?.speak(state.messages.get(id)?.text || '', speaking => {
            state.speakingMessageId = speaking ? id : null;
            article.read.textContent = speaking ? 'Остановить озвучивание' : 'Озвучить';
            article.read.setAttribute('aria-pressed', String(speaking));
          });
        });
      }
      article.className = `message ${message.role}${message.pending ? ' pending' : ''}`;
      article.label.textContent = message.role === 'user' ? 'Вы' : 'Преподаватель';
      if (article.renderedText !== message.text) {
        if (message.role === 'assistant') renderAssistantText(article.body, message.text);
        else article.body.textContent = message.text;
        article.renderedText = message.text;
      }
      article.copy.hidden = message.role !== 'assistant' || !message.text || state.active;
      article.read.hidden = message.role !== 'assistant' || !message.text || state.active || !state.speech?.canSpeak();
    }
    $('welcome').hidden = state.messages.size > 0;
    if (shouldScroll) scrollLatest(true);
    else $('jump-latest').hidden = false;
  }
  function upsertMessage(id, role, text, pending = false) {
    if (!id || !['user', 'assistant'].includes(role)) return;
    state.messages.set(String(id), {id: String(id), role, text: validText(text), pending});
  }
  function renderHistory(conversations) {
    const fragment = document.createDocumentFragment();
    for (const conversation of Array.isArray(conversations) ? conversations : []) {
      if (typeof conversation.id !== 'string') continue;
      const button = node('button', `conversation-link${conversation.id === state.conversationId ? ' selected' : ''}`);
      button.type = 'button';
      if (conversation.id === state.conversationId) button.setAttribute('aria-current', 'true');
      button.append(node('b', '', validText(conversation.context?.title) || validText(conversation.title) || 'Практика английского'));
      if (conversation.context?.goal) button.append(node('span', 'conversation-goal', validText(conversation.context.goal)));
      const date = new Date(conversation.updated_at || conversation.updatedAt || '');
      if (Number.isFinite(date.getTime())) button.append(node('small', '', new Intl.DateTimeFormat('ru', {day:'numeric', month:'short'}).format(date)));
      button.addEventListener('click', () => { if (!state.contextBusy) openConversation(conversation.id).catch(error => showNotice(errorMessage(error), [], 'error')); });
      fragment.append(button);
    }
    if (!fragment.childNodes.length) fragment.append(node('p', 'sidebar-empty', 'Сохранённые занятия появятся здесь.'));
    $('conversation-list').replaceChildren(fragment);
  }
  const stepNames = {
    srs_review: 'Повторить знакомые слова', retrieval: 'Вспомнить пройденное', practice: 'Попрактиковаться',
    remediation: 'Разобрать сложное место', new_material: 'Новая тема', cumulative_review: 'Закрепить пройденное',
    reflection: 'Подвести итоги', speaking: 'Устная практика', pronunciation: 'Произношение'
  };
  const preferenceDefaults = {dialect:'us', register:'informal', explanation_language:'native', explanation_style:'plain', grammar_terminology:'minimal', correction_style:'balanced', topics:[], notes:''};
  const preferenceFields = {dialect:'pref-dialect', register:'pref-register', explanation_language:'pref-explanation-language', explanation_style:'pref-explanation-style', grammar_terminology:'pref-grammar', correction_style:'pref-correction', topics:'pref-topics', notes:'pref-notes'};
  const contextFields = {title:'context-name', goal:'context-goal-input', topics:'context-topics', scenario:'context-scenario', notes:'context-notes', direction_id:'context-direction', mode:'context-mode', challenge:'context-challenge', dialect:'context-dialect', register:'context-register', explanation_style:'context-explanation', grammar_terminology:'context-grammar', correction_style:'context-correction'};
  const overrideFields = ['dialect','register','explanation_style','grammar_terminology','correction_style'];
  const modeNames = {guided:'Занятие с преподавателем', conversation:'Свободный разговор', roleplay:'Ролевая ситуация', writing:'Письменная практика', diagnostic:'Диагностика'};
  const dialectNames = {us:'Американский английский', uk:'Британский английский', international:'Международный английский'};
  const registerNames = {informal:'Неформальное общение', neutral:'Нейтральный стиль', professional:'Деловое общение'};
  const directionNames = {everyday:'Повседневное общение', work:'Английский для работы', travel:'Английский в поездке', interests:'Мои интересы', custom:'Своя задача'};
  const listValue = text => text.split('\n').map(line => line.trim()).filter(Boolean);
  function topicsError(topics) {
    if (topics.length > 12 || topics.some(topic => topic.length > 120)) return 'Укажите до 12 тем, по 120 символов каждая.';
    if (new Set(topics).size !== topics.length) return 'В списке есть повторяющиеся темы. Оставьте каждую один раз.';
    return null;
  }
  function newContext() {
    try { const value = JSON.parse(stored('new-context') || '{}'); return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; }
    catch { return {}; }
  }
  function preferences() { return {...preferenceDefaults, ...(state.personalization?.account_preferences || {})}; }
  function effectivePreferences() {
    const result = preferences();
    for (const field of overrideFields) if (state.context[field]) result[field] = state.context[field];
    return result;
  }
  function directionContext(id) {
    const direction = state.personalization?.directions?.find(item => item.id === id);
    if (!direction) return {direction_id:id, title:directionNames[id] || '', mode:'guided', challenge:'adaptive'};
    const context = {direction_id:direction.id, title:direction.title, goal:direction.goal, topics:direction.topics, mode:direction.mode || 'guided', scenario:direction.scenario || '', challenge:'adaptive'};
    if (direction.register) context.register = direction.register;
    return context;
  }
  function renderContext() {
    const context = state.context, prefs = effectivePreferences();
    const goal = validText(context.goal) || validText(context.scenario);
    $('context-format').textContent = modeNames[context.mode] || modeNames.guided;
    $('context-goal').textContent = goal || directionNames[context.direction_id] || 'Выберите цель для этого занятия';
    $('context-summary').textContent = [dialectNames[prefs.dialect], registerNames[prefs.register], prefs.explanation_style === 'detailed' ? 'Подробные объяснения' : 'Коротко, с примерами'].filter(Boolean).join(' · ');
    $('conversation-title').textContent = validText(context.title) || validText(state.conversation?.title) || 'Практика английского';
    $('welcome-title').textContent = goal ? 'Начнём с вашей задачи' : 'С чего начнём?';
    $('welcome-description').textContent = goal || 'Выберите направление, расскажите о своей задаче или продолжите план занятия.';
    const exercise = state.conversation?.current_exercise;
    const view = exercise?.learner_view || exercise;
    $('current-task-title').textContent = view ? exercise.answered ? 'Последнее задание' : 'Текущее задание' : 'Ваша задача';
    $('current-task-prompt').textContent = validText(view?.prompt) || (context.mode === 'roleplay' && context.scenario ? context.scenario : 'Напишите, что хотите потренировать. Преподаватель предложит первый шаг.');
    $('current-task-context').textContent = validText(view?.context);
    $('current-task-context').hidden = !$('current-task-context').textContent;
    $('task-feedback').hidden = !exercise?.answered;
    $('task-feedback').textContent = exercise?.last_observation_id ? 'Ответ сохранён. Разбор — в сообщении преподавателя.' : 'Вы уже ответили. Разбор — в сообщении преподавателя.';
    const pace = {adaptive:'По одному заданию, сложность по вашим ответам', easy:'Спокойный темп, больше повторения', stretch:'По одному заданию, чуть сложнее привычного'};
    $('current-task-pacing').textContent = pace[context.challenge] || pace.adaptive;
    renderMemories();
  }
  function renderPersonalization(data) {
    if (!data || typeof data !== 'object' || !data.account_preferences) return;
    if (Number.isSafeInteger(data.revision) && state.personalizationRevision !== null && data.revision < state.personalizationRevision) return;
    state.personalization = data;
    if (Number.isSafeInteger(data.revision)) state.personalizationRevision = data.revision;
    const prefs = preferences();
    $('profile-summary').textContent = `${dialectNames[prefs.dialect] || dialectNames.us} · ${prefs.explanation_style === 'detailed' ? 'Подробно' : 'Без лишних терминов'}`;
    renderContext();
  }
  async function refreshPersonalization() {
    const data = await request('/api/web/personalization'); renderPersonalization(data); return data;
  }
  function openPreferences() {
    const prefs = preferences();
    for (const [field, id] of Object.entries(preferenceFields)) $(id).value = Array.isArray(prefs[field]) ? prefs[field].join('\n') : prefs[field];
    state.preferencesRevision = state.personalizationRevision;
    $('preferences-error').hidden = true; $('preferences-success').hidden = true;
    $('preferences-dialog').showModal(); renderMemories();
  }
  async function savePreferences(event) {
    event.preventDefault();
    if (!$('preferences-form').reportValidity()) return;
    const patch = {};
    for (const [field, id] of Object.entries(preferenceFields)) patch[field] = field === 'topics' ? listValue($(id).value) : $(id).value;
    const invalidTopics = topicsError(patch.topics);
    if (invalidTopics) { $('preferences-error').textContent = invalidTopics; $('preferences-error').hidden = false; return; }
    $('save-preferences').disabled = true; $('preferences-error').hidden = true; $('preferences-success').hidden = true;
    try {
      const result = await request('/api/web/preferences', {preferences:patch, ...(state.preferencesRevision !== null ? {expected_revision:state.preferencesRevision} : {})});
      renderPersonalization(result); state.preferencesRevision = state.personalizationRevision;
      $('preferences-success').textContent = 'Сохранено. Следующий ответ учтёт ваши предпочтения.'; $('preferences-success').hidden = false;
    } catch (error) {
      if (error.status === 409) { await refreshPersonalization().catch(() => {}); state.preferencesRevision = state.personalizationRevision; }
      $('preferences-error').textContent = error.status === 409 ? 'Настройки изменились в другой вкладке. Ваши правки остались в форме. Проверьте их и сохраните ещё раз.' : errorMessage(error);
      $('preferences-error').hidden = false;
    } finally { $('save-preferences').disabled = false; }
  }
  function fillContextForm(context) {
    for (const [field, id] of Object.entries(contextFields)) $(id).value = field === 'topics' ? (Array.isArray(context.topics) ? context.topics : []).join('\n') : context[field] || (field === 'mode' ? 'guided' : field === 'challenge' ? 'adaptive' : field === 'direction_id' ? 'custom' : '');
  }
  function openContext() {
    fillContextForm(state.context); state.contextRevision = state.personalizationRevision;
    $('context-error').hidden = true; $('context-dialog').showModal();
  }
  function contextPatch() {
    const context = {};
    for (const [field, id] of Object.entries(contextFields)) context[field] = field === 'topics' ? listValue($(id).value) : overrideFields.includes(field) ? $(id).value || null : $(id).value;
    return context;
  }
  async function saveContext(event) {
    event.preventDefault();
    if (state.contextBusy || !$('context-form').reportValidity()) return;
    const context = contextPatch(), id = state.conversationId;
    const invalidTopics = topicsError(context.topics);
    if (invalidTopics) { $('context-error').textContent = invalidTopics; $('context-error').hidden = false; return; }
    state.contextBusy = true; $('save-context').disabled = true; $('context-error').hidden = true; updateControls();
    try {
      if (id) {
        const result = await request('/api/web/context', {conversation_id:id, context, ...(state.contextRevision !== null ? {expected_revision:state.contextRevision} : {})});
        if (Number.isSafeInteger(result.revision)) state.personalizationRevision = result.revision;
        if (state.conversationId === id) { state.context = result.context || context; renderContext(); }
      } else {
        const conversation = await request('/api/web/conversations', {context});
        if (typeof conversation.id !== 'string') throw new Error('Conversation not created');
        // Carry the untouched draft into the persisted empty lesson workspace.
        saveDraft();
        state.conversationId = conversation.id; state.context = conversation.context || context;
        state.conversation = conversation; store('conversation', conversation.id);
        if (saveDraft()) { store('draft:new', null); store('draft-source:new', null); store('new-context', null); }
        await openConversation(conversation.id, {focus:false});
      }
      $('context-dialog').close(); renderContext();
      refreshStatus().catch(() => showNotice('Направление сохранено. Обновить остальные данные пока не удалось.'));
    } catch (error) {
      if (error.status === 409) { await refreshPersonalization().catch(() => {}); state.contextRevision = state.personalizationRevision; }
      $('context-error').textContent = error.status === 409 ? 'Контекст изменился в другой вкладке. Правки остались в форме. Проверьте их и сохраните ещё раз.' : errorMessage(error);
      $('context-error').hidden = false;
    } finally { state.contextBusy = false; $('save-context').disabled = false; updateControls(); }
  }
  function memoryScope(memory) { return memory.scope === 'conversation' ? memory.conversation_id === state.conversationId ? 'Только эта беседа' : 'Другая беседа' : 'Все занятия'; }
  function renderMemories() {
    const data = state.personalization || {}, memories = Array.isArray(data.memories) ? data.memories : [];
    const pending = Array.isArray(data.pending_memories) ? data.pending_memories : [];
    const active = memories.filter(item => item.scope !== 'conversation' || item.conversation_id === state.conversationId);
    const localPending = pending.filter(item => item.scope !== 'conversation' || item.conversation_id === state.conversationId);
    $('context-memories').hidden = !active.length && !localPending.length;
    $('active-memories').replaceChildren();
    for (const item of active) $('active-memories').append(node('p', 'memory-summary', validText(item.text)));
    if (localPending.length) $('active-memories').append(node('p', 'memory-pending-count', `Предложено запомнить: ${localPending.length}. Нужно ваше подтверждение.`));
    $('memory-list').replaceChildren(); $('memory-proposals').replaceChildren();
    for (const item of memories) {
      const card = node('div', 'memory-item'); card.append(node('small', '', memoryScope(item)), node('p', '', validText(item.text)));
      const actions = node('div', 'memory-actions');
      const edit = node('button', '', 'Изменить'); edit.type = 'button';
      edit.addEventListener('click', () => { state.editingMemory = item; $('memory-text').value = validText(item.text); $('memory-scope').value = item.scope || 'account'; $('cancel-memory-edit').hidden = false; $('memory-text').focus(); });
      const remove = node('button', '', 'Удалить заметку'); remove.type = 'button'; remove.addEventListener('click', () => mutateMemory({action:'delete',id:item.id}));
      actions.append(edit,remove); card.append(actions); $('memory-list').append(card);
    }
    for (const item of pending) {
      const card = node('div', 'memory-item proposal'); card.append(node('small', '', `Преподаватель предлагает · ${memoryScope(item)}`), node('p', '', validText(item.text)));
      if (item.source?.evidence) card.append(node('blockquote', '', validText(item.source.evidence)));
      const actions = node('div', 'memory-actions');
      for (const [label,action] of [['Запомнить','confirm'],['Не сохранять','dismiss']]) { const button = node('button','',label); button.type = 'button'; button.addEventListener('click', () => mutateMemory({action,id:item.id})); actions.append(button); }
      card.append(actions); $('memory-proposals').append(card);
    }
  }
  async function mutateMemory(payload) {
    if (state.memoryBusy) return;
    state.memoryBusy = true;
    $('memory-error').hidden = true; $('save-memory').disabled = true;
    try {
      const result = await request('/api/web/memory', {...payload, ...(state.personalizationRevision !== null ? {expected_revision:state.personalizationRevision} : {})});
      renderPersonalization(result);
      if (payload.action === 'save' || payload.id === state.editingMemory?.id) { state.editingMemory = null; $('memory-text').value = ''; $('cancel-memory-edit').hidden = true; }
    } catch (error) {
      if (error.status === 409) await refreshPersonalization().catch(() => {});
      $('memory-error').textContent = error.status === 409 ? 'Заметки изменились в другой вкладке. Проверьте список и повторите действие.' : errorMessage(error); $('memory-error').hidden = false;
    } finally { state.memoryBusy = false; $('save-memory').disabled = false; }
  }
  function lessonBinding(status = state.status) {
    const binding = state.conversation?.lesson;
    if (!status?.platform_summary) return binding;
    const owner = status.platform_summary.active_session_owner;
    const owned = !!status.session && !!state.conversationId && owner?.conversation_id === state.conversationId;
    return {...binding, owner, owned, can_manage:owned, requires_handoff:!!status.session && !owned, session:owned ? status.session : binding?.session};
  }
  function renderLesson(status) {
    const plan = status.plan?.plan || status.plan || {};
    const binding = lessonBinding(status);
    const session = (binding?.owned ? binding.session : null) || status.session || status.active_session || status.progress?.active_session || {};
    const sessionState = session.status || status.plan?.status || status.progress?.session_status;
    const steps = Array.isArray(plan.steps) ? plan.steps : Array.isArray(session.plan?.steps) ? session.plan.steps : [];
    const completed = new Set(session.completed_steps || status.plan?.completed_steps || []);
    const fragment = document.createDocumentFragment();
    steps.forEach((step, index) => {
      const done = completed.has(step.id) || step.completed === true || step.status === 'completed';
      const item = node('li', `lesson-step${done ? ' done' : ''}`);
      item.append(node('span', 'step-number', done ? '✓' : index + 1));
      const text = node('div');
      text.append(node('b', '', validText(step.title) || validText(step.unit_title) || stepNames[step.type] || 'Практика английского'));
      const details = [];
      if (Number.isFinite(step.minutes)) details.push(`${step.minutes} мин`);
      if (step.mode === 'voice-required') details.push('нужен голос');
      if (done) details.push('выполнено');
      if (details.length) text.append(node('small', '', details.join(' · ')));
      item.append(text); fragment.append(item);
    });
    $('lesson-steps').replaceChildren(fragment);
    $('lesson-title').textContent = validText(plan.title) || 'План на сегодня';
    $('lesson-description').textContent = steps.length ? 'Работаем по одному шагу. Если что-то непонятно, попросите объяснить по-русски.' : 'План появится после начала занятия. Преподаватель учтёт ваши ответы и время.';
    const active = sessionState === 'active' || (!sessionState && steps.length > 0 && sessionState !== 'completed');
    const interrupted = sessionState === 'interrupted';
    $('start-session').hidden = active || interrupted;
    $('start-session').disabled = !status.initialized || state.sending || state.sessionBusy;
    for (const id of ['resume-session', 'interrupt-session', 'finish-session']) $(id).disabled = state.sessionBusy || (binding && !binding.can_manage);
    $('resume-session').hidden = !interrupted;
    $('interrupt-session').hidden = !active;
    $('finish-session').hidden = !(active || interrupted);
    const foreign = binding?.requires_handoff === true;
    $('shared-session-notice').hidden = !foreign;
    if (foreign) {
      const owner = binding.owner;
      $('shared-session-text').textContent = owner?.conversation_id ? `План уже начат в беседе «${validText(owner.title) || 'Занятие'}». Можно вернуться туда или перенести этот же план сюда.` : 'Есть начатый план. Свяжите его с этой беседой, чтобы продолжить.';
      $('shared-session-link').hidden = !owner?.conversation_id;
      $('shared-session-link').href = owner?.conversation_id ? `chat.html?conversation=${encodeURIComponent(owner.conversation_id)}` : 'chat.html';
      $('handoff-session').disabled = state.sessionBusy;
      $('start-session').hidden = true;
    }
    const level = status.progress?.working_level || status.progress?.level || status.proficiency?.working_level;
    $('working-level').hidden = !level;
    $('working-level').textContent = validText(level);
    $('working-level').title = 'Рабочая отправная точка; без сертификации CEFR';
    const objectives = status.objectives || status.profile?.objectives || [];
    const objectiveText = Array.isArray(objectives) ? objectives.map(item => typeof item === 'string' ? item : validText(item.text || item.description)).filter(Boolean).join(' · ') : validText(objectives);
    $('learning-objective').textContent = objectiveText || 'Добавьте цель в профиле, чтобы выбирать близкие вам темы.';
    const next = steps.find(step => !completed.has(step.id) && step.completed !== true && step.status !== 'completed');
    $('next-step').textContent = next ? validText(next.title) || validText(next.unit_title) || stepNames[next.type] || 'Следующее задание из плана' : steps.length ? 'План пройден. Подведите итоги с преподавателем.' : 'Выберите цель, затем начните с одного короткого задания.';
    $('voice-note').textContent = status.profile?.voice_channel === 'external' ? 'Для голосового занятия попросите преподавателя подготовить отдельный проход. Его результат нужно проверить перед записью в прогресс.' : 'Голосовой ввод создаёт текстовый черновик. Устную речь и произношение проверяют в отдельном голосовом занятии.';
  }
  function renderStatus(status) {
    state.status = status;
    const current = status.conversations?.find(item => item.id === state.conversationId);
    const oldSettings = Number.isSafeInteger(status.personalization?.revision) && state.personalizationRevision !== null && status.personalization.revision < state.personalizationRevision;
    if (current && state.conversation && !oldSettings) {
      if (current.context) state.context = current.context;
      if ('current_exercise' in current) state.conversation.current_exercise = current.current_exercise;
    }
    const backupStatus = status.backup?.status;
    if (['warning', 'unavailable'].includes(backupStatus)) $('backup-warning').hidden = false;
    else if (['created', 'not_due', 'disabled'].includes(backupStatus)) $('backup-warning').hidden = true;
    const auth = status.auth || {};
    const connected = auth.status === 'chatgpt';
    $('connection-label').textContent = connected ? 'ChatGPT подключён' : auth.status === 'unavailable' ? 'Нет подключения' : 'Нужен вход';
    $('connection-indicator').className = `connection-indicator ${connected ? 'connected' : 'warning'}`;
    $('account-notice').hidden = connected;
    $('login-button').hidden = connected;
    $('login-button').textContent = state.loginWaiting ? 'Повторить вход' : 'Войти через ChatGPT';
    $('login-button').className = `button ${state.loginWaiting ? 'subtle' : 'primary'}`;
    $('login-button').disabled = auth.status === 'unavailable';
    $('account-title').textContent = auth.status === 'unavailable' ? 'Преподаватель пока недоступен' : state.loginWaiting ? 'Завершите вход в ChatGPT' : 'Подключите преподавателя';
    $('account-description').textContent = validText(auth.error) || (state.loginWaiting ? 'Продолжите в официальном окне входа. Мы проверим подключение автоматически.' : 'Войдите в свой аккаунт ChatGPT, чтобы заниматься здесь.');
    if (connected) { state.loginWaiting = false; $('login-link').hidden = true; $('login-link').removeAttribute('href'); }
    $('setup-notice').hidden = status.initialized === true;
    if (status.personalization) renderPersonalization(status.personalization);
    else if (status.account_preferences) renderPersonalization(status);
    const selected = $('model-select').value || stored('model') || '';
    const models = Array.isArray(status.models) ? status.models : [];
    const options = document.createDocumentFragment(); options.append(node('option', '', 'Модель по умолчанию'));
    options.firstChild.value = '';
    for (const model of models) {
      if (typeof model.id !== 'string') continue;
      const option = node('option', '', validText(model.displayName) || validText(model.display_name) || model.id);
      option.value = model.id; options.append(option);
    }
    $('model-select').replaceChildren(options);
    $('model-select').value = models.some(model => model.id === selected) ? selected : '';
    renderHistory(status.conversations); renderLesson(status); renderContext(); updateControls();
  }
  async function refreshStatus() {
    if (state.refreshPromise) return state.refreshPromise;
    state.refreshPromise = request('/api/web/status').then(renderStatus).finally(() => { state.refreshPromise = null; });
    return state.refreshPromise;
  }
  function closeNav() {
    const wasOpen = document.body.classList.contains('nav-open');
    document.body.classList.remove('nav-open'); $('nav-scrim').hidden = true;
    $('toggle-nav').setAttribute('aria-expanded', 'false'); updateNavAccessibility();
    if (wasOpen) $('toggle-nav').focus();
  }
  function updateNavAccessibility() {
    const mobile = window.matchMedia('(max-width: 760px)').matches;
    const open = document.body.classList.contains('nav-open');
    $('sidebar').inert = mobile && !open;
    document.querySelector('.workspace').inert = mobile && open;
  }
  function stopPolling() {
    clearTimeout(state.pollTimer); state.pollTimer = null;
    state.pollController?.abort(); state.pollController = null;
    state.generation += 1;
  }
  function updateConversationUrl() {
    const url = new URL(location.href);
    for (const key of ['conversation','new','direction','mode','settings','setup']) url.searchParams.delete(key);
    url.searchParams.set(state.conversationId ? 'conversation' : 'new', state.conversationId || '1');
    window.history?.replaceState({}, '', url.href);
  }
  async function openConversation(id, {focus = true} = {}) {
    state.speech?.stopSpeaking();
    saveDraft(); stopPolling(); state.loading = true; updateControls();
    const generation = state.generation;
    try {
      if (!id) {
        state.conversationId = null; state.conversation = null; state.context = newContext(); state.messages.clear(); state.cursor = 0; state.active = false; state.replay = null;
        store('conversation', null);
      } else {
        const conversation = await request(`/api/web/conversation?id=${encodeURIComponent(id)}`);
        if (generation !== state.generation) return;
        state.conversationId = conversation.id; state.conversation = conversation; state.context = conversation.context || {}; state.messages.clear();
        for (const message of Array.isArray(conversation.messages) ? conversation.messages : []) upsertMessage(message.id, message.role, message.text);
        state.cursor = Number.isSafeInteger(conversation.cursor) && conversation.cursor >= 0 ? conversation.cursor : 0;
        state.replay = 'cursor' in conversation ? null : new Map();
        state.active = conversation.active === true;
        store('conversation', conversation.id);
      }
      $('turn-status').textContent = state.active ? 'Преподаватель отвечает…' : '';
      loadDraft(); renderMessages(true); renderContext(); updateConversationUrl(); closeNav();
      if (state.status) { renderHistory(state.status.conversations); renderLesson(state.status); }
    } finally {
      if (generation === state.generation) { state.loading = false; updateControls(); }
    }
    if (state.conversationId) schedulePoll(50);
    if (focus && authReady()) $('message-input').focus();
  }
  function schedulePoll(delay = 1000) {
    clearTimeout(state.pollTimer);
    if (state.conversationId) state.pollTimer = setTimeout(pollEvents, delay);
  }
  async function pollEvents() {
    const id = state.conversationId, generation = state.generation;
    if (!id || state.loading) return;
    const controller = new AbortController(); state.pollController = controller;
    let ended = false;
    try {
      const result = await request(`/api/web/events?conversation_id=${encodeURIComponent(id)}&after=${state.cursor}`, undefined, {signal: controller.signal});
      if (generation !== state.generation || id !== state.conversationId) return;
      state.pollFailures = 0;
      if (result.reset === true) { await openConversation(id, {focus:false}); return; }
      let changed = false, refresh = false;
      const wasActive = state.active;
      for (const event of Array.isArray(result.events) ? result.events : []) {
        if (!Number.isSafeInteger(event.seq) || event.seq <= state.cursor) continue;
        state.cursor = event.seq;
        const messageId = event.message_id || event.message?.id || `event:${event.seq}`;
        if (event.type === 'message') {
          const role = event.role || event.message?.role;
          const text = validText(event.text ?? event.message?.text);
          state.replay?.set(messageId, text); upsertMessage(messageId, role, text); changed = true;
        } else if (event.type === 'delta') {
          const previous = state.replay ? state.replay.get(messageId) || '' : state.messages.get(messageId)?.text || '';
          const text = previous + validText(event.text);
          state.replay?.set(messageId, text); upsertMessage(messageId, 'assistant', text); changed = true;
          $('turn-status').textContent = 'Преподаватель отвечает…';
        } else if (event.type === 'turn_started') {
          state.active = true; $('turn-status').textContent = 'Преподаватель думает…';
        } else if (event.type === 'turn_completed') {
          state.active = false; ended = true; refresh = true;
          $('turn-status').textContent = event.status === 'interrupted' ? 'Ответ остановлен' : '';
          if (event.status === 'failed') showNotice('Ответ не удалось закончить. Сохранённая часть осталась в разговоре.', [], 'error');
        } else if (event.type === 'tool') {
          $('turn-status').textContent = event.status === 'completed' ? 'Готовлю ответ…' : 'Работаю с материалами занятия…';
        } else if (event.type === 'error') {
          showNotice(validText(event.text) || 'Не удалось закончить ответ. Попробуйте продолжить разговор.', [], 'error');
        } else if (event.type === 'state') refresh = true;
      }
      if (Number.isSafeInteger(result.cursor) && result.cursor >= state.cursor) state.cursor = result.cursor;
      if (typeof result.active === 'boolean') state.active = result.active;
      if (wasActive && !state.active) { ended = true; refresh = true; }
      if (changed) renderMessages();
      updateControls();
      if (refresh) refreshStatus().catch(() => {});
      if (ended) { await openConversation(id, {focus:false}); return; }
    } catch (error) {
      if (error.name === 'AbortError' || generation !== state.generation) return;
      state.pollFailures += 1;
      if (state.pollFailures === 1) showNotice('Связь прервалась. Проверяем сохранённый ответ; сообщение повторно не отправляется.', [['Проверить сейчас', () => schedulePoll(0)]]);
    } finally { if (state.pollController === controller) state.pollController = null; }
    if (generation === state.generation) schedulePoll(state.pollFailures ? Math.min(15000, 1000 * 2 ** state.pollFailures) : state.active ? 1000 : 4000);
  }
  function pendingFromStorage() {
    try {
      const pending = JSON.parse(stored('pending') || 'null');
      if (!pending || typeof pending !== 'object' || typeof pending.request_id !== 'string' || pending.request_id.length > 200 || typeof pending.message !== 'string' || !pending.message.trim() || pending.message.length > 16000 || !(pending.conversation_id === null || typeof pending.conversation_id === 'string')) return null;
      return {request_id: pending.request_id, message: pending.message, conversation_id: pending.conversation_id, input_source: pending.input_source === 'whisper_transcript' ? 'whisper_transcript' : 'typed', ...(typeof pending.model === 'string' ? {model:pending.model} : {}), ...(pending.context && typeof pending.context === 'object' && !Array.isArray(pending.context) ? {context:pending.context} : {})};
    } catch { return null; }
  }
  function renderPending() {
    $('pending-notice').hidden = !state.pending || state.sending;
    $('pending-description').textContent = state.storageWarning ? 'Отправка не подтверждена. Текст остался на странице; автосохранение недоступно.' : 'Отправка не подтверждена. Сообщение сохранено в этом браузере.';
    updateControls();
  }
  async function sendPending() {
    if (!state.pending || state.sending || !authReady()) return;
    const payload = {...state.pending};
    const originDraft = storageKey(`draft:${payload.conversation_id || 'new'}`);
    const originSource = storageKey(`draft-source:${payload.conversation_id || 'new'}`);
    state.sending = true; clearNotice(); renderPending();
    upsertMessage(`pending:${payload.request_id}`, 'user', payload.message, true); renderMessages(true);
    $('turn-status').textContent = 'Отправляю…';
    let acknowledged = false, acknowledgedId = null;
    try {
      const result = await request('/api/web/chat', payload);
      const accepted = (result.accepted === true && result.request_id === payload.request_id) || (typeof result.turn_id === 'string' && result.turn_id.length > 0);
      if (typeof result.conversation_id !== 'string' || !accepted) throw new Error('Chat not acknowledged');
      state.pending = null; store('pending', null);
      acknowledged = true; acknowledgedId = result.conversation_id;
      const sameComposer = state.conversationId === payload.conversation_id;
      const unchanged = sameComposer && $('message-input').value === payload.message;
      if (unchanged) {
        try { localStorage.removeItem(originDraft); localStorage.removeItem(originSource); } catch { storageWarning(); }
        $('message-input').value = ''; state.draftSource = 'typed'; state.draftRevision += 1;
      } else {
        saveDraft();
        if (!sameComposer) {
          try {
            if (localStorage.getItem(originDraft) === payload.message) { localStorage.removeItem(originDraft); localStorage.removeItem(originSource); }
          } catch { storageWarning(); }
        }
      }
      // Carry a newly edited draft into the just-created conversation. A retry
      // made from another conversation keeps that other draft in its own scope.
      if (payload.conversation_id === null && sameComposer) { state.conversationId = result.conversation_id; saveDraft(); }
      if (payload.conversation_id === null && JSON.stringify(newContext()) === JSON.stringify(payload.context || {})) store('new-context', null);
      state.active = true; store('conversation', result.conversation_id);
      await openConversation(result.conversation_id, {focus:false});
      refreshStatus().catch(() => {});
    } catch (error) {
      if (acknowledged && acknowledgedId !== state.conversationId) { saveDraft(); state.conversationId = acknowledgedId; loadDraft(); }
      const optimistic = state.messages.get(`pending:${payload.request_id}`);
      if (optimistic) { state.messages.delete(optimistic.id); renderMessages(); }
      $('turn-status').textContent = '';
      showNotice(acknowledged ? 'Сообщение принято, но сохранённый ответ пока не загрузился. Проверяем разговор; повторно отправлять сообщение не нужно.' : errorMessage(error), [], 'error');
    } finally { state.sending = false; renderPending(); resizeInput(); if (acknowledged) schedulePoll(500); }
  }
  function resizeInput() {
    const input = $('message-input'); input.style.height = 'auto';
    input.style.height = `${Math.min(180, Math.max(43, input.scrollHeight))}px`; updateControls();
  }
  function officialLoginUrl(value) {
    try {
      const url = new URL(value);
      const official = ['openai.com', 'chatgpt.com'].some(domain => url.hostname === domain || url.hostname.endsWith(`.${domain}`));
      return url.protocol === 'https:' && official && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  async function login() {
    $('login-button').disabled = true; clearNotice();
    try {
      const result = await request('/api/web/login', {});
      const url = officialLoginUrl(result.auth_url);
      if (!url) throw new Error('Invalid sign-in URL');
      state.loginWaiting = true; $('login-link').href = url; $('login-link').hidden = false; $('login-button').hidden = true;
      $('account-title').textContent = 'Завершите вход в ChatGPT';
      $('account-description').textContent = 'Откройте официальную страницу входа. После входа подключение появится здесь автоматически.';
      $('login-link').focus();
    } catch (error) { showNotice(errorMessage(error), [['Проверить подключение', () => refreshStatus().catch(failed => showNotice(errorMessage(failed), [], 'error'))]], 'error'); }
    finally { if (!state.loginWaiting) $('login-button').disabled = false; }
  }
  function openSettings() {
    const profile = state.status?.profile || {};
    const language = validText(profile.native_language) || validText(state.status?.native_language) || 'russian';
    const names = {russian:'Русский', english:'Английский', spanish:'Испанский', german:'Немецкий', french:'Французский', ukrainian:'Украинский'};
    $('native-language').value = names[language.toLocaleLowerCase('ru')] || language;
    $('daily-minutes').value = profile.daily_minutes || 20;
    $('voice-channel').value = profile.voice_channel === 'external' ? 'external' : 'none';
    const objectives = state.status?.objectives || profile.objectives || [];
    $('objectives-input').value = Array.isArray(objectives) ? objectives.map(item => typeof item === 'string' ? item : validText(item.text || item.description)).filter(Boolean).join('\n') : validText(objectives);
    $('settings-error').hidden = true;
    $('settings-dialog').showModal();
  }
  async function saveSettings(event) {
    event.preventDefault();
    if (!$('settings-form').reportValidity()) return;
    $('save-settings').disabled = true; $('settings-error').hidden = true; saveDraft();
    try {
      const native = $('native-language').value.trim();
      const languageIds = {'русский':'russian', 'английский':'english', 'испанский':'spanish', 'немецкий':'german', 'французский':'french', 'украинский':'ukrainian'};
      await request('/api/web/setup', {
        native_language: languageIds[native.toLocaleLowerCase('ru')] || native, daily_minutes: Number($('daily-minutes').value),
        voice_channel: $('voice-channel').value, objectives: $('objectives-input').value.split('\n').map(line => line.trim()).filter(Boolean)
      });
      location.reload();
    } catch (error) { $('settings-error').textContent = errorMessage(error); $('settings-error').hidden = false; }
    finally { $('save-settings').disabled = false; }
  }
  async function sessionAction(action, allowIncomplete = false) {
    if (state.sessionBusy) return;
    state.sessionBusy = true;
    clearNotice();
    const buttons = document.querySelectorAll('[data-session-action]'); buttons.forEach(button => { button.disabled = true; });
    try {
      if (!state.conversationId) {
        const conversation = await request('/api/web/conversations', {context:state.context});
        if (typeof conversation.id !== 'string') throw new Error('Conversation not created');
        saveDraft(); state.conversationId = conversation.id;
        if (saveDraft()) { store('draft:new', null); store('draft-source:new', null); store('new-context', null); }
        await openConversation(conversation.id, {focus:false});
      }
      const binding = lessonBinding();
      if (binding && !binding.can_manage && action !== 'start' && action !== 'handoff') { showNotice('Этот план открыт в другой беседе. Перейдите к ней или выберите «Продолжить занятие здесь».'); return; }
      const status = await request('/api/web/session', {action, conversation_id:state.conversationId, ...(action === 'handoff' ? {expected_owner:binding?.owner?.conversation_id || null} : {}), ...(allowIncomplete ? {allow_incomplete:true} : {})});
      if ('initialized' in status) renderStatus(status); else await refreshStatus();
      await openConversation(state.conversationId, {focus:false});
      if (status.ok === false) { showNotice('План открыт в другой беседе. Перейдите к ней или выберите «Продолжить занятие здесь».'); return; }
      if (action === 'start' || action === 'resume') {
        if (!$('message-input').value.trim()) {
          $('message-input').value = action === 'start' ? 'План занятия готов. Давай начнём с первого шага.' : 'Продолжим прерванное занятие с текущего шага.';
          saveDraft(); resizeInput();
        }
        $('message-input').focus();
      }
    } catch (error) {
      const actions = action === 'finish' && !allowIncomplete ? [['Закончить с незавершёнными шагами', () => sessionAction('finish', true)]] : [];
      showNotice(errorMessage(error), actions, 'error');
    } finally { state.sessionBusy = false; buttons.forEach(button => { button.disabled = false; }); if (state.status) renderLesson(state.status); }
  }
  async function downloadBackup() {
    $('download-backup').disabled = true;
    try {
      const response = await Tutor.request('/api/web/backup', {cache:'no-store'});
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      const link = node('a'); link.href = url; link.download = 'ai-language-tutor-backup.zip';
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { showNotice(errorMessage(error), [], 'error'); }
    finally { $('download-backup').disabled = false; }
  }
  async function boot() {
    state.session = await Tutor.ready;
    if (window.TutorSpeech) state.speech = window.TutorSpeech.create({
      request: (path, options) => Tutor.request(path, options),
      getDraft: () => ({text:$('message-input').value, context:state.conversationId || 'new', revision:state.draftRevision}),
      applyDraft: applySpeechDraft,
      notice: text => showNotice(text)
    });
    $('today-label').textContent = new Intl.DateTimeFormat('ru', {day:'numeric',month:'long',weekday:'long'}).format(new Date()).toLocaleUpperCase('ru');
    state.pending = pendingFromStorage();
    await refreshStatus();
    if (!state.personalization) await refreshPersonalization().catch(error => showNotice(errorMessage(error), [], 'error'));
    const parameters = new URL(location.href).searchParams;
    const startNew = parameters.get('new') === '1';
    const requestedDirection = parameters.get('direction');
    const requestedMode = parameters.get('mode');
    const saved = stored('conversation');
    const id = startNew ? null : parameters.get('conversation') || saved || state.status.active_conversation_id;
    if (id) {
      try { await openConversation(id, {focus:false}); }
      catch (error) { store('conversation', null); await openConversation(null, {focus:false}); showNotice(errorMessage(error), [], 'error'); }
    } else { state.context = newContext(); loadDraft(); updateControls(); }
    if (!id && requestedDirection && Object.hasOwn(directionNames, requestedDirection)) {
      state.context = directionContext(requestedDirection); store('new-context', JSON.stringify(state.context));
    }
    if (!id && requestedMode && Object.hasOwn(modeNames, requestedMode)) {
      const goals = {diagnostic:'Определить, с какой сложности начать', conversation:'Потренировать разговор на английском', roleplay:'Потренировать ситуацию на английском', writing:'Попрактиковаться в письменном английском', guided:'Продолжить практику с преподавателем'};
      state.context = requestedDirection ? {...state.context,mode:requestedMode} : {title:modeNames[requestedMode],goal:goals[requestedMode],mode:requestedMode,challenge:'adaptive',direction_id:'custom'};
      store('new-context', JSON.stringify(state.context));
    }
    renderContext();
    if (parameters.get('setup') === '1') openSettings();
    else if (parameters.get('settings') === '1') openPreferences();
    renderPending(); updateNavAccessibility();
    setInterval(() => {
      if (!document.hidden) refreshStatus().catch(() => {});
    }, 5000);
  }

  $('chat-form').addEventListener('submit', event => {
    event.preventDefault();
    const message = $('message-input').value;
    if (!message.trim() || state.active || state.sending || state.pending || !authReady()) return;
    if (message.length > 16000) { showNotice('В одном сообщении можно отправить до 16 000 символов. Разделите текст на части.'); return; }
    state.pending = {conversation_id:state.conversationId, message, input_source:state.draftSource, request_id:crypto.randomUUID()};
    if (!state.conversationId) state.pending.context = structuredClone(state.context);
    if ($('model-select').value) state.pending.model = $('model-select').value;
    store('pending', JSON.stringify(state.pending)); saveDraft(); sendPending();
  });
  $('message-input').addEventListener('input', () => { state.draftRevision += 1; saveDraft(); resizeInput(); });
  $('message-input').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('chat-form').requestSubmit(); }
  });
  $('model-select').addEventListener('change', () => store('model', $('model-select').value));
  $('new-conversation').addEventListener('click', () => openConversation(null).catch(error => showNotice(errorMessage(error), [], 'error')));
  $('refresh-history').addEventListener('click', () => refreshStatus().catch(error => showNotice(errorMessage(error), [], 'error')));
  $('retry-message').addEventListener('click', sendPending);
  $('keep-draft').addEventListener('click', () => {
    if (!state.pending || state.sending) return;
    $('message-input').value = state.pending.message; state.draftSource = state.pending.input_source || 'typed'; state.draftRevision += 1; saveDraft(); state.pending = null; store('pending', null); renderPending(); resizeInput();
    showNotice('Текст оставлен в черновике. Перед новой отправкой проверьте историю: сервер мог принять предыдущее сообщение.');
  });
  $('stop-button').addEventListener('click', async () => {
    if (!state.conversationId || !state.active) return;
    $('stop-button').disabled = true;
    try { await request('/api/web/interrupt', {conversation_id:state.conversationId}); $('turn-status').textContent = 'Останавливаю ответ…'; schedulePoll(0); }
    catch (error) { showNotice(errorMessage(error), [], 'error'); }
    finally { $('stop-button').disabled = false; }
  });
  $('login-button').addEventListener('click', login);
  $('open-settings').addEventListener('click', openSettings); $('setup-button').addEventListener('click', openSettings);
  $('close-settings').addEventListener('click', () => $('settings-dialog').close()); $('cancel-settings').addEventListener('click', () => $('settings-dialog').close());
  $('settings-form').addEventListener('submit', saveSettings);
  $('open-preferences').addEventListener('click', openPreferences); $('open-memory').addEventListener('click', openPreferences);
  $('close-preferences').addEventListener('click', () => $('preferences-dialog').close()); $('cancel-preferences').addEventListener('click', () => $('preferences-dialog').close());
  $('preferences-form').addEventListener('submit', savePreferences);
  $('edit-context').addEventListener('click', openContext);
  $('close-context').addEventListener('click', () => $('context-dialog').close()); $('cancel-context').addEventListener('click', () => $('context-dialog').close());
  $('context-form').addEventListener('submit', saveContext);
  $('context-direction').addEventListener('change', () => fillContextForm(directionContext($('context-direction').value)));
  $('handoff-session').addEventListener('click', () => sessionAction('handoff'));
  $('cancel-memory-edit').addEventListener('click', () => { state.editingMemory = null; $('memory-text').value = ''; $('cancel-memory-edit').hidden = true; });
  $('memory-form').addEventListener('submit', event => {
    event.preventDefault(); const text = $('memory-text').value.trim();
    if (!text) { $('memory-error').textContent = 'Напишите, что учитывать.'; $('memory-error').hidden = false; return; }
    const scope = $('memory-scope').value, conversationId = state.editingMemory?.conversation_id || state.conversationId;
    if (scope === 'conversation' && !conversationId) { $('memory-error').textContent = 'Сначала сохраните направление беседы или отправьте первое сообщение.'; $('memory-error').hidden = false; return; }
    mutateMemory({action:'save', text, scope, ...(state.editingMemory ? {id:state.editingMemory.id} : {}), ...(scope === 'conversation' ? {conversation_id:conversationId} : {})});
  });
  $('download-backup').addEventListener('click', downloadBackup);
  document.querySelectorAll('[data-session-action]').forEach(button => button.addEventListener('click', () => sessionAction(button.dataset.sessionAction)));
  document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
    $('message-input').value = button.dataset.prompt; saveDraft(); resizeInput();
    state.draftRevision += 1;
    if (!state.status?.initialized) openSettings();
    else if (!authReady()) showNotice('Сначала подключите преподавателя через ChatGPT. Сообщение осталось в черновике.');
    else $('message-input').focus();
  }));
  $('toggle-nav').addEventListener('click', () => {
    const open = !document.body.classList.contains('nav-open'); document.body.classList.toggle('nav-open', open);
    $('nav-scrim').hidden = !open; $('toggle-nav').setAttribute('aria-expanded', String(open)); updateNavAccessibility();
    if (open) $('new-conversation').focus();
  });
  $('nav-scrim').addEventListener('click', closeNav);
  $('toggle-lesson').addEventListener('click', () => {
    const open = $('lesson-panel').classList.toggle('open'); $('toggle-lesson').setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeNav(); $('lesson-panel').classList.remove('open'); $('toggle-lesson').setAttribute('aria-expanded', 'false'); } });
  $('messages-scroll').addEventListener('scroll', () => { if (nearBottom()) $('jump-latest').hidden = true; });
  $('jump-latest').addEventListener('click', () => scrollLatest(true));
  window.addEventListener('resize', updateNavAccessibility);
  window.addEventListener('online', () => { if (state.conversationId) schedulePoll(0); refreshStatus().catch(() => {}); });
  window.addEventListener('offline', () => { $('connection-label').textContent = 'Нет сети'; showNotice('Соединение недоступно. Текст остаётся в черновике; отправка возобновится только по вашему действию.'); });
  window.addEventListener('focus', () => { if (state.session) { refreshStatus().catch(() => {}); if (state.conversationId) schedulePoll(0); } });
  window.addEventListener('beforeunload', () => { saveDraft(); state.speech?.dispose(); });
  window.TutorChatReady = boot().catch(error => {
    showNotice(errorMessage(error), [['Загрузить заново', () => location.reload()]], 'error');
    $('connection-label').textContent = 'Нет подключения'; $('account-description').textContent = 'Не удалось связаться с локальным сервером. Обновите страницу после восстановления подключения.';
  });
})();
