/* ========================================
   Daiver Auto-Ruta
   Carga la ruta guardada en localStorage, la dibuja como mapa 2.5D sobre
   el heatmap del lidar, permite editar waypoints manualmente y pedirle al
   backend que siga la ruta N veces.
   ======================================== */

const API = window.location.origin;

/* Proyeccion 2.5D: el plano XY del mundo se "inclina" hacia adelante
   (foreshortening en Y) y cada voxel 3D se dibuja como un cubito en su
   altura real. La misma transformacion XY se usa para clicks inversos. */
const TILT_KY = 0.62;
const VOXEL_Z_PX_PER_M = 70;      // 1 m de Z real = 70 px en pantalla
const VOXEL_ALPHA_BASE = 0.55;    // opacidad base de voxels

const AutoRoute = {
    socket: null,
    state: {
        serverConnected: false,
        robotConnected: false,
        yoloRunning: false,
        running: false,
        cycleNow: 0,
        cycleTotal: 0,
        wpNow: 0,
        wpTotal: 0,
    },
    route: null,          // { points: [{x,y}], totalMeters, heat, heatCellSize }
    pose: null,           // { x, y, yaw }
    canvas: null,
    ctx: null,
    dpr: 1,

    // Estado de edicion
    edit: {
        on: false,
        history: [],      // snapshots de points para undo
        draggingIdx: -1,
        dragStart: null,
        dirty: false,
    },

    // Transformacion world <-> screen (se recalcula en cada render)
    view: {
        originX: 0,
        originY: 0,
        scale: 40,        // px por metro
        minWorldX: -4, maxWorldX: 4,
        minWorldY: -4, maxWorldY: 4,
    },

    init() {
        this.cacheEls();
        this.loadRoute();
        this.setupSocket();
        this.setupControls();
        this.setupEditor();
        this.initCanvas();
        this.render();
        this.refreshStatus();
        setInterval(() => this.drawRoute(), 200);
    },

    cacheEls() {
        this.el = {
            statusServer: document.getElementById('ar-status-server'),
            statusRobot:  document.getElementById('ar-status-robot'),
            runStatus:    document.getElementById('ar-run-status'),
            video:        document.getElementById('ar-video'),
            videoPh:      document.getElementById('ar-video-placeholder'),
            routePoints:  document.getElementById('ar-route-points'),
            routeLength:  document.getElementById('ar-route-length'),
            cyclesInput:  document.getElementById('ar-cycles-input'),
            cycMinus:     document.getElementById('ar-cyc-minus'),
            cycPlus:      document.getElementById('ar-cyc-plus'),
            cycleNow:     document.getElementById('ar-cycle-now'),
            cycleTotal:   document.getElementById('ar-cycle-total'),
            wpNow:        document.getElementById('ar-wp-now'),
            wpTotal:      document.getElementById('ar-wp-total'),
            btnStart:     document.getElementById('ar-start'),
            btnStop:      document.getElementById('ar-stop'),
            btnYolo:      document.getElementById('ar-yolo-toggle'),
            btnEdit:      document.getElementById('ar-edit-toggle'),
            btnBlank:     document.getElementById('ar-edit-blank'),
            btnUndo:      document.getElementById('ar-edit-undo'),
            btnClear:     document.getElementById('ar-edit-clear'),
            btnSave:      document.getElementById('ar-edit-save'),
            btnSaveScan:  document.getElementById('ar-save-scan'),
            chkTranslate: document.getElementById('ar-translate-to-pose'),
            chkSmooth:    document.getElementById('ar-smooth-mode'),
            editModeLbl:  document.getElementById('ar-edit-mode-label'),
            coordTip:     document.getElementById('ar-coord-tip'),
            robotBadge:   document.getElementById('ar-robot-badge'),
            robotX:       document.getElementById('ar-robot-x'),
            robotY:       document.getElementById('ar-robot-y'),
            robotYaw:     document.getElementById('ar-robot-yaw'),
            inX:          document.getElementById('ar-coord-x'),
            inY:          document.getElementById('ar-coord-y'),
            btnCoordAdd:  document.getElementById('ar-coord-add'),
            wpRegistryList:  document.getElementById('ar-wp-registry-list'),
            wpRegistryCount: document.getElementById('ar-wp-registry-count'),
        };
    },

    loadRoute() {
        try {
            const raw = localStorage.getItem('daiver:lastRoute');
            if (!raw) {
                this.route = { points: [], totalMeters: 0, heat: [], heatCellSize: 0.15 };
                return;
            }
            const data = JSON.parse(raw);
            if (!data || !Array.isArray(data.points)) return;
            this.route = {
                points: data.points.slice(),
                totalMeters: data.totalMeters || 0,
                savedAt: data.savedAt,
                heat: Array.isArray(data.heat) ? data.heat : [],
                heatCellSize: data.heatCellSize || 0.08,
                heatCellSizeZ: data.heatCellSizeZ || 0.12,
            };
            // Si el heat venia truncado en localStorage (quota), intentamos
            // reconstruirlo desde el auto-save 'liveScan'.
            if (data.heatTruncated) {
                try {
                    const live = JSON.parse(localStorage.getItem('daiver:liveScan') || '{}');
                    if (Array.isArray(live.heat) && live.heat.length) {
                        this.route.heat = live.heat;
                        this.route.heatCellSize = live.heatCellSize || this.route.heatCellSize;
                        this.route.heatCellSizeZ = live.heatCellSizeZ || this.route.heatCellSizeZ;
                    }
                } catch (_) { /* ignore */ }
            }
        } catch (err) {
            console.warn('No se pudo cargar ruta', err);
            this.route = { points: [], totalMeters: 0, heat: [], heatCellSize: 0.08, heatCellSizeZ: 0.12 };
        }
    },

    render() {
        const pts = this.route ? this.route.points : [];
        const n = pts.length;
        if (n > 0) {
            this.el.routePoints.textContent = `${n} waypoint${n === 1 ? '' : 's'}`;
            const m = this.route.totalMeters || this.computeRouteLength(pts);
            this.el.routeLength.textContent = m >= 1
                ? `${m.toFixed(1)} m`
                : `${Math.round(m * 100)} cm`;
            this.el.wpTotal.textContent = n;
        } else {
            this.el.routePoints.textContent = 'Sin ruta (edita el mapa)';
            this.el.routeLength.textContent = '';
            this.el.wpTotal.textContent = '0';
        }
        this.refreshEditorButtons();
        this.renderWaypointRegistry();
    },

    renderWaypointRegistry() {
        const list = this.el.wpRegistryList;
        const countEl = this.el.wpRegistryCount;
        if (!list) return;
        const pts = (this.route && this.route.points) || [];
        if (countEl) countEl.textContent = `(${pts.length})`;
        list.innerHTML = '';
        if (pts.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'ar-wp-registry-empty';
            empty.textContent = 'Sin waypoints registrados.';
            list.appendChild(empty);
            return;
        }
        pts.forEach((p, i) => {
            const item = document.createElement('div');
            const isActive = (i + 1 === this.state.wpNow) && this.state.running;
            item.className = 'ar-wp-registry-item'
                + (i === 0 ? ' origin' : '')
                + (isActive ? ' active' : '');
            const ts = p.ts ? new Date(p.ts) : null;
            const tsStr = ts
                ? ts.toLocaleTimeString('es-CO', { hour12: false })
                : '';
            item.innerHTML = `
                <span class="num">${i + 1}</span>
                <span class="coords">x=${p.x.toFixed(2)}  y=${p.y.toFixed(2)}</span>
                <span class="ts">${tsStr}</span>
            `;
            // Click: centra la vista alrededor de ese waypoint (util para ubicarlo).
            item.addEventListener('click', () => {
                this.focusWaypoint(i);
            });
            list.appendChild(item);
        });
    },

    focusWaypoint(idx) {
        const pts = this.route && this.route.points;
        if (!pts || idx < 0 || idx >= pts.length) return;
        const wp = pts[idx];
        // Ajusta view para que ese waypoint quede centrado en pantalla.
        // Simple: forzamos re-fit expandiendo alrededor del punto.
        this.drawRoute();
        // Flash visual: destacar el item brevemente dibujando un anillo.
        this._focusFlash = { idx, until: Date.now() + 1500 };
    },

    computeRouteLength(pts) {
        let t = 0;
        for (let i = 1; i < pts.length; i++) {
            t += Math.hypot(pts[i].x - pts[i-1].x, pts[i].y - pts[i-1].y);
        }
        return t;
    },

    /* -------------------- Socket -------------------- */
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
                this.updateRobotBadge();
            }
        });

        this.socket.on('autoroute_progress', (p) => {
            if (!p) return;
            this.state.cycleNow = p.cycle || 0;
            this.state.cycleTotal = p.cycle_total || 0;
            this.state.wpNow = p.waypoint || 0;
            this.state.wpTotal = p.waypoint_total || this.state.wpTotal;
            this.state.running = Boolean(p.running);
            this.state.returning = Boolean(p.returning);
            this.updateProgress();
        });

        this.socket.on('autoroute_done', () => {
            this.state.running = false;
            this.updateProgress();
            this.setRun(false);
        });
    },

    setServer(connected) {
        this.state.serverConnected = connected;
        const el = this.el.statusServer;
        if (!el) return;
        el.classList.toggle('connected', connected);
        el.classList.toggle('disconnected', !connected);
        el.querySelector('.txt').textContent = connected ? 'Servidor OK' : 'Offline';
    },

    setRobot(connected) {
        this.state.robotConnected = connected;
        const el = this.el.statusRobot;
        if (!el) return;
        el.classList.toggle('connected', connected);
        el.classList.toggle('disconnected', !connected);
        el.querySelector('.txt').textContent = connected ? 'Robot OK' : 'Sin robot';
    },

    setRun(running) {
        this.state.running = running;
        const el = this.el.runStatus;
        if (!el) return;
        el.classList.toggle('connected', running);
        el.classList.toggle('disconnected', !running);
        el.querySelector('.txt').textContent = running
            ? (this.state.returning ? 'Volviendo al origen...' : 'Siguiendo ruta')
            : 'Detenido';
        this.el.btnStart.disabled = running || !this.hasRoute();
        this.el.btnStop.disabled = !running;
    },

    updateProgress() {
        this.el.cycleNow.textContent = this.state.cycleNow;
        this.el.cycleTotal.textContent = this.state.cycleTotal;
        this.el.wpNow.textContent = this.state.wpNow;
        this.el.wpTotal.textContent = this.state.wpTotal;
        // Refresca el texto del pill segun si esta volviendo al origen.
        if (this.state.running) this.setRun(true);
    },

    hasRoute() {
        return this.route && this.route.points && this.route.points.length >= 2;
    },

    /* -------------------- Controls -------------------- */
    setupControls() {
        this.el.cycMinus.addEventListener('click', () => this.bumpCycles(-1));
        this.el.cycPlus.addEventListener('click', () => this.bumpCycles(+1));
        this.el.btnStart.addEventListener('click', () => this.startRoute());
        this.el.btnStop.addEventListener('click', () => this.stopRoute());
        this.el.btnYolo.addEventListener('click', () => this.toggleYolo());

        if (!this.hasRoute()) this.el.btnStart.disabled = true;
    },

    bumpCycles(delta) {
        const input = this.el.cyclesInput;
        const v = Math.max(1, Math.min(99, (parseInt(input.value, 10) || 1) + delta));
        input.value = v;
    },

    async startRoute() {
        if (!this.hasRoute()) {
            alert('No hay ruta. Edita el mapa para poner al menos dos waypoints.');
            return;
        }
        if (!this.state.robotConnected) {
            alert('El robot no esta conectado. Abre el Control Remoto primero y conectalo.');
            return;
        }
        const cycles = Math.max(1, parseInt(this.el.cyclesInput.value, 10) || 1);
        const translate = !!(this.el.chkTranslate && this.el.chkTranslate.checked);
        const smooth = !!(this.el.chkSmooth && this.el.chkSmooth.checked);
        const res = await this.api('/api/autoroute/start', 'POST', {
            points: this.route.points,
            cycles,
            translate_to_pose: translate,
            smooth_mode: smooth,
        });
        if (res && res.status === 'ok') {
            this.state.cycleTotal = cycles;
            this.setRun(true);
        } else {
            alert('No se pudo iniciar: ' + (res && res.message || 'error'));
        }
    },

    async stopRoute() {
        await this.api('/api/autoroute/stop', 'POST');
        this.setRun(false);
    },

    async toggleYolo() {
        const status = await this.api('/api/yolo/status', 'GET');
        if (status && status.running) {
            await this.api('/api/yolo/stop', 'POST');
            this.el.video.src = '';
            this.el.video.style.display = 'none';
            this.el.videoPh.style.display = 'flex';
        } else {
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
            }
        }
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
        }
    },

    /* -------------------- Editor de waypoints -------------------- */
    setupEditor() {
        this.el.btnEdit.addEventListener('click', () => this.toggleEdit());
        this.el.btnUndo.addEventListener('click', () => this.undo());
        this.el.btnClear.addEventListener('click', () => this.clearPoints());
        this.el.btnSave.addEventListener('click', () => this.savePoints());
        this.el.btnBlank?.addEventListener('click', () => this.startBlank());
        this.el.btnSaveScan?.addEventListener('click', () => this.downloadScan());

        // Input numerico: agregar waypoint por coordenadas exactas
        this.el.btnCoordAdd?.addEventListener('click', () => this.addWaypointFromInputs());
        const onEnter = (e) => { if (e.key === 'Enter') this.addWaypointFromInputs(); };
        this.el.inX?.addEventListener('keydown', onEnter);
        this.el.inY?.addEventListener('keydown', onEnter);
    },

    addWaypointFromInputs() {
        const x = parseFloat(this.el.inX.value);
        const y = parseFloat(this.el.inY.value);
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
            alert('Ingresa coordenadas X e Y numericas (en metros).');
            return;
        }
        this.addWaypointAt(x, y, { source: 'numeric' });
        this.el.inX.value = '';
        this.el.inY.value = '';
    },

    startBlank() {
        const n = this.route ? this.route.points.length : 0;
        const msg = n > 0
            ? `Descartar los ${n} waypoints actuales y empezar una ruta vacia?`
            : 'Entrar en modo edicion con ruta vacia?';
        if (!confirm(msg)) return;
        if (n > 0) this.pushHistory();
        this.route.points = [];
        this.edit.dirty = n > 0;
        // Activar modo edicion si no lo esta
        if (!this.edit.on) this.toggleEdit();
        this.render();
    },

    downloadScan() {
        const heat = this.route && this.route.heat ? this.route.heat : [];
        const payload = {
            savedAt: new Date().toISOString(),
            heatCellSize: this.route?.heatCellSize || 0.15,
            heat: heat,
            points: this.route?.points || [],
            note: 'Daiver CUN - datos escaneados del lidar Go2',
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        a.href = url;
        a.download = `daiver_scan_${ts}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },

    toggleEdit() {
        this.edit.on = !this.edit.on;
        this.el.btnEdit.setAttribute('aria-pressed', this.edit.on ? 'true' : 'false');
        this.el.editModeLbl.textContent = this.edit.on ? 'ON' : 'OFF';
        if (this.canvas) this.canvas.classList.toggle('ar-editing', this.edit.on);
        this.refreshEditorButtons();
    },

    refreshEditorButtons() {
        const n = this.route ? this.route.points.length : 0;
        this.el.btnUndo.disabled = this.edit.history.length === 0;
        this.el.btnClear.disabled = n === 0;
        this.el.btnSave.disabled = !this.edit.dirty;
        this.el.btnStart.disabled = this.state.running || n < 2;
    },

    pushHistory() {
        if (!this.route) return;
        this.edit.history.push(this.route.points.map(p => ({ x: p.x, y: p.y })));
        if (this.edit.history.length > 40) this.edit.history.shift();
        this.edit.dirty = true;
    },

    undo() {
        if (!this.edit.history.length) return;
        this.route.points = this.edit.history.pop();
        this.edit.dirty = this.edit.history.length > 0;
        this.render();
    },

    clearPoints() {
        if (!this.route || this.route.points.length === 0) return;
        if (!confirm('Borrar todos los waypoints?')) return;
        this.pushHistory();
        this.route.points = [];
        this.render();
    },

    savePoints() {
        if (!this.route) return;
        const payload = {
            savedAt: Date.now(),
            points: this.route.points,
            totalMeters: this.computeRouteLength(this.route.points),
            heatCellSize: this.route.heatCellSize,
            heat: this.route.heat,
        };
        localStorage.setItem('daiver:lastRoute', JSON.stringify(payload));
        this.route.totalMeters = payload.totalMeters;
        this.edit.history = [];
        this.edit.dirty = false;
        this.render();
    },

    addWaypointAt(worldX, worldY, opts = {}) {
        this.pushHistory();
        this.route.points.push({
            x: +worldX.toFixed(3),
            y: +worldY.toFixed(3),
            ts: Date.now(),
            source: opts.source || 'click',
        });
        this.render();
    },

    removeWaypoint(idx) {
        if (idx < 0 || idx >= this.route.points.length) return;
        this.pushHistory();
        this.route.points.splice(idx, 1);
        this.render();
    },

    moveWaypoint(idx, worldX, worldY) {
        if (idx < 0 || idx >= this.route.points.length) return;
        this.route.points[idx] = { x: worldX, y: worldY };
        this.edit.dirty = true;
        this.refreshEditorButtons();
    },

    pickWaypointAt(px, py) {
        // Busca el waypoint mas cercano dentro de ~14 px para permitir arrastrar.
        const pts = this.route ? this.route.points : [];
        let best = -1, bestD = 14 * 14;
        for (let i = 0; i < pts.length; i++) {
            const [sx, sy] = this.worldToScreen(pts[i].x, pts[i].y);
            const d = (sx - px) ** 2 + (sy - py) ** 2;
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    },

    /* -------------------- Canvas init + eventos -------------------- */
    initCanvas() {
        const c = document.getElementById('ar-route-canvas');
        if (!c) return;
        this.canvas = c;

        const resize = () => {
            const r = c.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            this.dpr = dpr;
            c.width = Math.max(1, Math.round(r.width * dpr));
            c.height = Math.max(1, Math.round(r.height * dpr));
            this.ctx = c.getContext('2d');
            this.drawRoute();
        };
        resize();
        window.addEventListener('resize', resize);

        // Click / drag para editar
        c.addEventListener('pointerdown', (e) => this.onPointerDown(e));
        c.addEventListener('pointermove', (e) => this.onPointerMove(e));
        c.addEventListener('pointerup',   (e) => this.onPointerUp(e));
        c.addEventListener('pointercancel', (e) => this.onPointerUp(e));
        c.addEventListener('contextmenu', (e) => e.preventDefault());

        // Hover: mostrar coordenadas del mundo bajo el cursor
        c.addEventListener('mousemove', (e) => this.onHoverCoords(e));
        c.addEventListener('mouseleave', () => {
            if (this.el.coordTip) this.el.coordTip.classList.remove('visible');
        });
    },

    onHoverCoords(e) {
        const { x: px, y: py } = this.clientToCanvas(e);
        const [wx, wy] = this.screenToWorld(px, py);
        const tip = this.el.coordTip;
        if (!tip) return;
        tip.textContent = `x=${wx.toFixed(2)} m  y=${wy.toFixed(2)} m`;
        // Offset pequeno para que no tape el cursor
        tip.style.left = (px + 14) + 'px';
        tip.style.top  = (py + 14) + 'px';
        tip.classList.add('visible');
    },

    updateRobotBadge() {
        if (!this.pose) return;
        if (this.el.robotBadge) this.el.robotBadge.classList.remove('stale');
        if (this.el.robotX) this.el.robotX.textContent = this.pose.x.toFixed(2);
        if (this.el.robotY) this.el.robotY.textContent = this.pose.y.toFixed(2);
        if (this.el.robotYaw) this.el.robotYaw.textContent = (this.pose.yaw || 0).toFixed(2);
    },

    clientToCanvas(e) {
        const r = this.canvas.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    },

    onPointerDown(e) {
        if (!this.edit.on || this.state.running) return;
        const { x, y } = this.clientToCanvas(e);
        const idx = this.pickWaypointAt(x, y);

        // Shift+click en un waypoint existente: eliminar.
        if (idx >= 0 && e.shiftKey) {
            this.removeWaypoint(idx);
            return;
        }

        // Click en waypoint existente: iniciar arrastre.
        if (idx >= 0) {
            this.edit.draggingIdx = idx;
            this.edit.dragStart = { x, y };
            this.pushHistory();
            this.canvas.setPointerCapture(e.pointerId);
            this.canvas.classList.add('ar-dragging');
            return;
        }

        // Click en area vacia: anadir waypoint.
        const [wx, wy] = this.screenToWorld(x, y);
        this.addWaypointAt(wx, wy);
    },

    onPointerMove(e) {
        if (this.edit.draggingIdx < 0) return;
        const { x, y } = this.clientToCanvas(e);
        const [wx, wy] = this.screenToWorld(x, y);
        this.moveWaypoint(this.edit.draggingIdx, wx, wy);
    },

    onPointerUp(e) {
        if (this.edit.draggingIdx < 0) return;
        try { this.canvas.releasePointerCapture(e.pointerId); } catch {}
        this.edit.draggingIdx = -1;
        this.edit.dragStart = null;
        this.canvas.classList.remove('ar-dragging');
    },

    /* -------------------- Proyeccion world <-> screen -------------------- */
    computeView() {
        // Calcula los extremos del mundo a partir del heatmap, la ruta y la pose.
        // Si no hay nada, usa un cuadro 8x8 m centrado en (0,0).
        const pts = this.route ? this.route.points : [];
        const heat = this.route ? this.route.heat : [];
        const cell = this.route ? (this.route.heatCellSize || 0.15) : 0.15;

        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        const absorb = (x, y) => {
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
        };
        for (const p of pts) absorb(p.x, p.y);
        // heat puede venir como [ix,iy,v] (legado) o [ix,iy,iz,v] (3D nuevo).
        // En ambos casos ix,iy estan en los mismos indices.
        for (const h of heat) absorb(h[0] * cell, h[1] * cell);
        if (this.pose) absorb(this.pose.x, this.pose.y);

        if (!isFinite(minX)) { minX = -4; maxX = 4; minY = -4; maxY = 4; }

        // Margen minimo visible.
        if (maxX - minX < 4) { const c = (minX + maxX) / 2; minX = c - 2; maxX = c + 2; }
        if (maxY - minY < 4) { const c = (minY + maxY) / 2; minY = c - 2; maxY = c + 2; }
        const padX = (maxX - minX) * 0.15;
        const padY = (maxY - minY) * 0.15;
        minX -= padX; maxX += padX; minY -= padY; maxY += padY;

        const W = this.canvas.width / this.dpr;
        const H = this.canvas.height / this.dpr;

        const worldW = maxX - minX;
        const worldH = maxY - minY;
        const sx = (W * 0.9) / worldW;
        const sy = (H * 0.82) / (worldH * TILT_KY);
        const scale = Math.min(sx, sy);

        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;

        this.view.scale = scale;
        this.view.originX = W / 2 - cx * scale;
        this.view.originY = H * 0.58 + cy * scale * TILT_KY;
        this.view.minWorldX = minX; this.view.maxWorldX = maxX;
        this.view.minWorldY = minY; this.view.maxWorldY = maxY;
    },

    worldToScreen(x, y) {
        return [
            this.view.originX + x * this.view.scale,
            this.view.originY - y * this.view.scale * TILT_KY,
        ];
    },

    screenToWorld(sx, sy) {
        return [
            (sx - this.view.originX) / this.view.scale,
            (this.view.originY - sy) / (this.view.scale * TILT_KY),
        ];
    },

    /* -------------------- Render 2.5D -------------------- */
    drawRoute() {
        const ctx = this.ctx, c = this.canvas;
        if (!ctx || !c) return;

        this.computeView();

        const W = c.width / this.dpr;
        const H = c.height / this.dpr;

        ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);

        this.drawSkyAndFloor(ctx, W, H);
        this.drawGrid(ctx, W, H);
        this.drawHeatColumns(ctx);
        this.drawRouteLine(ctx);
        this.drawWaypoints(ctx);
        this.drawRobot(ctx);
    },

    drawSkyAndFloor(ctx, W, H) {
        // Bandas horizonte -> suelo para el efecto de profundidad.
        const horizon = H * 0.18;
        const grdSky = ctx.createLinearGradient(0, 0, 0, horizon);
        grdSky.addColorStop(0, '#081221');
        grdSky.addColorStop(1, '#05080f');
        ctx.fillStyle = grdSky;
        ctx.fillRect(0, 0, W, horizon);

        const grdFloor = ctx.createLinearGradient(0, horizon, 0, H);
        grdFloor.addColorStop(0, '#0a1120');
        grdFloor.addColorStop(0.55, '#050812');
        grdFloor.addColorStop(1, '#02040a');
        ctx.fillStyle = grdFloor;
        ctx.fillRect(0, horizon, W, H - horizon);
    },

    drawGrid(ctx, W, H) {
        // Grilla 1 m, con lineas foreshortened. Se dibujan en world space
        // segun minWorldX/Y y se proyectan linea por linea.
        const v = this.view;
        ctx.lineWidth = 1;
        const stepX = 1, stepY = 1;

        // Lineas perpendiculares al horizonte (en X): verticales en mundo.
        const x0 = Math.ceil(v.minWorldX / stepX) * stepX;
        for (let x = x0; x <= v.maxWorldX; x += stepX) {
            const [sx1, sy1] = this.worldToScreen(x, v.minWorldY);
            const [sx2, sy2] = this.worldToScreen(x, v.maxWorldY);
            const near = x === 0;
            ctx.strokeStyle = near ? 'rgba(90, 168, 255, 0.35)' : 'rgba(255, 255, 255, 0.055)';
            ctx.beginPath();
            ctx.moveTo(sx1, sy1);
            ctx.lineTo(sx2, sy2);
            ctx.stroke();
        }
        // Lineas paralelas al horizonte (en Y): horizontales en mundo.
        const y0 = Math.ceil(v.minWorldY / stepY) * stepY;
        for (let y = y0; y <= v.maxWorldY; y += stepY) {
            const [sx1, sy1] = this.worldToScreen(v.minWorldX, y);
            const [sx2, sy2] = this.worldToScreen(v.maxWorldX, y);
            const near = y === 0;
            ctx.strokeStyle = near ? 'rgba(90, 168, 255, 0.35)' : 'rgba(255, 255, 255, 0.055)';
            ctx.beginPath();
            ctx.moveTo(sx1, sy1);
            ctx.lineTo(sx2, sy2);
            ctx.stroke();
        }
    },

    drawHeatColumns(ctx) {
        const heat = this.route ? this.route.heat : [];
        if (!heat || heat.length === 0) return;
        const cell = this.route.heatCellSize || 0.08;
        const cellZ = this.route.heatCellSizeZ || 0.12;

        const scale = this.view.scale;
        const cellPxX = Math.max(2, cell * scale);
        const cellPxYGround = Math.max(1.5, cell * scale * TILT_KY);
        const voxelPxH = Math.max(2, cellZ * VOXEL_Z_PX_PER_M);

        // Normaliza intensidad por voxel.
        let maxHits = 1;
        for (const h of heat) { if (h[3] > maxHits) maxHits = h[3]; }

        // Soporte legacy: entradas [ix, iy, v] (sin Z). Las tratamos como z=0.
        const normalized = heat.map(h => h.length >= 4
            ? { ix: h[0], iy: h[1], iz: h[2], v: h[3] }
            : { ix: h[0], iy: h[1], iz: 0,    v: h[2] });

        // Ordena back-to-front para que voxels cercanos cubran los lejanos.
        // 1) mayor iy = mas atras (se dibuja primero)
        // 2) menor iz = mas abajo (se dibuja primero)
        normalized.sort((a, b) => b.iy - a.iy || a.iz - b.iz);

        // Sombras en el piso: una por columna (ix,iy), usando el voxel de
        // mayor intensidad de esa columna como referencia.
        const columnIntensity = new Map();  // "ix,iy" -> max v
        for (const n of normalized) {
            const key = n.ix + ',' + n.iy;
            const cur = columnIntensity.get(key) || 0;
            if (n.v > cur) columnIntensity.set(key, n.v);
        }
        for (const [key, v] of columnIntensity) {
            const [ix, iy] = key.split(',').map(Number);
            const [gx, gy] = this.worldToScreen(ix * cell, iy * cell);
            const intensity = Math.min(1, Math.pow(v / maxHits, 0.5));
            ctx.fillStyle = `rgba(0, 0, 0, ${0.28 * intensity})`;
            ctx.beginPath();
            ctx.ellipse(gx, gy + cellPxYGround * 0.2,
                cellPxX * 0.55, cellPxYGround * 0.55, 0, 0, Math.PI * 2);
            ctx.fill();
        }

        // Dibuja cada voxel como un cubito con cara frontal y cara superior.
        const tiltOff = cellPxYGround * 0.35;
        for (const n of normalized) {
            const intensity = Math.min(1, Math.pow(n.v / maxHits, 0.55));
            if (intensity < 0.05) continue;  // umbral visual

            const [gx, gy] = this.worldToScreen(n.ix * cell, n.iy * cell);
            // Altura del voxel: su Z en pantalla. Z=0 = suelo; mayor Z -> mas arriba en pantalla.
            const zMid = n.iz * cellZ;
            const voxelTopY = gy - zMid * VOXEL_Z_PX_PER_M - voxelPxH;
            const voxelBotY = gy - zMid * VOXEL_Z_PX_PER_M;

            // Color por altura Z: bajo = azul, medio = amarillo, alto = rojo.
            const zNorm = Math.max(0, Math.min(1, zMid / 1.6));  // normaliza 0..1.6m
            const rT = Math.round(255 * Math.max(0, Math.min(1, zNorm * 1.8 - 0.2)));
            const gT = Math.round(255 * Math.max(0, Math.min(1, 1.2 - Math.abs(zNorm - 0.5) * 2)));
            const bT = Math.round(255 * Math.max(0, 0.9 - zNorm * 0.9));
            const alpha = VOXEL_ALPHA_BASE + 0.35 * intensity;

            // Cara frontal con gradiente vertical (luz cenital).
            const grd = ctx.createLinearGradient(gx, voxelTopY, gx, voxelBotY);
            grd.addColorStop(0, `rgba(${Math.min(255, rT + 40)}, ${Math.min(255, gT + 40)}, ${Math.min(255, bT + 40)}, ${alpha})`);
            grd.addColorStop(1, `rgba(${Math.floor(rT*0.5)}, ${Math.floor(gT*0.5)}, ${Math.floor(bT*0.5)}, ${alpha * 0.85})`);
            ctx.fillStyle = grd;
            ctx.fillRect(gx - cellPxX / 2, voxelTopY, cellPxX, voxelPxH + 1);

            // Cara superior (paralelogramo isometrico).
            ctx.beginPath();
            ctx.moveTo(gx - cellPxX / 2, voxelTopY);
            ctx.lineTo(gx + cellPxX / 2, voxelTopY);
            ctx.lineTo(gx + cellPxX / 2, voxelTopY - tiltOff);
            ctx.lineTo(gx - cellPxX / 2, voxelTopY - tiltOff);
            ctx.closePath();
            ctx.fillStyle = `rgba(${Math.min(255, rT + 70)}, ${Math.min(255, gT + 70)}, ${Math.min(255, bT + 70)}, ${alpha * 1.1})`;
            ctx.fill();

            // Borde tenue arriba para contrastar bordes entre voxels.
            ctx.strokeStyle = `rgba(255, 255, 255, ${0.18 * intensity})`;
            ctx.lineWidth = 1;
            ctx.strokeRect(gx - cellPxX / 2, voxelTopY, cellPxX, voxelPxH);
        }
    },

    drawRouteLine(ctx) {
        const pts = this.route ? this.route.points : [];
        if (pts.length < 2) return;

        // Sombra en el suelo.
        ctx.save();
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.lineWidth = 6;
        ctx.beginPath();
        pts.forEach((p, i) => {
            const [sx, sy] = this.worldToScreen(p.x, p.y);
            if (i === 0) ctx.moveTo(sx, sy + 3); else ctx.lineTo(sx, sy + 3);
        });
        ctx.stroke();

        // Linea principal: glow verde neon.
        ctx.strokeStyle = 'rgba(62, 255, 160, 0.85)';
        ctx.lineWidth = 3.2;
        ctx.shadowColor = 'rgba(0, 200, 83, 0.9)';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        pts.forEach((p, i) => {
            const [sx, sy] = this.worldToScreen(p.x, p.y);
            if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
        });
        ctx.stroke();
        ctx.restore();

        // Flechas direccionales cada ~1 m.
        ctx.save();
        ctx.fillStyle = 'rgba(62, 255, 160, 0.9)';
        for (let i = 1; i < pts.length; i++) {
            const [ax, ay] = this.worldToScreen(pts[i-1].x, pts[i-1].y);
            const [bx, by] = this.worldToScreen(pts[i].x, pts[i].y);
            const mx = (ax + bx) / 2, my = (ay + by) / 2;
            const dx = bx - ax, dy = by - ay;
            const len = Math.hypot(dx, dy);
            if (len < 40) continue;
            const nx = dx / len, ny = dy / len;
            const size = 5;
            ctx.beginPath();
            ctx.moveTo(mx + nx * size, my + ny * size);
            ctx.lineTo(mx - nx * size - ny * size * 0.6, my - ny * size + nx * size * 0.6);
            ctx.lineTo(mx - nx * size + ny * size * 0.6, my - ny * size - nx * size * 0.6);
            ctx.closePath();
            ctx.fill();
        }
        ctx.restore();
    },

    drawWaypoints(ctx) {
        const pts = this.route ? this.route.points : [];
        pts.forEach((p, i) => {
            const [sx, sy] = this.worldToScreen(p.x, p.y);
            const isOrigin = i === 0;
            const isEnd = i === pts.length - 1;
            const isActive = (i + 1 === this.state.wpNow) && this.state.running;

            // Poste vertical (le da volumen al marcador).
            ctx.strokeStyle = 'rgba(0, 0, 0, 0.6)';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(sx, sy);
            ctx.lineTo(sx, sy - 16);
            ctx.stroke();

            // Cabeza del waypoint.
            let fill, glow, r;
            if (isActive)       { fill = '#ffca28'; glow = 'rgba(255, 202, 40, 0.85)'; r = 8; }
            else if (isOrigin)  { fill = '#00c853'; glow = 'rgba(0, 200, 83, 0.7)'; r = 8; }
            else if (isEnd)     { fill = '#d93025'; glow = 'rgba(217, 48, 37, 0.7)'; r = 7; }
            else                { fill = '#5aa8ff'; glow = 'rgba(90, 168, 255, 0.55)'; r = 5.5; }

            ctx.save();
            ctx.shadowColor = glow;
            ctx.shadowBlur = 12;
            ctx.fillStyle = fill;
            ctx.beginPath();
            ctx.arc(sx, sy - 16, r, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();

            // Numero encima (solo si hay espacio).
            if (pts.length <= 40) {
                ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
                ctx.font = 'bold 10px "Segoe UI", sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(String(i + 1), sx, sy - 16);
            }

            // Coordenadas debajo del waypoint (solo con densidad razonable
            // para no saturar el mapa). En rutas mas densas mostramos solo
            // origen, final y el waypoint activo.
            const showCoords = pts.length <= 30
                || isOrigin || isEnd || isActive;
            if (showCoords) {
                const txt = `(${p.x.toFixed(2)}, ${p.y.toFixed(2)})`;
                ctx.font = 'bold 9px "Consolas", monospace';
                const mw = ctx.measureText(txt).width;
                const offsetY = isOrigin ? 22 : 8;  // el origen tiene "ORIGEN" primero
                const tagX = sx - mw / 2 - 3;
                const tagY = sy + offsetY;
                // Fondo semitransparente para legibilidad
                ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                ctx.fillRect(tagX, tagY - 8, mw + 6, 12);
                ctx.strokeStyle = isActive
                    ? 'rgba(255, 202, 40, 0.7)'
                    : (isOrigin ? 'rgba(0, 200, 83, 0.5)' :
                       isEnd ? 'rgba(217, 48, 37, 0.5)' :
                       'rgba(90, 168, 255, 0.35)');
                ctx.lineWidth = 1;
                ctx.strokeRect(tagX, tagY - 8, mw + 6, 12);
                ctx.fillStyle = isActive ? '#ffca28'
                    : (isOrigin ? '#3effa0' : (isEnd ? '#ff8a80' : '#cfd2d6'));
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(txt, sx, tagY - 2);
            }

            // Etiqueta "ORIGEN" debajo del primer waypoint.
            if (isOrigin) {
                ctx.fillStyle = '#00c853';
                ctx.font = 'bold 9px "Segoe UI", sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('ORIGEN', sx, sy + 12);
            }
        });
    },

    drawRobot(ctx) {
        if (!this.pose) return;
        const [rx, ry] = this.worldToScreen(this.pose.x, this.pose.y);

        // Sombra.
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        ctx.beginPath();
        ctx.ellipse(rx, ry + 3, 9, 4, 0, 0, Math.PI * 2);
        ctx.fill();

        // Cuerpo.
        ctx.save();
        ctx.shadowColor = 'rgba(26, 115, 232, 0.9)';
        ctx.shadowBlur = 14;
        ctx.fillStyle = '#1a73e8';
        ctx.beginPath();
        ctx.arc(rx, ry, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // Flecha de heading.
        const yaw = this.pose.yaw || 0;
        ctx.strokeStyle = '#5aa8ff';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(rx, ry);
        ctx.lineTo(rx + Math.cos(yaw) * 16, ry - Math.sin(yaw) * 16 * TILT_KY);
        ctx.stroke();

        // Etiqueta de coordenadas del robot junto al punto, actualizada
        // en tiempo real cada vez que llega un `lidar_points`.
        const coordsTxt = `(${this.pose.x.toFixed(2)}, ${this.pose.y.toFixed(2)})`;
        ctx.font = 'bold 11px "Consolas", monospace';
        const mw = ctx.measureText(coordsTxt).width;
        const lx = rx + 12;
        const ly = ry - 22;
        ctx.fillStyle = 'rgba(0, 0, 0, 0.72)';
        ctx.fillRect(lx - 4, ly - 12, mw + 10, 18);
        ctx.strokeStyle = 'rgba(90, 168, 255, 0.55)';
        ctx.lineWidth = 1;
        ctx.strokeRect(lx - 4, ly - 12, mw + 10, 18);
        ctx.fillStyle = '#5aa8ff';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(coordsTxt, lx + 1, ly - 3);
    },

    /* -------------------- API helper -------------------- */
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

document.addEventListener('DOMContentLoaded', () => AutoRoute.init());
