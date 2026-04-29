/* ========================================
   Daiver Control CUN — Main Application
   Conecta al backend Flask via SocketIO
   ======================================== */

const API_BASE = window.location.origin;

const App = {
    socket: null,
    state: {
        connected: false,
        robotIP: '',
        battery: 0,
        speed: 0,
        mode: 'Standby',
        routine_running: false,
        routine_name: null
    },

    init() {
        this.setupNavigation();
        this.setupSocketIO();
        this.loadConfig();
    },

    // SocketIO connection to Flask backend
    setupSocketIO() {
        this.socket = io(API_BASE);

        this.socket.on('connect', () => {
            this.addLog('success', 'Conectado al servidor Flask');
            const el = document.getElementById('flask-status');
            if (el) el.textContent = 'Conectado';
        });

        this.socket.on('disconnect', () => {
            this.addLog('warning', 'Desconectado del servidor Flask');
            const el = document.getElementById('flask-status');
            if (el) el.textContent = 'Desconectado';
        });

        // Recibir logs del backend
        this.socket.on('log', (data) => {
            this.addLog(data.type, data.message);
        });

        // Recibir actualizaciones de estado
        this.socket.on('state_update', (data) => {
            this.state = { ...this.state, ...data };
            this.updateUI();
        });
    },

    // Load initial config from API
    async loadConfig() {
        try {
            const res = await fetch(`${API_BASE}/api/config`);
            const config = await res.json();
            const ipInput = document.getElementById('ip-input');
            if (ipInput) ipInput.value = config.robot_ip;
            this.state.robotIP = config.robot_ip;

            const robotIP = document.getElementById('robot-ip');
            if (robotIP) robotIP.textContent = config.robot_ip;
        } catch {
            this.addLog('warning', 'No se pudo cargar la configuracion del servidor');
        }

        // Also fetch current status
        try {
            const res = await fetch(`${API_BASE}/api/status`);
            const status = await res.json();
            this.state = { ...this.state, ...status };
            this.updateUI();
        } catch {
            // Server might not be ready yet
        }
    },

    // Navigation between sections
    setupNavigation() {
        const navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                navLinks.forEach(l => l.classList.remove('active'));
                e.target.classList.add('active');
            });
        });
    },

    // Update all UI elements based on state
    updateUI() {
        // Connection status indicator
        const indicator = document.getElementById('connection-status');
        if (indicator) {
            indicator.className = 'status-indicator';
            if (this.state.connected) {
                indicator.classList.add('connected');
                indicator.textContent = 'Conectado';
            } else {
                indicator.classList.add('disconnected');
                indicator.textContent = 'Desconectado';
            }
        }

        // WebRTC state
        const webrtcState = document.getElementById('webrtc-state');
        if (webrtcState) {
            webrtcState.textContent = this.state.connected ? 'Activa' : 'Sin conexion';
        }

        // Robot IP
        const robotIP = document.getElementById('robot-ip');
        if (robotIP) robotIP.textContent = this.state.ip || this.state.robotIP || '--';

        // Telemetry
        const battery = document.getElementById('battery-level');
        if (battery) battery.textContent = this.state.battery + '%';

        const speed = document.getElementById('speed');
        if (speed) speed.textContent = (this.state.speed || 0).toFixed(2) + ' m/s';

        const mode = document.getElementById('robot-mode');
        if (mode) mode.textContent = this.state.mode || '--';

        // Routine status
        const routineStatus = document.getElementById('routine-status');
        if (routineStatus) {
            routineStatus.textContent = this.state.routine_running
                ? this.state.routine_name || 'En ejecucion'
                : 'Ninguna';
        }

        // Enable/disable buttons
        this.toggleControls(this.state.connected);
    },

    // Enable/disable controls based on connection
    toggleControls(enabled) {
        const btnConnect = document.getElementById('btn-connect');
        const btnDisconnect = document.getElementById('btn-disconnect');

        if (btnConnect) btnConnect.disabled = enabled;
        if (btnDisconnect) btnDisconnect.disabled = !enabled;

        document.querySelectorAll('.dpad-btn, [data-action], [data-routine], #btn-rotate-left, #btn-rotate-right').forEach(btn => {
            btn.disabled = !enabled;
        });
    },

    // API helper
    async apiCall(endpoint, method = 'POST', body = null) {
        try {
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' }
            };
            if (body) options.body = JSON.stringify(body);

            const res = await fetch(`${API_BASE}${endpoint}`, options);
            const data = await res.json();

            if (!res.ok) {
                this.addLog('error', data.message || 'Error en la peticion');
            }
            return data;
        } catch (err) {
            this.addLog('error', `Error de red: ${err.message}`);
            return null;
        }
    },

    // Logging system
    addLog(type, message) {
        const container = document.getElementById('log-container');
        if (!container) return;

        const timestamp = new Date().toLocaleTimeString('es-CO');
        const entry = document.createElement('div');
        entry.className = `log-entry log-${type}`;
        entry.textContent = `[${timestamp}] [${type.toUpperCase()}] ${message}`;

        container.appendChild(entry);
        container.scrollTop = container.scrollHeight;

        // Keep max 200 entries
        while (container.children.length > 200) {
            container.removeChild(container.firstChild);
        }
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
