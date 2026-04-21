/* ========================================
   Daiver Control Remoto - Landscape Gamepad
   WASD + IJKL (desktop) / Joystick + A·B·X·Y (mobile)
   ======================================== */

const API_BASE = window.location.origin;

const ACTION_MAP = {
    a: { action: 'frontjump',   label: 'Saltar',          icon: 'A' },
    b: { action: 'hello',       label: 'Pata',            icon: 'B' },
    y: { action: 'heart',       label: 'Corazon',         icon: 'Y' },
    x: { action: 'frontpounce', label: 'Salto agresivo',  icon: 'X' }
};

// Web keyboard maps to the same gamepad letters
const KEY_TO_CROSS = { i: 'a', I: 'a', j: 'b', J: 'b', k: 'y', K: 'y', l: 'x', L: 'x' };

const ControlRemoto = {
    socket: null,
    state: {
        serverConnected: false,
        robotConnected: false,
        yoloRunning: false,
        sensorEnabled: false,
        battery: 0,
        mode: '--',
        ip: ''
    },

    // TTS: preferred Spanish voice is picked once voices load.
    tts: { voice: null, lastAlertTs: 0 },

    // Movement state (dead-man's switch: robot moves ONLY while an input is held)
    movement: {
        speedFactor: 0.45,
        rotFactor: 0.75,
        interval: null,
        activeKeys: new Set(),
        keyboard: { x: 0, y: 0, z: 0 },
        joyMove: { x: 0, y: 0 },
        joyRotate: { z: 0 },
        // Doble tap de WASD/QE activa "force": los comandos se marcan con
        // force=true y el backend salta el bloqueo del sensor. Dura MIENTRAS
        // el operador siga conduciendo; se apaga solo cuando suelta todas
        // las teclas (stopLoop) o se desconecta el robot.
        forceActive: false,
        lastKeyTap: {},
    },

    // Simple dead-reckoning trace
    trace: {
        canvas: null,
        ctx: null,
        history: [],           // [{x,y}]
        pose: { x: 0, y: 0, heading: 0 },
        lastTick: null,
        tickTimer: null,
        heat: new Map(),
        heatCellSize: 0.15,
        lidarPose: null,
        totalMeters: 0.0,
        lastPoseForDistance: null,
        metersPerStep: 0.30,
        // Pan manual del mapa: mientras el usuario arrastra, se desacopla
        // del centrado automático en la pose. Doble click vuelve a centrar.
        viewOffset: { x: 0, y: 0 },
        viewOffsetInUse: false,
        dragging: false,
        dragStart: null,
        zoom: 1.0,            // zoom con wheel / pinch
    },

    yoloPollTimer: null,

    init() {
        this.cacheElements();
        this.setupSocket();
        this.setupConnectBar();
        this.setupJoysticks();
        this.setupActionBar();
        this.setupMobileActions();
        this.setupSensorToggle();
        this.setupTts();
        this.setupAutoRotate();
        this.setupKeyboard();
        this.setupSidePanelToggle();
        this.initTraceCanvas();
        this.loadInitialData();
        this.startStatusPolling();
        this.refreshYoloStatus();
    },

    cacheElements() {
        this.el = {
            ipInput: document.getElementById('cr-ip'),
            btnConnect: document.getElementById('cr-connect'),
            btnDisconnect: document.getElementById('cr-disconnect'),
            btnEmergency: document.getElementById('cr-emergency'),
            btnYoloStart: document.getElementById('cr-yolo-start'),
            btnYoloStop: document.getElementById('cr-yolo-stop'),
            video: document.getElementById('cr-video'),
            videoPlaceholder: document.getElementById('cr-video-placeholder'),
            statusServer: document.getElementById('cr-status-server'),
            statusRobot: document.getElementById('cr-status-robot'),
            statusYolo: document.getElementById('cr-status-yolo'),
            metricBattery: document.getElementById('cr-m-battery'),
            metricMode: document.getElementById('cr-m-mode'),
            metricSpeed: document.getElementById('cr-m-speed'),
            metricFps: document.getElementById('cr-m-fps'),
            batteryBar: document.getElementById('cr-battery-bar'),
            detections: document.getElementById('cr-detections'),
            joyMove: document.getElementById('cr-joy-move'),
            joyRotate: document.getElementById('cr-joy-rotate'),
            btnSensor: document.getElementById('cr-sensor'),
            btnMobileSensor: document.getElementById('cr-mobile-sensor'),
            proximityBanner: document.getElementById('cr-proximity-banner'),
            sidePanel: document.getElementById('cr-side'),
            sideToggle: document.getElementById('cr-side-toggle'),
            traceCanvas: document.getElementById('cr-trace-canvas'),
            mobileStatus: document.getElementById('cr-mobile-status'),
            statDistance: document.getElementById('cr-m-distance'),
            statSteps: document.getElementById('cr-m-steps')
        };
    },

    /* ============ Socket & status ============ */
    setupSocket() {
        if (typeof io !== 'function') return;
        this.socket = io(API_BASE, { reconnection: true });

        this.socket.on('connect', () => this.setServerState(true));
        this.socket.on('disconnect', () => {
            this.setServerState(false);
            this.setRobotState(false);
        });
        this.socket.on('state_update', (data) => {
            this.setServerState(true);
            if (data) {
                this.setRobotState(Boolean(data.connected));
                this.state.battery = data.battery ?? this.state.battery;
                this.state.mode = data.mode || this.state.mode;
                this.updateMetrics();
            }
        });

        // Proximity sensor alerts: backend emits when YOLO sees something too
        // close. Speak the warning, stop the robot, flash a banner.
        this.socket.on('proximity_alert', (data) => this.onProximityAlert(data));

        // Puntos del lidar (world frame) para el heatmap + paredes.
        this.socket.on('lidar_points', (data) => this.onLidarPoints(data));
    },

    async loadInitialData() {
        const cfg = await this.apiCall('/api/config', 'GET');
        if (cfg && cfg.robot_ip && this.el.ipInput) {
            this.el.ipInput.value = cfg.robot_ip;
        }
        await this.refreshStatus();
    },

    startStatusPolling() {
        setInterval(() => this.refreshStatus(), 4000);
    },

    async refreshStatus() {
        const s = await this.apiCall('/api/status', 'GET');
        if (!s || s.status === 'error') {
            this.setServerState(false);
            this.setRobotState(false);
            return;
        }
        this.setServerState(true);
        this.setRobotState(Boolean(s.connected));
        this.state.battery = s.battery ?? this.state.battery;
        this.state.mode = s.mode || this.state.mode;
        this.state.ip = s.ip || this.state.ip;
        this.updateMetrics();
    },

    setServerState(connected) {
        this.state.serverConnected = connected;
        this.renderPill(this.el.statusServer, connected, 'Servidor', 'Offline');
        this.toggleControls();
    },

    setRobotState(connected, connecting = false) {
        this.state.robotConnected = connected;
        const pill = this.el.statusRobot;
        if (pill) {
            pill.classList.remove('connected', 'disconnected', 'connecting');
            if (connecting) { pill.classList.add('connecting'); pill.querySelector('.txt').textContent = 'Conectando...'; }
            else if (connected) { pill.classList.add('connected'); pill.querySelector('.txt').textContent = 'Robot OK'; }
            else { pill.classList.add('disconnected'); pill.querySelector('.txt').textContent = 'Sin robot'; }
        }
        // Mobile floating dot mirrors the robot connection state.
        if (this.el.mobileStatus) {
            this.el.mobileStatus.classList.toggle('connected', Boolean(connected));
        }
        // Safety: if we lose the robot while moving, stop immediately.
        if (!connected) this.stopMovement();
        this.toggleControls();
    },

    renderPill(el, ok, labelOn, labelOff) {
        if (!el) return;
        el.classList.remove('connected', 'disconnected');
        el.classList.add(ok ? 'connected' : 'disconnected');
        const txt = el.querySelector('.txt');
        if (txt) txt.textContent = ok ? labelOn : labelOff;
    },

    updateMetrics() {
        if (this.el.metricBattery) this.el.metricBattery.textContent = `${this.state.battery}%`;
        if (this.el.batteryBar) this.el.batteryBar.style.width = `${Math.max(0, Math.min(100, this.state.battery))}%`;
        if (this.el.metricMode) this.el.metricMode.textContent = this.state.mode || '--';
    },

    toggleControls() {
        const canDo = this.state.serverConnected && this.state.robotConnected;
        if (this.el.btnConnect) this.el.btnConnect.disabled = !this.state.serverConnected || this.state.robotConnected;
        if (this.el.btnDisconnect) this.el.btnDisconnect.disabled = !canDo;
        if (this.el.btnEmergency) this.el.btnEmergency.disabled = !this.state.serverConnected;
        document.querySelectorAll('.cr-action-btn').forEach(btn => {
            btn.disabled = !canDo;
        });
        document.querySelectorAll('.cr-mob-action-btn').forEach(btn => {
            btn.disabled = !canDo;
        });
    },

    /* ============ Connect bar ============ */
    setupConnectBar() {
        this.el.btnConnect?.addEventListener('click', () => this.connectRobot());
        this.el.btnDisconnect?.addEventListener('click', () => this.disconnectRobot());
        this.el.btnEmergency?.addEventListener('click', () => this.emergencyStop());
        this.el.btnYoloStart?.addEventListener('click', () => this.startYolo());
        this.el.btnYoloStop?.addEventListener('click', () => this.stopYolo());
    },

    async connectRobot() {
        const ip = (this.el.ipInput?.value || '').trim();
        if (!ip) return;
        this.setRobotState(false, true);
        await this.apiCall('/api/config/ip', 'POST', { ip });
        const res = await this.apiCall('/api/connect', 'POST', { ip });
        if (!res || res.status !== 'ok') this.setRobotState(false);
        await this.refreshStatus();
    },

    async disconnectRobot() {
        await this.apiCall('/api/disconnect', 'POST');
        await this.refreshStatus();
    },

    async emergencyStop() {
        this.stopMovement();
        await this.apiCall('/api/emergency', 'POST');
        await this.refreshStatus();
    },

    /* ============ Movement ============
       Dead-man's switch: each input source (keyboard / move joystick /
       rotate joystick) maintains its own vector. composeVector() merges
       them. When every source returns to zero, stopLoop() halts the send
       interval and emits stop_command once — so releasing the key or the
       joystick stops the robot immediately.
    */
    setupKeyboard() {
        const keys = this.movement.activeKeys;

        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT') return;

            const cross = KEY_TO_CROSS[e.key];
            if (cross) {
                e.preventDefault();
                if (!keys.has(e.key)) { keys.add(e.key); this.pressCross(cross); }
                return;
            }

            if (/^[wWsSaAdDqQeE]$/.test(e.key)) {
                e.preventDefault();
                // Doble tap de la misma tecla en <350 ms activa el modo FORCE.
                // Una vez activo, el movimiento es libre hasta que sueltes
                // todas las teclas (ver stopLoop).
                if (!keys.has(e.key)) {
                    const now = Date.now();
                    const k = e.key.toLowerCase();
                    const last = this.movement.lastKeyTap[k] || 0;
                    if (now - last < 350) {
                        this.movement.forceActive = true;
                        this.showForceBadge();
                    }
                    this.movement.lastKeyTap[k] = now;
                }
                keys.add(e.key);
                this.recomputeKeyboardVector();
            }
        });

        document.addEventListener('keyup', (e) => {
            if (!keys.has(e.key)) return;
            keys.delete(e.key);
            if (KEY_TO_CROSS[e.key]) { this.releaseCross(KEY_TO_CROSS[e.key]); return; }
            this.recomputeKeyboardVector();
        });

        // If the window loses focus, treat every key as released and force-stop.
        // Without this, holding W and alt-tabbing away would leave the robot moving.
        const abort = () => { keys.clear(); this.stopMovement(); };
        window.addEventListener('blur', abort);
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') abort();
        });
    },

    // Recompute the keyboard source vector from currently-held keys.
    recomputeKeyboardVector() {
        const keys = this.movement.activeKeys;
        const s = this.movement.speedFactor;
        const r = this.movement.rotFactor;

        const fwd  = keys.has('w') || keys.has('W');
        const back = keys.has('s') || keys.has('S');
        const lft  = keys.has('a') || keys.has('A');
        const rgt  = keys.has('d') || keys.has('D');
        const rotL = keys.has('q') || keys.has('Q');
        const rotR = keys.has('e') || keys.has('E');

        let x = 0, y = 0, z = 0;
        // Dominant-axis rule: forward/back cancels strafe to avoid crab-walk
        if (fwd && !back) x = s;
        else if (back && !fwd) x = -s;
        else if (lft && !rgt) y = s;        // strafe a factor completo
        else if (rgt && !lft) y = -s;       // (antes 0.5, el Go2 se balanceaba)

        if (rotL && !rotR) z = r;
        else if (rotR && !rotL) z = -r;

        this.movement.keyboard = { x, y, z };
        this.syncMovement();
    },

    // Compose the final velocity from all three input sources. Priority:
    // keyboard overrides a given axis if non-zero; otherwise the joystick
    // value on that axis wins.
    composeVector() {
        const kb = this.movement.keyboard;
        const jm = this.movement.joyMove;
        const jr = this.movement.joyRotate;
        return {
            x: kb.x !== 0 ? kb.x : jm.x,
            y: kb.y !== 0 ? kb.y : jm.y,
            z: kb.z !== 0 ? kb.z : jr.z
        };
    },

    // Called after any input source changes. Starts the 200ms send loop
    // when something is active, stops it (and sends stop_command) otherwise.
    syncMovement() {
        const v = this.composeVector();
        const active = v.x !== 0 || v.y !== 0 || v.z !== 0;
        if (active) {
            this.startLoopIfNeeded();
        } else {
            this.stopLoop();
        }
    },

    startLoopIfNeeded() {
        if (this.movement.interval) return;
        const tick = () => {
            const raw = this.composeVector();
            const q = (n) => Math.abs(n) < 0.05 ? 0 : Math.round(n * 20) / 20;
            const v = { x: q(raw.x), y: q(raw.y), z: q(raw.z) };

            if (v.x === 0 && v.y === 0 && v.z === 0) {
                this.stopLoop();
                return;
            }

            if (this.socket && this.state.robotConnected) {
                const payload = { ...v };
                if (this.movement.forceActive) payload.force = true;
                this.socket.emit('move_command', payload);
            }
            this.advanceTraceFromVelocity(v, 0.2);
        };
        tick();
        this.movement.interval = setInterval(tick, 200);
    },

    showForceBadge() {
        let el = document.getElementById('cr-force-badge');
        if (!el) {
            el = document.createElement('div');
            el.id = 'cr-force-badge';
            el.className = 'cr-force-badge';
            el.textContent = 'FORCE';
            document.body.appendChild(el);
        }
        el.classList.add('visible');
    },

    hideForceBadge() {
        const el = document.getElementById('cr-force-badge');
        if (el) el.classList.remove('visible');
    },

    stopLoop() {
        if (this.movement.interval) {
            clearInterval(this.movement.interval);
            this.movement.interval = null;
        }
        // Al soltar todas las teclas, apagamos el modo FORCE: la próxima
        // conducción pedirá un nuevo doble tap para forzar.
        if (this.movement.forceActive) {
            this.movement.forceActive = false;
            this.hideForceBadge();
        }
        if (this.socket) this.socket.emit('stop_command');
    },

    stopMovement() {
        this.movement.keyboard = { x: 0, y: 0, z: 0 };
        this.movement.joyMove = { x: 0, y: 0 };
        this.movement.joyRotate = { z: 0 };
        this.movement.activeKeys.clear();
        this.stopLoop();
    },

    /* ============ Joysticks (dual: move + rotate) ============ */
    setupJoysticks() {
        this.bindJoystick(this.el.joyMove, 'move');
        this.bindJoystick(this.el.joyRotate, 'rotate');
    },

    bindJoystick(root, axis) {
        if (!root) return;
        const knob = root.querySelector('.cr-joy-knob');
        if (!knob) return;

        const maxRadius = 48;
        const deadzone = 0.22;
        let pointerId = null;

        const setMove = (x, y) => { this.movement.joyMove = { x, y }; this.syncMovement(); };
        const setRot  = (z)    => { this.movement.joyRotate = { z };   this.syncMovement(); };

        const reset = () => {
            knob.style.transform = 'translate(-50%, -50%)';
            root.classList.remove('active');
            if (axis === 'move') setMove(0, 0); else setRot(0);
        };

        const update = (clientX, clientY) => {
            const rect = root.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            let dx = clientX - cx;
            let dy = clientY - cy;
            const dist = Math.hypot(dx, dy);
            const r = Math.min(dist, maxRadius);
            if (dist > 0) { dx = (dx / dist) * r; dy = (dy / dist) * r; }

            if (axis === 'rotate') {
                knob.style.transform = `translate(calc(-50% + ${dx}px), -50%)`;
                const nz = -dx / maxRadius;
                if (Math.abs(nz) < deadzone) { setRot(0); return; }
                setRot(Math.max(-1, Math.min(1, nz)) * this.movement.rotFactor);
                return;
            }

            knob.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
            const nFwd    = -dy / maxRadius;
            const nStrafe = -dx / maxRadius;
            const absFwd = Math.abs(nFwd);
            const absStr = Math.abs(nStrafe);

            if (absFwd < deadzone && absStr < deadzone) { setMove(0, 0); return; }

            // Dominant-axis rule prevents crab-walk drift when pushing mostly forward.
            let fwd = nFwd, str = nStrafe;
            if (absFwd > absStr * 1.8) str = 0;
            else if (absStr > absFwd * 1.8) fwd = 0;

            const s = this.movement.speedFactor;
            setMove(
                Math.max(-1, Math.min(1, fwd)) * s,
                Math.max(-1, Math.min(1, str)) * s * 0.5
            );
        };

        root.addEventListener('pointerdown', (e) => {
            if (!this.state.robotConnected) return;
            pointerId = e.pointerId;
            root.setPointerCapture(pointerId);
            root.classList.add('active');
            update(e.clientX, e.clientY);
        });

        root.addEventListener('pointermove', (e) => {
            if (pointerId !== e.pointerId) return;
            update(e.clientX, e.clientY);
        });

        const release = (e) => {
            if (pointerId !== e.pointerId) return;
            try { root.releasePointerCapture(pointerId); } catch {}
            pointerId = null;
            reset();
        };

        root.addEventListener('pointerup', release);
        root.addEventListener('pointercancel', release);
        root.addEventListener('pointerleave', release);
    },

    /* ============ Action bar (A·B·Y·X) ============ */
    setupActionBar() {
        document.querySelectorAll('.cr-action-btn').forEach(btn => {
            const letter = btn.dataset.cross;
            btn.addEventListener('click', () => this.triggerCross(letter));
        });
    },

    pressCross(letter) {
        const btn = document.querySelector(`.cr-action-btn[data-cross="${letter}"]`);
        if (btn) btn.classList.add('pressed');
        this.triggerCross(letter);
    },

    releaseCross(letter) {
        const btn = document.querySelector(`.cr-action-btn[data-cross="${letter}"]`);
        if (btn) btn.classList.remove('pressed');
    },

    async triggerCross(letter) {
        const entry = ACTION_MAP[letter];
        if (!entry) return;
        if (!this.state.robotConnected) return;
        await this.apiCall('/api/action', 'POST', { action: entry.action });
    },

    /* ============ Mobile action buttons (hello / sit / recovery) ============
       Always visible on mobile so the operator reaches the poses without
       opening the side panel. Disabled while the robot is offline. */
    setupMobileActions() {
        document.querySelectorAll('.cr-mob-action-btn').forEach(btn => {
            const action = btn.dataset.action;
            if (!action) return;
            btn.addEventListener('click', async () => {
                if (!this.state.robotConnected) return;
                btn.classList.add('pressed');
                setTimeout(() => btn.classList.remove('pressed'), 180);
                await this.apiCall('/api/action', 'POST', { action });
            });
        });
    },

    /* ============ Sensor de proximidad ============
       Toggle ON: backend arranca un watcher que mira detecciones YOLO
       "near" y emite `proximity_alert`. Aquí respondemos con TTS + stop.
       La alerta también llega desde el servidor, así que el stop es
       doble: el servidor manda Move=0 y nosotros mandamos stop_command. */
    setupSensorToggle() {
        const handler = () => this.toggleSensor();
        this.el.btnSensor?.addEventListener('click', handler);
        this.el.btnMobileSensor?.addEventListener('click', handler);
        this.refreshSensorStatus();
    },

    async refreshSensorStatus() {
        const s = await this.apiCall('/api/sensor/status', 'GET');
        if (s && typeof s.enabled === 'boolean') {
            this.applySensorState(s.enabled);
        }
    },

    async toggleSensor() {
        if (!this.state.sensorEnabled && !this.state.robotConnected) return;
        const desired = !this.state.sensorEnabled;
        const res = await this.apiCall('/api/sensor/toggle', 'POST', { enabled: desired });
        if (res && typeof res.enabled === 'boolean') {
            this.applySensorState(res.enabled);
        }
    },

    applySensorState(enabled) {
        this.state.sensorEnabled = enabled;
        const pressed = enabled ? 'true' : 'false';
        if (this.el.btnSensor) {
            this.el.btnSensor.setAttribute('aria-pressed', pressed);
            this.el.btnSensor.textContent = enabled ? 'Sensor ON' : 'Sensor';
            this.el.btnSensor.classList.toggle('ghost', !enabled);
        }
        if (this.el.btnMobileSensor) {
            this.el.btnMobileSensor.setAttribute('aria-pressed', pressed);
        }
    },

    /* ============ Text-to-speech (alerta de voz) ============ */
    setupTts() {
        if (!('speechSynthesis' in window)) return;
        const pickVoice = () => {
            const voices = speechSynthesis.getVoices() || [];
            const es = voices.find(v => /^es/i.test(v.lang)) || voices[0];
            this.tts.voice = es || null;
        };
        pickVoice();
        speechSynthesis.onvoiceschanged = pickVoice;
    },

    speak(text) {
        if (!text || !('speechSynthesis' in window)) return;
        try {
            speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(text);
            if (this.tts.voice) u.voice = this.tts.voice;
            else u.lang = 'es-CO';
            u.rate = 1.05;
            u.pitch = 1.0;
            u.volume = 1.0;
            speechSynthesis.speak(u);
        } catch (_) { /* ignore */ }
    },

    onProximityAlert(data) {
        const now = Date.now();
        if (now - this.tts.lastAlertTs < 2000) return;
        this.tts.lastAlertTs = now;

        this.stopMovement();
        if (this.socket) this.socket.emit('stop_command');

        // Solo alerta visual (el usuario pidió sin voz).
        this.flashProximityBanner(data);
    },

    flashProximityBanner(data) {
        const el = this.el.proximityBanner;
        if (!el) return;
        const where = data && data.direction ? ` (${data.direction})` : '';
        const cm = data && typeof data.distance_m === 'number'
            ? `${Math.round(data.distance_m * 100)} cm`
            : 'obstaculo';
        el.textContent = `!Detente! ${cm}${where}`;
        el.classList.add('visible');
        clearTimeout(this._banTimer);
        this._banTimer = setTimeout(() => el.classList.remove('visible'), 1600);
    },

    /* ============ Auto-rotar a landscape ============
       screen.orientation.lock() solo funciona en fullscreen en iOS/Android,
       así que primero pedimos fullscreen y después el lock. Si el navegador
       no lo soporta, mostramos un aviso para que el usuario gire manualmente
       (iOS Safari bloquea la API de orientation.lock). */
    setupAutoRotate() {
        const btn = document.getElementById('cr-auto-rotate');
        const note = document.getElementById('cr-orient-note');
        if (!btn) return;

        btn.addEventListener('click', async () => {
            if (note) note.textContent = '';
            try {
                const root = document.documentElement;
                const req = root.requestFullscreen
                    || root.webkitRequestFullscreen
                    || root.msRequestFullscreen;
                if (req) await req.call(root);
            } catch (err) {
                if (note) note.textContent = 'No se pudo entrar a pantalla completa: ' + err.message;
            }

            try {
                if (screen.orientation && typeof screen.orientation.lock === 'function') {
                    await screen.orientation.lock('landscape');
                    if (note) note.textContent = '';
                } else {
                    throw new Error('API de orientación no soportada');
                }
            } catch (err) {
                if (note) {
                    note.textContent = 'Tu navegador no permite rotar automaticamente. Gira el dispositivo manualmente.';
                }
            }
        });
    },

    /* ============ Side panel toggle (mobile) ============ */
    setupSidePanelToggle() {
        this.el.sideToggle?.addEventListener('click', () => {
            this.el.sidePanel?.classList.toggle('open');
        });
    },

    /* ============ YOLO ============ */
    async startYolo() {
        const payload = {
            source: this.state.robotConnected ? 'robot' : 'webcam',
            camera_index: 0,
            conf: 0.4,
            model: 'yolov8n.pt'
        };
        const res = await this.apiCall('/api/yolo/start', 'POST', payload);
        if (res && res.status === 'ok') {
            this.setYoloRunning(true);
            this.attachYoloStream();
            this.startYoloPolling();
        }
    },

    async stopYolo() {
        this.stopYoloPolling();
        this.detachYoloStream();
        await this.apiCall('/api/yolo/stop', 'POST');
        this.setYoloRunning(false);
        this.renderDetections([]);
        this.updateFps(null);
    },

    async refreshYoloStatus() {
        const s = await this.apiCall('/api/yolo/status', 'GET');
        if (!s) return;
        this.setYoloRunning(Boolean(s.running));
        this.updateFps(s.running ? s.fps : null);
        if (s.running) {
            this.attachYoloStream();
            this.startYoloPolling();
        }
    },

    setYoloRunning(running) {
        this.state.yoloRunning = running;
        if (this.el.btnYoloStart) this.el.btnYoloStart.disabled = running;
        if (this.el.btnYoloStop) this.el.btnYoloStop.disabled = !running;
        const pill = this.el.statusYolo;
        if (pill) {
            pill.classList.remove('connected', 'disconnected');
            pill.classList.add(running ? 'connected' : 'disconnected');
            const txt = pill.querySelector('.txt');
            if (txt) txt.textContent = running ? 'YOLO ON' : 'YOLO OFF';
        }
    },

    attachYoloStream() {
        const img = this.el.video;
        if (!img) return;
        img.src = `${API_BASE}/api/yolo/stream?t=${Date.now()}`;
        img.style.display = 'block';
        if (this.el.videoPlaceholder) this.el.videoPlaceholder.style.display = 'none';
    },

    detachYoloStream() {
        if (this.el.video) {
            this.el.video.src = '';
            this.el.video.style.display = 'none';
        }
        if (this.el.videoPlaceholder) this.el.videoPlaceholder.style.display = 'flex';
    },

    startYoloPolling() {
        this.stopYoloPolling();
        this.yoloPollTimer = setInterval(async () => {
            const [det, status] = await Promise.all([
                this.apiCall('/api/yolo/detections', 'GET'),
                this.apiCall('/api/yolo/status', 'GET')
            ]);
            if (status) {
                this.updateFps(status.running ? status.fps : null);
                if (!status.running) {
                    this.setYoloRunning(false);
                    this.detachYoloStream();
                    this.renderDetections([]);
                    this.stopYoloPolling();
                    return;
                }
            }
            if (det && Array.isArray(det.detections)) {
                this.renderDetections(det.detections);
            }
        }, 800);
    },

    stopYoloPolling() {
        if (this.yoloPollTimer) {
            clearInterval(this.yoloPollTimer);
            this.yoloPollTimer = null;
        }
    },

    updateFps(fps) {
        if (!this.el.metricFps) return;
        this.el.metricFps.textContent = fps == null ? '--' : `${fps}`;
    },

    renderDetections(list) {
        const cont = this.el.detections;
        if (!cont) return;
        if (!list || list.length === 0) {
            cont.innerHTML = '<div class="cr-det-empty">Sin detecciones</div>';
            return;
        }
        const ordered = [...list].sort((a, b) => b.confidence - a.confidence).slice(0, 6);
        cont.innerHTML = ordered.map(d => {
            const pct = Math.round(d.confidence * 100);
            return `
                <div class="cr-det-item dir-${d.direction}">
                    <span class="lbl">${this.escapeHtml(d.label)}</span>
                    <span class="conf">${pct}% · ${d.direction}</span>
                </div>
            `;
        }).join('');
    },

    escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    /* ============ 3D-like trace canvas (dead reckoning) ============ */
    initTraceCanvas() {
        const canvas = this.el.traceCanvas;
        if (!canvas) return;
        this.trace.canvas = canvas;

        const resize = () => {
            const r = canvas.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            canvas.width = r.width * dpr;
            canvas.height = r.height * dpr;
            this.trace.ctx = canvas.getContext('2d');
            this.trace.ctx.scale(dpr, dpr);
            this.drawTrace();
        };
        resize();
        window.addEventListener('resize', resize);

        setInterval(() => this.drawTrace(), 150);

        // -------- Pan / zoom con mouse y touch --------
        canvas.style.cursor = 'grab';
        canvas.title = 'Arrastra para mover · doble click para centrar · rueda para zoom';

        const startDrag = (cx, cy) => {
            this.trace.dragging = true;
            this.trace.dragStart = { x: cx, y: cy };
            this.trace.viewOffsetInUse = true;
            canvas.style.cursor = 'grabbing';
        };
        const moveDrag = (cx, cy) => {
            if (!this.trace.dragging) return;
            const dx = cx - this.trace.dragStart.x;
            const dy = cy - this.trace.dragStart.y;
            this.trace.viewOffset.x += dx;
            this.trace.viewOffset.y += dy;   // en píxeles, direct
            this.trace.dragStart = { x: cx, y: cy };
        };
        const endDrag = () => {
            this.trace.dragging = false;
            canvas.style.cursor = 'grab';
        };

        canvas.addEventListener('mousedown', (e) => startDrag(e.clientX, e.clientY));
        window.addEventListener('mousemove', (e) => moveDrag(e.clientX, e.clientY));
        window.addEventListener('mouseup', endDrag);

        canvas.addEventListener('touchstart', (e) => {
            if (e.touches.length !== 1) return;
            startDrag(e.touches[0].clientX, e.touches[0].clientY);
        }, { passive: true });
        canvas.addEventListener('touchmove', (e) => {
            if (e.touches.length !== 1) return;
            moveDrag(e.touches[0].clientX, e.touches[0].clientY);
        }, { passive: true });
        canvas.addEventListener('touchend', endDrag);

        canvas.addEventListener('dblclick', () => {
            this.trace.viewOffset = { x: 0, y: 0 };
            this.trace.viewOffsetInUse = false;
            this.trace.zoom = 1.0;
        });

        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const f = Math.exp(-e.deltaY * 0.0015);
            this.trace.zoom = Math.max(0.3, Math.min(4.0, this.trace.zoom * f));
        }, { passive: false });
    },

    /* ============ Lidar heatmap + paredes ============
       Recibimos puntos del lidar en coordenadas del mapa del robot. Los
       acumulamos en una grid 2D (key `ix,iy`) para formar un heatmap de
       densidad — cuanto más tiempo vea una superficie, más brillante. El
       trayecto del robot (pose del lidar) sobrescribe esto al dibujar. */
    onLidarPoints(data) {
        if (!data || !Array.isArray(data.xy)) return;
        const cell = this.trace.heatCellSize;
        const heat = this.trace.heat;
        const xy = data.xy;
        // xy viene aplanado [x0,y0,x1,y1,...]
        for (let i = 0; i + 1 < xy.length; i += 2) {
            const ix = Math.round(xy[i] / cell);
            const iy = Math.round(xy[i + 1] / cell);
            const k = ix + ',' + iy;
            heat.set(k, Math.min(255, (heat.get(k) || 0) + 1));
        }
        // Evita crecimiento ilimitado (decae cada 1500 entradas).
        if (heat.size > 20000) {
            for (const [k, v] of heat) {
                if (v <= 1) heat.delete(k);
                else heat.set(k, v - 1);
            }
        }

        if (data.pose) {
            this.trace.lidarPose = data.pose;
            const last = this.trace.history.at(-1);
            if (!last || Math.hypot(data.pose.x - last.x, data.pose.y - last.y) > 0.05) {
                this.trace.history.push({ x: data.pose.x, y: data.pose.y });
                if (this.trace.history.length > 600) this.trace.history.shift();
            }

            // Suma distancia real desde la pose anterior (filtramos saltos
            // anómalos >1 m típicos de reinicios del SLAM).
            const prev = this.trace.lastPoseForDistance;
            if (prev) {
                const d = Math.hypot(data.pose.x - prev.x, data.pose.y - prev.y);
                if (d < 1.0) this.trace.totalMeters += d;
            }
            this.trace.lastPoseForDistance = { x: data.pose.x, y: data.pose.y };
            this.updateTraceStats();
        }
    },

    updateTraceStats() {
        const km = this.trace.totalMeters / 1000;
        const steps = Math.round(this.trace.totalMeters / this.trace.metersPerStep);
        if (this.el.statDistance) this.el.statDistance.textContent = `${km.toFixed(3)} km`;
        if (this.el.statSteps) this.el.statSteps.textContent = steps.toLocaleString('es-CO');
    },

    advanceTraceFromVelocity(v, dt) {
        const p = this.trace.pose;
        p.heading += (v.z || 0) * dt;
        const forward = (v.x || 0) * dt;
        const strafe = (v.y || 0) * dt;
        p.x += forward * Math.cos(p.heading) - strafe * Math.sin(p.heading);
        p.y += forward * Math.sin(p.heading) + strafe * Math.cos(p.heading);

        if (!this.trace.history.length ||
            Math.hypot(p.x - this.trace.history.at(-1).x, p.y - this.trace.history.at(-1).y) > 0.02) {
            this.trace.history.push({ x: p.x, y: p.y });
            if (this.trace.history.length > 400) this.trace.history.shift();
        }
    },

    drawTrace() {
        const ctx = this.trace.ctx;
        const canvas = this.trace.canvas;
        if (!ctx || !canvas) return;
        const W = canvas.clientWidth;
        const H = canvas.clientHeight;
        ctx.clearRect(0, 0, W, H);

        // Fondo y grilla
        ctx.fillStyle = 'rgba(5, 10, 18, 0.85)';
        ctx.fillRect(0, 0, W, H);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
        ctx.lineWidth = 1;
        const step = 20;
        for (let x = 0; x < W; x += step) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
        }
        for (let y = 0; y < H; y += step) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }

        // Si tenemos pose del lidar, centramos la vista en el robot.
        // Si el usuario arrastró, respetamos su offset.
        const pose = this.trace.lidarPose || { x: 0, y: 0, yaw: 0 };
        const scale = (Math.min(W, H) / 8) * this.trace.zoom;   // 8 m visibles * zoom
        const off = this.trace.viewOffset;

        ctx.save();
        ctx.translate(W / 2 + off.x, H / 2 + off.y);
        ctx.scale(1, -1);  // y arriba

        // --- Heatmap de paredes (desde el lidar) ---
        const heat = this.trace.heat;
        const cell = this.trace.heatCellSize;
        const cellPx = Math.max(2, cell * scale);
        let maxHits = 1;
        for (const v of heat.values()) if (v > maxHits) maxHits = v;
        for (const [k, v] of heat) {
            const [ix, iy] = k.split(',').map(Number);
            const wx = ix * cell - pose.x;
            const wy = iy * cell - pose.y;
            // Recorta al área visible
            const px = wx * scale, py = wy * scale;
            if (Math.abs(px) > W / 2 + cellPx || Math.abs(py) > H / 2 + cellPx) continue;
            const intensity = Math.min(1, Math.pow(v / maxHits, 0.45));
            // gradiente azul -> cyan -> amarillo -> naranja
            const r = Math.round(255 * Math.min(1, intensity * 1.8 - 0.3));
            const g = Math.round(255 * Math.min(1, intensity * 1.3));
            const b = Math.round(255 * (0.9 - intensity * 0.6));
            ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${0.25 + intensity * 0.6})`;
            ctx.fillRect(px - cellPx / 2, py - cellPx / 2, cellPx, cellPx);
        }

        // --- Trayectoria (verde) relativa a la pose ---
        if (this.trace.history.length > 1) {
            ctx.strokeStyle = 'rgba(0, 230, 110, 0.9)';
            ctx.lineWidth = 2;
            ctx.beginPath();
            this.trace.history.forEach((pt, i) => {
                const px = (pt.x - pose.x) * scale;
                const py = (pt.y - pose.y) * scale;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            });
            ctx.stroke();
        }

        // --- Robot (centro) con flecha de heading ---
        ctx.fillStyle = '#1a73e8';
        ctx.shadowColor = 'rgba(90, 168, 255, 0.7)';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.arc(0, 0, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        const yaw = pose.yaw || 0;
        ctx.strokeStyle = '#5aa8ff';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(Math.cos(yaw) * 18, Math.sin(yaw) * 18);
        ctx.stroke();

        ctx.restore();
    },

    /* ============ Network helpers ============ */
    async apiCall(endpoint, method = 'POST', body = null) {
        try {
            const opt = { method, headers: { 'Content-Type': 'application/json' }, cache: 'no-store' };
            if (body) opt.body = JSON.stringify(body);
            const res = await fetch(`${API_BASE}${endpoint}`, opt);
            const text = await res.text();
            if (!text) return res.ok ? {} : { status: 'error' };
            try { return JSON.parse(text); } catch { return { status: 'error' }; }
        } catch (err) {
            return { status: 'error', message: err.message };
        }
    }
};

document.addEventListener('DOMContentLoaded', () => ControlRemoto.init());
