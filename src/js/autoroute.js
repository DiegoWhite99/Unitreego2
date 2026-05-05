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
        yaw: 0,           // rotacion alrededor de (centerX, centerY) — vista 4D orbitable
        centerX: 0,
        centerY: 0,
        minWorldX: -4, maxWorldX: 4,
        minWorldY: -4, maxWorldY: 4,
    },

    // Estado del orbit (right-mouse drag rota la vista en yaw).
    orbit: {
        active: false,
        startX: 0,
        startY: 0,
        startYaw: 0,
    },

    // Trail real: histórico de poses del robot recibidas vía lidar_points.
    poseTrail: [],            // [{x, y}]
    _maxTrailPoints: 250,     // ~5 min a 5 Hz con downsample
    _minTrailStepM: 0.05,     // mínimo desplazamiento para añadir punto

    // Simulación de ruta (para probar sin mover el robot real).
    sim: {
        active: false,
        wpIdx: 0,
        returning: false,
        pos: null,             // {x, y, yaw}
        lastTickMs: 0,
        cycle: 0,
        cyclesTotal: 0,
        path: [],              // ruta ya transformada (translate + rotación)
        trail: [],             // simTrail
    },

    // Render loop: RAF + dirty flag. Solo redibuja cuando hace falta.
    _needsRedraw: true,
    _rafHandle: null,
    // Caches de heatmap (offscreen) y de la view, indexadas por una key
    // que cambia solo cuando cambian la geometría base (route+heat+canvas).
    _heatCache: null,
    _heatCacheKey: '',
    _viewKey: '',
    _viewBoundsLocked: null,   // {minX,maxX,minY,maxY} estables

    init() {
        this.cacheEls();
        this.loadRoute();
        this.setupSocket();
        this.setupControls();
        this.setupEditor();
        this.initCanvas();
        this.render();
        this.refreshStatus();
        this.startRenderLoop();
    },

    markDirty() { this._needsRedraw = true; },

    startRenderLoop() {
        const tick = (now) => {
            if (this.sim.active) {
                this.advanceSim(now);
                this._needsRedraw = true;
            }
            if (this._needsRedraw) {
                this.drawRoute();
                this._needsRedraw = false;
            }
            this._rafHandle = requestAnimationFrame(tick);
        };
        this._rafHandle = requestAnimationFrame(tick);
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
            btnSim:       document.getElementById('ar-sim'),
            btnYolo:      document.getElementById('ar-yolo-toggle'),
            btnEdit:      document.getElementById('ar-edit-toggle'),
            btnBlank:     document.getElementById('ar-edit-blank'),
            btnUndo:      document.getElementById('ar-edit-undo'),
            btnLinear:    document.getElementById('ar-edit-linear'),
            btnClear:     document.getElementById('ar-edit-clear'),
            btnSave:      document.getElementById('ar-edit-save'),
            btnSaveScan:  document.getElementById('ar-save-scan'),
            btnResetView: document.getElementById('ar-reset-view'),
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
        this.markDirty();
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
            if (!d || !d.pose) return;
            const prev = this.pose;
            this.pose = d.pose;
            this.updateRobotBadge();
            // Acumular trail (downsample) para ver el camino real.
            const last = this.poseTrail[this.poseTrail.length - 1];
            const newPoint = !last
                || Math.hypot(d.pose.x - last.x, d.pose.y - last.y) > this._minTrailStepM;
            if (newPoint) {
                this.poseTrail.push({ x: d.pose.x, y: d.pose.y });
                if (this.poseTrail.length > this._maxTrailPoints) {
                    this.poseTrail.shift();
                }
            }
            // Solo redibujar si la pose cambió de forma visible o se añadió
            // un punto nuevo al trail. Robot quieto = sin redraw = CPU libre.
            if (newPoint
                || !prev
                || Math.abs((prev.yaw || 0) - (d.pose.yaw || 0)) > 0.02
                || Math.hypot(d.pose.x - prev.x, d.pose.y - prev.y) > 0.01) {
                this.markDirty();
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
            this.markDirty();
        });

        this.socket.on('autoroute_done', () => {
            this.state.running = false;
            this.updateProgress();
            this.setRun(false);
            this.markDirty();
            // Limpiar trail al terminar para que la próxima ruta arranque
            // con un mapa limpio (el trail viejo confundiría al operador).
            this.poseTrail = [];
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
        this.el.btnStart.disabled = running || !this.hasRoute() || this.sim.active;
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
        this.el.btnSim?.addEventListener('click', () => this.toggleSim());
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
        let translate = !!(this.el.chkTranslate && this.el.chkTranslate.checked);

        // Aviso UX: si la pose actual del robot esta lejos del origen
        // guardado, casi seguro el frame del lidar cambio entre sesiones.
        // Sugerimos activar la casilla para evitar que el robot se vaya
        // a coordenadas absolutas que ya no existen fisicamente.
        if (this.pose && this.route.points.length >= 1 && !translate) {
            const wp0 = this.route.points[0];
            const dx = this.pose.x - wp0.x;
            const dy = this.pose.y - wp0.y;
            const dist = Math.hypot(dx, dy);
            if (dist > 1.0) {
                const msg =
                    `Atencion: el robot esta a ${dist.toFixed(2)} m del origen guardado ` +
                    `(robot=${this.pose.x.toFixed(2)},${this.pose.y.toFixed(2)} ; ` +
                    `origen=${wp0.x.toFixed(2)},${wp0.y.toFixed(2)}).\n\n` +
                    `Si el frame del lidar cambio (reinicio del robot, sensor reactivado), ` +
                    `el robot se ira a un lugar incorrecto.\n\n` +
                    `¿Quieres ANCLAR la ruta a la posicion y orientacion actuales del robot? ` +
                    `(Recomendado: SI)`;
                if (confirm(msg)) {
                    translate = true;
                    if (this.el.chkTranslate) this.el.chkTranslate.checked = true;
                } else {
                    if (!confirm('Iniciar igualmente con coordenadas absolutas? El robot puede irse a otro lado.')) {
                        return;
                    }
                }
            }
        } else if (!this.pose && !translate) {
            if (!confirm('No hay pose del lidar todavia. Iniciar sin anclaje al robot puede mandarlo a otro lado. ¿Continuar?')) {
                return;
            }
        }

        const cycles = Math.max(1, parseInt(this.el.cyclesInput.value, 10) || 1);
        const smooth = !!(this.el.chkSmooth && this.el.chkSmooth.checked);
        // Trail limpio para esta corrida (no mezclar con runs anteriores).
        this.poseTrail = [];
        this.markDirty();
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
                imgsz: 416,
                with_objects: false,
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
        this.el.btnLinear?.addEventListener('click', () => this.linearizeRoute());
        this.el.btnClear.addEventListener('click', () => this.clearPoints());
        this.el.btnSave.addEventListener('click', () => this.savePoints());
        this.el.btnBlank?.addEventListener('click', () => this.startBlank());
        this.el.btnSaveScan?.addEventListener('click', () => this.downloadScan());
        this.el.btnResetView?.addEventListener('click', () => this.resetView());

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

    /* Reemplaza la ruta por una recta entre origen y final con waypoints
       intermedios uniformemente espaciados. Util cuando el operador
       camino recto pero el SLAM grabo un trayecto curvo por drift de yaw.
       Si la ruta tiene <2 puntos, no hace nada. */
    linearizeRoute() {
        const pts = this.route ? this.route.points : [];
        if (pts.length < 2) {
            alert('Necesitas al menos 2 waypoints (origen y final) para linealizar.');
            return;
        }
        const a = pts[0];
        const b = pts[pts.length - 1];
        const dist = Math.hypot(b.x - a.x, b.y - a.y);
        // Un waypoint intermedio cada ~1.2 m para que el seguidor tenga
        // referencias y no derive en tramos largos. 0 intermedios para
        // rutas cortas (<1.5 m).
        const intermediates = Math.max(0, Math.floor(dist / 1.2) - 1);
        const msg = intermediates > 0
            ? `Reemplazar la ruta por una linea recta entre origen y final con ${intermediates} waypoint(s) intermedio(s)?\n\n(Distancia: ${dist.toFixed(2)} m, ${pts.length} waypoints actuales)`
            : `Reemplazar la ruta por una linea recta entre origen y final?\n\n(Distancia: ${dist.toFixed(2)} m, ${pts.length} waypoints actuales)`;
        if (!confirm(msg)) return;

        this.pushHistory();
        const next = [{ x: a.x, y: a.y, ts: a.ts || Date.now(), source: a.source || 'click' }];
        const segments = intermediates + 1;
        for (let i = 1; i <= intermediates; i++) {
            const t = i / segments;
            next.push({
                x: +(a.x + (b.x - a.x) * t).toFixed(3),
                y: +(a.y + (b.y - a.y) * t).toFixed(3),
                ts: Date.now(),
                source: 'linearize',
            });
        }
        next.push({ x: b.x, y: b.y, ts: b.ts || Date.now(), source: b.source || 'click' });
        this.route.points = next;
        this.edit.dirty = true;
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
        this.markDirty();
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
            this._heatCache = null;
            this._heatCacheKey = '';
            this.markDirty();
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
        const { x, y } = this.clientToCanvas(e);

        // Boton derecho (button=2) o medio (button=1): orbit (rotar vista).
        // Funciona en cualquier modo — no interfiere con la edicion.
        if (e.button === 2 || e.button === 1) {
            this.orbit.active = true;
            this.orbit.startX = x;
            this.orbit.startY = y;
            this.orbit.startYaw = this.view.yaw;
            try { this.canvas.setPointerCapture(e.pointerId); } catch {}
            this.canvas.classList.add('ar-orbiting');
            e.preventDefault();
            return;
        }

        if (!this.edit.on || this.state.running) return;
        const idx = this.pickWaypointAt(x, y);

        if (idx >= 0 && e.shiftKey) {
            this.removeWaypoint(idx);
            return;
        }

        if (idx >= 0) {
            this.edit.draggingIdx = idx;
            this.edit.dragStart = { x, y };
            this.pushHistory();
            this.canvas.setPointerCapture(e.pointerId);
            this.canvas.classList.add('ar-dragging');
            return;
        }

        const [wx, wy] = this.screenToWorld(x, y);
        this.addWaypointAt(wx, wy);
    },

    onPointerMove(e) {
        if (this.orbit.active) {
            const { x, y } = this.clientToCanvas(e);
            // 1 px de drag horizontal ≈ 0.5° de rotacion.
            const dx = x - this.orbit.startX;
            this.view.yaw = this.orbit.startYaw + dx * (Math.PI / 360);
            this._heatCache = null;
            this._heatCacheKey = '';
            this.markDirty();
            return;
        }
        if (this.edit.draggingIdx < 0) return;
        const { x, y } = this.clientToCanvas(e);
        const [wx, wy] = this.screenToWorld(x, y);
        this.moveWaypoint(this.edit.draggingIdx, wx, wy);
    },

    onPointerUp(e) {
        if (this.orbit.active) {
            this.orbit.active = false;
            try { this.canvas.releasePointerCapture(e.pointerId); } catch {}
            this.canvas.classList.remove('ar-orbiting');
            return;
        }
        if (this.edit.draggingIdx < 0) return;
        try { this.canvas.releasePointerCapture(e.pointerId); } catch {}
        this.edit.draggingIdx = -1;
        this.edit.dragStart = null;
        this.canvas.classList.remove('ar-dragging');
    },

    /* -------------------- Proyeccion world <-> screen -------------------- */
    computeView() {
        // Calcula los extremos del mundo a partir del heatmap y la ruta.
        // OJO: NO usamos la pose ni el sim para los bounds — eso haría que
        // el heatmap recachee en cada tick. La pose se dibuja sobre la
        // misma view fija (si sale de cuadro, igual se dibuja).
        const pts = this.route ? this.route.points : [];
        const heat = this.route ? this.route.heat : [];
        const cell = this.route ? (this.route.heatCellSize || 0.15) : 0.15;

        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        const absorb = (x, y) => {
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
        };
        for (const p of pts) absorb(p.x, p.y);
        // heat puede venir como [ix,iy,v] (legado), [ix,iy,iz,v] o [ix,iy,iz,v,age].
        // En todos los casos ix,iy estan en los mismos indices.
        for (const h of heat) absorb(h[0] * cell, h[1] * cell);

        if (!isFinite(minX)) { minX = -4; maxX = 4; minY = -4; maxY = 4; }

        // Margen minimo visible.
        if (maxX - minX < 4) { const c = (minX + maxX) / 2; minX = c - 2; maxX = c + 2; }
        if (maxY - minY < 4) { const c = (minY + maxY) / 2; minY = c - 2; maxY = c + 2; }
        const padX = (maxX - minX) * 0.15;
        const padY = (maxY - minY) * 0.15;
        minX -= padX; maxX += padX; minY -= padY; maxY += padY;

        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;

        // Si la vista esta rotada, las bounds rotadas crecen — recalculamos
        // los extremos sobre las 4 esquinas rotadas para que la escena
        // entera siga cabiendo en la pantalla en cualquier yaw.
        let fitMinX = minX, fitMaxX = maxX, fitMinY = minY, fitMaxY = maxY;
        const yaw = this.view.yaw || 0;
        if (yaw) {
            const c = Math.cos(yaw), s = Math.sin(yaw);
            fitMinX = Infinity; fitMaxX = -Infinity;
            fitMinY = Infinity; fitMaxY = -Infinity;
            const corners = [[minX, minY], [minX, maxY], [maxX, minY], [maxX, maxY]];
            for (const [x, y] of corners) {
                const dx = x - cx, dy = y - cy;
                const rx = cx + dx * c - dy * s;
                const ry = cy + dx * s + dy * c;
                if (rx < fitMinX) fitMinX = rx; if (rx > fitMaxX) fitMaxX = rx;
                if (ry < fitMinY) fitMinY = ry; if (ry > fitMaxY) fitMaxY = ry;
            }
        }

        const W = this.canvas.width / this.dpr;
        const H = this.canvas.height / this.dpr;
        const worldW = fitMaxX - fitMinX;
        const worldH = fitMaxY - fitMinY;
        const sx = (W * 0.9) / worldW;
        const sy = (H * 0.82) / (worldH * TILT_KY);
        const scale = Math.min(sx, sy);

        this.view.scale = scale;
        this.view.centerX = cx;
        this.view.centerY = cy;
        this.view.originX = W / 2 - cx * scale;
        this.view.originY = H * 0.58 + cy * scale * TILT_KY;
        this.view.minWorldX = minX; this.view.maxWorldX = maxX;
        this.view.minWorldY = minY; this.view.maxWorldY = maxY;
    },

    worldToScreen(x, y) {
        const v = this.view;
        if (v.yaw) {
            const dx = x - v.centerX;
            const dy = y - v.centerY;
            const c = Math.cos(v.yaw), s = Math.sin(v.yaw);
            x = v.centerX + dx * c - dy * s;
            y = v.centerY + dx * s + dy * c;
        }
        return [
            v.originX + x * v.scale,
            v.originY - y * v.scale * TILT_KY,
        ];
    },

    screenToWorld(sx, sy) {
        const v = this.view;
        let x = (sx - v.originX) / v.scale;
        let y = (v.originY - sy) / (v.scale * TILT_KY);
        if (v.yaw) {
            const dx = x - v.centerX;
            const dy = y - v.centerY;
            const c = Math.cos(-v.yaw), s = Math.sin(-v.yaw);
            x = v.centerX + dx * c - dy * s;
            y = v.centerY + dx * s + dy * c;
        }
        return [x, y];
    },

    resetView() {
        this.view.yaw = 0;
        this._heatCache = null;
        this._heatCacheKey = '';
        this.markDirty();
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
        this.drawHeatColumnsCached(ctx, W, H);
        this.drawTrail(ctx);
        this.drawRouteLine(ctx);
        this.drawWaypoints(ctx);
        this.drawRobot(ctx);
        if (this.sim.active) this.drawSimRobot(ctx);
    },

    /* Heatmap cacheado: sólo se re-renderiza cuando cambian los datos del
       heat o las dimensiones de la view. Reutiliza un canvas offscreen y
       lo blittea en cada frame, evitando dibujar miles de voxels cada tick. */
    drawHeatColumnsCached(ctx, W, H) {
        const heat = this.route ? this.route.heat : [];
        if (!heat || heat.length === 0) return;

        const v = this.view;
        const cellPx = (this.route.heatCellSize || 0.08).toFixed(3);
        const key = [
            heat.length,
            v.scale.toFixed(2),
            v.minWorldX.toFixed(2), v.maxWorldX.toFixed(2),
            v.minWorldY.toFixed(2), v.maxWorldY.toFixed(2),
            v.yaw.toFixed(3),
            cellPx,
            Math.round(W), Math.round(H),
        ].join('|');

        if (this._heatCacheKey !== key
            || !this._heatCache
            || this._heatCache.width !== Math.round(W * this.dpr)
            || this._heatCache.height !== Math.round(H * this.dpr)) {
            const off = document.createElement('canvas');
            off.width  = Math.round(W * this.dpr);
            off.height = Math.round(H * this.dpr);
            const offCtx = off.getContext('2d');
            offCtx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
            this.drawHeatColumns(offCtx);
            this._heatCache = off;
            this._heatCacheKey = key;
        }

        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(this._heatCache, 0, 0);
        ctx.restore();
        ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    },

    /* Trail del robot real: línea con fade desde más viejo (transparente)
       hasta más nuevo (saturado). Indica el camino REAL recorrido. */
    drawTrail(ctx) {
        const trail = this.poseTrail;
        if (!trail || trail.length < 2) return;
        ctx.save();
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        // Sombra al piso
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.lineWidth = 4;
        ctx.beginPath();
        for (let i = 0; i < trail.length; i++) {
            const [sx, sy] = this.worldToScreen(trail[i].x, trail[i].y);
            if (i === 0) ctx.moveTo(sx, sy + 2);
            else ctx.lineTo(sx, sy + 2);
        }
        ctx.stroke();
        // Línea principal con gradiente de opacidad por edad
        const n = trail.length;
        for (let i = 1; i < n; i++) {
            const [ax, ay] = this.worldToScreen(trail[i-1].x, trail[i-1].y);
            const [bx, by] = this.worldToScreen(trail[i].x, trail[i].y);
            const alpha = 0.15 + 0.75 * (i / n);
            ctx.strokeStyle = `rgba(255, 196, 0, ${alpha.toFixed(3)})`;
            ctx.lineWidth = 2.4;
            ctx.beginPath();
            ctx.moveTo(ax, ay);
            ctx.lineTo(bx, by);
            ctx.stroke();
        }
        ctx.restore();
    },

    /* Sprite del robot virtual + su trail durante la simulación. */
    drawSimRobot(ctx) {
        const sim = this.sim;
        if (!sim.pos) return;

        // Trail virtual (línea punteada celeste)
        if (sim.trail.length > 1) {
            ctx.save();
            ctx.strokeStyle = 'rgba(102, 204, 255, 0.85)';
            ctx.lineWidth = 2.5;
            ctx.setLineDash([5, 4]);
            ctx.lineCap = 'round';
            ctx.beginPath();
            for (let i = 0; i < sim.trail.length; i++) {
                const [sx, sy] = this.worldToScreen(sim.trail[i].x, sim.trail[i].y);
                if (i === 0) ctx.moveTo(sx, sy);
                else ctx.lineTo(sx, sy);
            }
            ctx.stroke();
            ctx.restore();
        }

        const [rx, ry] = this.worldToScreen(sim.pos.x, sim.pos.y);

        // Sombra
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        ctx.beginPath();
        ctx.ellipse(rx, ry + 3, 10, 4.5, 0, 0, Math.PI * 2);
        ctx.fill();

        // Cuerpo (anillo punteado para distinguirlo del robot real)
        ctx.save();
        ctx.shadowColor = 'rgba(102, 204, 255, 0.95)';
        ctx.shadowBlur = 14;
        ctx.fillStyle = 'rgba(102, 204, 255, 0.9)';
        ctx.beginPath();
        ctx.arc(rx, ry, 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        ctx.strokeStyle = '#cce6ff';
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.arc(rx, ry, 11, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);

        // Heading
        ctx.strokeStyle = '#cce6ff';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(rx, ry);
        ctx.lineTo(
            rx + Math.cos(sim.pos.yaw) * 18,
            ry - Math.sin(sim.pos.yaw) * 18 * TILT_KY,
        );
        ctx.stroke();

        // Etiqueta
        ctx.fillStyle = '#cce6ff';
        ctx.font = 'bold 10px "Segoe UI", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('TEST', rx, ry - 22);
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

        // Formatos soportados:
        //   [ix, iy, v]               (legacy 2D)
        //   [ix, iy, iz, v]           (3D sin canal de tiempo)
        //   [ix, iy, iz, v, age]      (4D: age en [0..1], 1 = recien capturado)
        const normalized = heat.map(h => {
            if (h.length >= 5) return { ix: h[0], iy: h[1], iz: h[2], v: h[3], age: h[4] };
            if (h.length === 4) return { ix: h[0], iy: h[1], iz: h[2], v: h[3], age: 1 };
            return { ix: h[0], iy: h[1], iz: 0, v: h[2], age: 1 };
        });

        // Normaliza intensidad por voxel (el campo ya esta unificado en .v).
        let maxHits = 1;
        for (const n of normalized) { if (n.v > maxHits) maxHits = n.v; }

        // Ordena back-to-front segun la profundidad EN PANTALLA (que depende
        // del yaw actual), no del iy crudo. Asi al rotar la vista los voxels
        // del fondo se dibujan primero sin importar el angulo.
        const yawC = Math.cos(this.view.yaw || 0);
        const yawS = Math.sin(this.view.yaw || 0);
        const cx = this.view.centerX, cy = this.view.centerY;
        for (const n of normalized) {
            const wx = n.ix * cell - cx, wy = n.iy * cell - cy;
            n.depth = wx * yawS + wy * yawC;  // Y rotado: mayor = mas atras
        }
        normalized.sort((a, b) => b.depth - a.depth || a.iz - b.iz);

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
            // Canal "tiempo" (4D): voxels recien capturados al 100%, los mas
            // antiguos del scan al 40%. Permite distinguir lo recien
            // mapeado (paredes que el robot acaba de ver) de lo viejo.
            const ageMult = 0.4 + 0.6 * (n.age != null ? n.age : 1);
            const alpha = (VOXEL_ALPHA_BASE + 0.35 * intensity) * ageMult;

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

    /* Devuelve la ruta tal cual se va a dibujar:
       - En modo edicion: coordenadas crudas (lo que el usuario edita).
       - Fuera de edicion + "Anclar a la pose actual" + pose disponible:
         coordenadas transformadas, identicas a las que sigue el TEST y el
         backend. Asi la linea verde y el TEST coinciden visualmente. */
    _displayPath() {
        const raw = (this.route && this.route.points) || [];
        if (raw.length === 0) return [];
        const useTransformed = !this.edit.on
            && this.el.chkTranslate && this.el.chkTranslate.checked
            && this.pose;
        if (useTransformed) return this._transformedPath(true);
        return raw.map(p => ({ x: p.x, y: p.y, _raw: p }));
    },

    drawRouteLine(ctx) {
        const pts = this._displayPath();
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
        const pts = this._displayPath();
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

    /* -------------------- Simulación de ruta -------------------- */
    /* Anima un sprite virtual recorriendo la ruta sin enviar comandos al
       robot real. Aplica la MISMA transformación que el backend cuando
       "Anclar a la pose actual" está activo, así ves exactamente qué
       camino seguirá el Daiver al iniciar.

       Útil para: validar la ruta antes de ejecutarla, detectar errores
       de waypoints, y verificar la geometría tras cambiar el frame del lidar. */

    toggleSim() {
        if (this.sim.active) {
            this.stopSim();
        } else {
            this.startSim();
        }
    },

    startSim() {
        if (!this.hasRoute()) {
            alert('No hay ruta para simular. Pone al menos 2 waypoints.');
            return;
        }
        if (this.state.running) {
            alert('Hay una ruta real en curso. Detenela primero.');
            return;
        }
        const useTranslate = !!(this.el.chkTranslate && this.el.chkTranslate.checked);
        if (useTranslate && !this.pose) {
            const ok = confirm(
                'No hay pose del lidar. ¿Simular usando los waypoints tal cual?\n\n' +
                '(Activa el sensor de proximidad en el Control Remoto para que la simulación arranque desde la pose real.)'
            );
            if (!ok) return;
        }
        const path = this._transformedPath(useTranslate);
        if (path.length < 2) return;

        const yaw0 = Math.atan2(path[1].y - path[0].y, path[1].x - path[0].x);
        const cyclesTotal = Math.max(1, parseInt(this.el.cyclesInput.value, 10) || 1);

        this.sim = {
            active: true,
            wpIdx: 1,
            returning: false,
            pos: { x: path[0].x, y: path[0].y, yaw: yaw0 },
            lastTickMs: performance.now(),
            cycle: 1,
            cyclesTotal,
            path,
            trail: [{ x: path[0].x, y: path[0].y }],
        };
        this.el.btnSim.textContent = '⏹ Detener test';
        this.el.btnSim.classList.add('danger');
        this.el.btnStart.disabled = true;
        // Reflejar progreso simulado en la misma UI de ciclos/wp
        this.state.cycleNow = 1;
        this.state.cycleTotal = cyclesTotal;
        this.state.wpNow = 1;
        this.state.wpTotal = path.length;
        this.updateProgress();
        const el = this.el.runStatus;
        if (el) {
            el.classList.add('connected');
            el.classList.remove('disconnected');
            el.querySelector('.txt').textContent = 'Simulando ruta';
        }
        this.markDirty();
    },

    stopSim() {
        this.sim.active = false;
        this.el.btnSim.textContent = '\u{1F9EA} Probar ruta (sin robot)';
        this.el.btnSim.classList.remove('danger');
        this.el.btnStart.disabled = !this.hasRoute() || this.state.running;
        const el = this.el.runStatus;
        if (el && !this.state.running) {
            el.classList.remove('connected');
            el.classList.add('disconnected');
            el.querySelector('.txt').textContent = 'Detenido';
        }
        this.markDirty();
    },

    advanceSim(nowMs) {
        const sim = this.sim;
        const dt = Math.min(0.1, (nowMs - sim.lastTickMs) / 1000);
        sim.lastTickMs = nowMs;
        if (dt <= 0) return;

        const target = sim.path[sim.wpIdx];
        if (!target) { this._completeSimCycle(); return; }

        const dx = target.x - sim.pos.x;
        const dy = target.y - sim.pos.y;
        const dist = Math.hypot(dx, dy);

        // Parámetros conservadores ~iguales al backend (smooth_mode=false)
        const linMax = 0.4;
        const angMax = 1.2;
        const reach  = 0.20;
        const headingThr = 0.4;

        if (dist < reach) {
            this._advanceSimWaypoint();
            return;
        }

        const targetHeading = Math.atan2(dy, dx);
        const headingErr = this._normAng(targetHeading - sim.pos.yaw);

        if (Math.abs(headingErr) > headingThr) {
            // Solo girar
            const w = Math.max(-angMax, Math.min(angMax, headingErr * 1.8));
            sim.pos.yaw = this._normAng(sim.pos.yaw + w * dt);
        } else {
            const v = Math.min(linMax, dist * 0.8);
            sim.pos.x += Math.cos(sim.pos.yaw) * v * dt;
            sim.pos.y += Math.sin(sim.pos.yaw) * v * dt;
            // Pequeña corrección continua de yaw para no derivar
            const w = Math.max(-angMax, Math.min(angMax, headingErr * 1.0));
            sim.pos.yaw = this._normAng(sim.pos.yaw + w * dt);
        }

        // Trail virtual (downsample)
        const last = sim.trail[sim.trail.length - 1];
        if (!last
            || Math.hypot(sim.pos.x - last.x, sim.pos.y - last.y) > 0.04) {
            sim.trail.push({ x: sim.pos.x, y: sim.pos.y });
            if (sim.trail.length > 1000) sim.trail.shift();
        }
    },

    _advanceSimWaypoint() {
        const sim = this.sim;
        const n = sim.path.length;
        if (!sim.returning) {
            sim.wpIdx++;
            if (sim.wpIdx >= n) {
                sim.returning = true;
                sim.wpIdx = n - 2;
                if (sim.wpIdx < 0) { this._completeSimCycle(); return; }
            }
        } else {
            sim.wpIdx--;
            if (sim.wpIdx < 0) { this._completeSimCycle(); return; }
        }
        this.state.wpNow = sim.returning ? (sim.wpIdx + 1) : (sim.wpIdx + 1);
        this.state.cycleNow = sim.cycle;
        this.updateProgress();
    },

    _completeSimCycle() {
        const sim = this.sim;
        if (sim.cycle >= sim.cyclesTotal) {
            // Fin de la simulación
            this.stopSim();
            return;
        }
        sim.cycle++;
        sim.wpIdx = 1;
        sim.returning = false;
        const origin = sim.path[0];
        sim.pos.x = origin.x;
        sim.pos.y = origin.y;
        if (sim.path[1]) {
            sim.pos.yaw = Math.atan2(
                sim.path[1].y - origin.y,
                sim.path[1].x - origin.x,
            );
        }
        this.state.cycleNow = sim.cycle;
        this.updateProgress();
    },

    /* Replica la transformación del backend (core/autoroute.py): si
       translate_to_pose=true, ancla wp[0] a la pose actual y rota todo
       para que el primer tramo coincida con el yaw actual del robot. */
    _transformedPath(useTranslate) {
        const pts = (this.route && this.route.points) || [];
        if (pts.length < 2) return pts.map(p => ({ x: p.x, y: p.y }));
        if (!useTranslate || !this.pose) {
            return pts.map(p => ({ x: p.x, y: p.y }));
        }
        const pose = this.pose;
        const wp0 = pts[0], wp1 = pts[1];
        const savedHeading = Math.atan2(wp1.y - wp0.y, wp1.x - wp0.x);
        const dYaw = this._normAng((pose.yaw || 0) - savedHeading);
        const c = Math.cos(dYaw), s = Math.sin(dYaw);
        return pts.map(p => {
            const dx = p.x - wp0.x;
            const dy = p.y - wp0.y;
            return { x: pose.x + dx * c - dy * s, y: pose.y + dx * s + dy * c };
        });
    },

    _normAng(a) {
        while (a >  Math.PI) a -= 2 * Math.PI;
        while (a < -Math.PI) a += 2 * Math.PI;
        return a;
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
