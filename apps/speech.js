/* Explicit local dictation and browser read-aloud. Neither sends a chat message. */
(() => {
  'use strict';
  const MAX_TEXT = 16000;
  const recordingTypes = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg'];
  const baseType = type => String(type || '').split(';', 1)[0].trim().toLowerCase();
  const formatTime = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

  function create({request, getDraft, applyDraft, notice = () => {}}) {
    const $ = id => document.getElementById(id);
    const state = {
      status: null, phase: 'idle', composerAvailable: false, stream: null, recorder: null,
      chunks: [], bytes: 0, overflow: false, blob: null, previewUrl: null, snapshot: null,
      token: 0, timer: null, deadline: null, startedAt: 0, controller: null, setupTimer: null,
      speechToken: 0, speechCallback: null, disposed: false
    };
    const mediaSupported = () => !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder && window.isSecureContext !== false);
    const ready = () => state.status?.available === true && state.status?.status === 'ready';
    const runningSetup = () => state.status?.setup?.running === true || state.status?.status === 'installing';
    const limitSeconds = () => Math.min(60, Math.max(1, Number(state.status?.max_seconds) || 60));
    const limitBytes = () => Math.min(12 * 1024 * 1024, Math.max(1, Number(state.status?.max_bytes) || 12 * 1024 * 1024));
    function message(text) { $('speech-status').textContent = text; }
    function render() {
      const recording = state.phase === 'recording';
      const busy = ['permission', 'recording', 'stopping', 'transcribing'].includes(state.phase);
      $('speech-record').disabled = state.disposed || !state.composerAvailable || ['permission', 'stopping', 'transcribing'].includes(state.phase);
      $('speech-record').classList.toggle('recording', recording);
      $('speech-record').setAttribute('aria-label', recording ? 'Остановить запись и распознать речь' : ready() ? 'Продиктовать сообщение' : 'Настроить голосовой ввод');
      $('speech-record').title = recording ? 'Стоп и распознать' : ready() ? 'Продиктовать сообщение' : 'Настроить голосовой ввод';
      $('speech-recording').hidden = !recording;
      $('speech-language').disabled = busy;
      $('speech-cancel').textContent = busy ? 'Отменить' : 'Закрыть';
      $('speech-retry').hidden = state.phase !== 'error' || !state.blob;
      $('speech-new').hidden = !ready() || busy || !mediaSupported() || !state.composerAvailable;
      $('speech-setup').hidden = ready() || state.status?.setup_available !== true;
      $('speech-setup').disabled = runningSetup();
      $('speech-setup').textContent = runningSetup() ? 'Устанавливаем…' : 'Установить голосовой ввод';
      $('speech-refresh').disabled = busy;
      const command = typeof state.status?.setup_command === 'string' ? state.status.setup_command : '';
      $('speech-guide').hidden = !command || ready();
      $('speech-setup-command').textContent = command;
    }
    function stopTracks() {
      if (state.stream) for (const track of state.stream.getTracks()) track.stop();
      state.stream = null;
    }
    function stopTimer() { clearInterval(state.timer); clearTimeout(state.deadline); state.timer = null; state.deadline = null; }
    function clearPreview() {
      const audio = $('speech-preview'); audio.pause(); audio.removeAttribute('src'); audio.hidden = true;
      if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
      state.previewUrl = null;
    }
    function clearRecording() {
      state.blob = null; state.chunks = []; state.bytes = 0; clearPreview();
    }
    function showIdleStatus() {
      if (runningSetup()) message('Подготавливаем локальное распознавание. Текстовый чат доступен во время установки.');
      else if (ready() && !mediaSupported()) message('Браузер не поддерживает запись микрофона на этой странице. Можно продолжить текстом.');
      else if (ready()) message(`Можно продиктовать до ${limitSeconds()} секунд. После распознавания проверьте текст перед отправкой.`);
      else if (state.status?.setup?.error) message(state.status.setup.error);
      else message('Голосовой ввод пока не готов. Установите локальное распознавание или продолжите текстом.');
    }
    async function refresh() {
      try {
        const response = await request('/api/speech/status', {cache:'no-store'});
        const result = await response.json();
        if (state.disposed) return;
        state.status = result;
        if (['idle', 'unavailable'].includes(state.phase)) showIdleStatus();
        render();
        clearTimeout(state.setupTimer);
        if (runningSetup()) state.setupTimer = setTimeout(refresh, 1500);
      } catch {
        if (state.disposed) return;
        state.status = {status:'unavailable', available:false};
        if (['idle', 'unavailable'].includes(state.phase)) message('Не удалось проверить распознавание. Текстовый чат продолжает работать.');
        render();
      }
    }
    function cancel({hide = true} = {}) {
      state.token += 1;
      state.controller?.abort(); state.controller = null;
      const recorder = state.recorder; state.recorder = null;
      if (recorder && recorder.state !== 'inactive') { try { recorder.stop(); } catch {} }
      stopTracks(); stopTimer(); clearRecording();
      state.phase = 'idle'; state.snapshot = null;
      $('speech-result').hidden = true; $('speech-transcript').value = '';
      if (hide) $('speech-panel').hidden = true;
      showIdleStatus(); render();
    }
    function transcriptionError(error) {
      if (typeof error?.detail === 'string' && error.detail.trim()) return error.detail;
      if (error?.name === 'AbortError') return 'Распознавание не успело закончиться. Запись сохранена на странице; можно повторить.';
      if (error?.status === 409) return 'Распознавание сейчас занято. Запись осталась на странице; повторите чуть позже.';
      if (error?.status === 413) return 'Запись слишком большая. Сделайте новую, покороче.';
      return 'Не удалось распознать речь. Запись осталась на странице: можно повторить или напечатать сообщение.';
    }
    async function transcribe() {
      if (!state.blob || state.phase === 'transcribing' || state.disposed) return;
      const token = state.token;
      const controller = new AbortController(); state.controller = controller;
      const timer = setTimeout(() => controller.abort(), 180000);
      state.phase = 'transcribing'; message('Распознаю речь на этом компьютере…'); render();
      try {
        const response = await request('/api/speech/transcribe', {
          method:'POST', headers:{'Content-Type':state.blob.type, 'X-Speech-Language':$('speech-language').value || 'auto'},
          body:state.blob, signal:controller.signal
        });
        const result = await response.json();
        if (token !== state.token || state.disposed) return;
        if (typeof result.text !== 'string' || !result.text.trim() || result.text.length > MAX_TEXT || result.backend !== 'whisper.cpp' || result.evidence_policy !== 'transcript_only') throw new Error('Invalid transcription');
        const transcript = result.text;
        const inserted = state.snapshot?.text === '' && applyDraft(transcript, {mode:'if-empty', snapshot:state.snapshot});
        clearRecording(); state.phase = 'done';
        $('speech-transcript').value = transcript;
        $('speech-result').hidden = inserted;
        message(inserted ? 'Текст добавлен в черновик. Проверьте его и отправьте, когда будете готовы.' : 'Черновик сохранён. Проверьте распознанный текст ниже и добавьте его, если нужно.');
        render();
      } catch (error) {
        if (token !== state.token || state.disposed) return;
        state.phase = 'error'; message(transcriptionError(error)); render();
      } finally {
        clearTimeout(timer);
        if (state.controller === controller) state.controller = null;
      }
    }
    async function startRecording() {
      if (state.disposed || !state.composerAvailable || ['permission', 'recording', 'stopping', 'transcribing'].includes(state.phase)) return;
      $('speech-panel').hidden = false;
      if (!ready() || !mediaSupported()) { showIdleStatus(); render(); return; }
      cancel({hide:false}); stopSpeaking();
      const token = state.token;
      state.snapshot = {...getDraft()}; state.phase = 'permission';
      message('Разрешите браузеру использовать микрофон. Запись начнётся после разрешения.'); render();
      try {
        const stream = await navigator.mediaDevices.getUserMedia({audio:true, video:false});
        if (token !== state.token || state.disposed) { stream.getTracks().forEach(track => track.stop()); return; }
        state.stream = stream;
        const accepted = new Set((state.status.accepted_mime_types || []).map(baseType));
        const mime = recordingTypes.find(type => accepted.has(baseType(type)) && window.MediaRecorder.isTypeSupported(type));
        const recorder = mime ? new window.MediaRecorder(stream, {mimeType:mime}) : new window.MediaRecorder(stream);
        if (!accepted.has(baseType(recorder.mimeType))) throw new Error('Unsupported recording format');
        state.recorder = recorder; state.chunks = []; state.bytes = 0; state.overflow = false;
        recorder.addEventListener('dataavailable', event => {
          if (token !== state.token || !event.data?.size) return;
          state.bytes += event.data.size;
          if (state.bytes > limitBytes()) { state.overflow = true; stopRecording(); return; }
          state.chunks.push(event.data);
        });
        recorder.addEventListener('error', () => {
          if (token !== state.token) return;
          state.token += 1; stopTracks(); stopTimer(); clearRecording(); state.recorder = null;
          state.phase = 'error'; message('Браузер не смог закончить запись. Черновик не изменился. Попробуйте ещё раз.'); render();
        });
        recorder.addEventListener('stop', () => {
          if (token !== state.token || state.disposed) return;
          stopTracks(); stopTimer();
          state.recorder = null;
          if (state.overflow) { clearRecording(); state.phase = 'error'; message('Запись слишком большая. Сделайте новую, покороче.'); render(); return; }
          state.blob = new Blob(state.chunks, {type:recorder.mimeType}); state.chunks = [];
          if (!state.blob.size) { clearRecording(); state.phase = 'error'; message('Запись пустая. Проверьте микрофон и попробуйте ещё раз.'); render(); return; }
          state.previewUrl = URL.createObjectURL(state.blob);
          $('speech-preview').src = state.previewUrl; $('speech-preview').hidden = false;
          transcribe();
        });
        recorder.start(500); state.phase = 'recording'; state.startedAt = Date.now();
        $('speech-timer').textContent = '00:00';
        message(`Скажите сообщение и нажмите «Стоп». Запись остановится через ${limitSeconds()} секунд.`); render();
        state.timer = setInterval(() => {
          const elapsed = Math.floor((Date.now() - state.startedAt) / 1000);
          $('speech-timer').textContent = formatTime(Math.min(elapsed, limitSeconds()));
          if (elapsed >= limitSeconds()) stopRecording();
        }, 250);
        state.deadline = setTimeout(stopRecording, Math.max(100, limitSeconds() * 1000 - 300));
      } catch (error) {
        if (token !== state.token || state.disposed) return;
        stopTracks(); stopTimer(); state.recorder = null; state.phase = 'error';
        message(error?.name === 'NotAllowedError' || error?.name === 'SecurityError' ? 'Доступ к микрофону не разрешён. Можно включить его в настройках браузера или продолжить текстом.' : 'Не удалось включить микрофон. Проверьте устройство или продолжите текстом.'); render();
      }
    }
    function stopRecording() {
      if (state.recorder?.state === 'recording') {
        state.phase = 'stopping'; stopTimer();
        message('Запись остановлена. Готовлю распознавание…'); render();
        try { state.recorder.stop(); } catch { stopTracks(); state.phase = 'error'; message('Не удалось закончить запись. Черновик не изменился.'); render(); }
      }
    }
    async function setup() {
      if (state.disposed || runningSetup()) return;
      $('speech-panel').hidden = false; $('speech-setup').disabled = true;
      message('Подготавливаем локальное распознавание. Потребуется скачать программу и модель на этот компьютер.');
      try {
        const response = await request('/api/speech/setup', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const result = await response.json();
        if (result.accepted !== true) throw new Error('Setup not acknowledged');
        state.status = {...state.status, status:'installing', setup:{running:true}};
        render(); await refresh();
      } catch (error) { message(typeof error?.detail === 'string' ? error.detail : 'Не удалось начать установку. Проверьте доступность или воспользуйтесь ручной установкой.'); $('speech-setup').disabled = false; }
    }
    function speechParts(text) {
      const forced = $('speech-read-language').value;
      const parts = [];
      const readable = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/\*\*/g, '');
      for (const block of readable.split(/(`[^`]+`)/g)) {
        const clean = block.replace(/^`|`$/g, '').trim();
        if (!clean) continue;
        for (const line of clean.split(/\n+/)) {
          const cyrillic = (line.match(/[А-Яа-яЁё]/g) || []).length;
          const latin = (line.match(/[A-Za-z]/g) || []).length;
          const language = forced === 'en' ? 'en-US' : forced === 'ru' ? 'ru-RU' : cyrillic > latin ? 'ru-RU' : 'en-US';
          const words = line.split(/\s+/); let chunk = '';
          for (const word of words) {
            if (chunk && chunk.length + word.length > 240) { parts.push({text:chunk, language}); chunk = ''; }
            chunk += (chunk ? ' ' : '') + word;
          }
          if (chunk) parts.push({text:chunk, language});
        }
      }
      return parts;
    }
    function stopSpeaking() {
      state.speechToken += 1;
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      state.speechCallback?.(false); state.speechCallback = null;
    }
    function speak(text, onState = () => {}) {
      if (['permission', 'recording', 'stopping'].includes(state.phase)) { notice('Сначала остановите или отмените запись микрофона.'); return; }
      stopSpeaking();
      if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) { notice('В этом браузере озвучивание недоступно. Текст ответа остаётся в чате.'); return; }
      if (typeof text !== 'string' || !text.trim() || text.length > MAX_TEXT) { notice('Для озвучивания выберите ответ не длиннее 16 000 символов.'); return; }
      const voices = window.speechSynthesis.getVoices().filter(voice => voice.localService === true);
      const parts = speechParts(text).map(part => ({...part,voice:voices.find(voice => voice.lang === part.language) || voices.find(voice => voice.lang?.startsWith(part.language.slice(0, 2)))}));
      if (parts.some(part => !part.voice)) { notice('В браузере не найден локальный голос для этого языка. Установите системный голос или выберите другой язык в меню «Голос».'); return; }
      const token = state.speechToken;
      state.speechCallback = onState; onState(true);
      function next(index) {
        if (token !== state.speechToken || state.disposed) return;
        if (index >= parts.length) { state.speechCallback?.(false); state.speechCallback = null; return; }
        const part = parts[index];
        const utterance = new window.SpeechSynthesisUtterance(part.text); utterance.lang = part.language;
        utterance.voice = part.voice;
        utterance.onend = () => next(index + 1);
        utterance.onerror = () => { if (token === state.speechToken) { stopSpeaking(); notice('Не удалось озвучить ответ. Проверьте голос браузера или попробуйте другой язык в меню «Голос».'); } };
        window.speechSynthesis.speak(utterance);
      }
      next(0);
    }
    function dispose() {
      cancel(); stopSpeaking(); clearTimeout(state.setupTimer); state.disposed = true;
    }
    $('speech-record').addEventListener('click', () => {
      if (state.phase === 'recording') stopRecording();
      else if (['error', 'done'].includes(state.phase)) { $('speech-panel').hidden = false; render(); }
      else startRecording();
    });
    $('speech-options').addEventListener('click', () => { $('speech-panel').hidden = false; if (state.phase === 'idle') refresh(); });
    $('speech-stop').addEventListener('click', stopRecording);
    $('speech-cancel').addEventListener('click', () => cancel());
    $('speech-new').addEventListener('click', startRecording);
    $('speech-retry').addEventListener('click', transcribe);
    $('speech-refresh').addEventListener('click', refresh);
    $('speech-setup').addEventListener('click', setup);
    $('speech-append').addEventListener('click', () => {
      const text = $('speech-transcript').value;
      if (!text.trim()) { message('Распознанный текст пуст. Можно сделать новую запись.'); return; }
      if (applyDraft(text, {mode:'append'})) { $('speech-result').hidden = true; message('Текст добавлен к черновику. Проверьте его перед отправкой.'); }
      else message('Текст не добавлен. В черновике может быть не больше 16 000 символов.');
    });
    const controller = {
      ready: refresh(), refresh, cancel, dispose, speak, stopSpeaking,
      canSpeak: () => !!(window.speechSynthesis && window.SpeechSynthesisUtterance),
      setComposerAvailable(available) { state.composerAvailable = available === true; render(); }
    };
    return controller;
  }
  window.TutorSpeech = {create};
})();
