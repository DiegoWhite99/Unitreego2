# Propuesta técnica — Despliegue del control autónomo del Unitree Go2

**Proyecto:** Daiver Control CUN · Unitree Go2 Air
**Fecha:** 30 de mayo de 2026
**Objetivo:** definir la arquitectura de despliegue para **comercializar** nuestra
aplicación de control (sin depender de la app oficial de Unitree) y poder operar
el robot **fuera de la red local**.

---

## 1. Resumen ejecutivo

Hoy nuestra app controla el Go2 vía **WebRTC sobre la red local (LAN)**: patrullaje
autónomo, visión YOLO, gestos, reconocimiento facial, lidar y agente de IA. El reto
para convertirla en producto es que **el control del robot debe ocurrir en la misma
red que el robot** (no se puede mover "tal cual" a la nube).

Existen **dos enfoques** para resolverlo, que **no compiten — se complementan**:

| Enfoque | Resuelve | Idea |
|---|---|---|
| **A. Conectividad (VPN)** | Llegar al robot desde fuera de la LAN | WireGuard + 4G/5G |
| **B. Cómputo a bordo** | Poner el "cerebro" sobre el robot, en tiempo real | NVIDIA Jetson en el lomo |

**Recomendación:** combinarlos en un **modelo por niveles**. La VPN da acceso remoto;
el Jetson da autonomía y potencia. El producto premium usa **ambos**.

---

## 2. El reto técnico (por qué no se puede "todo en la nube")

Nuestra conexión usa `WebRTC LocalSTA`, es decir **red local**. El robot no está
expuesto a internet (SSH bloqueado, detrás del router). Por lo tanto:

> **Quien hable WebRTC con el robot tiene que estar en su misma red.**

Esto significa que **el backend de control es, por naturaleza, local**. No se puede
alojar en un servidor cloud convencional. Lo que sí podemos hacer es:

- **Acercar la red** al robot mediante una **VPN** (Opción A), o
- **Meter el backend dentro del robot** con un computador a bordo (Opción B).

---

## 3. Opción A — Conectividad por VPN (WireGuard + 4G/5G)

### ¿Qué es?
Un **túnel seguro (WireGuard)** que hace que un operador o servidor remoto sea
"virtualmente" parte de la red del robot. Opcionalmente, un **módem 4G/5G** le da al
robot internet propio para operar donde no haya WiFi.

### ¿Cómo funciona?
```
Operador remoto  ──▶  Túnel WireGuard (cifrado)  ──▶  Red del robot  ──▶  Go2
   (en casa)                                          (LAN / 4G)
```
Un dispositivo pequeño en el lado del robot (un mini-PC, una Raspberry Pi o un
**Arduino UNO Q**) actúa como **gateway VPN**. El backend de control puede correr
en ese mismo lado o en el equipo remoto que entra por el túnel.

### Pros
- ✅ **Bajo costo** y rápido de montar.
- ✅ Permite **operación remota** desde cualquier lugar.
- ✅ **Seguro**: tráfico cifrado, sin abrir puertos al exterior.
- ✅ No añade peso de cómputo al robot.

### Contras
- ⚠️ **No aumenta la potencia**: la inteligencia (YOLO, etc.) sigue corriendo donde
  esté el backend; si es un equipo débil, va lento.
- ⚠️ La calidad del **video por 4G** depende de la señal (mitigable bajando FPS/resolución).
- ⚠️ Requiere configurar y mantener la VPN.

### Sobre el Arduino UNO Q
El UNO Q corre Linux (chip Qualcomm) y **sirve como gateway VPN o para sensores/cámara
auxiliar** (de hecho ya lo usamos como cámara por Socket.IO). **No es suficiente** para
correr el stack completo (WebRTC + YOLO) en tiempo real: para eso es la Opción B.

### Cuándo usarla
Para un **MVP remoto barato** o cuando el cómputo pesado puede vivir en un PC y solo
necesitamos **alcance remoto**.

---

## 4. Opción B — Cómputo a bordo (NVIDIA Jetson en el lomo)

### ¿Qué es?
Montar una **NVIDIA Jetson Orin** sobre el robot (como una "maletica" en el lomo) que
corre **todo el backend + YOLO + WebRTC** de forma autónoma. El robot lleva su propio
cerebro.

### ¿Cómo funciona?
```
[ Jetson en el lomo ]
   ├─ Backend (Flask + Socket.IO)      ← nuestro código actual, casi sin cambios
   ├─ YOLO en GPU (tiempo real)        ← detección/pose/rostros más rápido
   └─ WebRTC al Go2 por su propia WiFi/LAN
        + (opcional) WireGuard/4G para acceso remoto  ← se combina con la Opción A
```

### Pros
- ✅ **Robot autónomo**: no necesita una laptop conectada.
- ✅ **YOLO en GPU** → tiempo real, modelos más grandes, pose + rostros a la vez.
- ✅ Corre **nuestro código casi sin cambios** (es Python, arquitectura ya en capas).
- ✅ Latencia mínima con el robot (está físicamente sobre él).
- ✅ Es **el producto premium** que se vende.

### Contras
- ⚠️ **Costo** del hardware (Jetson + batería + carcasa).
- ⚠️ **Peso y energía**: hay que validar autonomía del Go2 con la carga y cómo
  alimentar el Jetson (batería propia).
- ⚠️ **Térmica**: requiere disipación en la carcasa.

### Cuándo usarla
Para el **producto final / premium**: un Go2 autónomo, inteligente y operable desde
cualquier lugar (combinándolo con la VPN de la Opción A).

---

## 5. Comparación lado a lado

| Criterio | A · VPN (WireGuard/4G) | B · Jetson a bordo |
|---|---|---|
| Resuelve | Acceso remoto | Cómputo + autonomía |
| Potencia de IA | La del backend externo | **Alta (GPU)** |
| Autonomía del robot | Media (depende de PC) | **Total** |
| Costo | **Bajo** | Medio-alto |
| Peso/energía extra | Mínimo | Notable |
| Complejidad | Media (config VPN) | Media (integración HW) |
| Cambios de código | Casi ninguno | Casi ninguno |
| Rol ideal | MVP remoto | **Producto premium** |

> **Clave:** no es "A o B". El producto serio es **B (cerebro) + A (acceso remoto)**.

---

## 6. Recomendación: producto por niveles

| Nivel | Configuración | Para qué |
|---|---|---|
| 🥉 **Tier 1 — Demo** | Laptop en la LAN (lo actual) | Mostrar/validar |
| 🥈 **Tier 2 — Remoto (MVP)** | Mini-PC o Arduino UNO Q + WireGuard/4G | Operación remota a bajo costo |
| 🥇 **Tier 3 — Autónomo (premium)** | **Jetson Orin en el lomo + WireGuard + 4G/5G** | Producto comercial diferenciador |

---

## 7. Hardware y costos aproximados *(estimado — a validar)*

| Componente | USD aprox. |
|---|---|
| NVIDIA Jetson Orin Nano (kit) | 250 – 500 |
| Módem 4G/5G (USB/HAT) | 50 – 150 |
| Batería para el Jetson | 50 – 100 |
| Carcasa "maletica" + disipación | 50 – 80 |
| WireGuard / Tailscale (software) | 0 |
| *(alternativa Tier 2)* Arduino UNO Q | 45 – 60 |

---

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Peso/energía del Jetson sobre el Go2 | Validar autonomía con carga; batería dedicada para el Jetson |
| Calentamiento en la carcasa | Disipación pasiva/activa; ventilación |
| Video deficiente por 4G | Bajar resolución/FPS (ya es configurable en la app) |
| Pérdida de conexión en remoto | **Watchdog**: el robot frena solo si no hay heartbeat *(pendiente, crítico para autonomía)* |
| Seguridad del control remoto | WireGuard con claves, sin abrir puertos |
| Vinculación de la clave AES del robot | Resolver antes de comercializar *(ver `docs/CONTEXTO_AES_KEY.md`)* |

---

## 9. Roadmap por fases

1. **Fase 1 — Estabilizar (en curso/hecho):** corrección de cuelgues, reorganización del proyecto.
2. **Fase 2 — MVP remoto:** montar WireGuard/4G (Opción A) y validar operación fuera de la LAN.
3. **Fase 3 — Prototipo a bordo:** migrar el backend a un Jetson (Opción B) y montarlo en el robot.
4. **Fase 4 — Producto/piloto comercial:** integrar A+B, watchdog, empaque y prueba con un cliente.

---

## 10. Conclusión y pedido a la dirección

- El **backend debe ser local** por diseño de WebRTC — eso no cambia.
- La **VPN (Opción A)** resuelve el acceso remoto a bajo costo.
- El **Jetson (Opción B)** es lo que convierte esto en un **producto vendible**: un Go2
  autónomo, con IA en tiempo real, operable desde cualquier lugar.
- Nuestro **código ya está listo** para migrar al Jetson con bajo esfuerzo → menor
  tiempo y costo de desarrollo.

**Solicitamos:** presupuesto para **un (1) Jetson Orin de prueba** + módem 4G y tiempo
de desarrollo para el prototipo de Fase 3. Con eso construimos la primera versión del
producto premium y la llevamos a un piloto comercial.
