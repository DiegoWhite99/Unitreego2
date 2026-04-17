/* ========================================
   Daiver User End - Landing Controller
   ======================================== */

const API_BASE = window.location.origin;

const UserEnd = {
    socket: null,
    pollTimer: null,
    state: {
        serverConnected: false,
        robotConnected: false,
        yoloRunning: false
    },
    yoloPollTimer: null,

    init() {
        this.setupNavigation();
        this.setupSocket();
        this.setupControls();
        this.setupYoloControls();
        this.loadInitialData();
        this.startStatusPolling();
        this.refreshYoloStatus();
    },

    setupNavigation() {
        const links = Array.from(document.querySelectorAll('.nav-link[href^="#"]'));
        if (links.length === 0) return;

        const sections = links
            .map((link) => document.querySelector(link.getAttribute('href')))
            .filter(Boolean);

        const setActive = (id) => {
            links.forEach((link) => {
                link.classList.toggle('active', link.getAttribute('href') === `#${id}`);
            });
        };

        links.forEach((link) => {
            link.addEventListener('click', () => {
                const target = link.getAttribute('href').replace('#', '');
                setActive(target);
            });
        });

        const onScroll = () => {
            const marker = window.scrollY + 140;
            let current = sections[0]?.id;

            sections.forEach((section) => {
                if (section.offsetTop <= marker) {
                    current = section.id;
                }
            });

            if (current) setActive(current);
        };

        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    },

    setupSocket() {
        if (typeof io !== 'function') {
            this.addLog('warning', 'Socket.IO no disponible. Se usara monitoreo por API.');
            return;
        }

        this.socket = io(API_BASE, {
            reconnection: true,
            reconnectionDelay: 1500,
            timeout: 5000
        });

        this.socket.on('connect', () => {
            this.setServerState(true);
            this.addLog('success', 'Socket conectado al servidor Flask');
        });

        this.socket.on('disconnect', () => {
            this.setServerState(false);
            this.setRobotState(false);
            this.addLog('warning', 'Socket desconectado. Reintentando...');
        });

        this.socket.on('connect_error', () => {
            this.setServerState(false);
        });

        this.socket.on('state_update', (data) => {
            this.setServerState(true);
            this.setRobotState(Boolean(data.connected));
        });

        this.socket.on('log', (data) => {
            if (!data || !data.message) return;
            this.addLog(data.type || 'info', data.message);
        });
    },

    setupControls() {
        document.getElementById('btn-connect')?.addEventListener('click', () => this.connectRobot());
        document.getElementById('btn-disconnect')?.addEventListener('click', () => this.disconnectRobot());
        document.getElementById('btn-emergency')?.addEventListener('click', () => this.emergencyStop());
        document.getElementById('btn-clear-logs')?.addEventListener('click', () => this.clearLogs());

        document.querySelectorAll('[data-action]').forEach((button) => {
            button.addEventListener('click', () => this.executeAction(button.dataset.action, button));
        });
    },

    async loadInitialData() {
        await this.loadRobotConfig();
        await this.refreshStatus();
    },

    async loadRobotConfig() {
        try {
            const data = await this.apiCall('/api/config', 'GET');
            if (data && data.robot_ip) {
                const ipInput = document.getElementById('ip-input');
                if (ipInput) ipInput.value = data.robot_ip;
            }
        } catch {
            this.addLog('warning', 'No se pudo leer la configuracion inicial');
        }
    },

    startStatusPolling() {
        this.pollTimer = window.setInterval(() => {
            this.refreshStatus();
        }, 4000);

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                this.refreshStatus();
            }
        });
    },

    async refreshStatus() {
        try {
            const data = await this.apiCall('/api/status', 'GET');
            if (!data || data.status === 'error') {
                throw new Error(data?.message || 'Respuesta vacia');
            }
            this.setServerState(true);
            this.setRobotState(Boolean(data.connected));
        } catch {
            this.setServerState(false);
            this.setRobotState(false);
        }
    },

    async connectRobot() {
        const ipInput = document.getElementById('ip-input');
        const ip = ipInput ? ipInput.value.trim() : '';

        if (!ip) {
            this.addLog('error', 'Ingresa una IP valida antes de conectar');
            return;
        }

        this.setRobotState(false, true);
        this.addLog('info', `Conectando a ${ip}...`);

        try {
            await this.apiCall('/api/config/ip', 'POST', { ip });
        } catch {
            this.addLog('warning', 'No se pudo guardar la IP en config.py');
        }

        const response = await this.apiCall('/api/connect', 'POST', { ip });
        if (response && response.status === 'ok') {
            this.addLog('success', response.message || `Conectado a ${ip}`);
            await this.refreshStatus();
            return;
        }

        const message = response?.message || 'No se pudo establecer conexion con el robot';
        this.addLog('error', message);
        this.setRobotState(false);
    },

    async disconnectRobot() {
        this.addLog('info', 'Solicitando desconexion...');
        const response = await this.apiCall('/api/disconnect', 'POST');
        if (response && response.status === 'ok') {
            this.addLog('success', response.message || 'Robot desconectado');
        } else {
            this.addLog('warning', response?.message || 'No se pudo desconectar');
        }
        await this.refreshStatus();
    },

    async emergencyStop() {
        this.addLog('warning', 'Parada de emergencia enviada');
        const response = await this.apiCall('/api/emergency', 'POST');
        if (response && response.status === 'ok') {
            this.addLog('success', response.message || 'Emergencia activada');
        } else {
            this.addLog('error', response?.message || 'No se pudo activar emergencia');
        }
        await this.refreshStatus();
    },

    async executeAction(action, button) {
        if (!action) return;
        if (!this.state.robotConnected) {
            this.addLog('warning', `Accion '${action}' bloqueada: robot no conectado`);
            return;
        }

        button.classList.add('executing');
        setTimeout(() => button.classList.remove('executing'), 450);

        this.addLog('info', `Ejecutando accion: ${this.formatActionName(action)}`);
        const response = await this.apiCall('/api/action', 'POST', { action });

        if (response && response.status === 'ok') {
            this.addLog('success', `Accion completada: ${this.formatActionName(action)}`);
        } else {
            this.addLog('error', response?.message || `Fallo al ejecutar ${action}`);
        }
    },

    async apiCall(endpoint, method = 'POST', body = null) {
        try {
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-store'
            };

            if (body) {
                options.body = JSON.stringify(body);
            }

            const response = await fetch(`${API_BASE}${endpoint}`, options);
            const text = await response.text();
            let data = null;

            if (text) {
                try {
                    data = JSON.parse(text);
                } catch {
                    data = { status: 'error', message: `Respuesta invalida en ${endpoint}` };
                }
            }

            if (!response.ok) {
                return data || { status: 'error', message: `HTTP ${response.status}` };
            }

            return data;
        } catch (error) {
            this.addLog('error', `Error de red en ${endpoint}: ${error.message}`);
            return { status: 'error', message: error.message };
        }
    },

    setServerState(isConnected) {
        this.state.serverConnected = isConnected;
        const status = document.getElementById('server-status');
        if (!status) return;

        status.className = 'status-indicator';
        if (isConnected) {
            status.classList.add('connected');
            status.textContent = 'Servidor Online';
        } else {
            status.classList.add('disconnected');
            status.textContent = 'Servidor Offline';
        }

        this.toggleControls();
    },

    setRobotState(isConnected, isConnecting = false) {
        this.state.robotConnected = isConnected;
        const status = document.getElementById('connection-status');
        if (!status) return;

        status.className = 'status-indicator';
        if (isConnecting) {
            status.classList.add('connecting');
            status.textContent = 'Robot Conectando...';
        } else if (isConnected) {
            status.classList.add('connected');
            status.textContent = 'Robot Conectado';
        } else {
            status.classList.add('disconnected');
            status.textContent = 'Robot Desconectado';
        }

        this.toggleControls();
    },

    toggleControls() {
        const connectButton = document.getElementById('btn-connect');
        const disconnectButton = document.getElementById('btn-disconnect');
        const canReachServer = this.state.serverConnected;
        const robotConnected = this.state.robotConnected;

        if (connectButton) connectButton.disabled = !canReachServer || robotConnected;
        if (disconnectButton) disconnectButton.disabled = !canReachServer || !robotConnected;

        document.querySelectorAll('[data-action], #btn-emergency').forEach((button) => {
            button.disabled = !canReachServer || !robotConnected;
        });
    },

    clearLogs() {
        const container = document.getElementById('log-container');
        if (!container) return;
        container.innerHTML = '';
        this.addLog('info', 'Logs limpiados');
    },

    addLog(type, message) {
        const container = document.getElementById('log-container');
        if (!container) return;

        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        const stamp = new Date().toLocaleTimeString('es-CO');
        entry.textContent = `[${stamp}] [${type.toUpperCase()}] ${message}`;

        container.appendChild(entry);
        container.scrollTop = container.scrollHeight;

        while (container.children.length > 180) {
            container.removeChild(container.firstChild);
        }
    },

    setupYoloControls() {
        document.getElementById('btn-yolo-start')?.addEventListener('click', () => this.startYolo());
        document.getElementById('btn-yolo-stop')?.addEventListener('click', () => this.stopYolo());
    },

    async startYolo() {
        const sourceEl = document.getElementById('yolo-source');
        const cameraEl = document.getElementById('yolo-camera');
        const confEl = document.getElementById('yolo-conf');
        const modelEl = document.getElementById('yolo-model');

        const payload = {
            source: sourceEl ? sourceEl.value : 'robot',
            camera_index: cameraEl ? parseInt(cameraEl.value, 10) || 0 : 0,
            conf: confEl ? parseFloat(confEl.value) || 0.35 : 0.35,
            model: modelEl ? modelEl.value : 'yolov8n.pt'
        };

        if (payload.source === 'robot' && !this.state.robotConnected) {
            this.addLog('error', 'Conecta primero el robot para usar su camara');
            return;
        }

        const srcLabel = payload.source === 'robot' ? 'camara Go2' : `webcam ${payload.camera_index}`;
        this.addLog('info', `Iniciando YOLO (${srcLabel}, modelo ${payload.model})...`);
        const response = await this.apiCall('/api/yolo/start', 'POST', payload);

        if (response && response.status === 'ok') {
            this.addLog('success', response.message || 'YOLO iniciado');
            this.setYoloRunning(true);
            this.attachYoloStream();
            this.startYoloPolling();
        } else {
            this.addLog('error', response?.message || 'No se pudo iniciar YOLO');
            this.setYoloRunning(false);
        }
    },

    async stopYolo() {
        this.addLog('info', 'Deteniendo YOLO...');
        this.stopYoloPolling();
        this.detachYoloStream();

        const response = await this.apiCall('/api/yolo/stop', 'POST');
        if (response && response.status === 'ok') {
            this.addLog('success', response.message || 'YOLO detenido');
        } else {
            this.addLog('warning', response?.message || 'No se pudo detener YOLO');
        }
        this.setYoloRunning(false);
        this.renderWaypoints([]);
        this.updateFps(null);
    },

    async refreshYoloStatus() {
        const data = await this.apiCall('/api/yolo/status', 'GET');
        if (!data) return;

        this.setYoloRunning(Boolean(data.running));
        this.updateFps(data.running ? data.fps : null);

        if (data.running) {
            this.attachYoloStream();
            this.startYoloPolling();
        }
    },

    attachYoloStream() {
        const img = document.getElementById('yolo-video');
        const placeholder = document.getElementById('yolo-placeholder');
        if (!img) return;
        img.src = `${API_BASE}/api/yolo/stream?t=${Date.now()}`;
        img.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
    },

    detachYoloStream() {
        const img = document.getElementById('yolo-video');
        const placeholder = document.getElementById('yolo-placeholder');
        if (img) {
            img.src = '';
            img.style.display = 'none';
        }
        if (placeholder) placeholder.style.display = 'flex';
    },

    startYoloPolling() {
        this.stopYoloPolling();
        this.yoloPollTimer = window.setInterval(async () => {
            const [det, status] = await Promise.all([
                this.apiCall('/api/yolo/detections', 'GET'),
                this.apiCall('/api/yolo/status', 'GET')
            ]);

            if (status) {
                this.updateFps(status.running ? status.fps : null);
                if (!status.running) {
                    this.setYoloRunning(false);
                    this.detachYoloStream();
                    this.renderWaypoints([]);
                    this.stopYoloPolling();
                    return;
                }
            }

            if (det && Array.isArray(det.detections)) {
                this.renderWaypoints(det.detections);
            }
        }, 800);
    },

    stopYoloPolling() {
        if (this.yoloPollTimer) {
            window.clearInterval(this.yoloPollTimer);
            this.yoloPollTimer = null;
        }
    },

    setYoloRunning(running) {
        this.state.yoloRunning = running;
        const startBtn = document.getElementById('btn-yolo-start');
        const stopBtn = document.getElementById('btn-yolo-stop');
        if (startBtn) startBtn.disabled = running;
        if (stopBtn) stopBtn.disabled = !running;
    },

    updateFps(fps) {
        const el = document.getElementById('yolo-fps');
        if (!el) return;
        el.textContent = fps == null ? 'FPS: --' : `FPS: ${fps}`;
    },

    renderWaypoints(detections) {
        const container = document.getElementById('yolo-waypoints');
        const count = document.getElementById('yolo-count');
        if (!container) return;

        if (count) count.textContent = `${detections.length} objeto${detections.length === 1 ? '' : 's'}`;

        if (detections.length === 0) {
            container.innerHTML = '<p class="yolo-empty">Sin detecciones en este frame.</p>';
            return;
        }

        const ordered = [...detections].sort((a, b) => b.confidence - a.confidence);

        container.innerHTML = ordered.map((d, idx) => {
            const pct = Math.round(d.confidence * 100);
            const dir = this.translateDirection(d.direction);
            const dist = this.translateDistance(d.distance_hint);
            const [nx, ny] = d.norm_center || [0, 0];

            return `
                <div class="waypoint-item waypoint-dir-${d.direction}">
                    <div class="waypoint-head">
                        <span class="waypoint-index">#${idx + 1}</span>
                        <span class="waypoint-label">${this.escapeHtml(d.label)}</span>
                        <span class="waypoint-conf">${pct}%</span>
                    </div>
                    <div class="waypoint-meta">
                        <span class="waypoint-tag tag-${d.direction}">${dir}</span>
                        <span class="waypoint-tag tag-${d.distance_hint}">${dist}</span>
                        <span class="waypoint-coord">x:${nx.toFixed(2)} y:${ny.toFixed(2)}</span>
                    </div>
                </div>
            `;
        }).join('');
    },

    translateDirection(d) {
        return ({ left: 'Izquierda', right: 'Derecha', center: 'Centro' })[d] || d;
    },

    translateDistance(d) {
        return ({ near: 'Cerca', mid: 'Media', far: 'Lejos' })[d] || d;
    },

    escapeHtml(str) {
        return String(str).replace(/[&<>"']/g, (c) => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    formatActionName(action) {
        const names = {
            stand: 'De Pie',
            lie: 'Acostarse',
            sit: 'Sentarse',
            rise: 'Levantarse',
            recovery: 'Recuperarse',
            hello: 'Saludar',
            stretch: 'Estirarse',
            heart: 'Corazon',
            wiggle: 'Meneo',
            scrape: 'Raspar',
            dance1: 'Baile 1',
            dance2: 'Baile 2',
            frontjump: 'Salto Frontal',
            frontpounce: 'Salto Agresivo'
        };
        return names[action] || action;
    }
};

document.addEventListener('DOMContentLoaded', () => {
    UserEnd.init();
});
