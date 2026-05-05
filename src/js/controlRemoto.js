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
        // Fuentes de "force" (bypass del sensor de proximidad):
        //   - forceShift:     Shift mantenido en teclado (preferido)
        //   - forceButton:    boton Override en movil mantenido
        //   - forceDoubleTap: doble tap WASD/QE (fallback legado)
        // forceActive es el OR logico de las tres y se recalcula por
        // refreshForceState(). El doble tap se resetea en stopLoop; los
        // sostenidos dependen de sus propios eventos de keyup/pointerup.
        forceActive: false,
        forceShift: false,
        forceButton: false,
        forceDoubleTap: false,
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
        heatTs: new Map(),       // ts (Date.now) del ultimo hit por voxel — canal "tiempo" 4D
        heatStartTs: 0,          // ts del primer punto del scan (para normalizar edad al guardar)
        heatCellSize: 0.08,      // 8 cm por celda XY (antes 15 cm; mas detalle fino)
        heatCellSizeZ: 0.12,     // 12 cm por capa Z (resolucion vertical del voxel)
        lastHeatPersistTs: 0,    // throttle del auto-save a localStorage
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
        this.setupMobileOverride();
        this.setupSensorToggle();
        this.setupTts();
        this.setupAutoRotate();
        this.setupSaveRoute();
        this.setupKeyboard();
        this.setupSidePanelToggle();
        this.setupTraceActions();
        this.initTraceCanvas();
        this.restoreLiveScan();
        this.setupSpeedControl();
        this.setupVideoRecording();
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

            // Shift mantenido = modo FORCE sostenido. Ideal para entornos
            // con muchas detecciones: no hay que doble-tapear cada vez.
            if (e.key === 'Shift') {
                if (!this.movement.forceShift) {
                    this.movement.forceShift = true;
                    this.refreshForceState();
                }
                return;
            }

            const cross = KEY_TO_CROSS[e.key];
            if (cross) {
                e.preventDefault();
                if (!keys.has(e.key)) { keys.add(e.key); this.pressCross(cross); }
                return;
            }

            if (/^[wWsSaAdDqQeE]$/.test(e.key)) {
                e.preventDefault();
                // Doble tap de la misma tecla en <350 ms activa FORCE como
                // fallback (compatibilidad). Se limpia en stopLoop.
                if (!keys.has(e.key)) {
                    const now = Date.now();
                    const k = e.key.toLowerCase();
                    const last = this.movement.lastKeyTap[k] || 0;
                    if (now - last < 350) {
                        this.movement.forceDoubleTap = true;
                        this.refreshForceState();
                    }
                    this.movement.lastKeyTap[k] = now;
                }
                keys.add(e.key);
                this.recomputeKeyboardVector();
            }
        });

        document.addEventListener('keyup', (e) => {
            if (e.key === 'Shift') {
                if (this.movement.forceShift) {
                    this.movement.forceShift = false;
                    this.refreshForceState();
                }
                return;
            }
            if (!keys.has(e.key)) return;
            keys.delete(e.key);
            if (KEY_TO_CROSS[e.key]) { this.releaseCross(KEY_TO_CROSS[e.key]); return; }
            this.recomputeKeyboardVector();
        });

        // If the window loses focus, treat every key as released and force-stop.
        // Without this, holding W and alt-tabbing away would leave the robot moving.
        const abort = () => {
            keys.clear();
            this.movement.forceShift = false;
            this.stopMovement();
        };
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

    refreshForceState() {
        const m = this.movement;
        const active = m.forceShift || m.forceButton || m.forceDoubleTap;
        m.forceActive = active;
        if (active) this.showForceBadge();
        else this.hideForceBadge();
    },

    stopLoop() {
        if (this.movement.interval) {
            clearInterval(this.movement.interval);
            this.movement.interval = null;
        }
        // Al soltar todas las teclas se limpia solo el fallback de doble tap.
        // Shift y el boton Override siguen controlados por sus propios eventos,
        // asi que si el operador los mantiene, la siguiente conduccion sigue
        // forzada sin repetir el gesto.
        if (this.movement.forceDoubleTap) {
            this.movement.forceDoubleTap = false;
        }
        this.refreshForceState();
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

    /* ============ Mobile Override (hold-to-force) ============
       Mientras se mantiene, los comandos de movimiento se marcan con
       force=true: el backend saltara el bloqueo del sensor. Equivalente
       movil a sostener Shift en teclado. */
    setupMobileOverride() {
        const btn = document.getElementById('cr-mobile-override');
        if (!btn) return;

        const press = (e) => {
            if (e) e.preventDefault();
            if (this.movement.forceButton) return;
            this.movement.forceButton = true;
            btn.classList.add('pressed');
            btn.setAttribute('aria-pressed', 'true');
            this.refreshForceState();
        };
        const release = () => {
            if (!this.movement.forceButton) return;
            this.movement.forceButton = false;
            btn.classList.remove('pressed');
            btn.setAttribute('aria-pressed', 'false');
            this.refreshForceState();
        };

        btn.addEventListener('pointerdown', press);
        btn.addEventListener('pointerup', release);
        btn.addEventListener('pointercancel', release);
        btn.addEventListener('pointerleave', release);
        // Accesibilidad: Space/Enter con el boton enfocado tambien fuerzan.
        btn.addEventListener('keydown', (e) => {
            if (e.key === ' ' || e.key === 'Enter') press(e);
        });
        btn.addEventListener('keyup', (e) => {
            if (e.key === ' ' || e.key === 'Enter') release();
        });
        btn.addEventListener('blur', release);
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
        // Modo FORCE (Shift sostenido, boton Override o doble tap): el
        // operador ha aceptado el riesgo. Ignoramos la alerta completa:
        // nada de stopMovement, nada de stop_command, nada de banner.
        // El robot sigue caminando como si el sensor estuviera apagado.
        if (this.movement.forceActive) return;

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

    /* ============ Reiniciar origen / Ir a ruta guiada ============
       Los dos botones nuevos del panel del mini-mapa. El de reinicio limpia
       trayectoria, heatmap y pose base; el de QR navega a la pagina de
       ruta guiada donde el robot captura waypoints a partir de QRs. */
    setupTraceActions() {
        const btnReset = document.getElementById('cr-reset-origin');
        const btnQR = document.getElementById('cr-go-qr');
        if (btnReset) {
            btnReset.addEventListener('click', () => this.resetOriginAndTrace());
        }
        if (btnQR) {
            btnQR.addEventListener('click', () => this.handleGoToQR());
        }

        // Botones del modal "usa tu celular"
        const mo = document.getElementById('cr-mobile-only-modal');
        const moClose = document.getElementById('cr-mo-close');
        const moContinue = document.getElementById('cr-mo-continue');
        if (moClose && mo) {
            moClose.addEventListener('click', () => mo.classList.add('hidden'));
        }
        if (moContinue) {
            moContinue.addEventListener('click', () => { window.location.href = '/rutaguiada'; });
        }
    },

    /* En escritorio la ruta guiada por QR no tiene sentido (necesitas
       caminar junto al robot mostrando marcadores). Mostramos un aviso
       con un QR de la URL para que el operador lo escanee con el
       celular y abra la pagina alli. En mobile se navega directo. */
    handleGoToQR() {
        const isTouchDevice = window.matchMedia &&
            (window.matchMedia('(hover: none) and (pointer: coarse)').matches
             || window.matchMedia('(max-width: 900px)').matches);
        if (isTouchDevice) {
            window.location.href = '/rutaguiada';
            return;
        }
        this.showMobileOnlyModal();
    },

    showMobileOnlyModal() {
        const mo = document.getElementById('cr-mobile-only-modal');
        if (!mo) return;
        const targetUrl = `${window.location.origin}/rutaguiada`;
        const img = document.getElementById('cr-mo-qr-img');
        const urlText = document.getElementById('cr-mo-url-text');
        if (img) {
            img.src = `/api/qr/image?text=${encodeURIComponent(targetUrl)}&t=${Date.now()}`;
        }
        if (urlText) {
            urlText.textContent = targetUrl;
        }
        mo.classList.remove('hidden');
    },

    resetOriginAndTrace() {
        if (!confirm('Borrar el mapa de calor y reiniciar el punto de origen aqui?')) return;
        this.trace.history = [];
        this.trace.heat = new Map();
        this.trace.heatTs = new Map();
        this.trace.heatStartTs = 0;
        this.trace.pose = { x: 0, y: 0, heading: 0 };
        this.trace.totalMeters = 0.0;
        this.trace.lastPoseForDistance = null;
        this.trace.lidarPose = null;
        this.trace.lastHeatPersistTs = 0;
        try { localStorage.removeItem('daiver:liveScan'); } catch (_) {}
        this.updateTraceStats();
        this.drawTrace();
    },

    /* ============ Guardar ruta y abrir Auto-Ruta ============
       Serializa la trayectoria registrada y la deja en localStorage para
       que la página de auto-ruta la cargue. Si hay menos de 4 puntos,
       avisa y no navega. */
    setupSaveRoute() {
        const btn = document.getElementById('cr-save-route');
        if (!btn) return;
        btn.addEventListener('click', () => {
            const pts = this.trace.history.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
            if (pts.length < 4) {
                alert('Camina primero un poco con el robot para registrar una ruta (mínimo 4 puntos).');
                return;
            }
            // Muestreo grueso: un waypoint cada ~60 cm (antes 40 cm). El
            // backend se atasca con waypoints muy juntos y el SLAM del Go2
            // genera drift que se transformaba en waypoints fantasma.
            const sampled = [pts[0]];
            for (const p of pts) {
                const last = sampled.at(-1);
                if (Math.hypot(p.x - last.x, p.y - last.y) >= 0.60) sampled.push(p);
            }
            // Garantiza que el ultimo waypoint este incluido aun si quedo
            // a <60 cm del previo (no perdemos el destino final).
            const tail = pts[pts.length - 1];
            const lastSampled = sampled[sampled.length - 1];
            if (Math.hypot(tail.x - lastSampled.x, tail.y - lastSampled.y) > 0.05) {
                sampled.push(tail);
            }
            // Douglas-Peucker: elimina puntos que estan casi en linea recta
            // entre sus vecinos. Quita el "zigzag" de drift sin tocar las
            // esquinas reales. Tolerancia 12 cm (mayor = ruta mas suelta).
            const simplified = sampled.length >= 3
                ? this._douglasPeucker(sampled, 0.12)
                : sampled;

            // Serializa el heatmap 3D (Map -> array [ix,iy,iz,v,age]).
            // age en [0..1]: 1 = capturado al final del scan, 0 = al inicio.
            const now = Date.now();
            const span = Math.max(1, now - (this.trace.heatStartTs || now));
            const heatArr = [];
            for (const [k, v] of this.trace.heat) {
                if (v < 2) continue;  // descarta ruido aislado
                const parts = k.split(',').map(Number);
                const ix = parts[0], iy = parts[1];
                const iz = parts.length > 2 ? parts[2] : 0;
                const ts = this.trace.heatTs.get(k) || now;
                const age = Math.max(0, Math.min(1, 1 - (now - ts) / span));
                heatArr.push([ix, iy, iz, v, +age.toFixed(3)]);
            }
            const payload = {
                savedAt: now,
                heatStartTs: this.trace.heatStartTs,
                points: simplified,
                totalMeters: this.trace.totalMeters,
                heatCellSize: this.trace.heatCellSize,
                heatCellSizeZ: this.trace.heatCellSizeZ,
                heat: heatArr,
            };
            try {
                localStorage.setItem('daiver:lastRoute', JSON.stringify(payload));
            } catch (err) {
                console.warn('heat demasiado grande para localStorage, se guardara sin heat', err);
                payload.heat = [];
                payload.heatTruncated = true;
                localStorage.setItem('daiver:lastRoute', JSON.stringify(payload));
            }
            window.location.href = '/autoroute';
        });
    },

    /* Ramer-Douglas-Peucker: simplifica una polilinea descartando puntos
       que estan a menos de `epsilon` (m) de la cuerda entre sus vecinos.
       Conserva esquinas reales y elimina drift colineal. */
    _douglasPeucker(points, epsilon) {
        if (points.length < 3) return points.slice();
        const a = points[0], b = points[points.length - 1];
        const dx = b.x - a.x, dy = b.y - a.y;
        const denom = dx * dx + dy * dy;
        let dmax = 0, idx = 0;
        for (let i = 1; i < points.length - 1; i++) {
            const p = points[i];
            let d;
            if (denom === 0) {
                d = Math.hypot(p.x - a.x, p.y - a.y);
            } else {
                const t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / denom;
                const tx = a.x + t * dx, ty = a.y + t * dy;
                d = Math.hypot(p.x - tx, p.y - ty);
            }
            if (d > dmax) { dmax = d; idx = i; }
        }
        if (dmax > epsilon) {
            const left  = this._douglasPeucker(points.slice(0, idx + 1), epsilon);
            const right = this._douglasPeucker(points.slice(idx),       epsilon);
            return left.slice(0, -1).concat(right);
        }
        return [a, b];
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

    /* ============ Control de velocidad ============
       Slider con cuatro zonas (semaforo): lento / normal / rapido / emergencia.
       Ajusta App.movement.speedFactor (0.15–1.00) y persiste la preferencia
       en localStorage. Sincroniza los dos sliders (side panel + flotante). */
    setupSpeedControl() {
        const LS_KEY = 'cr_speed_factor';
        const sliderDesktop = document.getElementById('cr-speed-slider');
        const sliderMobile  = document.getElementById('cr-speed-slider-m');
        const statusDesktop = document.getElementById('cr-speed-status');
        const statusMobile  = document.getElementById('cr-speed-floating');
        const labelDesktop  = document.getElementById('cr-speed-label');
        const labelMobile   = document.getElementById('cr-speed-label-m');
        const pctDesktop    = document.getElementById('cr-speed-pct');
        const pctMobile     = document.getElementById('cr-speed-pct-m');

        if (!sliderDesktop && !sliderMobile) return;

        // Rango del slider: 15 – 100 (%). Internamente va a 0.15–1.00.
        // Zonas: <35 lento, <60 normal, <85 rapido, >=85 emergencia.
        const zoneFor = (pct) => {
            if (pct >= 85) return { level: 'max',    label: 'EMERGENCIA', color: '#ef4444' };
            if (pct >= 60) return { level: 'fast',   label: 'RÁPIDO',     color: '#f97316' };
            if (pct >= 35) return { level: 'normal', label: 'NORMAL',     color: '#facc15' };
            return { level: 'slow', label: 'LENTO', color: '#22c55e' };
        };

        // Carga valor guardado o usa el default del objeto movement
        let initial = parseInt(localStorage.getItem(LS_KEY), 10);
        if (isNaN(initial) || initial < 15 || initial > 100) {
            initial = Math.round((this.movement?.speedFactor || 0.45) * 100);
        }

        const apply = (pct, fromEl) => {
            pct = Math.max(15, Math.min(100, Math.round(pct)));
            const factor = pct / 100;

            // Actualiza el estado interno del movimiento
            if (this.movement) this.movement.speedFactor = factor;
            // Guarda preferencia
            try { localStorage.setItem(LS_KEY, String(pct)); } catch (e) { /* ignore */ }

            // Sincroniza sliders (sin disparar loop infinito)
            if (sliderDesktop && fromEl !== sliderDesktop) sliderDesktop.value = pct;
            if (sliderMobile  && fromEl !== sliderMobile)  sliderMobile.value  = pct;

            // Actualiza labels y estado visual del slider
            const zone = zoneFor(pct);
            [statusDesktop, statusMobile].forEach(el => el && el.setAttribute('data-level', zone.level));
            [labelDesktop, labelMobile].forEach(el => { if (el) el.textContent = zone.label; });
            [pctDesktop, pctMobile].forEach(el => { if (el) el.textContent = pct + '%'; });

            // Variables CSS para pintar SOLO la parte llena del track en su color
            [sliderDesktop, sliderMobile].forEach(el => {
                if (!el) return;
                el.style.setProperty('--speed-pct', String(pct));
                el.style.setProperty('--speed-color', zone.color);
            });

            // --- Métrica "Velocidad" del panel Telemetría: reflejar el slider ---
            const metricSpeed = document.getElementById('cr-m-speed');
            const metricSpeedBar = document.getElementById('cr-m-speed-bar');
            const metricSpeedBox = document.getElementById('cr-metric-speed');

            if (metricSpeed) {
                // Texto: porcentaje + etiqueta corta ("45% · NORMAL")
                const shortLabel = zone.label.replace(/^⚠ /, '');
                metricSpeed.textContent = pct + '% · ' + shortLabel;
            }
            if (metricSpeedBar) {
                metricSpeedBar.style.width = pct + '%';
            }
            if (metricSpeedBox) {
                metricSpeedBox.setAttribute('data-level', zone.level);
            }

            // --- Barra vertical de velocidad (solo móvil, costado derecho) ---
            const tape = document.getElementById('cr-speed-tape');
            const tapeFill = document.getElementById('cr-speed-tape-fill');
            const tapeVal = document.getElementById('cr-speed-tape-val');
            const tapeTrackEl = document.getElementById('cr-speed-tape-track');
            if (tape) tape.setAttribute('data-level', zone.level);
            if (tapeFill) tapeFill.style.height = pct + '%';
            if (tapeVal) tapeVal.textContent = pct + '%';
            if (tapeTrackEl) tapeTrackEl.setAttribute('aria-valuenow', String(pct));
        };

        sliderDesktop?.addEventListener('input', (e) => apply(parseInt(e.target.value, 10), sliderDesktop));
        sliderMobile?.addEventListener('input',  (e) => apply(parseInt(e.target.value, 10), sliderMobile));

        // --- Barra vertical interactiva (móvil): botones +/- y track tappable ---
        const tapeUp    = document.getElementById('cr-speed-tape-up');
        const tapeDown  = document.getElementById('cr-speed-tape-down');
        const tapeTrack = document.getElementById('cr-speed-tape-track');
        const STEP = 5;

        const currentPct = () => {
            const v = sliderMobile?.value ?? sliderDesktop?.value;
            const n = parseInt(v, 10);
            return isNaN(n) ? Math.round((this.movement?.speedFactor || 0.45) * 100) : n;
        };

        tapeUp?.addEventListener('click', () => apply(currentPct() + STEP, null));
        tapeDown?.addEventListener('click', () => apply(currentPct() - STEP, null));

        // Tap/drag sobre el track: la posición vertical se traduce a %.
        // Top = 100%, bottom = 0%; se cuantiza al STEP para encajar con el slider.
        if (tapeTrack) {
            const pctFromY = (clientY) => {
                const rect = tapeTrack.getBoundingClientRect();
                const ratio = 1 - (clientY - rect.top) / rect.height;
                const raw = ratio * 100;
                return Math.max(15, Math.min(100, Math.round(raw / STEP) * STEP));
            };
            let dragging = false;
            tapeTrack.addEventListener('pointerdown', (e) => {
                dragging = true;
                tapeTrack.setPointerCapture?.(e.pointerId);
                apply(pctFromY(e.clientY), null);
                e.preventDefault();
            });
            tapeTrack.addEventListener('pointermove', (e) => {
                if (!dragging) return;
                apply(pctFromY(e.clientY), null);
            });
            const stop = (e) => {
                dragging = false;
                try { tapeTrack.releasePointerCapture?.(e.pointerId); } catch {}
            };
            tapeTrack.addEventListener('pointerup', stop);
            tapeTrack.addEventListener('pointercancel', stop);
        }

        // Estado inicial
        apply(initial, null);
    },

    /* ============ Grabación de video ============
       Captura el <img id="cr-video"> (stream MJPEG same-origin) hacia un
       canvas oculto y graba el resultado con MediaRecorder. Al detener,
       genera un Blob y dispara la descarga como archivo .webm/.mp4. */
    setupVideoRecording() {
        const btnDesktop = document.getElementById('cr-record');
        const btnMobile  = document.getElementById('cr-mobile-record');
        if (!btnDesktop && !btnMobile) return;

        // Sin soporte de MediaRecorder (algunos iOS muy viejos): ocultar UI.
        if (typeof MediaRecorder === 'undefined' || !HTMLCanvasElement.prototype.captureStream) {
            btnDesktop?.style.setProperty('display', 'none', 'important');
            btnMobile?.style.setProperty('display', 'none', 'important');
            return;
        }

        // Estado de grabación se cuelga de this para que setYoloRunning
        // pueda detenerlo si el stream cae mientras se está grabando.
        this.recording = {
            active: false,
            recorder: null,
            chunks: [],
            canvas: null,
            ctx: null,
            drawTimer: null,
            timerInterval: null,
            startTs: 0,
            mimeType: ''
        };

        const toggle = () => {
            if (!this.state.yoloRunning) {
                alert('Activa el stream YOLO para poder grabar video.');
                return;
            }
            if (this.recording.active) this.stopVideoRecording();
            else this.startVideoRecording();
        };

        btnDesktop?.addEventListener('click', toggle);
        btnMobile?.addEventListener('click', toggle);
    },

    /* startVideoRecording — produce SIEMPRE MP4 (H.264) cuando es posible.
       Estrategia:
         1. Si hay WebCodecs (VideoEncoder) + mp4-muxer cargado, usamos esa
            ruta: VideoEncoder genera chunks AVC y el muxer los empaqueta
            directamente en un contenedor MP4. Esto funciona en Chrome /
            Edge / Safari modernos AUN cuando MediaRecorder no exponga MP4.
         2. Fallback: MediaRecorder. Intentamos primero variantes MP4 y, si
            no están disponibles, dejamos webm con la extensión correcta. */
    async startVideoRecording() {
        const r = this.recording;
        if (!r || r.active) return;
        const videoEl = this.el.video;
        if (!videoEl || !videoEl.src) {
            alert('No hay stream de video activo.');
            return;
        }

        const w = videoEl.naturalWidth  || 640;
        const h = videoEl.naturalHeight || 480;
        const canvas = document.createElement('canvas');
        canvas.width  = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');

        // --- Ruta WebCodecs + mp4-muxer (MP4 real garantizado) ---
        const canUseWebCodecs = typeof window.VideoEncoder !== 'undefined'
                              && typeof window.VideoFrame !== 'undefined'
                              && typeof window.Mp4Muxer !== 'undefined';
        if (canUseWebCodecs) {
            try {
                await this._startRecordingMp4(videoEl, canvas, ctx, w, h);
                return;
            } catch (e) {
                console.warn('[REC] Ruta MP4 WebCodecs falló, usando MediaRecorder:', e);
            }
        }

        // --- Fallback MediaRecorder ---
        let mimeType = '';
        const candidates = [
            'video/mp4;codecs=avc1.42E01E,mp4a.40.2',
            'video/mp4;codecs=avc1,mp4a',
            'video/mp4;codecs=h264,aac',
            'video/mp4;codecs=avc1',
            'video/mp4;codecs=h264',
            'video/mp4',
            'video/webm;codecs=h264',
            'video/webm;codecs=vp9',
            'video/webm;codecs=vp8',
            'video/webm'
        ];
        for (const m of candidates) {
            if (MediaRecorder.isTypeSupported(m)) { mimeType = m; break; }
        }
        if (!mimeType) {
            alert('Tu navegador no soporta grabación de video.');
            return;
        }
        if (!mimeType.includes('mp4')) {
            console.warn('[REC] MP4 no soportado en este navegador; usando webm:', mimeType);
        }

        const stream = canvas.captureStream(30);
        const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 2_500_000 });
        const chunks = [];
        recorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: mimeType.split(';')[0] });
            const ext = mimeType.includes('mp4') ? 'mp4' : 'webm';
            this._downloadRecordingBlob(blob, ext);
        };

        r.drawTimer = setInterval(() => {
            try {
                if (videoEl.naturalWidth && videoEl.naturalHeight) {
                    ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
                }
            } catch (e) { /* frame no listo aun */ }
        }, 1000 / 30);

        recorder.start(1000);
        r.active = true;
        r.useWebCodecs = false;
        r.recorder = recorder;
        r.chunks = chunks;
        r.canvas = canvas;
        r.ctx = ctx;
        r.startTs = Date.now();
        r.mimeType = mimeType;
        this._showRecordingUI();
    },

    /* Ruta WebCodecs: VideoEncoder + Mp4Muxer.Muxer
       - Codifica cada frame como AVC (H.264) baseline.
       - El muxer agrupa los chunks en un contenedor .mp4 reproducible
         por cualquier player (VLC, QuickTime, Windows Media, etc.). */
    async _startRecordingMp4(videoEl, canvas, ctx, w, h) {
        const r = this.recording;
        const { Muxer, ArrayBufferTarget } = window.Mp4Muxer;

        const target = new ArrayBufferTarget();
        const muxer = new Muxer({
            target,
            video: { codec: 'avc', width: w, height: h, frameRate: 30 },
            fastStart: 'in-memory'
        });

        const encoder = new VideoEncoder({
            output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
            error: (e) => console.error('[REC] VideoEncoder:', e)
        });

        // avc1.42E01E = H.264 Baseline @ Level 3.0 — máxima compatibilidad.
        // Si el navegador rechaza el codec, lanzamos para caer al fallback.
        const support = await VideoEncoder.isConfigSupported({
            codec: 'avc1.42E01E', width: w, height: h, bitrate: 2_500_000, framerate: 30
        });
        if (!support || !support.supported) {
            throw new Error('avc1 no soportado por VideoEncoder');
        }

        encoder.configure({
            codec: 'avc1.42E01E',
            width: w,
            height: h,
            bitrate: 2_500_000,
            framerate: 30,
            avc: { format: 'avc' }
        });

        r.useWebCodecs = true;
        r.encoder = encoder;
        r.muxer = muxer;
        r.muxTarget = target;
        r.canvas = canvas;
        r.ctx = ctx;
        r.frameCount = 0;
        r.startTs = Date.now();
        r.active = true;

        const startPerf = performance.now();
        r.drawTimer = setInterval(() => {
            try {
                if (!videoEl.naturalWidth || !videoEl.naturalHeight) return;
                ctx.drawImage(videoEl, 0, 0, w, h);
                const tsMicro = Math.round((performance.now() - startPerf) * 1000);
                const frame = new VideoFrame(canvas, { timestamp: tsMicro });
                // keyframe cada ~2 s (60 frames a 30 fps) para que el archivo
                // sea seekable y, si se trunca, los frames previos se vean.
                encoder.encode(frame, { keyFrame: r.frameCount % 60 === 0 });
                frame.close();
                r.frameCount++;
                // Reactivamos backpressure: si la cola del encoder se llena,
                // skipemos el siguiente frame en lugar de acumular memoria.
            } catch (e) {
                console.warn('[REC] frame error:', e);
            }
        }, 1000 / 30);

        this._showRecordingUI();
    },

    _showRecordingUI() {
        const r = this.recording;
        const indicator = document.getElementById('cr-rec-indicator');
        const timeEl = document.getElementById('cr-rec-time');
        indicator?.classList.add('visible');
        const fmt = (ms) => {
            const t = Math.floor(ms / 1000);
            return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
        };
        if (timeEl) timeEl.textContent = '0:00';
        r.timerInterval = setInterval(() => {
            if (timeEl) timeEl.textContent = fmt(Date.now() - r.startTs);
        }, 250);
        document.getElementById('cr-record')?.setAttribute('aria-pressed', 'true');
        document.getElementById('cr-mobile-record')?.setAttribute('aria-pressed', 'true');
        const lbl = document.querySelector('#cr-record .cr-rec-lbl');
        if (lbl) lbl.textContent = 'STOP';
    },

    _downloadRecordingBlob(blob, ext) {
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `daiver-${ts}.${ext}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
    },

    async stopVideoRecording() {
        const r = this.recording;
        if (!r || !r.active) return;

        if (r.drawTimer) { clearInterval(r.drawTimer); r.drawTimer = null; }
        if (r.timerInterval) { clearInterval(r.timerInterval); r.timerInterval = null; }

        if (r.useWebCodecs && r.encoder && r.muxer) {
            try {
                await r.encoder.flush();
                r.muxer.finalize();
                const blob = new Blob([r.muxTarget.buffer], { type: 'video/mp4' });
                this._downloadRecordingBlob(blob, 'mp4');
            } catch (e) {
                console.error('[REC] Error finalizando MP4:', e);
                alert('Error al guardar el video: ' + (e?.message || e));
            } finally {
                try { r.encoder.close(); } catch (_) {}
            }
        } else if (r.recorder && r.recorder.state !== 'inactive') {
            try { r.recorder.stop(); } catch (e) { /* ignore */ }
        }

        r.active = false;
        r.recorder = null;
        r.encoder = null;
        r.muxer = null;
        r.muxTarget = null;
        r.chunks = [];
        r.canvas = null;
        r.ctx = null;

        document.getElementById('cr-rec-indicator')?.classList.remove('visible');
        document.getElementById('cr-record')?.setAttribute('aria-pressed', 'false');
        document.getElementById('cr-mobile-record')?.setAttribute('aria-pressed', 'false');
        const lbl = document.querySelector('#cr-record .cr-rec-lbl');
        if (lbl) lbl.textContent = 'REC';
        const timeEl = document.getElementById('cr-rec-time');
        if (timeEl) timeEl.textContent = '0:00';
    },

    /* ============ YOLO ============ */
    async startYolo() {
        const payload = {
            source: this.state.robotConnected ? 'robot' : 'webcam',
            camera_index: 0,
            conf: 0.4,
            model: 'yolov8n-pose.pt',
            imgsz: 416,
            with_objects: false
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
        // Habilitar grabación solo cuando hay stream; si se detiene mientras
        // grabamos, parar la grabación para no producir un video corrupto.
        const recBtnD = document.getElementById('cr-record');
        const recBtnM = document.getElementById('cr-mobile-record');
        if (recBtnD) recBtnD.disabled = !running;
        if (recBtnM) recBtnM.disabled = !running;
        if (!running && this.recording && this.recording.active) {
            this.stopVideoRecording();
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
       acumulamos en una grid 3D (key `ix,iy,iz`) para formar un heatmap de
       densidad — cuanto más tiempo vea una superficie, más brillante. Por
       cada voxel guardamos también el ts del último hit (canal "tiempo"
       que la auto-ruta usa para fade por edad). */
    onLidarPoints(data) {
        if (!data) return;
        const cell = this.trace.heatCellSize;
        const cellZ = this.trace.heatCellSizeZ;
        const heat = this.trace.heat;
        const heatTs = this.trace.heatTs;
        const now = Date.now();
        if (!this.trace.heatStartTs) this.trace.heatStartTs = now;

        // Preferimos xyz (3D real). Fallback a xy (backend antiguo).
        const xyz = Array.isArray(data.xyz) ? data.xyz : null;
        if (xyz) {
            for (let i = 0; i + 2 < xyz.length; i += 3) {
                const ix = Math.round(xyz[i] / cell);
                const iy = Math.round(xyz[i + 1] / cell);
                const iz = Math.round(xyz[i + 2] / cellZ);
                const k = ix + ',' + iy + ',' + iz;
                heat.set(k, Math.min(255, (heat.get(k) || 0) + 1));
                heatTs.set(k, now);
            }
        } else if (Array.isArray(data.xy)) {
            const xy = data.xy;
            for (let i = 0; i + 1 < xy.length; i += 2) {
                const ix = Math.round(xy[i] / cell);
                const iy = Math.round(xy[i + 1] / cell);
                const k = ix + ',' + iy + ',0';
                heat.set(k, Math.min(255, (heat.get(k) || 0) + 1));
                heatTs.set(k, now);
            }
        }

        // Evita crecimiento ilimitado: cuando hay muchas voxels, decae
        // solo los de baja confianza (ruido) y preserva los firmes.
        if (heat.size > 40000) {
            for (const [k, v] of heat) {
                if (v <= 1) { heat.delete(k); heatTs.delete(k); }
                else heat.set(k, v - 1);
            }
        }

        if (data.pose) {
            this.trace.lidarPose = data.pose;
            // Trail de pose con filtro de saltos del SLAM. Solo aceptamos
            // desplazamientos plausibles (>5 cm para anti-jitter, <60 cm
            // para descartar drift/relocalizaciones que generan waypoints
            // fantasma al guardar la ruta).
            const last = this.trace.history.at(-1);
            if (!last) {
                this.trace.history.push({ x: data.pose.x, y: data.pose.y });
            } else {
                const d = Math.hypot(data.pose.x - last.x, data.pose.y - last.y);
                if (d > 0.05 && d < 0.60) {
                    this.trace.history.push({ x: data.pose.x, y: data.pose.y });
                    if (this.trace.history.length > 600) this.trace.history.shift();
                }
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

        // Auto-persiste el escaneo cada 10 s para sobrevivir recargas.
        this.maybePersistLiveScan();
    },

    /* Auto-save throttled del heatmap 3D. Conserva el escaneo entre recargas
       dentro de la misma sesion y al cambiar de pagina. Al restaurar, los
       voxels siguen ahi y solo se suman los nuevos. */
    maybePersistLiveScan() {
        const now = Date.now();
        if (now - this.trace.lastHeatPersistTs < 10000) return;
        this.trace.lastHeatPersistTs = now;
        try {
            // Normaliza la edad de cada voxel a [0..1]: 1 = capturado ahora,
            // 0 = capturado al inicio del escaneo. Asi la auto-ruta puede
            // dibujar fade por antiguedad sin necesitar timestamps absolutos.
            const span = Math.max(1, now - (this.trace.heatStartTs || now));
            const arr = [];
            for (const [k, v] of this.trace.heat) {
                if (v < 2) continue;
                const parts = k.split(',').map(Number);
                const ts = this.trace.heatTs.get(k) || now;
                const age = Math.max(0, Math.min(1, 1 - (now - ts) / span));
                arr.push([parts[0], parts[1], parts.length > 2 ? parts[2] : 0, v, +age.toFixed(3)]);
            }
            localStorage.setItem('daiver:liveScan', JSON.stringify({
                savedAt: now,
                heatStartTs: this.trace.heatStartTs,
                heatCellSize: this.trace.heatCellSize,
                heatCellSizeZ: this.trace.heatCellSizeZ,
                heat: arr,
                history: this.trace.history.slice(-400),
                totalMeters: this.trace.totalMeters,
            }));
        } catch (_) {
            // Quota: dejar como esta (proxima ronda decae voxels debiles)
        }
    },

    restoreLiveScan() {
        try {
            const raw = localStorage.getItem('daiver:liveScan');
            if (!raw) return;
            const data = JSON.parse(raw);
            if (!data) return;
            if (data.heatCellSize) this.trace.heatCellSize = data.heatCellSize;
            if (data.heatCellSizeZ) this.trace.heatCellSizeZ = data.heatCellSizeZ;
            if (typeof data.heatStartTs === 'number') this.trace.heatStartTs = data.heatStartTs;
            if (Array.isArray(data.heat)) {
                const now = Date.now();
                const savedAt = data.savedAt || now;
                const span = Math.max(1, savedAt - (data.heatStartTs || savedAt));
                for (const h of data.heat) {
                    const k = h[0] + ',' + h[1] + ',' + (h[2] || 0);
                    this.trace.heat.set(k, h[3]);
                    // Si guardamos age normalizado (formato nuevo, 5 elems),
                    // reconstruimos un ts absoluto plausible. Si no, asumimos
                    // que todo se capturo cerca del savedAt.
                    const age = h.length >= 5 ? h[4] : 1;
                    this.trace.heatTs.set(k, savedAt - (1 - age) * span);
                }
            }
            if (Array.isArray(data.history)) {
                this.trace.history = data.history.slice();
            }
            if (typeof data.totalMeters === 'number') {
                this.trace.totalMeters = data.totalMeters;
            }
        } catch (_) { /* ignore */ }
    },

    updateTraceStats() {
        const km = this.trace.totalMeters / 1000;
        const steps = Math.round(this.trace.totalMeters / this.trace.metersPerStep);
        if (this.el.statDistance) this.el.statDistance.textContent = `${km.toFixed(3)} km`;
        if (this.el.statSteps) this.el.statSteps.textContent = steps.toLocaleString('es-CO');
    },

    /* ============ Indicador de rumbo (línea roja, móvil) ============
       Convierte el heading (radianes) a grados 0–360 y actualiza el badge
       y la etiqueta cardinal (N / NE / E / SE / S / SO / O / NO). */
    updateHeadingStrip() {
        const label    = document.getElementById('cr-heading-label');
        const card     = document.getElementById('cr-heading-card');
        const panel    = document.getElementById('cr-m-heading');
        const floatVal = document.getElementById('cr-heading-floating-val');
        const floatCd  = document.getElementById('cr-heading-floating-card');

        const h = (this.trace && this.trace.pose) ? this.trace.pose.heading : 0;
        let deg = (h * 180 / Math.PI) % 360;
        if (deg < 0) deg += 360;
        const degInt = Math.round(deg);

        const cards = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];
        const idx = Math.round(deg / 45) % 8;

        if (label)    label.textContent    = degInt + '°';
        if (card)     card.textContent     = cards[idx];
        if (panel)    panel.textContent    = degInt + '° ' + cards[idx];
        if (floatVal) floatVal.textContent = degInt + '°';
        if (floatCd)  floatCd.textContent  = cards[idx];

        // Rotar aguja de la mini brújula (web, panel Telemetría)
        const needle = document.getElementById('cr-compass-needle');
        if (needle) needle.setAttribute('transform', `rotate(${degInt} 20 20)`);
    },

    advanceTraceFromVelocity(v, dt) {
        const p = this.trace.pose;
        p.heading += (v.z || 0) * dt;
        const forward = (v.x || 0) * dt;
        const strafe = (v.y || 0) * dt;
        p.x += forward * Math.cos(p.heading) - strafe * Math.sin(p.heading);
        p.y += forward * Math.sin(p.heading) + strafe * Math.cos(p.heading);

        // Refrescar indicador de rumbo (móvil)
        this.updateHeadingStrip();

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

        // --- Heatmap de paredes (desde el lidar 3D) ---
        // Colapsamos los voxels 3D a la columna (x,y) de mayor intensidad
        // para el mini-mapa del control remoto. El 3D completo se ve en
        // la pagina de Auto-Ruta.
        const heat = this.trace.heat;
        const cell = this.trace.heatCellSize;
        const cellPx = Math.max(2, cell * scale);
        const column = new Map();  // "ix,iy" -> max v
        let maxHits = 1;
        for (const [k, v] of heat) {
            const parts = k.split(',');
            const colKey = parts[0] + ',' + parts[1];
            const cur = column.get(colKey) || 0;
            if (v > cur) column.set(colKey, v);
            if (v > maxHits) maxHits = v;
        }
        for (const [colKey, v] of column) {
            if (v < 2) continue;  // umbral de confianza
            const [ix, iy] = colKey.split(',').map(Number);
            const wx = ix * cell - pose.x;
            const wy = iy * cell - pose.y;
            const px = wx * scale, py = wy * scale;
            if (Math.abs(px) > W / 2 + cellPx || Math.abs(py) > H / 2 + cellPx) continue;
            const intensity = Math.min(1, Math.pow(v / maxHits, 0.45));
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
