/* ========================================
   Daiver Landing — Interactive Controller
   Voice (Web Speech API) + Robot Actions
   ======================================== */

const API_BASE = window.location.origin;

const Landing = {
    socket: null,
    socketConnected: false,
    robotConnected: false,
    voices: [],
    selectedVoice: null,
    speakRate: 1.0,

    init() {
        this.setupVoice();
        this.setupConnection();
        this.setupActions();
        this.setupRoutines();
        this.setupEmergency();
        this.setupSocketIO();
        this.loadConfig();
    },

    // ════════════════════════════════════════
    //  SOCKET.IO
    // ════════════════════════════════════════

    setupSocketIO() {
        try {
            this.socket = io(API_BASE, {
                reconnection: true,
                reconnectionDelay: 2000,
                timeout: 5000
            });

            this.socket.on('connect', () => {
                this.socketConnected = true;
                this.showToast('🟢 Servidor conectado');
            });

            this.socket.on('disconnect', () => {
                this.socketConnected = false;
                this.robotConnected = false;
                this.setStatus('offline');
                this.showToast('🔴 Servidor desconectado');
            });

            this.socket.on('connect_error', () => {
                this.socketConnected = false;
            });

            this.socket.on('state_update', (data) => {
                this.robotConnected = data.connected;
                this.setStatus(data.connected ? 'online' : 'offline');
            });

            this.socket.on('log', (data) => {
                if (data.type === 'error') {
                    this.showToast('❌ ' + data.message);
                } else if (data.type === 'success') {
                    this.showToast('✅ ' + data.message);
                }
            });
        } catch (err) {
            console.warn('SocketIO no disponible:', err);
        }
    },

    // ════════════════════════════════════════
    //  CONNECTION
    // ════════════════════════════════════════

    setupConnection() {
        document.getElementById('btn-connect')?.addEventListener('click', () => this.connect());
        document.getElementById('btn-disconnect')?.addEventListener('click', () => this.disconnect());
    },

    async loadConfig() {
        try {
            const res = await fetch(`${API_BASE}/api/config`);
            if (res.ok) {
                const config = await res.json();
                const ipInput = document.getElementById('ip-input');
                if (ipInput && config.robot_ip) ipInput.value = config.robot_ip;
            }
        } catch {
            // Server not ready
        }

        try {
            const res = await fetch(`${API_BASE}/api/status`);
            if (res.ok) {
                const status = await res.json();
                this.robotConnected = status.connected;
                this.setStatus(status.connected ? 'online' : 'offline');
            }
        } catch {
            // Ignore
        }
    },

    async connect() {
        const ip = document.getElementById('ip-input')?.value.trim();
        if (!ip) {
            this.showToast('⚠️ Ingresa la IP del robot');
            return;
        }

        this.setStatus('connecting');
        this.showToast('🔄 Conectando a ' + ip + '...');

        // Guardar IP en config.py
        try {
            await fetch(`${API_BASE}/api/config/ip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip })
            });
        } catch {
            // No bloquear conexion si falla guardar config
        }

        try {
            const res = await fetch(`${API_BASE}/api/connect`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip })
            });
            const data = await res.json();

            if (data.status === 'ok') {
                this.robotConnected = true;
                this.setStatus('online');
                this.speak('Conectado! Hola, soy Daiver!');
                this.showToast('✅ Conectado a ' + ip);
            } else {
                this.showToast('❌ ' + (data.message || 'Error'));
                this.setStatus('offline');
            }
        } catch (err) {
            this.showToast('❌ Error de conexion al servidor');
            this.setStatus('offline');
        }
    },

    async disconnect() {
        this.speak('Adios! Hasta la proxima!');

        try {
            await fetch(`${API_BASE}/api/disconnect`, { method: 'POST' });
            this.robotConnected = false;
            this.setStatus('offline');
        } catch {
            // Ignore
        }
    },

    // ════════════════════════════════════════
    //  ACTIONS — Siempre hablan, envian
    //  comando solo si hay robot conectado
    // ════════════════════════════════════════

    setupActions() {
        document.querySelectorAll('.action-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                const voice = btn.dataset.voice;
                this.executeAction(action, voice, btn);
            });
        });
    },

    async executeAction(action, voiceText, btnElement) {
        // Visual feedback siempre
        if (btnElement) {
            btnElement.classList.add('executing');
            setTimeout(() => btnElement.classList.remove('executing'), 800);
        }

        // Voz siempre funciona
        if (voiceText) {
            this.speak(voiceText);
        }

        // Si hay robot conectado, enviar comando
        if (this.robotConnected) {
            try {
                const res = await fetch(`${API_BASE}/api/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action })
                });
                const data = await res.json();

                if (data.status !== 'ok') {
                    this.showToast('❌ ' + (data.message || 'Error'));
                }
            } catch (err) {
                this.showToast('❌ Error enviando comando');
            }
        } else {
            this.showToast('🔊 Solo voz — robot no conectado');
        }
    },

    // ════════════════════════════════════════
    //  ROUTINES
    // ════════════════════════════════════════

    setupRoutines() {
        document.querySelectorAll('.action-routine').forEach(btn => {
            btn.addEventListener('click', () => {
                const routine = btn.dataset.routine;
                const voice = btn.dataset.voice;
                this.executeRoutine(routine, voice, btn);
            });
        });

        document.getElementById('btn-routine-stop')?.addEventListener('click', async () => {
            this.speak('Deteniendo la rutina.');
            if (this.robotConnected) {
                try {
                    await fetch(`${API_BASE}/api/routine/stop`, { method: 'POST' });
                    this.showToast('⏹️ Rutina detenida');
                } catch {
                    this.showToast('❌ Error deteniendo rutina');
                }
            }
        });
    },

    async executeRoutine(routine, voiceText, btnElement) {
        if (btnElement) {
            btnElement.classList.add('executing');
            setTimeout(() => btnElement.classList.remove('executing'), 800);
        }

        if (voiceText) {
            this.speak(voiceText);
        }

        if (this.robotConnected) {
            try {
                const res = await fetch(`${API_BASE}/api/routine`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ routine })
                });
                const data = await res.json();

                if (data.status === 'ok') {
                    this.showToast('▶️ Rutina ' + routine + ' iniciada');
                } else {
                    this.showToast('❌ ' + (data.message || 'Error'));
                }
            } catch (err) {
                this.showToast('❌ Error iniciando rutina');
            }
        } else {
            this.showToast('🔊 Solo voz — robot no conectado');
        }
    },

    // ════════════════════════════════════════
    //  EMERGENCY
    // ════════════════════════════════════════

    setupEmergency() {
        document.getElementById('btn-emergency')?.addEventListener('click', async () => {
            this.speak('Parada de emergencia activada');

            if (this.robotConnected) {
                try {
                    await fetch(`${API_BASE}/api/emergency`, { method: 'POST' });
                    this.showToast('🛑 Emergencia activada');
                } catch {
                    this.showToast('❌ Error en emergencia');
                }
            }
        });
    },

    // ════════════════════════════════════════
    //  VOICE — Web Speech API
    //  Reproduce por el dispositivo de audio
    //  activo (Bluetooth speaker si conectado)
    // ════════════════════════════════════════

    setupVoice() {
        if (!('speechSynthesis' in window)) {
            this.showToast('⚠️ Tu navegador no soporta sintesis de voz');
            return;
        }

        // Load voices
        const loadVoices = () => {
            this.voices = speechSynthesis.getVoices();
            if (this.voices.length > 0) {
                this.populateVoiceList();
            }
        };

        // Voices load asynchronously in some browsers
        speechSynthesis.onvoiceschanged = loadVoices;
        // Also try immediately
        setTimeout(loadVoices, 100);
        setTimeout(loadVoices, 500);

        // Speak button
        document.getElementById('btn-speak')?.addEventListener('click', () => {
            const input = document.getElementById('voice-input');
            const text = input?.value.trim();
            if (text) {
                this.speak(text);
            } else {
                this.showToast('⚠️ Escribe un mensaje');
            }
        });

        // Enter key to speak
        document.getElementById('voice-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('btn-speak')?.click();
            }
        });

        // Voice selection
        document.getElementById('voice-select')?.addEventListener('change', (e) => {
            const voiceName = e.target.value;
            this.selectedVoice = this.voices.find(v => v.name === voiceName) || null;
        });

        // Rate slider
        const rateSlider = document.getElementById('voice-rate');
        const rateValue = document.getElementById('voice-rate-value');
        rateSlider?.addEventListener('input', () => {
            this.speakRate = parseFloat(rateSlider.value);
            if (rateValue) rateValue.textContent = this.speakRate.toFixed(1) + 'x';
        });

        // Quick phrases
        document.querySelectorAll('.phrase-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const phrase = btn.dataset.phrase;
                if (phrase) {
                    this.speak(phrase);
                    const input = document.getElementById('voice-input');
                    if (input) input.value = phrase;
                }
            });
        });
    },

    populateVoiceList() {
        const select = document.getElementById('voice-select');
        if (!select) return;

        select.innerHTML = '';

        // Prefer Spanish voices
        const spanishVoices = this.voices.filter(v => v.lang.startsWith('es'));
        const otherVoices = this.voices.filter(v => !v.lang.startsWith('es'));
        const sorted = [...spanishVoices, ...otherVoices];

        sorted.forEach(voice => {
            const option = document.createElement('option');
            const langTag = voice.lang.startsWith('es') ? '🇪🇸 ' : '';
            option.textContent = `${langTag}${voice.name} (${voice.lang})`;
            option.value = voice.name;
            select.appendChild(option);
        });

        // Auto-select first Spanish voice
        if (spanishVoices.length > 0) {
            this.selectedVoice = spanishVoices[0];
            select.value = spanishVoices[0].name;
        }
    },

    speak(text) {
        if (!text || !('speechSynthesis' in window)) return;

        // Cancel any ongoing speech
        speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);

        if (this.selectedVoice) {
            utterance.voice = this.selectedVoice;
        }

        utterance.rate = this.speakRate;
        utterance.pitch = 1.1;
        utterance.volume = 1.0;

        if (!this.selectedVoice) {
            utterance.lang = 'es-CO';
        }

        speechSynthesis.speak(utterance);
    },

    // ════════════════════════════════════════
    //  UI HELPERS
    // ════════════════════════════════════════

    setStatus(status) {
        const badge = document.getElementById('status-badge');
        const text = document.getElementById('status-text');
        const btnConnect = document.getElementById('btn-connect');
        const btnDisconnect = document.getElementById('btn-disconnect');

        if (badge) {
            badge.className = 'status-badge ' + status;
        }

        if (text) {
            const labels = {
                'online': 'Robot Conectado',
                'offline': 'Sin conexion',
                'connecting': 'Conectando...'
            };
            text.textContent = labels[status] || status;
        }

        if (btnConnect) btnConnect.disabled = (status === 'online');
        if (btnDisconnect) btnDisconnect.disabled = (status !== 'online');
    },

    showToast(message) {
        // Remove existing toast
        document.querySelector('.toast')?.remove();

        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = message;
        document.body.appendChild(toast);

        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 400);
        }, 3000);
    }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    Landing.init();
});
