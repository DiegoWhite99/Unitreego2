/* ========================================
   Diver - Agente IA (chat con Gemini + visión YOLO en vivo)
   Conecta el frontend al backend /api/agente/chat y lista detecciones
   en tiempo real desde /api/yolo/detections.
   ======================================== */

const API_BASE = window.location.origin;

const AGENT = {
    socket: null,
    state: {
        serverConnected: false,
        robotConnected: false,
        yoloRunning: false,
        yoloFalseStreak: 0,   // protege contra hipos transitorios del backend
        streamAttached: false,// evita re-asignar img.src y causar blink
        aiReady: false,
        history: [],          // mensajes para enviar contexto al backend
        voice: {
            recognition: null,
            listening: false,
            ttsEnabled: false,
            ttsSpeaking: false,
            voice: null,       // SpeechSynthesisVoice elegida (masculina ES)
            micHint: null
        },
        gestureReact: false,
        faceGreeting: true,
        sessionActive: false  // true mientras hay conversación activa con Diver
    },
    el: {},
    detectPollTimer: null,
    statusPollTimer: null,

    init() {
        this.cacheElements();
        this.setupSocket();
        this.setupChat();
        this.setupWakeButton();
        this.setupVoice();
        this.setupWakeWord();
        this.setupGestureReactor();
        this.setupFaceGreetingReactor();
        this.checkAiHealth();
        // Si YOLO ya está corriendo, engancharse al stream automáticamente
        this.refreshYoloAndAttach();
        this.startDetectionsPolling();
    },

    cacheElements() {
        this.el = {
            video: document.getElementById('ag-video'),
            placeholder: document.getElementById('ag-video-placeholder'),
            wake: document.getElementById('ag-wake'),
            statusServer: document.getElementById('ag-status-server'),
            statusRobot:  document.getElementById('ag-status-robot'),
            statusYolo:   document.getElementById('ag-status-yolo'),
            statusAi:     document.getElementById('ag-status-ai'),
            mFps: document.getElementById('ag-m-fps'),
            mCount: document.getElementById('ag-m-count'),
            mBattery: document.getElementById('ag-m-battery'),
            detectList: document.getElementById('ag-detect-list'),
            detectSummary: document.getElementById('ag-detect-summary'),
            watchOverlay: document.querySelector('.ag-watch-overlay'),
            messages: document.getElementById('ag-messages'),
            input: document.getElementById('ag-input'),
            form: document.getElementById('ag-form'),
            send: document.getElementById('ag-send'),
            clear: document.getElementById('ag-clear'),
            suggestions: document.getElementById('ag-suggestions'),
            banner: document.getElementById('ag-banner'),
            mic: document.getElementById('ag-mic'),
            wakeWordBtn: document.getElementById('ag-wakeword-btn'),
            ttsToggle: document.getElementById('ag-tts-toggle'),
            voiceSelect: document.getElementById('ag-voice-select'),
            gestureToggle: document.getElementById('ag-gesture-toggle'),
            faceToggle: document.getElementById('ag-face-toggle')
        };
    },

    /* ============ Conexión / sockets ============ */
    setupSocket() {
        if (typeof io === 'undefined') return;
        this.socket = io(API_BASE, { transports: ['websocket', 'polling'] });

        this.socket.on('connect', () => this._setStatus('statusServer', true, 'Servidor'));
        this.socket.on('disconnect', () => this._setStatus('statusServer', false, 'Servidor'));

        this.socket.on('robot_connected', () => this._setStatus('statusRobot', true, 'Robot'));
        this.socket.on('robot_disconnected', () => this._setStatus('statusRobot', false, 'Robot'));

        this.socket.on('state_update', (data) => {
            if (typeof data?.battery === 'number') {
                this.el.mBattery.textContent = `${data.battery}%`;
            }
            if (typeof data?.connected === 'boolean') {
                this._setStatus('statusRobot', data.connected, 'Robot');
                this.state.robotConnected = data.connected;
            }
        });
    },

    _setStatus(key, connected, label) {
        const el = this.el[key];
        if (!el) return;
        el.classList.remove('connected', 'disconnected', 'connecting');
        el.classList.add(connected ? 'connected' : 'disconnected');
        const txt = el.querySelector('.txt');
        if (txt) txt.textContent = label;
    },

    /* ============ Vista YOLO ============ */
    async refreshYoloAndAttach() {
        try {
            const r = await fetch(`${API_BASE}/api/yolo/status`).then(r => r.json());
            if (r && r.running) {
                this.state.yoloRunning = true;
                this._setStatus('statusYolo', true, 'Visión');
                this.attachYoloStream(r.fps);
            } else {
                this._setStatus('statusYolo', false, 'Visión');
            }
        } catch (e) { /* sin servidor aún */ }
    },

    attachYoloStream(fps) {
        const img = this.el.video;
        if (!img) return;
        // Solo asignar src la PRIMERA vez (o tras un detach explícito).
        // Re-asignarlo causa blink/intermitencia porque obliga al browser
        // a soltar la conexión MJPEG y abrir otra.
        if (!this.state.streamAttached) {
            img.src = `${API_BASE}/api/yolo/stream`;
            img.style.display = 'block';
            this.state.streamAttached = true;

            // Si el browser tira la conexión (timeout, error de red), reintentar
            // UNA vez tras 1.5s en lugar de quedarse en placeholder.
            img.onerror = () => {
                console.warn('[AGENTE] Stream MJPEG falló, reintentando…');
                this.state.streamAttached = false;
                clearTimeout(this._reattachTimer);
                this._reattachTimer = setTimeout(() => {
                    if (this.state.yoloRunning) this.attachYoloStream();
                }, 1500);
            };
        }
        if (this.el.placeholder) this.el.placeholder.style.display = 'none';
        if (typeof fps === 'number') this.el.mFps.textContent = fps.toFixed(1);
        if (this.el.watchOverlay) this.el.watchOverlay.classList.add('visible');
    },

    detachYoloStream() {
        if (this.el.video) {
            this.el.video.onerror = null;
            this.el.video.src = '';
            this.el.video.style.display = 'none';
        }
        if (this.el.placeholder) this.el.placeholder.style.display = 'flex';
        if (this.el.watchOverlay) this.el.watchOverlay.classList.remove('visible');
        this.state.streamAttached = false;
    },

    setupWakeButton() {
        this.el.wake?.addEventListener('click', async () => {
            this.el.wake.disabled = true;
            this.el.wake.textContent = 'Despertando…';
            try {
                const r = await fetch(`${API_BASE}/api/yolo/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source: this.state.robotConnected ? 'robot' : 'webcam',
                        camera_index: 0,
                        conf: 0.4,
                        // Modelo pose: detecta personas + 17 keypoints +
                        // gestos derivados (mano_arriba, sentado, etc.)
                        model: 'yolov8n-pose.pt',
                        imgsz: 416,
                        with_objects: false
                    })
                }).then(r => r.json());
                if (r && r.status === 'ok') {
                    this.state.yoloRunning = true;
                    this.state.yoloFalseStreak = 0;
                    this._setStatus('statusYolo', true, 'Visión');
                    this.attachYoloStream();
                } else {
                    this._showBanner(`No pude activar la visión: ${r?.message || 'desconocido'}`, 'error');
                    this.el.wake.disabled = false;
                    this.el.wake.textContent = 'Activar visión';
                }
            } catch (e) {
                this._showBanner('Error contactando al servidor.', 'error');
                this.el.wake.disabled = false;
                this.el.wake.textContent = 'Activar visión';
            }
        });
    },

    /* ============ Voz: STT (micrófono) + TTS (voz natural masculina) ====
       STT: Web Speech Recognition (Chrome/Edge). Click → escucha →
            transcribe al input → envía automáticamente al soltar.
       TTS: Web Speech Synthesis con voz masculina española natural
            (Microsoft Neural / Pablo / Jorge / Diego), tono parejo y
            tasa normal. Sin pitch hundido ni patrones robóticos. */
    setupVoice() {
        // Restaurar preferencia de voz
        try {
            if (localStorage.getItem('diver_tts_enabled') === '1') {
                this.state.voice.ttsEnabled = true;
            }
        } catch (e) { /* localStorage bloqueado, ignoramos */ }
        this._renderTtsButton();

        // ── Speech Synthesis: voz LATINA masculina + selector manual ──
        // Estrategia: priorizamos español de Latinoamérica (es-MX, es-AR,
        // es-CO, es-US, es-419) sobre español de España (es-ES). Dentro
        // de eso, voces neuronales > masculinas conocidas > resto. El
        // operador puede sobrescribir con el dropdown del header.
        if ('speechSynthesis' in window) {
            const LATIN_RE = /^es-(MX|AR|CO|US|419|CL|PE|VE|UY|PY|BO|EC|HN|GT|NI|CR|PA|DO|PR|SV)/i;
            const SPAIN_RE = /^es-ES/i;
            const naturalPatterns = [
                /natural/i, /neural/i, /online/i, /studio/i, /wavenet/i
            ];
            const malePatterns = [
                /pablo/i, /diego/i, /jorge/i, /juan/i, /carlos/i,
                /andr[eé]s/i, /[aá]lvaro/i, /javier/i, /mateo/i,
                /miguel/i, /ra[uú]l/i, /alex/i, /enrique/i, /ricardo/i,
                /sebasti[aá]n/i, /lorenzo/i, /tom[aá]s/i, /pedro/i,
                /daniel/i, /antonio/i, /\bgonzalo\b/i, /\bf[eé]lix\b/i,
                /\bmateo\b/i, /\bdavid\b/i, /\bmark\b/i, /\bguy\b/i
            ];

            const autoPick = (voices) => {
                const latin = voices.filter(v => LATIN_RE.test(v.lang || ''));
                const spain = voices.filter(v => SPAIN_RE.test(v.lang || ''));
                const otherEs = voices.filter(v =>
                    /^es/i.test(v.lang || '') && !latin.includes(v) && !spain.includes(v));

                const findBest = (pool) => {
                    return pool.find(v =>
                        malePatterns.some(p => p.test(v.name || '')) &&
                        naturalPatterns.some(p => p.test(v.name || ''))
                    ) || pool.find(v => naturalPatterns.some(p => p.test(v.name || '')))
                      || pool.find(v => malePatterns.some(p => p.test(v.name || '')))
                      || pool.find(v => /male/i.test(v.name || ''))
                      || pool[0]
                      || null;
                };
                return findBest(latin) || findBest(otherEs) || findBest(spain) || voices[0] || null;
            };

            const fillSelect = (voices, currentName) => {
                const sel = this.el.voiceSelect;
                if (!sel) return;
                while (sel.options.length > 1) sel.remove(1);
                const latin = voices.filter(v => LATIN_RE.test(v.lang || ''));
                const spain = voices.filter(v => SPAIN_RE.test(v.lang || ''));
                const otherEs = voices.filter(v =>
                    /^es/i.test(v.lang || '') && !latin.includes(v) && !spain.includes(v));
                const addGroup = (label, pool) => {
                    if (!pool.length) return;
                    const og = document.createElement('optgroup');
                    og.label = label;
                    pool.forEach(v => {
                        const o = document.createElement('option');
                        o.value = v.name;
                        o.textContent = `${v.name} · ${v.lang}`;
                        if (v.name === currentName) o.selected = true;
                        og.appendChild(o);
                    });
                    sel.appendChild(og);
                };
                addGroup('Latinoamérica', latin);
                addGroup('España', spain);
                addGroup('Otras español', otherEs);
            };

            const pickVoice = () => {
                const voices = window.speechSynthesis.getVoices() || [];
                if (!voices.length) return;

                let saved = '';
                try { saved = localStorage.getItem('diver_voice_name') || ''; } catch (e) {}
                let chosen = null;
                if (saved) chosen = voices.find(v => v.name === saved) || null;
                if (!chosen) chosen = autoPick(voices);

                this.state.voice.voice = chosen;
                fillSelect(voices, chosen ? chosen.name : '');
                if (chosen) {
                    console.log('[VOZ] elegida:', chosen.name, '/', chosen.lang);
                }
            };
            pickVoice();
            if ('onvoiceschanged' in window.speechSynthesis) {
                window.speechSynthesis.onvoiceschanged = pickVoice;
            }

            // Cambio manual desde el dropdown
            this.el.voiceSelect?.addEventListener('change', () => {
                const name = this.el.voiceSelect.value;
                const voices = window.speechSynthesis.getVoices() || [];
                if (!name) {
                    // "Auto"
                    try { localStorage.removeItem('diver_voice_name'); } catch (e) {}
                    this.state.voice.voice = autoPick(voices);
                } else {
                    const v = voices.find(x => x.name === name);
                    if (v) {
                        this.state.voice.voice = v;
                        try { localStorage.setItem('diver_voice_name', name); } catch (e) {}
                    }
                }
                // Pequeño preview para que el usuario escuche el cambio
                if (this.state.voice.ttsEnabled) {
                    this.speakReply('Voz lista.');
                }
            });
        }

        // ── Toggle TTS ──
        this.el.ttsToggle?.addEventListener('click', () => {
            if (!('speechSynthesis' in window)) {
                this._showBanner('Tu navegador no soporta voz sintética. Usa Chrome o Edge.', 'warn');
                return;
            }
            this.state.voice.ttsEnabled = !this.state.voice.ttsEnabled;
            try {
                localStorage.setItem('diver_tts_enabled',
                    this.state.voice.ttsEnabled ? '1' : '0');
            } catch (e) { /* ignore */ }
            if (!this.state.voice.ttsEnabled) {
                try { window.speechSynthesis.cancel(); } catch (e) {}
            } else {
                // Pequeño "ack" auditivo para confirmar que está activa
                this.speakReply('Voz activada.');
            }
            this._renderTtsButton();
        });

        // ── Speech Recognition (entrada por voz) ──
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) {
            if (this.el.mic) {
                this.el.mic.disabled = true;
                this.el.mic.title = 'Tu navegador no soporta dictado por voz. Usa Chrome o Edge.';
            }
            return;
        }

        const recog = new SR();
        recog.lang = 'es-ES';
        recog.interimResults = true;
        recog.continuous = false;
        recog.maxAlternatives = 1;

        let lastFinal = '';

        recog.onresult = (ev) => {
            let interim = '';
            for (let i = ev.resultIndex; i < ev.results.length; i++) {
                const r = ev.results[i];
                if (r.isFinal) lastFinal += r[0].transcript;
                else interim += r[0].transcript;
            }
            if (interim) this._showMicHint(interim);
            if (lastFinal) this._showMicHint(lastFinal, true);
        };
        recog.onerror = (ev) => {
            this.state.voice.listening = false;
            this._renderMicButton();
            this._hideMicHint();
            const code = ev.error || '';
            if (code === 'not-allowed' || code === 'service-not-allowed') {
                this._showBanner('Permiso de micrófono denegado. Habilítalo en el navegador.', 'error');
            } else if (code && code !== 'aborted' && code !== 'no-speech') {
                this._showBanner('Error de voz: ' + code, 'error');
            }
        };
        recog.onend = () => {
            this.state.voice.listening = false;
            this._renderMicButton();
            this._hideMicHint();
            const text = lastFinal.trim();
            lastFinal = '';
            if (text) {
                this.el.input.value = text;
                this.sendMessage();
            }
            // Reanuda el oyente de wake word cuando termina la sesión de chat
            this._restartWakeWord?.();
        };

        this.state.voice.recognition = recog;

        this.el.mic?.addEventListener('click', () => {
            if (this.state.voice.listening) {
                try { recog.stop(); } catch (e) {}
                return;
            }
            // Pausar TTS para no auto-escucharse
            try { window.speechSynthesis?.cancel(); } catch (e) {}
            this.el.input.value = '';
            lastFinal = '';
            try {
                recog.start();
                this.state.voice.listening = true;
                this._renderMicButton();
                this._showMicHint('Escuchando…');
            } catch (e) {
                console.warn('No pude iniciar reconocimiento:', e);
                this.state.voice.listening = false;
                this._renderMicButton();
            }
        });
    },

    _renderMicButton() {
        const btn = this.el.mic;
        if (!btn) return;
        const on = this.state.voice.listening;
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.title = on ? 'Escuchando… toca para detener'
                       : 'Hablar con Diver (dictado por voz)';
    },

    /* ============ Reacción a gestos (autónoma) ============
       Al activarlo, el backend vigila las detecciones de YOLO. Cuando ve
       un gesto de saludo (mano arriba, brazos arriba), dispara la acción
       'Hello' en el robot. Recibimos un evento socket 'gesture_reaction'
       con detalles para mostrar en chat. */
    setupGestureReactor() {
        // Restaurar preferencia
        try {
            if (localStorage.getItem('diver_gesture_react') === '1') {
                this.state.gestureReact = true;
            }
        } catch (e) {}

        // Sincronizar con backend al cargar
        this._syncGestureState();

        // Click en toggle → llama API y actualiza
        this.el.gestureToggle?.addEventListener('click', () => {
            const next = !this.state.gestureReact;
            const path = next ? '/api/gestures/start' : '/api/gestures/stop';
            fetch(`${API_BASE}${path}`, { method: 'POST' })
                .then(r => r.json())
                .then(r => {
                    this.state.gestureReact = !!r.enabled;
                    try {
                        localStorage.setItem('diver_gesture_react',
                            this.state.gestureReact ? '1' : '0');
                    } catch (e) {}
                    this._renderGestureButton();
                    this._showBanner(
                        this.state.gestureReact
                            ? 'Reacción a gestos activa — saludaré si me saludan.'
                            : 'Reacción a gestos desactivada.',
                        'warn'
                    );
                })
                .catch(e => {
                    this._showBanner('No pude cambiar reacción a gestos.', 'error');
                });
        });

        // Suscribirse al evento del backend
        if (this.socket) {
            this.socket.on('gesture_reaction', (data) => {
                this._onGestureReaction(data || {});
            });
        }

        this._renderGestureButton();
    },

    _syncGestureState() {
        fetch(`${API_BASE}/api/gestures/state`).then(r => r.json())
            .then(r => {
                this.state.gestureReact = !!r.enabled;
                this._renderGestureButton();
                // Si el usuario tenía preferencia "on" y backend está "off"
                // (porque app.py se reinició), re-activamos automáticamente.
                let wantOn = false;
                try { wantOn = localStorage.getItem('diver_gesture_react') === '1'; }
                catch (e) {}
                if (wantOn && !this.state.gestureReact) {
                    fetch(`${API_BASE}/api/gestures/start`, { method: 'POST' })
                        .then(r => r.json())
                        .then(r => {
                            this.state.gestureReact = !!r.enabled;
                            this._renderGestureButton();
                        }).catch(() => {});
                }
            }).catch(() => {});
    },

    _renderGestureButton() {
        const btn = this.el.gestureToggle;
        if (!btn) return;
        const on = !!this.state.gestureReact;
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.title = on
            ? 'Reacción a gestos ACTIVA — saludaré si te veo saludar. Toca para apagar.'
            : 'Activar reacción autónoma a gestos (saluda al ver mano arriba)';
    },

    _onGestureReaction(data) {
        // Mostrar lo que pasó como mensaje del bot en el chat
        const gestureNames = {
            mano_arriba: 'mano arriba',
            ambas_manos_arriba: 'ambas manos arriba',
            brazos_arriba: 'brazos arriba',
            manos_juntas: 'manos juntas',
            t_pose: 'T-pose'
        };
        const gName = gestureNames[data.gesture] || data.gesture || 'gesto';
        const sayText = (data.say && data.ok)
            ? data.say
            : (data.ok ? `Detecté ${gName} y reaccioné.`
                       : `No pude reaccionar a ${gName}: ${data.msg || 'error'}`);
        this.appendMessage('bot', `🎯 ${sayText} (gesto: ${gName})`,
                           [{ name: data.action, ok: data.ok }]);
        if (data.ok) this.speakReply(sayText);
    },

    /* ============ Saludo por reconocimiento facial ============ */
    setupFaceGreetingReactor() {
        try {
            const stored = localStorage.getItem('diver_face_greeting');
            if (stored === '0') this.state.faceGreeting = false;
        } catch (e) {}

        this._syncFaceGreetingState();

        this.el.faceToggle?.addEventListener('click', () => {
            const next = !this.state.faceGreeting;
            const path = next ? '/api/faces/greetings/start' : '/api/faces/greetings/stop';
            fetch(`${API_BASE}${path}`, { method: 'POST' })
                .then(r => r.json())
                .then(r => {
                    this.state.faceGreeting = !!r.enabled;
                    try {
                        localStorage.setItem('diver_face_greeting',
                            this.state.faceGreeting ? '1' : '0');
                    } catch (e) {}
                    this._renderFaceGreetingButton();
                    this._showBanner(
                        this.state.faceGreeting
                            ? 'Saludo por rostro activo.'
                            : 'Saludo por rostro desactivado.',
                        'warn'
                    );
                })
                .catch(() => this._showBanner('No pude cambiar saludo por rostro.', 'error'));
        });

        if (this.socket) {
            this.socket.on('face_greeting', (data) => {
                this._onFaceGreeting(data || {});
            });
        }

        this._renderFaceGreetingButton();
    },

    _syncFaceGreetingState() {
        fetch(`${API_BASE}/api/faces/greetings/state`).then(r => r.json())
            .then(r => {
                this.state.faceGreeting = !!r.enabled;
                this._renderFaceGreetingButton();
                let wantOn = true;
                try { wantOn = localStorage.getItem('diver_face_greeting') !== '0'; }
                catch (e) {}
                if (wantOn && !this.state.faceGreeting) {
                    fetch(`${API_BASE}/api/faces/greetings/start`, { method: 'POST' })
                        .then(r => r.json())
                        .then(r => {
                            this.state.faceGreeting = !!r.enabled;
                            this._renderFaceGreetingButton();
                        }).catch(() => {});
                }
                if (!wantOn && this.state.faceGreeting) {
                    fetch(`${API_BASE}/api/faces/greetings/stop`, { method: 'POST' })
                        .then(r => r.json())
                        .then(r => {
                            this.state.faceGreeting = !!r.enabled;
                            this._renderFaceGreetingButton();
                        }).catch(() => {});
                }
            }).catch(() => {});
    },

    _renderFaceGreetingButton() {
        const btn = this.el.faceToggle;
        if (!btn) return;
        const on = !!this.state.faceGreeting;
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.title = on
            ? 'Saludo por rostro ACTIVO — diré hola al reconocer a alguien.'
            : 'Activar saludo automático al reconocer rostros registrados';
    },

    _onFaceGreeting(data) {
        const name = data.person_name || 'alguien conocido';
        const sayText = data.say || `Hola, ${name}.`;
        this.appendMessage('bot', sayText, [{ name: 'face_greeting', ok: true }]);
        this.state.history.push({ role: 'model', text: sayText });
        this.speakReply(sayText);
    },

    _renderTtsButton() {
        const btn = this.el.ttsToggle;
        if (!btn) return;
        const on = !!this.state.voice.ttsEnabled;
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.title = on ? 'Voz activa — toca para silenciar'
                       : 'Activar voz robótica de Diver';
        const onIcon = btn.querySelector('.ag-tts-on');
        const offIcon = btn.querySelector('.ag-tts-off');
        if (onIcon)  onIcon.style.display  = on ? 'block' : 'none';
        if (offIcon) offIcon.style.display = on ? 'none'  : 'block';
    },

    _showMicHint(text, isFinal) {
        if (!this.el.mic) return;
        if (!this.state.voice.micHint) {
            const hint = document.createElement('div');
            hint.className = 'ag-mic-hint';
            this.el.mic.style.position = this.el.mic.style.position || 'relative';
            this.el.mic.appendChild(hint);
            this.state.voice.micHint = hint;
        }
        this.state.voice.micHint.textContent = (text || '…').slice(0, 80);
        if (isFinal) {
            clearTimeout(this._micHintTimer);
            this._micHintTimer = setTimeout(() => this._hideMicHint(), 700);
        }
    },

    _hideMicHint() {
        if (this.state.voice.micHint) {
            this.state.voice.micHint.remove();
            this.state.voice.micHint = null;
        }
    },

    _playRobotBeep(freq, ms) {
        // Pitido corto sintético — añade carácter robótico antes/después
        // del habla (estilo R2D2 / "compute"). Usa Web Audio API y se
        // limpia solo. Si AudioContext no existe en este browser, no hace nada.
        try {
            if (!this._audioCtx) {
                const Ctx = window.AudioContext || window.webkitAudioContext;
                if (!Ctx) return;
                this._audioCtx = new Ctx();
            }
            const ctx = this._audioCtx;
            // Algunos browsers suspenden el contexto hasta interacción
            if (ctx.state === 'suspended') { try { ctx.resume(); } catch (e) {} }
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'square';        // square = más sintético
            osc.frequency.value = freq;
            gain.gain.value = 0.0001;   // attack rápido para evitar click
            osc.connect(gain);
            gain.connect(ctx.destination);
            const now = ctx.currentTime;
            gain.gain.exponentialRampToValueAtTime(0.08, now + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + ms / 1000);
            osc.start(now);
            osc.stop(now + ms / 1000 + 0.05);
        } catch (e) { /* fail silently */ }
    },

    speakReply(text) {
        if (!this.state.voice.ttsEnabled) return;
        if (!('speechSynthesis' in window)) return;
        if (!text) return;
        try {
            // Quitar emojis y signos extraños — la voz no debe leerlos
            const clean = String(text)
                .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}🐾]/gu, '')
                .replace(/[`*_~]+/g, '')
                .replace(/\s+/g, ' ')
                .trim();
            if (!clean) return;
            try { window.speechSynthesis.cancel(); } catch (e) {}
            const utt = new SpeechSynthesisUtterance(clean);
            // Forzar idioma español aunque la voz por defecto sea otra
            utt.lang = (this.state.voice.voice && this.state.voice.voice.lang) || 'es-ES';
            if (this.state.voice.voice) utt.voice = this.state.voice.voice;
            // Tono natural: pitch 1.0 (la voz ya es masculina latina por
            // selección), rate apenas por debajo de 1 para cadencia
            // colombiana. Sin pitch hundido — eso suena robótico.
            utt.pitch  = 1.0;
            utt.rate   = 0.98;
            utt.volume = 1.0;
            utt.onstart = () => {
                this.state.voice.ttsSpeaking = true;
                this.el.ttsToggle?.classList.add('speaking');
                this._sessionRecog?.pause(); // pausa escucha mientras Diver habla
            };
            const stop = () => {
                this.state.voice.ttsSpeaking = false;
                this.el.ttsToggle?.classList.remove('speaking');
                const action = this._postSpeakAction;
                this._postSpeakAction = null;
                action?.();
                this._sessionRecog?.resume(); // reanuda escucha cuando termina
            };
            utt.onend = stop;
            utt.onerror = stop;
            window.speechSynthesis.speak(utt);
        } catch (e) {
            console.warn('TTS error:', e);
        }
    },

    /* ============ Voz unificada ============
       Un solo reconocedor continuo.
       Azul encendido → mic encendido.
       Modo wake: espera "Diver".
       Modo sesión: escucha todo, pausa solo mientras Diver habla,
       termina con "adiós Diver". */
    setupWakeWord() {
        const SR  = window.SpeechRecognition || window.webkitSpeechRecognition;
        const btn = this.el.wakeWordBtn;
        const mic = this.el.mic;
        if (!SR) { btn?.remove(); return; }

        let on      = false;   // sistema encendido
        let session = false;   // false=wake word mode, true=sesión activa
        let tts     = false;   // true mientras Diver está hablando
        let recog   = null;
        let _pending = false;  // true mientras hay fetch o TTS en curso

        const ui = () => {
            btn?.setAttribute('aria-pressed', String(on));
            if (btn) btn.style.color = on ? 'var(--accent,#4f8ef7)' : '';
            mic?.setAttribute('aria-pressed', String(on && !tts));
        };

        const kill = () => { try { recog?.abort(); } catch (_) {} recog = null; };

        const go = () => {
            kill();
            if (!on || tts || _pending) return;

            const r = new SR();
            r.lang            = 'es-ES';
            r.continuous      = true;
            r.interimResults  = true;
            r.maxAlternatives = 1;

            r.onresult = (ev) => {
                if (tts) return;
                for (let i = ev.resultIndex; i < ev.results.length; i++) {
                    const t     = ev.results[i][0].transcript.trim();
                    const final = ev.results[i].isFinal;

                    if (!session) {
                        // ── Wake word mode ──
                        if (/\bdiver\b/i.test(t)) {
                            session = true;
                            this.state.sessionActive    = true;
                            this.state.voice.ttsEnabled = true;
                            kill(); _pending = true; // detener escucha hasta que llegue respuesta + TTS
                            this.el.input.value = 'DIVER';
                            this.sendMessage();
                        }
                    } else if (final && t && !_pending) {
                        // ── Sesión activa ──
                        if (/(\badi[oó]s\b|\bchao\b|\bbye\b)[\s\S]*\bdiver\b|\bdiver\b[\s\S]*(\badi[oó]s\b|\bchao\b|\bbye\b)/i.test(t)) {
                            // Despedida → apagar todo
                            on = false; session = false; _pending = false;
                            this.state.sessionActive    = false;
                            this.state.voice.ttsEnabled = false;
                            this.el.input.value = t;
                            this.sendMessage();
                            kill(); ui(); return;
                        }
                        kill(); _pending = true; // detener escucha hasta que llegue respuesta + TTS
                        this.el.input.value = t;
                        this.sendMessage();
                    }
                }
            };

            r.onerror = (ev) => {
                if (ev.error === 'no-speech') return; // silencio normal, sigue
                recog = null;
                if (on && !tts && !_pending) setTimeout(go, 600);
            };
            r.onend = () => {
                recog = null;
                if (on && !tts && !_pending) setTimeout(go, 200); // reinicio automático
            };

            try { r.start(); recog = r; ui(); }
            catch (e) { recog = null; if (on) setTimeout(go, 1000); }
        };

        // speakReply.onstart/stop llaman a estos
        this._sessionRecog = {
            pause:  () => { tts = true;  kill(); ui(); },
            resume: () => { tts = false; _pending = false; if (on) setTimeout(go, 400); ui(); },
            stop:   () => {}
        };

        btn?.addEventListener('click', () => {
            on = !on;
            if (!on) { session = false; tts = false; _pending = false; this.state.sessionActive = false; kill(); }
            else go();
            ui();
        });

        this._restartWakeWord = () => {};
    },

    /* ============ Polling detecciones YOLO ============
       Dos timers separados para no saturar el navegador:
       - Detecciones: cada 1.5s (rápido, lista en pantalla)
       - Status (fps): cada 4s (lento, métrica de feedback)
       Ya no llamamos a `/api/yolo/status` y `/api/yolo/detections` en paralelo
       cada segundo — eso causaba intermitencia en el MJPEG por presión
       de conexiones (Chrome topea a 6 por origen).

       /api/yolo/detections ya retorna {running, detections}, así que es
       la única fuente para detectar transiciones de estado. */
    startDetectionsPolling() {
        clearInterval(this.detectPollTimer);
        clearInterval(this.statusPollTimer);

        // Polling rápido: detecciones + estado de running
        this.detectPollTimer = setInterval(async () => {
            try {
                const det = await fetch(`${API_BASE}/api/yolo/detections`)
                    .then(r => r.json()).catch(() => null);
                if (!det) return;

                const running = !!det.running;
                if (running) {
                    this.state.yoloFalseStreak = 0;
                    if (!this.state.yoloRunning) {
                        this.state.yoloRunning = true;
                        this._setStatus('statusYolo', true, 'Visión');
                    }
                    if (!this.state.streamAttached) this.attachYoloStream();
                } else {
                    // Anti-flicker: solo aceptamos "no running" tras 3 lecturas
                    // consecutivas en falso (≈4.5s). Evita tirar el stream por
                    // un hipo del backend.
                    this.state.yoloFalseStreak += 1;
                    if (this.state.yoloFalseStreak >= 3 && this.state.yoloRunning) {
                        this.state.yoloRunning = false;
                        this._setStatus('statusYolo', false, 'Visión');
                        this.detachYoloStream();
                    }
                }
                if (Array.isArray(det.detections)) {
                    this.renderDetections(det.detections);
                }
            } catch (e) { /* ignore */ }
        }, 1500);

        // Polling lento: solo para refrescar el contador de FPS
        this.statusPollTimer = setInterval(async () => {
            if (!this.state.yoloRunning) return;
            try {
                const s = await fetch(`${API_BASE}/api/yolo/status`)
                    .then(r => r.json()).catch(() => null);
                if (s && typeof s.fps === 'number') {
                    this.el.mFps.textContent = s.fps.toFixed(1);
                }
            } catch (e) { /* ignore */ }
        }, 4000);
    },

    renderDetections(detections) {
        const list = this.el.detectList;
        if (!list) return;

        // Agrupar por clase + recolectar gestos + interacciones.
        // yolo_detector emite "label", opcionalmente "gesture" (modelo pose)
        // y opcionalmente "holding" (lista de objetos que la persona toca).
        const grouped = new Map();
        const gestures = [];
        const interactions = [];   // ["persona con celular", ...]
        const knownFaces = [];
        let unknownFaces = 0;
        for (const d of detections) {
            const key = d.label || d.class_name || d.class || 'desconocido';
            const cur = grouped.get(key) || { count: 0, conf: 0 };
            cur.count += 1;
            if (typeof d.confidence === 'number' && d.confidence > cur.conf) {
                cur.conf = d.confidence;
            }
            grouped.set(key, cur);
            if (d.gesture) gestures.push(d.gesture);
            if (d.kind === 'face' || key === 'rostro') {
                if (d.known && d.person_name) {
                    knownFaces.push({
                        name: d.person_name,
                        conf: typeof d.recognition_confidence === 'number'
                            ? d.recognition_confidence
                            : 0
                    });
                } else {
                    unknownFaces += 1;
                }
            }
            if (Array.isArray(d.holding) && d.holding.length) {
                for (const obj of d.holding) {
                    interactions.push(`persona con ${obj}`);
                }
            }
        }

        list.innerHTML = '';
        if (grouped.size === 0) {
            list.innerHTML = '<li class="ag-detect-empty">Sin detecciones aún…</li>';
            this.el.mCount.textContent = '0';
            this._setSummary('--');
            return;
        }

        // Primero: rostros conocidos, gestos e interacciones, arriba de objetos.
        const faceCounts = new Map();
        for (const f of knownFaces) {
            const cur = faceCounts.get(f.name) || { count: 0, conf: 0 };
            cur.count += 1;
            cur.conf = Math.max(cur.conf, f.conf || 0);
            faceCounts.set(f.name, cur);
        }
        for (const [name, info] of faceCounts) {
            const li = document.createElement('li');
            li.style.borderLeftColor = '#38bdf8';
            li.style.background = 'rgba(56, 189, 248, 0.08)';
            li.style.borderColor = 'rgba(56, 189, 248, 0.35)';
            li.innerHTML = `
                <span class="lbl" style="color:#bae6fd;">Rostro: ${this._escape(name)}</span>
                ${info.count > 1 ? `<span class="count" style="background:rgba(56,189,248,0.15);color:#7dd3fc;">x${info.count}</span>` : ''}
                <span class="conf">${Math.round((info.conf || 0) * 100)}%</span>
            `;
            list.appendChild(li);
        }
        if (unknownFaces > 0) {
            const li = document.createElement('li');
            li.style.borderLeftColor = '#94a3b8';
            li.style.background = 'rgba(148, 163, 184, 0.08)';
            li.style.borderColor = 'rgba(148, 163, 184, 0.28)';
            li.innerHTML = `
                <span class="lbl" style="color:#cbd5e1;">Rostro desconocido</span>
                <span class="count" style="background:rgba(148,163,184,0.15);color:#cbd5e1;">x${unknownFaces}</span>
            `;
            list.appendChild(li);
        }

        const gestureCounts = new Map();
        for (const g of gestures) gestureCounts.set(g, (gestureCounts.get(g) || 0) + 1);
        for (const [g, n] of gestureCounts) {
            const li = document.createElement('li');
            li.style.borderLeftColor = '#f59e0b';
            li.style.background = 'rgba(245, 158, 11, 0.08)';
            li.style.borderColor = 'rgba(245, 158, 11, 0.35)';
            li.innerHTML = `
                <span class="lbl" style="color:#fcd34d;">🤚 ${this._escape(this._translateGesture(g))}</span>
                <span class="count" style="background:rgba(245,158,11,0.15);color:#fbbf24;">x${n}</span>
            `;
            list.appendChild(li);
        }

        const interactionCounts = new Map();
        for (const i of interactions) interactionCounts.set(i, (interactionCounts.get(i) || 0) + 1);
        for (const [text, n] of interactionCounts) {
            const li = document.createElement('li');
            li.style.borderLeftColor = '#22d3ee';
            li.style.background = 'rgba(34, 211, 238, 0.08)';
            li.style.borderColor = 'rgba(34, 211, 238, 0.35)';
            li.innerHTML = `
                <span class="lbl" style="color:#a5f3fc;">🔗 ${this._escape(text)}</span>
                ${n > 1 ? `<span class="count" style="background:rgba(34,211,238,0.15);color:#67e8f9;">x${n}</span>` : ''}
            `;
            list.appendChild(li);
        }

        // Luego objetos detectados (top 6)
        const sorted = [...grouped.entries()]
            .filter(([cls]) => cls !== 'rostro')
            .sort((a, b) => b[1].conf - a[1].conf)
            .slice(0, 6);
        for (const [cls, info] of sorted) {
            const li = document.createElement('li');
            li.innerHTML = `
                <span class="lbl">${this._escape(this._translateClass(cls))}</span>
                <span class="count">x${info.count}</span>
                <span class="conf">${Math.round(info.conf * 100)}%</span>
            `;
            list.appendChild(li);
        }
        this.el.mCount.textContent = String(detections.length);
        const summaryParts = [];
        if (grouped.size) summaryParts.push(`${grouped.size} clase${grouped.size === 1 ? '' : 's'}`);
        if (faceCounts.size) summaryParts.push(`${faceCounts.size} conocido${faceCounts.size === 1 ? '' : 's'}`);
        if (gestureCounts.size) summaryParts.push(`${gestureCounts.size} gesto${gestureCounts.size === 1 ? '' : 's'}`);
        this._setSummary(summaryParts.join(' · ') || '--');
    },

    _translateGesture(g) {
        const t = {
            mano_arriba: 'mano arriba',
            ambas_manos_arriba: 'ambas manos arriba',
            brazos_arriba: 'brazos arriba',
            señalando_derecha: 'señala a la derecha',
            señalando_izquierda: 'señala a la izquierda',
            sentado: 'persona sentada',
            t_pose: 'brazos en cruz (T-pose)',
            manos_juntas: 'manos juntas',
            brazos_cruzados: 'brazos cruzados',
            agachado: 'agachado'
        };
        return t[g] || g;
    },

    _setSummary(text) {
        const span = this.el.detectSummary?.querySelector('span:last-child');
        if (span) span.textContent = text;
    },

    /* ============ Health del agente IA ============ */
    async checkAiHealth() {
        try {
            const r = await fetch(`${API_BASE}/api/agente/health`).then(r => r.json());
            if (r && r.ok) {
                this.state.aiReady = true;
                this._setStatus('statusAi', true, 'IA');
            } else {
                this.state.aiReady = false;
                this._setStatus('statusAi', false, 'IA');
                this._showBanner(r?.message || 'IA no configurada', 'warn');
            }
        } catch (e) {
            this._setStatus('statusAi', false, 'IA');
            this._showBanner('No puedo contactar al backend del agente.', 'error');
        }
    },

    /* ============ Chat ============ */
    setupChat() {
        this.el.form?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendMessage();
        });
        this.el.input?.addEventListener('keydown', (e) => {
            // Enter envía; Shift+Enter saltaría línea pero el campo es input simple
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        this.el.suggestions?.querySelectorAll('.ag-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const prompt = chip.dataset.prompt;
                if (prompt) {
                    this.el.input.value = prompt;
                    this.sendMessage();
                }
            });
        });
        this.el.clear?.addEventListener('click', () => this.clearConversation());
    },

    async sendMessage() {
        const text = (this.el.input.value || '').trim();
        if (!text) return;
        this.el.input.value = '';
        this.el.input.focus();

        this.appendMessage('user', text);
        this.state.history.push({ role: 'user', text });
        if (this.el.suggestions) this.el.suggestions.style.display = 'none';

        const typingNode = this.appendTyping();
        this.el.send.disabled = true;

        try {
            const r = await fetch(`${API_BASE}/api/agente/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    history: this.state.history.slice(-24)
                })
            }).then(r => r.json());

            typingNode.remove();
            const reply = (r && r.reply) ? String(r.reply) : '🐾';
            const actions = (r && Array.isArray(r.actions)) ? r.actions : [];
            this.appendMessage('bot', reply, actions);
            this.state.history.push({ role: 'model', text: reply });
            this.speakReply(reply);
            // Si TTS está desactivado speakReply retorna sin llamar resume → desbloquear manualmente
            if (!this.state.voice.ttsEnabled && this.state.sessionActive) {
                setTimeout(() => this._sessionRecog?.resume?.(), 300);
            }
        } catch (e) {
            typingNode.remove();
            const errMsg = '⚠ No pude contactar al servidor. Revisa que `app.py` esté corriendo.';
            this.appendMessage('bot', errMsg, [{ name: 'error', ok: false }]);
            this.speakReply('No pude contactar al servidor.');
        } finally {
            this.el.send.disabled = false;
        }
    },

    appendMessage(role, text, actions) {
        const wrap = document.createElement('div');
        wrap.className = `ag-msg ag-msg-${role}`;

        const bubble = document.createElement('div');
        bubble.className = 'ag-bubble';
        // Dejamos que el bot use saltos de línea simples; escapamos HTML.
        bubble.innerHTML = this._escape(text).replace(/\n/g, '<br>');
        wrap.appendChild(bubble);

        // Por preferencia del usuario: no mostramos las "etiquetas de acción"
        // bajo el mensaje. La acción ya se ejecuta en el robot; el chat
        // queda limpio mostrando sólo la respuesta de Diver.
        // (El parámetro `actions` sigue llegando, simplemente no lo
        //  renderizamos. Si en el futuro se quiere reactivar, basta con
        //  volver a iterar y crear los `ag-action-tag`.)

        this.el.messages.appendChild(wrap);
        this._scrollToBottom();
        return wrap;
    },

    appendTyping() {
        const wrap = document.createElement('div');
        wrap.className = 'ag-msg ag-msg-bot';
        wrap.innerHTML = `
            <div class="ag-bubble" style="padding:0;">
                <div class="ag-typing"><span></span><span></span><span></span></div>
            </div>`;
        this.el.messages.appendChild(wrap);
        this._scrollToBottom();
        return wrap;
    },

    clearConversation() {
        this.state.history = [];
        if (this.el.suggestions) this.el.suggestions.style.display = '';
        this.el.messages.innerHTML = `
            <div class="ag-msg ag-msg-bot">
                <div class="ag-bubble">
                    <p>Listo, conversación limpia. Háblame normal y seguimos desde aquí. 🐾</p>
                </div>
            </div>`;
    },

    /* ============ Helpers ============ */
    _scrollToBottom() {
        requestAnimationFrame(() => {
            this.el.messages.scrollTop = this.el.messages.scrollHeight;
        });
    },

    _showBanner(message, kind) {
        const el = this.el.banner;
        if (!el) return;
        el.textContent = message;
        el.classList.remove('hidden', 'error', 'warn');
        if (kind) el.classList.add(kind);
        clearTimeout(this._bannerTimer);
        this._bannerTimer = setTimeout(() => el.classList.add('hidden'), 6000);
    },

    _escape(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },

    _translateClass(cls) {
        // Traducción rápida de las clases COCO más comunes
        const t = {
            person: 'persona',
            chair: 'silla',
            'dining table': 'mesa',
            'cell phone': 'celular',
            laptop: 'laptop',
            book: 'libro',
            bottle: 'botella',
            cup: 'taza',
            tv: 'pantalla',
            keyboard: 'teclado',
            mouse: 'ratón',
            backpack: 'mochila',
            handbag: 'bolso',
            'potted plant': 'planta',
            dog: 'perro',
            cat: 'gato',
            car: 'auto',
            bicycle: 'bicicleta',
            motorcycle: 'moto',
            bus: 'bus'
        };
        return t[cls] || cls;
    }
};

window.addEventListener('DOMContentLoaded', () => AGENT.init());
