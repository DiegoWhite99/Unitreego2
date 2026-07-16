/* ============================================================
   Menú de navegación unificado — fuente ÚNICA de la navegación
   entre páginas del sistema. Se inyecta en todas las páginas vía
   <script src="/js/nav.js">. Cada página incluye además /css/nav.css.

   - Si la página ya tiene un botón #menu-toggle, lo enlaza.
   - Si no, inyecta un botón flotante (☰) arriba a la derecha.
   - Resalta automáticamente la página actual.
   ============================================================ */
(function () {
    const ITEMS = [
        { href: '/',               label: 'Inicio',         icon: '▣',  match: ['/', '/index.html'] },
        { href: '/control-remoto', label: 'Control Remoto', icon: '🎮', match: ['/control-remoto', '/controlremoto', '/controlremoto.html'] },
        { href: '/autoroute',      label: 'Auto-Ruta',      icon: '🗺', match: ['/autoroute', '/auto-ruta', '/autoroute.html'] },
        { href: '/rutaguiada',     label: 'Ruta Guiada',    icon: '📍', match: ['/rutaguiada'] },
        { href: '/agente',         label: 'Agente IA',      icon: '✦',  match: ['/agente', '/agente.html'] },
        { href: '/user-end',       label: 'Más funciones',  icon: '▸',  match: ['/user-end', '/user_end.html'] },
        { href: '/console-ia',     label: 'Console IA',     icon: '🎙', match: ['/console-ia', '/console_ia.html'] },
        { href: '/help',           label: 'Ayuda',          icon: '?',  match: ['/help', '/help.html'] },
    ];

    const path = (location.pathname || '/').toLowerCase().replace(/\/+$/, '') || '/';

    function isActive(item) {
        return item.match.some(m => {
            m = m.toLowerCase();
            return m === '/' ? path === '/' : (path === m || path.startsWith(m));
        });
    }

    function build() {
        if (document.getElementById('dvnav-drawer')) return; // idempotente

        const backdrop = document.createElement('div');
        backdrop.className = 'dvnav-backdrop';
        backdrop.id = 'dvnav-backdrop';

        const drawer = document.createElement('aside');
        drawer.className = 'dvnav-drawer';
        drawer.id = 'dvnav-drawer';
        drawer.setAttribute('aria-hidden', 'true');

        const links = ITEMS.map(it =>
            `<a class="dvnav-link${isActive(it) ? ' active' : ''}" href="${it.href}">` +
            `<span class="dvnav-ic">${it.icon}</span><span>${it.label}</span></a>`
        ).join('');

        drawer.innerHTML =
            '<div class="dvnav-head">' +
                '<span class="dvnav-brand">DIVER CONTROL</span>' +
                '<button class="dvnav-close" id="dvnav-close" type="button" aria-label="Cerrar">✕</button>' +
            '</div>' +
            '<nav class="dvnav-links">' + links + '</nav>';

        document.body.appendChild(backdrop);
        document.body.appendChild(drawer);

        function open()  { drawer.classList.add('open');  backdrop.classList.add('open');  drawer.setAttribute('aria-hidden', 'false'); }
        function close() { drawer.classList.remove('open'); backdrop.classList.remove('open'); drawer.setAttribute('aria-hidden', 'true'); }

        backdrop.addEventListener('click', close);
        drawer.querySelector('#dvnav-close').addEventListener('click', close);
        drawer.querySelectorAll('a.dvnav-link').forEach(a =>
            a.addEventListener('click', () => setTimeout(close, 120)));
        document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });

        // Enlaza un toggle existente, o inyecta uno flotante si la página no tiene.
        const existing = document.getElementById('menu-toggle');
        if (existing) {
            existing.addEventListener('click', e => { e.preventDefault(); open(); });
        } else {
            const btn = document.createElement('button');
            btn.className = 'dvnav-fab';
            btn.id = 'dvnav-fab';
            btn.type = 'button';
            btn.setAttribute('aria-label', 'Abrir menú');
            btn.textContent = '☰';
            btn.addEventListener('click', open);
            document.body.appendChild(btn);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', build);
    } else {
        build();
    }
})();
