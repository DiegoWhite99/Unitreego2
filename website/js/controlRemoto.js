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
        battery: 0,
        mode: '--',
        ip: ''
    },

    // Movement state (dead-man's switch: robot moves ONLY while an input is held)
    movement: {
        speedFactor: 0.45,
        rotFactor: 0.75,
        interval: null,
        activeKeys: new Set(),
        // Three independent input sources — the final velocity is composed
        // from whichever are non-zero. When all go to zero, the loop stops
        // and stop_command is emitted immediately.
        keyboard: { x: 0, y: 0, z: 0 },
        joyMove: { x: 0, y: 0 },
        joyRotate: { z: 0 }
    },

    // Simple dead-reckoning trace
    trace: {
        canvas: null,
        ctx: null,
        history: [],           // [{x,y}]
        pose: { x: 0, y: 0, heading: 0 },
        lastTick: null,
        tickTimer: null
    },

    yoloPollTimer: null,

    init() {
        this.cacheElements();
        this.setupSocket();
        this.setupConnectBar();
        this.setupJoysticks();
        this.setupActionBar();
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
            sidePanel: document.getElementById('cr-side'),
            sideToggle: document.getElementById('cr-side-toggle'),
            traceCanvas: document.getElementById('cr-trace-canvas'),
            mobileStatus: document.getElementById('cr-mobile-status')
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
        else if (lft && !rgt) y = s * 0.5;
        else if (rgt && !lft) y = -s * 0.5;

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
            // Quantize to 0.05 to kill micro-jitter -> smoother, non-drunk walking
            const q = (n) => Math.abs(n) < 0.05 ? 0 : Math.round(n * 20) / 20;
            const v = { x: q(raw.x), y: q(raw.y), z: q(raw.z) };

            if (v.x === 0 && v.y === 0 && v.z === 0) {
                // Source went idle between ticks — stop right now.
                this.stopLoop();
                return;
            }
            if (this.socket && this.state.robotConnected) {
                this.socket.emit('move_command', v);
            }
            this.advanceTraceFromVelocity(v, 0.2);
        };
        tick();
        this.movement.interval = setInterval(tick, 200);
    },

    stopLoop() {
        if (this.movement.interval) {
            clearInterval(this.movement.interval);
            this.movement.interval = null;
        }
        // Emit stop_command even if the interval wasn't running — it's cheap
        // and guarantees the robot halts the moment every input releases.
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

        // Draw every 150ms so the trace animates smoothly
        setInterval(() => this.drawTrace(), 150);
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

        // Grid
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
        ctx.lineWidth = 1;
        const step = 20;
        for (let x = 0; x < W; x += step) {
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
        }
        for (let y = 0; y < H; y += step) {
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }

        // Axes
        ctx.strokeStyle = 'rgba(26, 115, 232, 0.35)';
        ctx.beginPath();
        ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H);
        ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2);
        ctx.stroke();

        // Scale meters -> pixels
        const scale = Math.min(W, H) / 6;  // 6 m visible

        ctx.save();
        ctx.translate(W / 2, H / 2);
        ctx.scale(1, -1);  // y up

        // Trace
        if (this.trace.history.length > 1) {
            ctx.strokeStyle = 'rgba(0, 200, 83, 0.85)';
            ctx.lineWidth = 2;
            ctx.beginPath();
            this.trace.history.forEach((pt, i) => {
                const px = pt.x * scale;
                const py = pt.y * scale;
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            });
            ctx.stroke();
        }

        // Robot pose
        const rx = this.trace.pose.x * scale;
        const ry = this.trace.pose.y * scale;
        ctx.fillStyle = '#1a73e8';
        ctx.beginPath();
        ctx.arc(rx, ry, 5, 0, Math.PI * 2);
        ctx.fill();

        // Heading arrow
        ctx.strokeStyle = '#5aa8ff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(rx, ry);
        ctx.lineTo(rx + Math.cos(this.trace.pose.heading) * 15,
                   ry + Math.sin(this.trace.pose.heading) * 15);
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
