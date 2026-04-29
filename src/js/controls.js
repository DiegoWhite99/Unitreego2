/* ========================================
   Movement Controls via Flask SocketIO
   ======================================== */

const Controls = {
    currentSpeed: 50,
    moveInterval: null,
    currentDirection: null,

    init() {
        this.setupDPad();
        this.setupSpeedSlider();
        this.setupRotation();
        this.setupKeyboard();
    },

    // D-Pad movement buttons
    setupDPad() {
        document.querySelectorAll('.dpad-btn').forEach(btn => {
            const command = btn.dataset.command;
            if (!command) return;

            // Mouse events
            btn.addEventListener('mousedown', () => this.startMovement(command));
            btn.addEventListener('mouseup', () => this.stopMovement());
            btn.addEventListener('mouseleave', () => this.stopMovement());

            // Touch events for mobile
            btn.addEventListener('touchstart', (e) => {
                e.preventDefault();
                this.startMovement(command);
            });
            btn.addEventListener('touchend', () => this.stopMovement());
        });
    },

    // Speed slider
    setupSpeedSlider() {
        const slider = document.getElementById('speed-slider');
        const value = document.getElementById('speed-value');

        if (slider) {
            slider.addEventListener('input', () => {
                this.currentSpeed = parseInt(slider.value);
                if (value) value.textContent = this.currentSpeed + '%';
            });
        }
    },

    // Rotation buttons
    setupRotation() {
        document.getElementById('btn-rotate-left')?.addEventListener('mousedown', () => {
            this.startMovement('rotate-left');
        });
        document.getElementById('btn-rotate-left')?.addEventListener('mouseup', () => {
            this.stopMovement();
        });
        document.getElementById('btn-rotate-left')?.addEventListener('mouseleave', () => {
            this.stopMovement();
        });

        document.getElementById('btn-rotate-right')?.addEventListener('mousedown', () => {
            this.startMovement('rotate-right');
        });
        document.getElementById('btn-rotate-right')?.addEventListener('mouseup', () => {
            this.stopMovement();
        });
        document.getElementById('btn-rotate-right')?.addEventListener('mouseleave', () => {
            this.stopMovement();
        });
    },

    // Keyboard controls (WASD + Q/E for rotation)
    setupKeyboard() {
        const keyMap = {
            'w': 'forward', 'W': 'forward', 'ArrowUp': 'forward',
            's': 'backward', 'S': 'backward', 'ArrowDown': 'backward',
            'a': 'left', 'A': 'left', 'ArrowLeft': 'left',
            'd': 'right', 'D': 'right', 'ArrowRight': 'right',
            'q': 'rotate-left', 'Q': 'rotate-left',
            'e': 'rotate-right', 'E': 'rotate-right',
            ' ': 'stop'
        };

        const activeKeys = new Set();

        document.addEventListener('keydown', (e) => {
            if (!App.state.connected) return;
            // Ignore if typing in input field
            if (e.target.tagName === 'INPUT') return;

            const command = keyMap[e.key];
            if (!command) return;

            e.preventDefault();

            if (command === 'stop') {
                this.stopMovement();
                return;
            }

            if (!activeKeys.has(e.key)) {
                activeKeys.add(e.key);
                this.startMovement(command);
            }
        });

        document.addEventListener('keyup', (e) => {
            if (!App.state.connected) return;
            if (e.target.tagName === 'INPUT') return;

            if (keyMap[e.key] && keyMap[e.key] !== 'stop') {
                activeKeys.delete(e.key);
                if (activeKeys.size === 0) {
                    this.stopMovement();
                }
            }
        });
    },

    // Convert direction + speed to x, y, z velocities
    getVelocity(direction) {
        const speedFactor = (this.currentSpeed / 100) * 0.8; // max 0.8 m/s
        const rotFactor = (this.currentSpeed / 100) * 1.0;   // max 1.0 rad/s

        const velocities = {
            'forward':      { x:  speedFactor, y: 0, z: 0 },
            'backward':     { x: -speedFactor, y: 0, z: 0 },
            'left':         { x: 0, y:  speedFactor * 0.6, z: 0 },
            'right':        { x: 0, y: -speedFactor * 0.6, z: 0 },
            'rotate-left':  { x: 0, y: 0, z:  rotFactor },
            'rotate-right': { x: 0, y: 0, z: -rotFactor },
            'stop':         { x: 0, y: 0, z: 0 }
        };

        return velocities[direction] || { x: 0, y: 0, z: 0 };
    },

    startMovement(direction) {
        if (!App.state.connected) return;

        // Clear previous interval
        if (this.moveInterval) {
            clearInterval(this.moveInterval);
        }

        this.currentDirection = direction;

        if (direction === 'stop') {
            this.stopMovement();
            return;
        }

        const vel = this.getVelocity(direction);

        // Send command immediately via SocketIO (real-time)
        const sendMove = () => {
            if (App.socket && App.state.connected) {
                App.socket.emit('move_command', vel);
            }
        };

        sendMove();

        // Re-send every 200ms (robot requires continuous commands)
        this.moveInterval = setInterval(sendMove, 200);
    },

    stopMovement() {
        if (this.moveInterval) {
            clearInterval(this.moveInterval);
            this.moveInterval = null;
        }

        this.currentDirection = null;

        // Send stop via SocketIO
        if (App.socket) {
            App.socket.emit('stop_command');
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Controls.init();
});
