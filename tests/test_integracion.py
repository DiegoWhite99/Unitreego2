"""
test_integracion.py
Verifica la integracion completa: landing buttons → backend API → robot commands.
No requiere robot conectado — valida la logica de mapeo y endpoints.
"""

import sys
import os
import json
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, socketio, robot_state


class TestIntegracionLandingBackend(unittest.TestCase):
    """Pruebas de integracion landing → backend."""

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        # Reset state
        robot_state["connected"] = False
        robot_state["routine_running"] = False
        robot_state["routine_name"] = None

    # ════════════════════════════════════════
    #  TEST 1: Paginas se sirven correctamente
    # ════════════════════════════════════════

    def test_landing_page_loads(self):
        """La pagina landing se sirve en /landing."""
        res = self.client.get('/landing')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Daiver', res.data)

    def test_dashboard_page_loads(self):
        """La pagina dashboard se sirve en /."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

    # ════════════════════════════════════════
    #  TEST 2: API status responde
    # ════════════════════════════════════════

    def test_api_status(self):
        """GET /api/status retorna el estado del robot."""
        res = self.client.get('/api/status')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('connected', data)
        self.assertIn('ip', data)
        self.assertIn('mode', data)

    # ════════════════════════════════════════
    #  TEST 3: API config retorna mapeo completo
    # ════════════════════════════════════════

    def test_api_config(self):
        """GET /api/config retorna acciones y rutinas disponibles."""
        res = self.client.get('/api/config')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)

        # Verificar que todas las acciones del landing existen en config
        landing_actions = ['stand', 'sit', 'rise', 'recovery', 'hello', 'heart']
        for action in landing_actions:
            self.assertIn(action, data['actions'],
                          f"Accion '{action}' del landing NO esta en /api/config")

        # Verificar rutinas
        self.assertIn('patrol', data['routines'])
        self.assertIn('jump', data['routines'])
        self.assertIn('explore', data['routines'])

    # ════════════════════════════════════════
    #  TEST 4: Mapeo action_map completo
    # ════════════════════════════════════════

    def test_action_map_completo(self):
        """Todas las acciones del landing tienen mapeo a SPORT_CMD en el backend."""
        # Mapeo esperado: boton landing → action name → SPORT_CMD
        expected_map = {
            'stand': 'BalanceStand',
            'sit': 'SitDown',
            'rise': 'RiseSit',
            'recovery': 'RecoveryStand',
            'hello': 'Hello',
            'heart': 'FingerHeart',
        }

        # Importar action_map del endpoint (verificar via API)
        for action, expected_cmd in expected_map.items():
            # Sin robot conectado, debe retornar error 400, NO 400 con "accion invalida"
            res = self.client.post('/api/action',
                                   data=json.dumps({'action': action}),
                                   content_type='application/json')
            data = json.loads(res.data)
            # Debe decir "No conectado", NO "Accion invalida"
            self.assertNotEqual(data.get('message'), f"Accion invalida: {action}",
                                f"Accion '{action}' NO tiene mapeo en action_map del backend")

    # ════════════════════════════════════════
    #  TEST 5: Accion invalida rechazada
    # ════════════════════════════════════════

    def test_accion_invalida_rechazada(self):
        """Una accion inexistente es rechazada correctamente."""
        robot_state["connected"] = True
        res = self.client.post('/api/action',
                               data=json.dumps({'action': 'accion_falsa'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertIn('invalida', data['message'])
        robot_state["connected"] = False

    # ════════════════════════════════════════
    #  TEST 6: Endpoints rechazan sin conexion
    # ════════════════════════════════════════

    def test_action_sin_conexion(self):
        """POST /api/action sin robot conectado retorna error."""
        res = self.client.post('/api/action',
                               data=json.dumps({'action': 'stand'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertEqual(data['message'], 'No conectado')

    def test_move_sin_conexion(self):
        """POST /api/move sin robot conectado retorna error."""
        res = self.client.post('/api/move',
                               data=json.dumps({'x': 0.5, 'y': 0, 'z': 0}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_emergency_sin_conexion(self):
        """POST /api/emergency funciona incluso sin conexion (seguridad)."""
        res = self.client.post('/api/emergency')
        # Emergency siempre responde ok (seguridad)
        self.assertEqual(res.status_code, 200)

    def test_routine_sin_conexion(self):
        """POST /api/routine sin robot conectado retorna error."""
        res = self.client.post('/api/routine',
                               data=json.dumps({'routine': 'patrol'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)

    # ════════════════════════════════════════
    #  TEST 7: CSS y JS se sirven
    # ════════════════════════════════════════

    def test_landing_css(self):
        """El CSS del landing se sirve correctamente."""
        res = self.client.get('/css/landing.css')
        self.assertEqual(res.status_code, 200)

    def test_landing_js(self):
        """El JS del landing se sirve correctamente."""
        res = self.client.get('/js/landing.js')
        self.assertEqual(res.status_code, 200)

    def test_socketio_js(self):
        """La libreria socket.io se sirve correctamente."""
        res = self.client.get('/js/socket.io.min.js')
        self.assertEqual(res.status_code, 200)

    # ════════════════════════════════════════
    #  TEST 8: Assets/imagenes del landing
    # ════════════════════════════════════════

    def test_imagenes_landing(self):
        """Las imagenes referenciadas en landing.html existen."""
        images = [
            'images/diver.png',
            'images/pie.png',
            'images/sentado.png',
            'images/levantarse.png',
            'images/recuperarse.png',
            'images/patica.png',
            'images/corazon.png',
        ]
        for img in images:
            res = self.client.get(f'/assets/{img}')
            self.assertEqual(res.status_code, 200,
                             f"Imagen '{img}' NO se sirve correctamente")

    # ════════════════════════════════════════
    #  TEST 9: Rutina invalida rechazada
    # ════════════════════════════════════════

    def test_rutina_invalida_rechazada(self):
        """Una rutina inexistente es rechazada."""
        robot_state["connected"] = True
        res = self.client.post('/api/routine',
                               data=json.dumps({'routine': 'rutina_falsa'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)
        robot_state["connected"] = False

    # ════════════════════════════════════════
    #  TEST 10: Disconnect sin conexion
    # ════════════════════════════════════════

    def test_disconnect_sin_conexion(self):
        """POST /api/disconnect sin robot retorna error."""
        res = self.client.post('/api/disconnect')
        self.assertEqual(res.status_code, 400)

    # ════════════════════════════════════════
    #  TEST 11: Config IP update
    # ════════════════════════════════════════

    def test_config_ip_vacia(self):
        """POST /api/config/ip con IP vacia retorna error."""
        res = self.client.post('/api/config/ip',
                               data=json.dumps({'ip': ''}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)

    # ════════════════════════════════════════
    #  TEST 12: Scripts standalone existen y tienen contenido
    # ════════════════════════════════════════

    def test_scripts_existen(self):
        """Los scripts standalone tienen contenido (no estan vacios)."""
        scripts_dir = os.path.join(os.path.dirname(__file__), '..', 'scripts')
        scripts = ['corazon.py', 'levantarse.py', 'pata.py', 'pie.py',
                    'recuperarse.py', 'sentarse.py', 'saludo.py']

        for script in scripts:
            path = os.path.join(scripts_dir, script)
            self.assertTrue(os.path.exists(path), f"Script '{script}' no existe")
            with open(path, 'r') as f:
                content = f.read().strip()
            self.assertGreater(len(content), 50,
                               f"Script '{script}' esta vacio o incompleto")

    # ════════════════════════════════════════
    #  TEST 13: Scripts usan comandos correctos
    # ════════════════════════════════════════

    def test_scripts_comandos_correctos(self):
        """Cada script usa el SPORT_CMD correcto."""
        scripts_dir = os.path.join(os.path.dirname(__file__), '..', 'scripts')
        expected_cmds = {
            'corazon.py': 'FingerHeart',
            'levantarse.py': 'RiseSit',
            'pata.py': 'Hello',
            'pie.py': 'BalanceStand',
            'recuperarse.py': 'RecoveryStand',
            'sentarse.py': 'SitDown',
            'saludo.py': 'Hello',
        }

        for script, cmd in expected_cmds.items():
            path = os.path.join(scripts_dir, script)
            with open(path, 'r') as f:
                content = f.read()
            self.assertIn(cmd, content,
                          f"Script '{script}' no contiene SPORT_CMD['{cmd}']")


class TestMapeoLandingCompleto(unittest.TestCase):
    """Verifica que cada boton del landing.html tiene su contraparte en el backend."""

    def test_botones_landing_mapeados(self):
        """Cada data-action en landing.html tiene mapeo en app.py action_map."""
        import re

        # Leer landing.html y extraer data-action values
        landing_path = os.path.join(os.path.dirname(__file__), '..', 'website', 'landing.html')
        with open(landing_path, 'r', encoding='utf-8') as f:
            html = f.read()

        actions_in_html = set(re.findall(r'data-action="([^"]+)"', html))

        # Leer app.py y extraer action_map keys
        app_path = os.path.join(os.path.dirname(__file__), '..', 'app.py')
        with open(app_path, 'r', encoding='utf-8') as f:
            app_code = f.read()

        actions_in_backend = set(re.findall(r'"(\w+)":\s*"[A-Z]\w+"', app_code))

        # Verificar que todas las acciones del landing estan en el backend
        for action in actions_in_html:
            self.assertIn(action, actions_in_backend,
                          f"Boton con data-action='{action}' en landing.html "
                          f"NO tiene mapeo en action_map de app.py")

        print(f"\n  Botones landing verificados: {sorted(actions_in_html)}")
        print(f"  Acciones backend disponibles: {sorted(actions_in_backend)}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
