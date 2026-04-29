"""Capa de dominio del proyecto Daiver Control.

Subpaquetes:
  - core.runtime:     Flask app, SocketIO, event loop asyncio, run_async helpers.
  - core.state:       diccionarios de estado global del robot.
  - core.connection:  conexion WebRTC al Go2 (connect/disconnect, video).
  - core.primitives:  Move/Stop/BalanceStand y combinadores.
  - core.poses:       acciones complejas estabilizadas (sit_safe, heart_safe...).
  - core.routines:    rutinas pre-grabadas (patrullaje, salto, exploracion).
  - core.follow:      seguidor de QR (Follow-Me).
  - core.autoroute:   seguidor de waypoints en frame del lidar.
  - core.perception:  lidar (proximity_sensor) y QR.
  - core.agents:      agente Diver (Gemini/OpenAI) y reactor de gestos.
"""
