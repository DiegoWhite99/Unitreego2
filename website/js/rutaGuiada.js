/* ========================================
   Daiver Ruta Guiada
   El operador lleva al robot a cada marcador QR y, cuando el robot lo ve,
   captura la pose del lidar como waypoint. Al final exporta a Auto-Ruta.
   ======================================== */

const API = window.location.origin;

const RutaGuiada = {
    socket: null,
    state: {
        serverConnected: false,
        robotConnected: false,
        yoloRunning: false,
        originSet: false,
    },
    pose: null,         // {x, y, yaw} ultimo reportado por el lidar
    lastQR: null,       // {text, ts, pose}
    waypoints: [],      // [{x, y, yaw, qr, ts}]
    toastTimer: null,

    init() {
        this.cacheEls();
        this.setupSocket();
        this.setupUI();
        this.refreshStatus();
        this.pollLastQR();
        setInterval(() => this.tickAges(), 500);
    },

    cacheEls() {
        this.el = {
            statusServer: document.getElementById('rg-status-server'),
            statusRobot:  document.getElementById('rg-status-robot'),
            statusQr:     document.getElementById('rg-status-qr'),
            video:        document.getElementById('rg-video'),
            videoPh:      document.getElementById('rg-video-placeholder'),
            toast:        document.getElementById('rg-toast'),
            poseX:        document.getElementById('rg-pose-x'),
            poseY:        document.getElementById('rg-pose-y'),
            poseYaw:      document.getElementById('rg-pose-yaw'),
            lastQrText:   document.getElementById('rg-last-qr-text'),
            lastQrAge:    document.getElementById('rg-last-qr-age'),
            lastQrBox:    document.querySelector('.rg-last-qr'),
            btnSaveWp:    document.getElementById('rg-save-wp'),
            wpList:       document.getElementById('rg-wp-list'),
            wpCount:      document.querySelector('#rg-wp-count span:last-child'),
            btnClear:     document.getElementById('rg-wp-clear'),
            btnExport:    document.getElementById('rg-export'),
            btnYoloStart: document.getElementById('rg-yolo-start'),
            btnYoloStop:  document.getElementById('rg-yolo-stop'),
            btnFollowStart: document.getElementById('rg-follow-start'),
            btnFollowStop:  document.getElementById('rg-follow-stop'),
            followStatus:   document.getElementById('rg-follow-status'),
            followStatusTxt: document.querySelector('#rg-follow-status .rg-follow-text'),
            followX:        document.getElementById('rg-follow-x'),
            followZ:        document.getElementById('rg-follow-z'),
            qrText:       document.getElementById('rg-qr-text'),
            qrGenerate:   document.getElementById('rg-qr-generate'),
            qrImg:        document.getElementById('rg-qr-img'),
            qrDownload:   document.getElementById('rg-qr-download'),
            initModal:    document.getElementById('rg-init-modal'),
            initOk:       document.getElementById('rg-init-ok'),
            initSkip:     document.getElementById('rg-init-skip'),
        };
    },

    setupSocket() {
        if (typeof io !== 'function') return;
        this.socket = io(API, { reconnection: true });

        this.socket.on('connect', () => this.setServer(true));
        this.socket.on('disconnect', () => { this.setServer(false); this.setRobot(false); });

        this.socket.on('state_update', (d) => {
            if (!d) return;
            this.setServer(true);
            this.setRobot(Boolean(d.connected));
        });

        this.socket.on('lidar_points', (d) => {
            if (d && d.pose) {
                this.pose = d.pose;
                this.updatePoseUI();
            }
        });

        this.socket.on('qr_detected', (d) => this.onQRDetected(d));

        this.socket.on('follow_status', (d) => this.onFollowStatus(d));
    },

    setServer(ok) {
        this.state.serverConnected = ok;
        const el = this.el.statusServer;
        if (!el) return;
        el.classList.toggle('connected', ok);
        el.classList.toggle('disconnected', !ok);
        el.querySelector('.txt').textContent = ok ? 'Servidor OK' : 'Offline';
    },

    setRobot(ok) {
        this.state.robotConnected = ok;
        const el = this.el.statusRobot;
        if (!el) return;
        el.classList.toggle('connected', ok);
        el.classList.toggle('disconnected', !ok);
        el.querySelector('.txt').textContent = ok ? 'Robot OK' : 'Sin robot';
        this.refreshSaveWpButton();
    },

    setupUI() {
        this.el.initOk.addEventListener('click', () => this.acceptInitialOrigin());
        this.el.initSkip.addEventListener('click', () => this.closeInitModal());

        this.el.btnSaveWp.addEventListener('click', () => this.saveWaypoint());
        this.el.btnClear.addEventListener('click', () => this.clearWaypoints());
        this.el.btnExport.addEventListener('click', () => this.exportToAutoRoute());

        this.el.btnYoloStart.addEventListener('click', () => this.startYolo());
        this.el.btnYoloStop.addEventListener('click', () => this.stopYolo());

        this.el.btnFollowStart.addEventListener('click', () => this.startFollow());
        this.el.btnFollowStop.addEventListener('click', () => this.stopFollow());

        this.el.qrGenerate.addEventListener('click', () => this.generateQR());
        this.el.qrText.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.generateQR();
        });
        // Genera el QR por defecto automaticamente
        this.generateQR();
    },

    /* -------- Modal inicial -------- */
    acceptInitialOrigin() {
        if (!this.pose) {
            alert('Aun no llega pose del lidar. Asegurate de que el sensor de proximidad este activado en el Control Remoto.');
            return;
        }
        this.state.originSet = true;
        this.addWaypointFromPose({ qr: 'ORIGEN' });
        this.closeInitModal();
    },

    closeInitModal() {
        this.el.initModal.classList.add('hidden');
    },

    /* -------- Pose y camara -------- */
    updatePoseUI() {
        if (!this.pose) return;
        this.el.poseX.textContent = this.pose.x.toFixed(2);
        this.el.poseY.textContent = this.pose.y.toFixed(2);
        this.el.poseYaw.textContent = (this.pose.yaw || 0).toFixed(2);
        this.refreshSaveWpButton();
    },

    async startYolo() {
        const res = await this.api('/api/yolo/start', 'POST', {
            source: this.state.robotConnected ? 'robot' : 'webcam',
            camera_index: 0,
            conf: 0.4,
            model: 'yolov8n.pt',
        });
        if (res && res.status === 'ok') {
            this.el.video.src = `${API}/api/yolo/stream?t=${Date.now()}`;
            this.el.video.style.display = 'block';
            this.el.videoPh.style.display = 'none';
            this.el.btnYoloStart.disabled = true;
            this.el.btnYoloStop.disabled = false;
            this.state.yoloRunning = true;
        } else {
            alert('No se pudo iniciar YOLO: ' + (res && res.message || 'error'));
        }
    },

    async stopYolo() {
        await this.api('/api/yolo/stop', 'POST');
        this.el.video.src = '';
        this.el.video.style.display = 'none';
        this.el.videoPh.style.display = 'flex';
        this.el.btnYoloStart.disabled = false;
        this.el.btnYoloStop.disabled = true;
        this.state.yoloRunning = false;
    },

    async refreshStatus() {
        const s = await this.api('/api/status', 'GET');
        if (s && s.status !== 'error') {
            this.setServer(true);
            this.setRobot(Boolean(s.connected));
        }
        const ys = await this.api('/api/yolo/status', 'GET');
        if (ys && ys.running) {
            this.el.video.src = `${API}/api/yolo/stream?t=${Date.now()}`;
            this.el.video.style.display = 'block';
            this.el.videoPh.style.display = 'none';
            this.el.btnYoloStart.disabled = true;
            this.el.btnYoloStop.disabled = false;
            this.state.yoloRunning = true;
        }
    },

    /* -------- QR detection: socket.io + poll fallback -------- */
    onQRDetected(data) {
        if (!data || !data.text) return;
        this.lastQR = { text: data.text, ts: data.ts || (Date.now() / 1000), pose: data.pose };
        this.el.lastQrText.textContent = data.text;
        this.el.lastQrAge.textContent = 'Recien detectado';
        this.el.lastQrBox.classList.remove('stale');
        this.setQrPill('connected', 'QR visto');
        this.showToast(`QR detectado: ${data.text}`);
        this.refreshSaveWpButton();
    },

    async pollLastQR() {
        // Fallback por si el socket.io se perdio un evento.
        setInterval(async () => {
            if (this.lastQR && Date.now() / 1000 - this.lastQR.ts < 5) return;
            const r = await this.api('/api/qr/last', 'GET');
            if (r && r.text && (!this.lastQR || r.last_ts > this.lastQR.ts)) {
                this.onQRDetected({ text: r.text, ts: r.last_ts, pose: r.pose });
            }
        }, 3000);
    },

    tickAges() {
        if (!this.lastQR) return;
        const age = Date.now() / 1000 - this.lastQR.ts;
        const stale = age > 6;
        this.el.lastQrAge.textContent = age < 1
            ? 'Recien detectado'
            : `hace ${age.toFixed(1)} s`;
        this.el.lastQrBox.classList.toggle('stale', stale);
        if (stale) this.setQrPill('disconnected', 'Sin QR');
    },

    setQrPill(cls, txt) {
        const el = this.el.statusQr;
        if (!el) return;
        el.classList.toggle('connected', cls === 'connected');
        el.classList.toggle('disconnected', cls !== 'connected');
        el.querySelector('.txt').textContent = txt;
    },

    showToast(msg) {
        const el = this.el.toast;
        if (!el) return;
        el.textContent = msg;
        el.classList.add('visible');
        clearTimeout(this.toastTimer);
        this.toastTimer = setTimeout(() => el.classList.remove('visible'), 2800);
    },

    /* -------- Waypoints -------- */
    refreshSaveWpButton() {
        // Habilitar si hay pose del lidar. Preferimos que haya QR reciente
        // pero no lo exigimos: el operador podria querer guardar la pose
        // sin marcador fisico (p. ej. en esquinas).
        const hasPose = !!this.pose;
        this.el.btnSaveWp.disabled = !hasPose;
        const n = this.waypoints.length;
        this.el.btnExport.disabled = n < 2;
        this.el.btnClear.disabled = n === 0;
    },

    saveWaypoint() {
        if (!this.pose) {
            alert('No hay pose del lidar disponible.');
            return;
        }
        // Si hay un QR reciente (<5s), lo usamos como etiqueta.
        let qrLabel = null;
        if (this.lastQR && Date.now() / 1000 - this.lastQR.ts < 5) {
            qrLabel = this.lastQR.text;
        }
        this.addWaypointFromPose({ qr: qrLabel });
    },

    addWaypointFromPose({ qr = null } = {}) {
        if (!this.pose) return;
        const wp = {
            x: +this.pose.x.toFixed(3),
            y: +this.pose.y.toFixed(3),
            yaw: +(this.pose.yaw || 0).toFixed(3),
            qr: qr,
            ts: Date.now(),
        };
        this.waypoints.push(wp);
        this.renderWaypoints();
    },

    removeWaypoint(idx) {
        this.waypoints.splice(idx, 1);
        this.renderWaypoints();
    },

    clearWaypoints() {
        if (!this.waypoints.length) return;
        if (!confirm('Borrar todos los waypoints capturados?')) return;
        this.waypoints = [];
        this.state.originSet = false;
        this.renderWaypoints();
    },

    renderWaypoints() {
        const list = this.el.wpList;
        list.innerHTML = '';
        if (this.waypoints.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'rg-wp-empty';
            empty.textContent = 'Sin waypoints todavia.';
            list.appendChild(empty);
        } else {
            this.waypoints.forEach((wp, i) => {
                const item = document.createElement('div');
                item.className = 'rg-wp-item' + (i === 0 ? ' origin' : '');
                const qrTag = wp.qr ? `<span class="label-qr">${wp.qr}</span>` : '';
                item.innerHTML = `
                    <span class="num">${i + 1}</span>
                    <span class="coords">x=${wp.x.toFixed(2)}  y=${wp.y.toFixed(2)}${qrTag}</span>
                    <button class="del-btn" title="Quitar" data-idx="${i}">&times;</button>
                `;
                item.querySelector('.del-btn').addEventListener('click', (e) => {
                    const idx = parseInt(e.currentTarget.dataset.idx, 10);
                    this.removeWaypoint(idx);
                });
                list.appendChild(item);
            });
        }
        this.el.wpCount.textContent = String(this.waypoints.length);
        this.refreshSaveWpButton();
    },

    /* -------- Exportar a Auto-Ruta -------- */
    exportToAutoRoute() {
        if (this.waypoints.length < 2) {
            alert('Necesitas al menos 2 waypoints para exportar.');
            return;
        }
        const points = this.waypoints.map(w => ({ x: w.x, y: w.y }));
        const length = this.routeLength(points);
        // Mantenemos el heat del liveScan si lo hay; si no, va vacio.
        let heat = [];
        let heatCellSize = 0.08;
        let heatCellSizeZ = 0.12;
        try {
            const live = JSON.parse(localStorage.getItem('daiver:liveScan') || '{}');
            if (Array.isArray(live.heat)) {
                heat = live.heat;
                heatCellSize = live.heatCellSize || heatCellSize;
                heatCellSizeZ = live.heatCellSizeZ || heatCellSizeZ;
            }
        } catch (_) { /* ignore */ }

        localStorage.setItem('daiver:lastRoute', JSON.stringify({
            savedAt: Date.now(),
            points: points,
            totalMeters: length,
            heatCellSize: heatCellSize,
            heatCellSizeZ: heatCellSizeZ,
            heat: heat,
            source: 'rutaGuiada',
            qr_labels: this.waypoints.map(w => w.qr || null),
        }));
        window.location.href = '/autoroute';
    },

    routeLength(pts) {
        let t = 0;
        for (let i = 1; i < pts.length; i++) {
            t += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
        }
        return t;
    },

    /* -------- Generador de QR (backend con qrcode python) -------- */
    generateQR() {
        const text = (this.el.qrText.value || 'DAIVER_WP').trim();
        const url = `${API}/api/qr/image?text=${encodeURIComponent(text)}&t=${Date.now()}`;
        this.el.qrImg.src = url;
        this.el.qrImg.onload = () => {
            this.el.qrDownload.href = url;
            this.el.qrDownload.download = `daiver_qr_${text.replace(/[^A-Za-z0-9_-]/g, '_')}.png`;
            this.el.qrDownload.style.display = 'inline-flex';
        };
        this.el.qrImg.onerror = () => {
            this.el.qrImg.removeAttribute('src');
            alert('No se pudo generar el QR. Verifica que el servidor tenga instalado "qrcode": pip install qrcode[pil]');
        };
    },

    /* -------- Follow-me: robot persigue el QR -------- */
    async startFollow() {
        if (!this.state.robotConnected) {
            alert('Robot no conectado. Abre el Control Remoto y conectalo.');
            return;
        }
        if (!this.state.yoloRunning) {
            alert('Primero iniciá la camara (YOLO) para que el robot pueda ver el QR.');
            return;
        }
        const r = await this.api('/api/follow/start', 'POST');
        if (r && r.status === 'ok') {
            this.setFollowUI(true, 'Esperando QR…', 'waiting');
        } else {
            alert('No se pudo iniciar: ' + (r && r.message || 'error'));
        }
    },

    async stopFollow() {
        await this.api('/api/follow/stop', 'POST');
        this.setFollowUI(false, 'Detenido', 'idle');
    },

    onFollowStatus(d) {
        if (!d) return;
        if (!d.running) {
            this.setFollowUI(false, d.reason || 'Detenido', 'idle');
            if (this.el.followX) this.el.followX.textContent = '0.00';
            if (this.el.followZ) this.el.followZ.textContent = '0.00';
            return;
        }
        // Running: calidad segun si hay QR visible
        const moving = (d.x && d.x !== 0) || (d.z && d.z !== 0);
        this.setFollowUI(true, d.reason || 'Siguiendo', moving ? 'running' : 'waiting');
        if (this.el.followX) this.el.followX.textContent = (d.x || 0).toFixed(2);
        if (this.el.followZ) this.el.followZ.textContent = (d.z || 0).toFixed(2);
    },

    setFollowUI(running, text, cls) {
        this.el.btnFollowStart.disabled = running;
        this.el.btnFollowStop.disabled = !running;
        if (this.el.followStatus) {
            this.el.followStatus.classList.remove('idle', 'running', 'waiting');
            this.el.followStatus.classList.add(cls || 'idle');
        }
        if (this.el.followStatusTxt) {
            this.el.followStatusTxt.textContent = text;
        }
    },

    /* -------- API helper -------- */
    async api(endpoint, method = 'POST', body = null) {
        try {
            const opts = { method, headers: { 'Content-Type': 'application/json' }, cache: 'no-store' };
            if (body) opts.body = JSON.stringify(body);
            const r = await fetch(API + endpoint, opts);
            const txt = await r.text();
            if (!txt) return r.ok ? {} : { status: 'error' };
            try { return JSON.parse(txt); } catch { return { status: 'error' }; }
        } catch (err) {
            return { status: 'error', message: err.message };
        }
    },
};

document.addEventListener('DOMContentLoaded', () => RutaGuiada.init());
