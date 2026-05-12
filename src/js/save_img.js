const API = window.location.origin;

const SPACE_STYLES = {
    habitacion: { color: 'rgba(90,168,255,0.95)', fill: 'rgba(90,168,255,0.14)', icon: 'HB', label: 'Habitacion' },
    bano:       { color: 'rgba(0,200,255,0.95)', fill: 'rgba(0,200,255,0.14)', icon: 'BA', label: 'Bano' },
    sala:       { color: 'rgba(62,255,160,0.95)', fill: 'rgba(62,255,160,0.14)', icon: 'SA', label: 'Sala' },
    cocina:     { color: 'rgba(255,193,7,0.95)', fill: 'rgba(255,193,7,0.14)', icon: 'CO', label: 'Cocina' },
    comedor:    { color: 'rgba(255,152,0,0.95)', fill: 'rgba(255,152,0,0.14)', icon: 'CM', label: 'Comedor' },
    pasillo:    { color: 'rgba(171,71,188,0.95)', fill: 'rgba(171,71,188,0.14)', icon: 'PS', label: 'Pasillo' },
    estudio:    { color: 'rgba(120,144,156,0.95)', fill: 'rgba(120,144,156,0.14)', icon: 'ES', label: 'Estudio' },
    lavanderia: { color: 'rgba(102,187,106,0.95)', fill: 'rgba(102,187,106,0.14)', icon: 'LV', label: 'Lavanderia' },
    balcon:     { color: 'rgba(38,198,218,0.95)', fill: 'rgba(38,198,218,0.14)', icon: 'BC', label: 'Balcon' },
    otro:       { color: 'rgba(207,210,214,0.95)', fill: 'rgba(207,210,214,0.14)', icon: 'OT', label: 'Otro' },
};

const SaveImg = {
    image: null,
    imageName: '',
    points: [],
    aiSuggestedPoints: [],
    aiZoneWaypoints: [],
    aiZones: [],
    aiSectors: [],
    aiSpaces: [],
    aiObjects: [],
    aiObstacles: [],
    nav: {
        ready: false,
        w: 0,
        h: 0,
        frame: null,
        doc: null,
        blocked: null,
        clearance: null,
        compId: null,
        components: [],
        roomBoxes: [],
    },
    dragIdx: -1,
    statusTimer: null,
    isAnalyzing: false,
    analysisStartedAt: 0,
    _fxRaf: null,

    init() {
        this.cacheEls();
        this.initCanvas();
        this.bindEvents();
        this.renderLegend();
        this.refreshStatus();
        this.startFxLoop();
        this.statusTimer = setInterval(() => this.refreshStatus(), 3000);
    },

    startFxLoop() {
        const tick = () => {
            if (this.isAnalyzing) this.draw();
            this._fxRaf = requestAnimationFrame(tick);
        };
        this._fxRaf = requestAnimationFrame(tick);
    },

    cacheEls() {
        this.el = {
            statusServer: document.getElementById('si-status-server'),
            statusRobot: document.getElementById('si-status-robot'),
            fileInput: document.getElementById('si-file-input'),
            btnAnalyze: document.getElementById('si-analyze'),
            btnApplyAi: document.getElementById('si-apply-ai'),
            btnClear: document.getElementById('si-clear'),
            btnSaveAutoroute: document.getElementById('si-save-autoroute'),
            btnExportRoute: document.getElementById('si-export-route'),
            btnStartMission: document.getElementById('si-start-mission'),
            pointsMeta: document.getElementById('si-points-meta'),
            lengthMeta: document.getElementById('si-length-meta'),
            waypoints: document.getElementById('si-waypoints'),
            report: document.getElementById('si-report'),
            spaceLegend: document.getElementById('si-space-legend'),
            tip: document.getElementById('si-map-tip'),
            scale: document.getElementById('si-scale'),
            cycles: document.getElementById('si-cycles'),
            chkTranslate: document.getElementById('si-translate'),
            chkSmooth: document.getElementById('si-smooth'),
            zoneType: document.getElementById('si-zone-type'),
            zoneView: document.getElementById('si-zone-view'),
            requireCloud: document.getElementById('si-require-cloud'),
            canvas: document.getElementById('si-map-canvas'),
        };

        // Limpieza preventiva: nunca mantener API keys en el navegador.
        try { sessionStorage.removeItem('daiver:mapai:openai_key'); } catch (_) { /* ignore */ }
    },

    initCanvas() {
        this.canvas = this.el.canvas;
        this.ctx = this.canvas.getContext('2d');
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());
        this.draw();
    },

    bindEvents() {
        this.el.fileInput.addEventListener('change', (e) => this.onFileSelected(e));
        this.el.btnAnalyze.addEventListener('click', () => this.analyzeMapWithAI());
        this.el.btnApplyAi.addEventListener('click', () => this.applyAiRoute());
        this.el.btnClear.addEventListener('click', () => this.clearPoints());
        this.el.zoneType?.addEventListener('change', () => this.draw());
        this.el.zoneView?.addEventListener('change', () => this.draw());
        this.el.btnSaveAutoroute.addEventListener('click', () => this.saveAndOpenAutoroute());
        this.el.btnExportRoute?.addEventListener('click', () => this.exportRouteJson());
        this.el.btnStartMission.addEventListener('click', () => this.saveAndStartMission());

        this.canvas.addEventListener('mousedown', (e) => this.onPointerDown(e));
        window.addEventListener('mousemove', (e) => this.onPointerMove(e));
        window.addEventListener('mouseup', () => { this.dragIdx = -1; });
        this.canvas.addEventListener('click', (e) => this.onCanvasClick(e));
    },

    resizeCanvas() {
        const rect = this.canvas.getBoundingClientRect();
        const dpr = Math.max(1, window.devicePixelRatio || 1);
        const w = Math.max(320, Math.floor(rect.width));
        const h = Math.max(240, Math.floor(rect.height));
        this.canvas.width = Math.floor(w * dpr);
        this.canvas.height = Math.floor(h * dpr);
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.draw();
    },

    async refreshStatus() {
        const st = await this.api('/api/status', 'GET');
        if (st && st.status !== 'error') {
            this.setPill(this.el.statusServer, true, 'Servidor online');
            this.setPill(this.el.statusRobot, !!st.connected, st.connected ? 'Robot conectado' : 'Robot desconectado');
        } else {
            this.setPill(this.el.statusServer, false, 'Servidor offline');
            this.setPill(this.el.statusRobot, false, 'Robot desconectado');
        }
    },

    setPill(el, ok, text) {
        if (!el) return;
        el.classList.toggle('connected', ok);
        el.classList.toggle('disconnected', !ok);
        const txt = el.querySelector('.txt');
        if (txt) txt.textContent = text;
    },

    normalizeSpaceKind(space) {
        const raw = String(space?.kind || '').toLowerCase();
        if (SPACE_STYLES[raw]) return raw;
        const name = String(space?.name || '').toLowerCase();
        if (/dorm|habit|cuarto/.test(name)) return 'habitacion';
        if (/ba[ñn]o|ws|toilet/.test(name)) return 'bano';
        if (/cocina|kitchen/.test(name)) return 'cocina';
        if (/comedor|dining/.test(name)) return 'comedor';
        if (/sala|living/.test(name)) return 'sala';
        if (/pasillo|hall/.test(name)) return 'pasillo';
        if (/estudio|oficina/.test(name)) return 'estudio';
        if (/lavand/.test(name)) return 'lavanderia';
        if (/balc/.test(name)) return 'balcon';
        return 'otro';
    },

    clamp01(v) {
        const n = Number(v);
        if (!Number.isFinite(n)) return 0;
        return Math.max(0, Math.min(1, n));
    },

    renderLegend() {
        const host = this.el.spaceLegend;
        if (!host) return;
        const kinds = new Set(['habitacion', 'bano', 'sala', 'cocina', 'comedor', 'pasillo', 'estudio', 'otro']);
        (this.aiSpaces || []).forEach((s) => kinds.add(this.normalizeSpaceKind(s)));
        host.innerHTML = '';
        Array.from(kinds).forEach((k) => {
            const style = SPACE_STYLES[k] || SPACE_STYLES.otro;
            const row = document.createElement('div');
            row.className = 'si-legend-item';
            row.innerHTML = `<span class="si-legend-icon" style="background:${style.color}">${style.icon}</span><span>${style.label}</span>`;
            host.appendChild(row);
        });
    },

    async onFileSelected(e) {
        const file = e.target.files && e.target.files[0];
        if (!file) return;

        const isImage = /^image\//.test(file.type);
        if (!isImage) {
            alert('Selecciona una imagen valida (PNG/JPG/WEBP).');
            return;
        }

        try {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                this.image = img;
                this.imageName = file.name;
                this.points = [];
                this.aiSuggestedPoints = [];
                this.aiZoneWaypoints = [];
                this.aiZones = [];
                this.aiSectors = [];
                this.aiSpaces = [];
                this.aiObjects = [];
                this.aiObstacles = [];
                this.nav.ready = false;
                this.el.btnApplyAi.disabled = true;
                this.el.report.textContent = 'Imagen cargada. Ya puedes analizarla con IA o crear waypoints manuales.';
                this.el.tip.textContent = `Mapa cargado: ${file.name}`;
                this.buildNavigableMask();
                this.draw();
                this.renderMeta();
                URL.revokeObjectURL(url);
            };
            img.onerror = () => {
                alert('No se pudo leer la imagen. Intenta con otro archivo.');
                URL.revokeObjectURL(url);
            };
            img.src = url;
        } catch (err) {
            alert(`Error al cargar imagen: ${err.message || err}`);
        }
    },

    getImageRect() {
        const cw = this.canvas.clientWidth;
        const ch = this.canvas.clientHeight;
        if (!this.image) return { x: 0, y: 0, w: cw, h: ch };
        const iw = this.image.width;
        const ih = this.image.height;
        const scale = Math.min(cw / iw, ch / ih);
        const w = iw * scale;
        const h = ih * scale;
        const x = (cw - w) / 2;
        const y = (ch - h) / 2;
        return { x, y, w, h };
    },

    buildNavigableMask() {
        if (!this.image) {
            this.nav.ready = false;
            return;
        }
        const frame = this.getImageRect();
        const target = 180;
        const scale = Math.max(frame.w, frame.h) / target;
        const gw = Math.max(48, Math.round(frame.w / Math.max(1, scale)));
        const gh = Math.max(48, Math.round(frame.h / Math.max(1, scale)));

        const off = document.createElement('canvas');
        off.width = gw;
        off.height = gh;
        const octx = off.getContext('2d', { willReadFrequently: true });
        octx.drawImage(this.image, 0, 0, gw, gh);
        const img = octx.getImageData(0, 0, gw, gh).data;

        const blocked = new Uint8Array(gw * gh);
        const lum = new Float32Array(gw * gh);
        for (let i = 0, p = 0; i < lum.length; i++, p += 4) {
            const r = img[p];
            const g = img[p + 1];
            const b = img[p + 2];
            lum[i] = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        }

        const doc = this._detectDocumentBounds(lum, gw, gh);

        for (let y = 0; y < gh; y++) {
            for (let x = 0; x < gw; x++) {
                const i = y * gw + x;
                const l = lum[i];
                const right = x + 1 < gw ? lum[i + 1] : l;
                const down = y + 1 < gh ? lum[i + gw] : l;
                const edge = Math.abs(l - right) + Math.abs(l - down);
                const outDoc = x < doc.minX || x > doc.maxX || y < doc.minY || y > doc.maxY;
                if (outDoc || l < 170 || edge > 42) blocked[i] = 1;
            }
        }

        // Bordes siempre bloqueados para no salir del plano.
        for (let x = 0; x < gw; x++) {
            blocked[x] = 1;
            blocked[(gh - 1) * gw + x] = 1;
        }
        for (let y = 0; y < gh; y++) {
            blocked[y * gw] = 1;
            blocked[y * gw + (gw - 1)] = 1;
        }

        const inflated = this._dilateBinary(blocked, gw, gh, 2);
        const clearance = this._computeClearance(inflated, gw, gh);
        const components = this._computeComponents(inflated, gw, gh);
        const roomBoxes = this._extractRoomBoxes(components.list, doc, gw, gh);

        this.nav = {
            ready: true,
            w: gw,
            h: gh,
            frame,
            doc,
            blocked: inflated,
            clearance,
            compId: components.compId,
            components: components.list,
            roomBoxes,
        };
    },

    _detectDocumentBounds(lum, w, h) {
        let minX = w;
        let minY = h;
        let maxX = 0;
        let maxY = 0;
        let cnt = 0;
        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                const i = y * w + x;
                if (lum[i] < 175) {
                    cnt++;
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }
        }

        if (cnt < (w * h * 0.02) || maxX <= minX || maxY <= minY) {
            return { minX: 0, minY: 0, maxX: w - 1, maxY: h - 1 };
        }

        const padX = Math.max(2, Math.floor((maxX - minX) * 0.06));
        const padY = Math.max(2, Math.floor((maxY - minY) * 0.06));
        minX = Math.max(0, minX - padX);
        minY = Math.max(0, minY - padY);
        maxX = Math.min(w - 1, maxX + padX);
        maxY = Math.min(h - 1, maxY + padY);

        const area = (maxX - minX + 1) * (maxY - minY + 1);
        if (area < w * h * 0.35) {
            return { minX: 0, minY: 0, maxX: w - 1, maxY: h - 1 };
        }
        return { minX, minY, maxX, maxY };
    },

    _extractRoomBoxes(components, doc, w, h) {
        const docArea = Math.max(1, (doc.maxX - doc.minX + 1) * (doc.maxY - doc.minY + 1));
        const boxes = [];
        for (const c of components) {
            if (!c || !Number.isFinite(c.area)) continue;
            if (c.area < docArea * 0.006 || c.area > docArea * 0.24) continue;
            const bw = c.maxX - c.minX + 1;
            const bh = c.maxY - c.minY + 1;
            if (bw < 6 || bh < 6) continue;
            const ratio = bw / Math.max(1, bh);
            if (ratio > 6.0 || ratio < 0.17) continue;
            boxes.push({
                x: c.minX / Math.max(1, w),
                y: c.minY / Math.max(1, h),
                w: bw / Math.max(1, w),
                h: bh / Math.max(1, h),
                _area: c.area,
            });
        }
        boxes.sort((a, b) => b._area - a._area);
        return boxes.slice(0, 20);
    },

    _computeComponents(blocked, w, h) {
        const n = w * h;
        const compId = new Int32Array(n);
        compId.fill(-1);
        const list = [];
        let cid = 0;
        const stack = new Int32Array(n);
        const dirs = [1, -1, w, -w, w + 1, w - 1, -w + 1, -w - 1];

        for (let i = 0; i < n; i++) {
            if (blocked[i] || compId[i] !== -1) continue;
            let top = 0;
            stack[top++] = i;
            compId[i] = cid;
            let area = 0;
            let minX = w, minY = h, maxX = 0, maxY = 0;
            while (top > 0) {
                const cur = stack[--top];
                area++;
                const x = cur % w;
                const y = Math.floor(cur / w);
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x > maxX) maxX = x;
                if (y > maxY) maxY = y;
                for (const d of dirs) {
                    const ni = cur + d;
                    if (ni < 0 || ni >= n) continue;
                    const nx = ni % w;
                    const ny = Math.floor(ni / w);
                    if (Math.abs(nx - x) > 1 || Math.abs(ny - y) > 1) continue;
                    if (blocked[ni] || compId[ni] !== -1) continue;
                    compId[ni] = cid;
                    stack[top++] = ni;
                }
            }
            list.push({ id: cid, area, minX, minY, maxX, maxY });
            cid++;
        }
        list.sort((a, b) => b.area - a.area);
        return { compId, list };
    },

    _dilateBinary(src, w, h, radius = 1) {
        let cur = new Uint8Array(src);
        for (let r = 0; r < radius; r++) {
            const next = new Uint8Array(cur);
            for (let y = 1; y < h - 1; y++) {
                for (let x = 1; x < w - 1; x++) {
                    const i = y * w + x;
                    if (cur[i]) {
                        next[i - 1] = 1;
                        next[i + 1] = 1;
                        next[i - w] = 1;
                        next[i + w] = 1;
                        next[i - w - 1] = 1;
                        next[i - w + 1] = 1;
                        next[i + w - 1] = 1;
                        next[i + w + 1] = 1;
                    }
                }
            }
            cur = next;
        }
        return cur;
    },

    _computeClearance(blocked, w, h) {
        const n = w * h;
        const dist = new Int16Array(n);
        dist.fill(32767);
        const qx = new Int32Array(n);
        const qy = new Int32Array(n);
        let qh = 0;
        let qt = 0;

        for (let y = 0; y < h; y++) {
            for (let x = 0; x < w; x++) {
                const i = y * w + x;
                if (blocked[i]) {
                    dist[i] = 0;
                    qx[qt] = x;
                    qy[qt] = y;
                    qt++;
                }
            }
        }

        const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];
        while (qh < qt) {
            const x = qx[qh];
            const y = qy[qh];
            qh++;
            const i = y * w + x;
            const base = dist[i];
            for (const [dx, dy] of dirs) {
                const nx = x + dx;
                const ny = y + dy;
                if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
                const ni = ny * w + nx;
                if (dist[ni] > base + 1) {
                    dist[ni] = base + 1;
                    qx[qt] = nx;
                    qy[qt] = ny;
                    qt++;
                }
            }
        }
        return dist;
    },

    _toGrid(px, py) {
        if (!this.nav.ready) return null;
        const f = this.getImageRect();
        this.nav.frame = f;
        const gx = Math.round(((px - f.x) / Math.max(1e-6, f.w)) * (this.nav.w - 1));
        const gy = Math.round(((py - f.y) / Math.max(1e-6, f.h)) * (this.nav.h - 1));
        return {
            x: Math.max(0, Math.min(this.nav.w - 1, gx)),
            y: Math.max(0, Math.min(this.nav.h - 1, gy)),
        };
    },

    _toCanvas(gx, gy) {
        const f = this.getImageRect();
        this.nav.frame = f;
        return {
            x: f.x + (gx / Math.max(1, this.nav.w - 1)) * f.w,
            y: f.y + (gy / Math.max(1, this.nav.h - 1)) * f.h,
        };
    },

    _isFreeCell(gx, gy) {
        if (!this.nav.ready) return true;
        const i = gy * this.nav.w + gx;
        return !this.nav.blocked[i];
    },

    _snapPointToCorridor(px, py) {
        if (!this.nav.ready) return { x: px, y: py };
        const g = this._toGrid(px, py);
        if (!g) return { x: px, y: py };
        let best = null;
        let bestScore = -1;
        const r = 7;
        for (let y = Math.max(0, g.y - r); y <= Math.min(this.nav.h - 1, g.y + r); y++) {
            for (let x = Math.max(0, g.x - r); x <= Math.min(this.nav.w - 1, g.x + r); x++) {
                if (!this._isFreeCell(x, y)) continue;
                const di = y * this.nav.w + x;
                const clearance = this.nav.clearance ? this.nav.clearance[di] : 0;
                const d = Math.hypot(x - g.x, y - g.y);
                const score = clearance * 2.0 - d;
                if (score > bestScore) {
                    bestScore = score;
                    best = { x, y };
                }
            }
        }
        if (!best) return { x: px, y: py };
        return this._toCanvas(best.x, best.y);
    },

    _lineIsFree(a, b) {
        if (!this.nav.ready) return true;
        const ga = this._toGrid(a.x, a.y);
        const gb = this._toGrid(b.x, b.y);
        if (!ga || !gb) return true;
        const steps = Math.max(8, Math.ceil(Math.hypot(gb.x - ga.x, gb.y - ga.y) * 2.2));
        for (let i = 0; i <= steps; i++) {
            const t = i / steps;
            const x = Math.round(ga.x + (gb.x - ga.x) * t);
            const y = Math.round(ga.y + (gb.y - ga.y) * t);
            if (!this._isFreeCell(x, y)) return false;
        }
        return true;
    },

    _astarPath(a, b) {
        if (!this.nav.ready) return [];
        const start = this._toGrid(a.x, a.y);
        const goal = this._toGrid(b.x, b.y);
        if (!start || !goal) return [];

        const w = this.nav.w;
        const h = this.nav.h;
        const n = w * h;
        const gScore = new Float32Array(n);
        gScore.fill(Number.POSITIVE_INFINITY);
        const parent = new Int32Array(n);
        parent.fill(-1);
        const visited = new Uint8Array(n);
        const heap = [];

        const sIdx = start.y * w + start.x;
        const gIdx = goal.y * w + goal.x;
        if (!this._isFreeCell(start.x, start.y) || !this._isFreeCell(goal.x, goal.y)) return [];

        gScore[sIdx] = 0;
        heap.push([0, sIdx]);
        const dirs = [
            [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1],
            [1, 1, 1.4142], [1, -1, 1.4142], [-1, 1, 1.4142], [-1, -1, 1.4142],
        ];

        const hCost = (idx) => {
            const x = idx % w;
            const y = Math.floor(idx / w);
            const gx = goal.x;
            const gy = goal.y;
            return Math.hypot(gx - x, gy - y);
        };

        while (heap.length) {
            heap.sort((u, v) => u[0] - v[0]);
            const [, cur] = heap.shift();
            if (visited[cur]) continue;
            visited[cur] = 1;
            if (cur === gIdx) break;
            const cx = cur % w;
            const cy = Math.floor(cur / w);

            for (const [dx, dy, step] of dirs) {
                const nx = cx + dx;
                const ny = cy + dy;
                if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
                if (!this._isFreeCell(nx, ny)) continue;
                const ni = ny * w + nx;
                const clear = this.nav.clearance ? this.nav.clearance[ni] : 0;
                const penalty = clear < 2 ? 1.3 : (clear < 4 ? 0.6 : 0.0);
                const ng = gScore[cur] + step + penalty;
                if (ng < gScore[ni]) {
                    gScore[ni] = ng;
                    parent[ni] = cur;
                    heap.push([ng + hCost(ni), ni]);
                }
            }
        }

        if (parent[gIdx] < 0) return [];
        const pathIdx = [];
        let cur = gIdx;
        while (cur >= 0) {
            pathIdx.push(cur);
            if (cur === sIdx) break;
            cur = parent[cur];
        }
        pathIdx.reverse();

        const simplified = [];
        for (let i = 0; i < pathIdx.length; i++) {
            if (i === 0 || i === pathIdx.length - 1 || i % 5 === 0) {
                const idx = pathIdx[i];
                const gx = idx % w;
                const gy = Math.floor(idx / w);
                simplified.push(this._toCanvas(gx, gy));
            }
        }
        return simplified;
    },

    validateRouteGeometry(pointsIn) {
        const pts = (pointsIn || []).map((p) => ({ x: p.x, y: p.y }));
        if (pts.length < 2) return pts;
        if (!this.nav.ready) this.buildNavigableMask();
        if (!this.nav.ready) return pts;

        const snapped = pts.map((p) => this._snapPointToCorridor(p.x, p.y));
        const repaired = [snapped[0]];
        for (let i = 1; i < snapped.length; i++) {
            const a = repaired[repaired.length - 1];
            const b = snapped[i];
            if (this._lineIsFree(a, b)) {
                repaired.push(b);
                continue;
            }
            const path = this._astarPath(a, b);
            if (path.length >= 2) {
                for (let k = 1; k < path.length; k++) repaired.push(path[k]);
            } else {
                repaired.push(b);
            }
        }
        return repaired;
    },

    _refineRectToMap(rect) {
        if (!this.nav.ready) return rect;
        const x = Number(rect.x) || 0;
        const y = Number(rect.y) || 0;
        const w = Number(rect.w) || 0;
        const h = Number(rect.h) || 0;
        const f = this.nav.frame;
        const cx = f.x + (x + w * 0.5) * f.w;
        const cy = f.y + (y + h * 0.5) * f.h;
        const c = this._snapPointToCorridor(cx, cy);
        const g = this._toGrid(c.x, c.y);
        if (!g || !this.nav.compId) return rect;
        const id = this.nav.compId[g.y * this.nav.w + g.x];
        if (id < 0) return rect;
        const comp = (this.nav.components || []).find((q) => q.id === id);
        if (!comp) return rect;

        const mx = 1;
        const minX = Math.max(0, comp.minX + mx);
        const minY = Math.max(0, comp.minY + mx);
        const maxX = Math.min(this.nav.w - 1, comp.maxX - mx);
        const maxY = Math.min(this.nav.h - 1, comp.maxY - mx);
        const p0 = this._toCanvas(minX, minY);
        const p1 = this._toCanvas(maxX, maxY);
        const nx = (Math.min(p0.x, p1.x) - f.x) / Math.max(1e-6, f.w);
        const ny = (Math.min(p0.y, p1.y) - f.y) / Math.max(1e-6, f.h);
        const nw = Math.abs(p1.x - p0.x) / Math.max(1e-6, f.w);
        const nh = Math.abs(p1.y - p0.y) / Math.max(1e-6, f.h);

        let out = {
            ...rect,
            x: Math.max(0, Math.min(1, nx)),
            y: Math.max(0, Math.min(1, ny)),
            w: Math.max(0.03, Math.min(1, nw)),
            h: Math.max(0.03, Math.min(1, nh)),
        };
        if (this.nav.doc) out = this._clipRectToDoc(out);
        return out;
    },

    _clipRectToDoc(rect) {
        if (!this.nav.ready || !this.nav.doc) return rect;
        const d = this.nav.doc;
        const dx = d.minX / Math.max(1, this.nav.w);
        const dy = d.minY / Math.max(1, this.nav.h);
        const dw = (d.maxX - d.minX + 1) / Math.max(1, this.nav.w);
        const dh = (d.maxY - d.minY + 1) / Math.max(1, this.nav.h);
        const x1 = Math.max(dx, rect.x);
        const y1 = Math.max(dy, rect.y);
        const x2 = Math.min(dx + dw, rect.x + rect.w);
        const y2 = Math.min(dy + dh, rect.y + rect.h);
        if (x2 <= x1 || y2 <= y1) return rect;
        return { ...rect, x: x1, y: y1, w: Math.max(0.02, x2 - x1), h: Math.max(0.02, y2 - y1) };
    },

    _fitSpaceRect(rect, kind = 'otro') {
        if (!this.nav.ready) return rect;
        const f = this.getImageRect();
        const cxPx = f.x + (this.clamp01(Number(rect.x) + Number(rect.w) * 0.5)) * f.w;
        const cyPx = f.y + (this.clamp01(Number(rect.y) + Number(rect.h) * 0.5)) * f.h;
        const seedPx = this._snapPointToCorridor(cxPx, cyPx);
        const seed = this._toGrid(seedPx.x, seedPx.y);
        if (!seed) return rect;

        const w = this.nav.w;
        const h = this.nav.h;
        const blocked = this.nav.blocked;
        const clearance = this.nav.clearance;
        const seedIdx = seed.y * w + seed.x;
        if (blocked[seedIdx]) return this._refineRectToMap(rect);

        // Cierra puertas angostas para no mezclar habitaciones contiguas.
        const minClr = (kind === 'pasillo') ? 1 : 2;

        const gx0 = Math.round((this.clamp01(Number(rect.x)) * (w - 1)));
        const gy0 = Math.round((this.clamp01(Number(rect.y)) * (h - 1)));
        const gw0 = Math.max(4, Math.round((this.clamp01(Number(rect.w)) * (w - 1))));
        const gh0 = Math.max(4, Math.round((this.clamp01(Number(rect.h)) * (h - 1))));

        const rx = Math.max(18, Math.floor(gw0 * 1.4));
        const ry = Math.max(18, Math.floor(gh0 * 1.4));
        const minXW = Math.max(0, seed.x - rx);
        const maxXW = Math.min(w - 1, seed.x + rx);
        const minYW = Math.max(0, seed.y - ry);
        const maxYW = Math.min(h - 1, seed.y + ry);

        const qx = new Int16Array(w * h);
        const qy = new Int16Array(w * h);
        const seen = new Uint8Array(w * h);
        let qh = 0;
        let qt = 0;
        qx[qt] = seed.x;
        qy[qt] = seed.y;
        qt++;
        seen[seedIdx] = 1;

        let minX = seed.x;
        let minY = seed.y;
        let maxX = seed.x;
        let maxY = seed.y;
        let area = 0;
        const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];

        while (qh < qt) {
            const x = qx[qh];
            const y = qy[qh];
            qh++;
            const i = y * w + x;
            if (blocked[i]) continue;
            if ((clearance?.[i] || 0) < minClr) continue;
            if (x < minXW || x > maxXW || y < minYW || y > maxYW) continue;
            area++;
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x > maxX) maxX = x;
            if (y > maxY) maxY = y;

            for (const [dx, dy] of dirs) {
                const nx = x + dx;
                const ny = y + dy;
                if (nx < minXW || nx > maxXW || ny < minYW || ny > maxYW) continue;
                const ni = ny * w + nx;
                if (seen[ni]) continue;
                seen[ni] = 1;
                qx[qt] = nx;
                qy[qt] = ny;
                qt++;
            }
        }

        if (area < 30) return this._refineRectToMap(rect);

        const p0 = this._toCanvas(minX, minY);
        const p1 = this._toCanvas(maxX, maxY);
        const nx = (Math.min(p0.x, p1.x) - f.x) / Math.max(1e-6, f.w);
        const ny = (Math.min(p0.y, p1.y) - f.y) / Math.max(1e-6, f.h);
        const nw = Math.abs(p1.x - p0.x) / Math.max(1e-6, f.w);
        const nh = Math.abs(p1.y - p0.y) / Math.max(1e-6, f.h);
        return {
            ...rect,
            x: Math.max(0, Math.min(1, nx)),
            y: Math.max(0, Math.min(1, ny)),
            w: Math.max(0.03, Math.min(1, nw)),
            h: Math.max(0.03, Math.min(1, nh)),
        };
    },

    _rectIoU(a, b) {
        const ax2 = a.x + a.w;
        const ay2 = a.y + a.h;
        const bx2 = b.x + b.w;
        const by2 = b.y + b.h;
        const ix = Math.max(0, Math.min(ax2, bx2) - Math.max(a.x, b.x));
        const iy = Math.max(0, Math.min(ay2, by2) - Math.max(a.y, b.y));
        const inter = ix * iy;
        if (inter <= 0) return 0;
        const union = a.w * a.h + b.w * b.h - inter;
        return union > 0 ? inter / union : 0;
    },

    _dedupeRects(rects) {
        const out = [];
        for (const r of rects) {
            let keep = true;
            for (const e of out) {
                if (this._rectIoU(r, e) > 0.62) {
                    keep = false;
                    break;
                }
            }
            if (keep) out.push(r);
        }
        return out;
    },

    _matchSpacesToRooms(spaces) {
        const rooms = (this.nav.roomBoxes || []).map((r) => ({ ...r, _used: false }));
        if (!rooms.length) return spaces;
        const matched = [];

        for (const s of spaces) {
            let best = null;
            let bestScore = -1;
            const sx = s.x + s.w * 0.5;
            const sy = s.y + s.h * 0.5;
            for (const r of rooms) {
                if (r._used) continue;
                const iou = this._rectIoU(s, r);
                const rx = r.x + r.w * 0.5;
                const ry = r.y + r.h * 0.5;
                const d = Math.hypot(rx - sx, ry - sy);
                const score = iou * 2.2 - d;
                if (score > bestScore) {
                    bestScore = score;
                    best = r;
                }
            }
            if (best) {
                best._used = true;
                matched.push({ ...s, x: best.x, y: best.y, w: best.w, h: best.h });
            } else {
                matched.push(s);
            }
        }

        return matched;
    },

    refineSpatialOverlays() {
        if (!this.nav.ready) this.buildNavigableMask();
        if (!this.nav.ready) return;
        if (Array.isArray(this.aiSpaces) && this.aiSpaces.length) {
            let refined = this.aiSpaces.map((s) => {
                const kind = this.normalizeSpaceKind(s);
                const r = this._fitSpaceRect(s, kind);
                return { ...s, ...r, kind };
            });
            refined = this._matchSpacesToRooms(refined);
            this.aiSpaces = this._dedupeRects(refined);
        } else if (Array.isArray(this.nav.roomBoxes) && this.nav.roomBoxes.length) {
            this.aiSpaces = this.nav.roomBoxes.slice(0, 12).map((r, i) => ({
                name: `Espacio ${i + 1}`,
                kind: 'otro',
                x: r.x,
                y: r.y,
                w: r.w,
                h: r.h,
                confidence: 0.58,
            }));
        }
        if (Array.isArray(this.aiZones)) {
            this.aiZones = this._dedupeRects(this.aiZones.map((z) => ({ ...z, ...this._fitSpaceRect(z, 'otro') })));
        }
        if (Array.isArray(this.aiSectors)) {
            this.aiSectors = this._dedupeRects(this.aiSectors.map((z) => ({ ...z, ...this._fitSpaceRect(z, 'otro') })));
        }
    },

    draw() {
        const ctx = this.ctx;
        if (!ctx) return;

        const w = this.canvas.clientWidth;
        const h = this.canvas.clientHeight;
        ctx.clearRect(0, 0, w, h);

        const bg = ctx.createLinearGradient(0, 0, 0, h);
        bg.addColorStop(0, '#060a12');
        bg.addColorStop(1, '#020409');
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, w, h);

        const frame = this.getImageRect();
        if (this.image) {
            ctx.drawImage(this.image, frame.x, frame.y, frame.w, frame.h);
            ctx.fillStyle = 'rgba(0,0,0,0.22)';
            ctx.fillRect(frame.x, frame.y, frame.w, frame.h);
            this.drawAiRelief(ctx, frame);
            if (this.isAnalyzing) this.drawAnalysisOverlay(ctx, frame);
        } else {
            ctx.fillStyle = '#8c919a';
            ctx.font = '600 16px Segoe UI';
            ctx.fillText('Sube una imagen de mapa para empezar', 20, 34);
        }

        if (this.points.length >= 2) {
            ctx.beginPath();
            ctx.strokeStyle = '#00c853';
            ctx.lineWidth = 2;
            this.points.forEach((p, i) => {
                if (i === 0) ctx.moveTo(p.x, p.y);
                else ctx.lineTo(p.x, p.y);
            });
            ctx.stroke();
        }

        this.points.forEach((p, i) => {
            const isOrigin = i === 0;
            ctx.beginPath();
            ctx.fillStyle = isOrigin ? '#00c853' : '#5aa8ff';
            ctx.arc(p.x, p.y, isOrigin ? 6.5 : 5.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = '#e8eaed';
            ctx.font = '700 11px Segoe UI';
            ctx.fillText(String(i + 1), p.x + 8, p.y - 8);
        });
    },

    drawAiRelief(ctx, frame) {
        const selectedRisk = String(this.el.zoneType?.value || 'all').toLowerCase();
        const viewMode = String(this.el.zoneView?.value || 'zones').toLowerCase();
        const sectorsAll = viewMode === 'sectors'
            ? (Array.isArray(this.aiSectors) && this.aiSectors.length ? this.aiSectors : this.aiZones)
            : this.aiZones;
        const zones = (sectorsAll || []).filter((z) => selectedRisk === 'all' || String(z.risk || '').toLowerCase() === selectedRisk);
        const spaces = Array.isArray(this.aiSpaces) ? this.aiSpaces : [];
        const obstacles = Array.isArray(this.aiObstacles) ? this.aiObstacles : [];
        const objects = Array.isArray(this.aiObjects) ? this.aiObjects : [];
        if (!zones.length && !spaces.length && !obstacles.length && !objects.length) return;

        const riskColor = {
            low: 'rgba(0, 200, 83, 0.18)',
            medium: 'rgba(255, 171, 0, 0.22)',
            high: 'rgba(217, 48, 37, 0.24)',
        };
        const riskStroke = {
            low: 'rgba(0, 200, 83, 0.9)',
            medium: 'rgba(255, 171, 0, 0.92)',
            high: 'rgba(255, 82, 82, 0.95)',
        };

        for (const z of zones) {
            const x = frame.x + Math.max(0, Math.min(1, Number(z.x) || 0)) * frame.w;
            const y = frame.y + Math.max(0, Math.min(1, Number(z.y) || 0)) * frame.h;
            const w = Math.max(6, Math.max(0, Math.min(1, Number(z.w) || 0)) * frame.w);
            const h = Math.max(6, Math.max(0, Math.min(1, Number(z.h) || 0)) * frame.h);
            const risk = String(z.risk || 'medium').toLowerCase();
            const fill = riskColor[risk] || riskColor.medium;
            const stroke = riskStroke[risk] || riskStroke.medium;

            ctx.fillStyle = fill;
            ctx.fillRect(x, y, w, h);
            ctx.strokeStyle = stroke;
            ctx.lineWidth = 1.5;
            ctx.strokeRect(x, y, w, h);

            const name = String(z.name || 'Zona').slice(0, 22);
            if (name) {
                ctx.fillStyle = stroke;
                ctx.font = '700 11px Segoe UI';
                ctx.fillText(name, x + 4, Math.max(12, y - 4));
            }
        }

        for (const s of spaces) {
            const x = frame.x + Math.max(0, Math.min(1, Number(s.x) || 0)) * frame.w;
            const y = frame.y + Math.max(0, Math.min(1, Number(s.y) || 0)) * frame.h;
            const w = Math.max(8, Math.max(0, Math.min(1, Number(s.w) || 0)) * frame.w);
            const h = Math.max(8, Math.max(0, Math.min(1, Number(s.h) || 0)) * frame.h);
            const k = this.normalizeSpaceKind(s);
            const style = SPACE_STYLES[k] || SPACE_STYLES.otro;
            const c = style.color;
            const fill = style.fill;
            ctx.fillStyle = fill;
            ctx.fillRect(x, y, w, h);
            ctx.strokeStyle = c;
            ctx.lineWidth = 2.1;
            ctx.strokeRect(x, y, w, h);
            const txt = `${style.icon} ${String(s.name || 'Espacio')} · ${style.label}`;
            ctx.fillStyle = 'rgba(5, 7, 11, 0.85)';
            const tw = Math.min(220, Math.ceil(ctx.measureText(txt).width) + 10);
            ctx.fillRect(x, Math.max(frame.y, y - 18), tw, 16);
            ctx.fillStyle = c;
            ctx.font = '700 10px Segoe UI';
            ctx.fillText(txt.slice(0, 34), x + 4, Math.max(frame.y + 12, y - 6));
        }

        for (const o of obstacles) {
            const x = frame.x + Math.max(0, Math.min(1, Number(o.x) || 0)) * frame.w;
            const y = frame.y + Math.max(0, Math.min(1, Number(o.y) || 0)) * frame.h;
            const w = Math.max(5, Math.max(0, Math.min(1, Number(o.w) || 0)) * frame.w);
            const h = Math.max(5, Math.max(0, Math.min(1, Number(o.h) || 0)) * frame.h);
            ctx.strokeStyle = 'rgba(255, 82, 82, 0.95)';
            ctx.setLineDash([4, 3]);
            ctx.lineWidth = 1.3;
            ctx.strokeRect(x, y, w, h);
            ctx.setLineDash([]);
        }

        for (const o of objects) {
            const x = frame.x + Math.max(0, Math.min(1, Number(o.x) || 0)) * frame.w;
            const y = frame.y + Math.max(0, Math.min(1, Number(o.y) || 0)) * frame.h;
            const w = Math.max(4, Math.max(0, Math.min(1, Number(o.w) || 0)) * frame.w);
            const h = Math.max(4, Math.max(0, Math.min(1, Number(o.h) || 0)) * frame.h);
            ctx.fillStyle = 'rgba(255,255,255,0.85)';
            ctx.fillRect(x - 1, y - 1, w + 2, h + 2);
            ctx.strokeStyle = 'rgba(5,7,11,0.95)';
            ctx.lineWidth = 1;
            ctx.strokeRect(x, y, w, h);
            ctx.fillStyle = 'rgba(255,255,255,0.95)';
            ctx.font = '700 9px Segoe UI';
            ctx.fillText(String(o.label || 'obj').slice(0, 18), x + 2, y + 10);
        }
    },

    drawAnalysisOverlay(ctx, frame) {
        const t = (performance.now() - this.analysisStartedAt) / 1000;
        const sweep = ((t * 0.28) % 1) * frame.h;
        ctx.save();
        ctx.strokeStyle = 'rgba(62,255,160,0.95)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(frame.x, frame.y + sweep);
        ctx.lineTo(frame.x + frame.w, frame.y + sweep);
        ctx.stroke();

        const grd = ctx.createLinearGradient(0, frame.y + sweep - 26, 0, frame.y + sweep + 26);
        grd.addColorStop(0, 'rgba(62,255,160,0.00)');
        grd.addColorStop(0.5, 'rgba(62,255,160,0.16)');
        grd.addColorStop(1, 'rgba(62,255,160,0.00)');
        ctx.fillStyle = grd;
        ctx.fillRect(frame.x, frame.y + sweep - 28, frame.w, 56);

        const msg = 'Analizando imagen: segmentando espacios y detectando objetos...';
        const pw = Math.min(frame.w - 16, Math.ceil(ctx.measureText(msg).width) + 14);
        ctx.fillStyle = 'rgba(0,0,0,0.72)';
        ctx.fillRect(frame.x + 8, frame.y + 8, pw, 20);
        ctx.fillStyle = '#3effa0';
        ctx.font = '700 11px Segoe UI';
        ctx.fillText(msg, frame.x + 14, frame.y + 22);
        ctx.restore();
    },

    canvasCoords(evt) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: evt.clientX - rect.left,
            y: evt.clientY - rect.top,
        };
    },

    nearestWaypoint(x, y) {
        let best = -1;
        let bestD = 9999;
        this.points.forEach((p, i) => {
            const d = Math.hypot(p.x - x, p.y - y);
            if (d < bestD) {
                best = i;
                bestD = d;
            }
        });
        return { idx: best, dist: bestD };
    },

    onPointerDown(evt) {
        if (!this.image) return;
        const pos = this.canvasCoords(evt);
        const near = this.nearestWaypoint(pos.x, pos.y);
        if (near.idx >= 0 && near.dist < 14) this.dragIdx = near.idx;
    },

    onPointerMove(evt) {
        if (this.dragIdx < 0) return;
        const pos = this.canvasCoords(evt);
        const frame = this.getImageRect();
        this.points[this.dragIdx] = {
            x: Math.max(frame.x, Math.min(frame.x + frame.w, pos.x)),
            y: Math.max(frame.y, Math.min(frame.y + frame.h, pos.y)),
        };
        this.draw();
        this.renderMeta();
    },

    onCanvasClick(evt) {
        if (!this.image || this.dragIdx >= 0) return;
        const pos = this.canvasCoords(evt);
        const frame = this.getImageRect();
        const inside = pos.x >= frame.x && pos.x <= frame.x + frame.w
            && pos.y >= frame.y && pos.y <= frame.y + frame.h;
        if (!inside) return;

        const near = this.nearestWaypoint(pos.x, pos.y);
        if (evt.shiftKey && near.idx >= 0 && near.dist < 14) {
            this.points.splice(near.idx, 1);
        } else if (near.idx >= 0 && near.dist < 14) {
            return;
        } else {
            this.points.push({ x: pos.x, y: pos.y });
        }
        this.draw();
        this.renderMeta();
    },

    clearPoints() {
        this.points = [];
        this.draw();
        this.renderMeta();
    },

    async analyzeMapWithAI() {
        const file = this.el.fileInput.files && this.el.fileInput.files[0];
        if (!file) {
            alert('Primero sube una imagen de mapa.');
            return;
        }

        this.el.btnAnalyze.disabled = true;
        this.el.btnAnalyze.textContent = 'Analizando...';
        this.el.report.textContent = 'Analizando mapa con IA...';
        this.isAnalyzing = true;
        this.analysisStartedAt = performance.now();
        this.draw();

        try {
            const form = new FormData();
            form.append('map_image', file);
            form.append('zone_filter', String(this.el.zoneType?.value || 'all'));
            form.append('require_cloud', this.el.requireCloud?.checked ? '1' : '0');
            const res = await fetch(`${API}/api/map-ai/analyze`, {
                method: 'POST',
                body: form,
            });
            const data = await res.json();
            if (!res.ok || data.status !== 'ok') {
                const detail = data.detail ? ` | ${String(data.detail).slice(0, 220)}` : '';
                throw new Error((data.message || 'Error analizando el mapa') + detail);
            }

            const frame = this.getImageRect();
            this.aiSuggestedPoints = (data.suggested_waypoints || []).map((p) => ({
                x: frame.x + Math.max(0, Math.min(1, Number(p.nx) || 0)) * frame.w,
                y: frame.y + Math.max(0, Math.min(1, Number(p.ny) || 0)) * frame.h,
            }));
            this.aiZoneWaypoints = (data.zone_waypoints || []).map((p) => ({
                x: frame.x + Math.max(0, Math.min(1, Number(p.nx) || 0)) * frame.w,
                y: frame.y + Math.max(0, Math.min(1, Number(p.ny) || 0)) * frame.h,
            }));
            this.aiZones = Array.isArray(data.zones) ? data.zones : [];
            this.aiSectors = Array.isArray(data.sectors) ? data.sectors : [];
            this.aiSpaces = Array.isArray(data.spaces) ? data.spaces : [];
            this.aiObjects = Array.isArray(data.objects) ? data.objects : [];
            this.aiObstacles = Array.isArray(data.obstacles) ? data.obstacles : [];
            this.refineSpatialOverlays();
            this.renderLegend();

            this.el.btnApplyAi.disabled = this.aiSuggestedPoints.length < 2;
            const hintScale = Number(data.scale_hint_m_per_px);
            if (Number.isFinite(hintScale) && hintScale > 0) {
                this.el.scale.value = hintScale.toFixed(3);
            }

            this.el.report.textContent = [
                `Resumen del mapa: ${data.map_overview || 'Sin resumen general.'}`,
                `Analisis: ${data.analysis || 'Sin descripcion.'}`,
                `Waypoints sugeridos: ${this.aiSuggestedPoints.length}`,
                `Waypoints por zona: ${this.aiZoneWaypoints.length}`,
                `Zonas identificadas: ${this.aiZones.length}`,
                `Sectores detectados: ${this.aiSectors.length}`,
                `Espacios tipificados: ${this.aiSpaces.length}`,
                `Objetos detectados: ${this.aiObjects.length}`,
                `Obstaculos detectados: ${this.aiObstacles.length}`,
                `Confianza: ${Number(data.confidence || 0).toFixed(2)}`,
                data.fallback
                    ? `Modo: Analisis local (sin nube)`
                    : `Modo: IA nube (${data.provider || 'provider'} / ${data.model || 'modelo'})`,
                data.warning ? `Aviso: ${data.warning}` : '',
            ].filter(Boolean).join('\n');
            this.draw();
        } catch (err) {
            this.el.report.textContent = `Error IA: ${err.message || err}`;
            alert(`No se pudo analizar el mapa: ${err.message || err}`);
        } finally {
            this.isAnalyzing = false;
            this.el.btnAnalyze.disabled = false;
            this.el.btnAnalyze.textContent = 'Analizar con IA';
            this.draw();
        }
    },

    applyAiRoute() {
        if (!this.aiSuggestedPoints || this.aiSuggestedPoints.length < 2) {
            alert('No hay ruta IA utilizable.');
            return;
        }
        const raw = this.aiSuggestedPoints.map((p) => ({ x: p.x, y: p.y }));
        this.points = this.validateRouteGeometry(raw);
        this.draw();
        this.renderMeta();
    },

    // Waypoints automaticos deshabilitados: zonas solamente.

    renderMeta() {
        this.el.pointsMeta.textContent = `${this.points.length} waypoint${this.points.length === 1 ? '' : 's'}`;

        const world = this.toWorldPoints(false);
        this.el.lengthMeta.textContent = `${this.computeLength(world).toFixed(2)} m`;

        this.el.waypoints.innerHTML = '';
        if (this.points.length === 0) {
            this.el.waypoints.innerHTML = '<div class="si-empty">Aun no hay waypoints.</div>';
            return;
        }

        world.forEach((p, i) => {
            const row = document.createElement('div');
            row.className = 'si-waypoint-item';
            row.innerHTML = `<span class="num">${i + 1}</span><span>x=${p.x.toFixed(2)} y=${p.y.toFixed(2)}</span>`;
            this.el.waypoints.appendChild(row);
        });
    },

    toWorldPoints(strict = true) {
        if (strict && this.points.length < 2) {
            throw new Error('Necesitas al menos 2 waypoints para crear una ruta.');
        }
        if (this.points.length === 0) return [];

        const scale = Number(this.el.scale.value);
        if (!Number.isFinite(scale) || scale <= 0) {
            throw new Error('Escala invalida. Debe ser mayor a 0.');
        }

        const origin = this.points[0];
        return this.points.map((p) => ({
            x: (p.x - origin.x) * scale,
            y: (origin.y - p.y) * scale,
            ts: new Date().toISOString(),
        }));
    },

    computeLength(points) {
        let total = 0;
        for (let i = 1; i < points.length; i++) {
            total += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
        }
        return total;
    },

    buildRoutePayload() {
        if (this.points.length >= 2) {
            this.points = this.validateRouteGeometry(this.points);
            this.draw();
            this.renderMeta();
        }
        const points = this.toWorldPoints(true);
        return {
            points,
            labels: [],
            totalMeters: this.computeLength(points),
            savedAt: new Date().toISOString(),
            source: 'save_img_ai',
            imageName: this.imageName || '',
        };
    },

    saveRouteLocal() {
        const payload = this.buildRoutePayload();
        localStorage.setItem('daiver:lastRoute', JSON.stringify(payload));
        return payload;
    },

    saveAndOpenAutoroute() {
        try {
            this.saveRouteLocal();
            window.location.href = '/autoroute';
        } catch (err) {
            alert(`No se pudo guardar ruta: ${err.message || err}`);
        }
    },

    exportRouteJson() {
        try {
            const route = this.buildRoutePayload();
            const blob = new Blob([JSON.stringify(route, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            a.href = url;
            a.download = `daiver_route_${ts}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) {
            alert(`No se pudo exportar ruta: ${err.message || err}`);
        }
    },

    async saveAndStartMission() {
        try {
            const route = this.saveRouteLocal();
            const cycles = Math.max(1, parseInt(this.el.cycles.value, 10) || 1);
            const res = await this.api('/api/autoroute/start', 'POST', {
                points: route.points,
                cycles,
                translate_to_pose: !!this.el.chkTranslate.checked,
                smooth_mode: !!this.el.chkSmooth.checked,
                pause_on_person: true,
                strict_path_mode: true,
                ai_path_assist: true,
            });
            if (!res || res.status !== 'ok') {
                throw new Error((res && res.message) || 'No se pudo iniciar la mision');
            }
            window.location.href = '/autoroute';
        } catch (err) {
            alert(`No se pudo iniciar la mision: ${err.message || err}`);
        }
    },

    async api(path, method = 'GET', body = null) {
        try {
            const res = await fetch(`${API}${path}`, {
                method,
                headers: body ? { 'Content-Type': 'application/json' } : {},
                body: body ? JSON.stringify(body) : null,
            });
            return await res.json();
        } catch (err) {
            return { status: 'error', message: String(err) };
        }
    },
};

window.addEventListener('DOMContentLoaded', () => SaveImg.init());
