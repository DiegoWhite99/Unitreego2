# Plan de mejora — de 6.5 a 9

**Proyecto:** Daiver Control CUN · Unitree Go2 Air
**Fecha:** 30 de mayo de 2026
**Meta:** subir el estado actual del proyecto de **6.5/10** a **9/10**, dejándolo
listo para un piloto comercial.

> **Idea central:** la brecha entre el potencial (8.5) y el estado actual (6.5) es
> **trabajo conocido, no incertidumbre**. Este plan lo ordena por prioridad e impacto.

---

## Regla de oro del plan

🚫 **No meter features nuevas hasta cerrar la resiliencia.** Lo que sube el puntaje
ahora no es "más cosas que hace el robot", es que **lo que ya hace sea confiable y
operable sin sustos**. Primero estabilidad y seguridad; después, hardware y venta.

---

## Sprint 0 · Resiliencia de software (sube ~6.5 → 8)

*Todo esto se hace **sin el robot**, apoyándose en el modo simulación. ~1 semana.*

| # | Tarea | Esfuerzo | Prioridad | Qué desbloquea |
|---|---|---|---|---|
| 1 | **Helper "no bloqueante en el loop"** (`run_blocking_in_thread`) y adoptarlo | 0.5 día | 🟡 Media | Que el cuelgue principal no reaparezca; regla reutilizable |
| 2 | **Modo simulación** (`pub_sub` falso + pose falsa, flag `SIMULATION=1`) | 1–2 días | 🟠 Alta | Probar lógica de rutas/IA **sin robot**; base de los tests y del watchdog |
| 3 | **Watchdog de conexión** (heartbeat → frena el robot si pierde señal) | 1–2 días | 🔴 Crítica | **Seguridad real** → permite autonomía y operación remota |
| 4 | **Timeout + reconexión en el frontend** (`AbortController` + UX de socket) | 1–2 días | 🟠 Alta | Mata la sensación de "app colgada" del lado del navegador |
| 5 | **2–3 tests de integración** (conexión, autoroute, dispatch del agente) | 1–2 días | 🟡 Media | Red de seguridad contra regresiones |

**Resultado del Sprint 0:** software estable, seguro y probable sin robot.
**El robot solo se necesita al final, para la validación física (el checklist del lunes).**

---

## Sprint 1 · Producto / hardware (sube ~8 → 8.7)

*Requiere compra de hardware (considerar tiempo de envío). ~2–3 semanas.*

| # | Tarea | Esfuerzo | Prioridad | Qué desbloquea |
|---|---|---|---|---|
| 6 | **VPN remota** (Tailscale rápido → WireGuard + 4G después) | 1–2 días | 🟠 Alta | Operación remota = el primer "wow" vendible (Tier 2) |
| 7 | **Prototipo Jetson** (provisionar, deps, YOLO en GPU, correr backend) | 3–5 días + envío | 🟠 Alta | El robot autónomo con su propio cerebro (Tier 3) |
| 8 | **Validación física** (peso, energía, térmica del Jetson en el lomo) | 1–2 días | 🟠 Alta | Confirmar que la "maletica" es viable en el Go2 real |

**Resultado del Sprint 1:** prototipo del producto premium funcionando y operable
desde cualquier lugar.

---

## Sprint 2 · Cierre comercial (sube ~8.7 → 9)

*Mezcla técnica + negocio. Tiempo según cliente.*

| # | Tarea | Esfuerzo | Prioridad | Qué desbloquea |
|---|---|---|---|---|
| 9 | **Resolver clave AES / vinculación del robot** | 1–3 días + dependencia externa | 🔴 Crítica | Sin esto no hay producto replicable (ver `docs/CONTEXTO_AES_KEY.md`) |
| 10 | **Empaque del producto** (instalador/imagen del Jetson lista) | 2–3 días | 🟡 Media | Que se pueda replicar en otro robot sin armarlo a mano |
| 11 | **Piloto con un cliente** (demo controlada + feedback) | Externo | 🟠 Alta | Validación de mercado real → caso de venta |

**Resultado del Sprint 2:** producto replicable y validado con un cliente piloto.

---

## Curva de puntaje

```
6.5  ──Sprint 0──▶  8.0  ──Sprint 1──▶  8.7  ──Sprint 2──▶  9.0
   (resiliencia)      (Jetson+VPN)        (AES+piloto)
```

| Hito | Puntaje | Estado |
|---|---|---|
| Hoy | 6.5 | Funciona, pero con brechas de resiliencia |
| Tras Sprint 0 | ~8.0 | Estable, seguro, probable sin robot |
| Tras Sprint 1 | ~8.7 | Producto premium prototipado y remoto |
| Tras Sprint 2 | ~9.0 | Replicable y validado con cliente |

---

## Qué pedir a la dirección (alineado con la propuesta)

- **Sprint 0:** solo tiempo de desarrollo (cero hardware nuevo).
- **Sprint 1:** presupuesto para **1 Jetson Orin + módem 4G** (ver costos en la propuesta).
- **Sprint 2:** apoyo para conseguir **un cliente piloto**.

---

## Resumen en una frase

> Cierra primero **resiliencia** (Sprint 0, sin robot, 1 semana), luego **hardware**
> (Sprint 1, Jetson + VPN), y de ahí a **piloto** (Sprint 2). El riesgo es de
> constancia, no técnico — el camino ya está claro.
