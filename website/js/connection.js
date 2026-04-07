/* ========================================
   Connection Management via Flask API
   ======================================== */

const Connection = {
    init() {
        document.getElementById('btn-connect')?.addEventListener('click', () => this.connect());
        document.getElementById('btn-disconnect')?.addEventListener('click', () => this.disconnect());
        document.getElementById('btn-emergency')?.addEventListener('click', () => this.emergencyStop());
        document.getElementById('btn-clear-logs')?.addEventListener('click', () => this.clearLogs());
        document.getElementById('btn-stop-routine')?.addEventListener('click', () => this.stopRoutine());

        // Actions
        document.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', () => this.executeAction(btn.dataset.action));
        });

        // Routines
        document.querySelectorAll('[data-routine]').forEach(btn => {
            btn.addEventListener('click', () => this.executeRoutine(btn.dataset.routine));
        });
    },

    async connect() {
        const ipInput = document.getElementById('ip-input');
        const ip = ipInput ? ipInput.value.trim() : '';

        if (!ip) {
            App.addLog('error', 'Ingrese la IP del robot');
            return;
        }

        App.addLog('info', `Conectando a ${ip}...`);

        // Update status to connecting
        const indicator = document.getElementById('connection-status');
        if (indicator) {
            indicator.className = 'status-indicator connecting';
            indicator.textContent = 'Conectando...';
        }

        const result = await App.apiCall('/api/connect', 'POST', { ip });

        if (!result || result.status !== 'ok') {
            // Revert to disconnected if failed
            if (indicator) {
                indicator.className = 'status-indicator disconnected';
                indicator.textContent = 'Desconectado';
            }
        }
    },

    async disconnect() {
        App.addLog('info', 'Desconectando...');
        await App.apiCall('/api/disconnect', 'POST');
    },

    async emergencyStop() {
        App.addLog('warning', 'PARADA DE EMERGENCIA');
        await App.apiCall('/api/emergency', 'POST');
    },

    async executeAction(action) {
        const actionNames = {
            stand: 'De Pie', sit: 'Sentarse', rise: 'Levantarse',
            recovery: 'Recuperarse', hello: 'Saludar', stretch: 'Estirarse',
            dance1: 'Baile 1', dance2: 'Baile 2', wiggle: 'Meneo',
            scrape: 'Raspar', heart: 'Corazon',
            frontflip: 'Voltereta', frontjump: 'Salto Frontal', frontpounce: 'Salto Agresivo'
        };

        App.addLog('info', `Ejecutando: ${actionNames[action] || action}`);
        await App.apiCall('/api/action', 'POST', { action });
    },

    async executeRoutine(routine) {
        const routineNames = {
            patrol: 'Patrullaje',
            jump: 'Rutina de Salto',
            explore: 'Exploracion'
        };

        App.addLog('info', `Iniciando rutina: ${routineNames[routine] || routine}`);
        await App.apiCall('/api/routine', 'POST', { routine });
    },

    async stopRoutine() {
        App.addLog('warning', 'Deteniendo rutina...');
        await App.apiCall('/api/routine/stop', 'POST');
    },

    clearLogs() {
        const container = document.getElementById('log-container');
        if (container) {
            container.innerHTML = '';
            App.addLog('info', 'Logs limpiados');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Connection.init();
});
