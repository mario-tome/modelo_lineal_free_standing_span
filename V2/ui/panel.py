import csv, math, os
import streamlit as st
from V2.modelos import Lineal
from V2.logica.constantes import TERRENOS
from V2.logica.estado import get_sim, SimState
from V2.logica.trayectoria import get_origen_latlon, parse_trayectoria, calcular_errores
from V2.ui.figura import build_figure


# ---------------------------------------------------------------------------
# Helpers de avance de simulación
# ---------------------------------------------------------------------------

def _sincronizar_configuracion(sim: SimState, lineal: Lineal) -> list:
    """
    Lee los controles del sidebar y aplica los valores actuales al modelo.
    Devuelve los puntos de trayectoria activos (lista vacía si no hay trayectoria).
    """
    ui = st.session_state

    # Trayectoria GPS objetivo
    puntos_tray = []
    if ui.get("k_tray_activa", False):
        lat, lon = get_origen_latlon()
        puntos = parse_trayectoria(ui.get("k_tray_input", ""), lat, lon)
        if len(puntos) >= 2:
            sim.trayectoria_activa = True
            sim.trayectoria_puntos = puntos
            puntos_tray = puntos
        else:
            sim.trayectoria_activa = False
            sim.trayectoria_puntos = None
    else:
        sim.trayectoria_activa = False
        sim.trayectoria_puntos = None

    # Velocidad, terreno e interferencia GPS
    lineal.set_speed(ui.get("k_vpct", 50))
    nivel_patinaje = TERRENOS.get(ui.get("k_terreno", "Normal"), 0.012)
    lineal.tramo_cart.ruido_lateral = nivel_patinaje
    lineal.tramo_end.ruido_lateral  = nivel_patinaje

    interferencia_mm = float(ui.get("k_interferencia_gps_mm", 0))
    if lineal.gps:
        lineal.gps.interferencia_gps_mm = interferencia_mm
    elif lineal.caja_interfaz:
        lineal.caja_interfaz.interferencia_gps_mm = interferencia_mm

    # Auto-reverse
    sim.auto_reverse_activo = bool(ui.get("k_auto_reverse", False))
    sim.limite_sur           = float(ui.get("k_ar_ymin", 0))
    sim.limite_norte         = float(ui.get("k_ar_ymax", sim.longitud_campo))

    return puntos_tray


def _procesar_mensajes_caja(sim: SimState, lineal: Lineal) -> None:
    """
    Procesa los mensajes recibidos del Arduino (caja de interfaz):
    actualiza slow_down, detecta safety/GPS fail y reanuda automáticamente.
    """
    if not lineal.caja_interfaz:
        return

    caja   = lineal.caja_interfaz
    previo = sim.estado_previo_caja

    # Cambios en slow_down (solo se registran si la simulación está en marcha)
    if sim.en_marcha:
        if caja.slow_down_cart != previo["cart"]:
            previo["cart"] = caja.slow_down_cart
            sim.registro.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_CART ON — Cart ralentizado, giro gradual hacia izquierda"
                        if caja.slow_down_cart
                        else "SLOW_DOWN_CART OFF — Cart a velocidad normal"),
            })
        if caja.slow_down_end_tower != previo["end"]:
            previo["end"] = caja.slow_down_end_tower
            sim.registro.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_END_TOWER ON — End-tower ralentizado, giro gradual hacia derecha"
                        if caja.slow_down_end_tower
                        else "SLOW_DOWN_END_TOWER OFF — End-tower a velocidad normal"),
            })
        lineal.slow_down_cart      = caja.slow_down_cart
        lineal.slow_down_end_tower = caja.slow_down_end_tower

    # Safety fail → parada de emergencia
    if not caja.safety_ok and previo.get("safety", True):
        previo["safety"] = False
        lineal.stop()
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "CRIT",
                             "msg": "SAFETY_FAIL — parada de emergencia"})
        sim.en_marcha    = False
        sim.pausado      = True
        sim.motivo_pausa = "safety_fail"
    elif caja.safety_ok and not previo.get("safety", True):
        previo["safety"] = True
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "OK",
                             "msg": "SAFETY_OK — seguridad restaurada (reanuda manualmente)"})

    # GPS fail → pausa; GPS ok → reanuda automáticamente si fue por pérdida de GPS
    if not caja.gps_ok and previo.get("gps", True):
        previo["gps"] = False
        if sim.en_marcha:
            lineal.stop()
            sim.en_marcha    = False
            sim.pausado      = True
            sim.motivo_pausa = "gps_fail"
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "CRIT",
                             "msg": "GPS_FAIL — señal GPS perdida, simulación pausada"})
    elif caja.gps_ok and not previo.get("gps", True):
        previo["gps"] = True
        sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "OK",
                             "msg": "GPS_OK — señal GPS restaurada"})
        if sim.pausado and sim.motivo_pausa == "gps_fail":
            lineal.start()
            caja.iniciar()
            sim.en_marcha    = True
            sim.pausado      = False
            sim.motivo_pausa = None
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "START",
                                 "msg": "Reanudación automática tras recuperar GPS"})


def _actualizar_errores_trayectoria(sim: SimState, lineal: Lineal, puntos_tray: list) -> None:
    """Calcula y almacena los errores de distancia y rumbo respecto a la trayectoria."""
    if not (sim.trayectoria_activa and puntos_tray):
        sim.error_distancia_mm = None
        sim.error_rumbo_grados = None
        return

    tramo_gps, indice_gps = _get_tramo_gps(lineal)
    if tramo_gps is None:
        sim.error_distancia_mm = None
        sim.error_rumbo_grados = None
        return

    posiciones_pasadas = (sim.rastros_secciones[indice_gps]
                          if sim.rastros_secciones and indice_gps < len(sim.rastros_secciones)
                          else [])
    error_dist, error_rumbo = calcular_errores(
        tramo_gps.posicion_x, tramo_gps.posicion_y,
        puntos_tray, posiciones_pasadas, lineal.en_marcha_atras,
    )
    sim.error_distancia_mm = error_dist
    sim.error_rumbo_grados = error_rumbo


def _avanzar_tick(sim: SimState, lineal: Lineal, segundos: int, puntos_tray: list) -> None:
    """
    Avanza el modelo un tick y actualiza todos los datos derivados:
    rastros de posición, velocidad real, errores de trayectoria, CSV, historial GPS y log de alineación.
    """
    lineal.avanza(segundos)

    # Rastros de posición por sección (muestra el camino recorrido en el campo)
    if sim.rastros_secciones and len(sim.rastros_secciones) == len(lineal.secciones):
        for idx, sec in enumerate(lineal.secciones):
            rastro = sim.rastros_secciones[idx]
            xn, yn = sec.posicion_x, sec.posicion_y
            if not rastro or math.hypot(xn - rastro[-1][0], yn - rastro[-1][1]) >= 0.5:
                rastro.append((xn, yn))
        if len(sim.rastros_secciones[0]) > 20_000:
            sim.rastros_secciones = [r[-20_000:] for r in sim.rastros_secciones]

    # Velocidad real (metros por minuto)
    sim.velocidad_real         = (lineal.posicion_norte - sim.posicion_norte_previa) / (segundos / 60.0)
    sim.posicion_norte_previa  = lineal.posicion_norte

    # Errores de trayectoria (antes de escribir CSV para que la fila tenga los valores actualizados)
    _actualizar_errores_trayectoria(sim, lineal, puntos_tray)

    # Exportación CSV
    _escribir_fila_csv(sim, _construir_fila_csv(lineal, sim))

    # Historial GPS (últimas 20 lecturas)
    if lineal.gps:
        sim.historial_gps.append({
            "Tiempo":    lineal._tiempo_formateado(),
            "LAT ×10⁷": lineal.gps.lat_e7,
            "LON ×10⁷": lineal.gps.lon_e7,
            "Lat (°)":   round(lineal.gps.latitud, 7),
            "Lon (°)":   round(lineal.gps.longitud, 7),
        })
        if len(sim.historial_gps) > 20:
            sim.historial_gps = sim.historial_gps[-20:]

    # Log de alineación: detecta desalineamientos y recuperaciones tramo a tramo
    alineacion_actual = [lineal.get_span_alineado(j) for j in range(lineal.numero_tramos)]
    if sim.alineacion_previa is not None:
        for j, (previo, actual) in enumerate(zip(sim.alineacion_previa, alineacion_actual)):
            if previo and not actual:
                sp = lineal.get_span_info(j)
                sim.registro.append({
                    "t": lineal._tiempo_formateado(), "tipo": "CRIT",
                    "msg": f"Tramo {j+1} desalineado  ({sp['desviacion_norte']:+.3f} m)",
                })
            elif not previo and actual:
                sim.registro.append({
                    "t": lineal._tiempo_formateado(), "tipo": "OK",
                    "msg": f"Tramo {j+1} recuperado",
                })
    sim.alineacion_previa = alineacion_actual


def _gestionar_limites(sim: SimState, lineal: Lineal) -> None:
    """Detecta si el lineal llegó al límite del campo y aplica auto-reverse o detiene."""
    if sim.auto_reverse_activo:
        posicion = lineal.posicion_norte
        if not lineal.en_marcha_atras and posicion >= sim.limite_norte:
            lineal.invertir_direccion()
            sim.numero_inversiones += 1
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "INFO",
                                 "msg": f"Auto-reverse ▼  ({posicion:.1f} m ≥ {sim.limite_norte:.0f} m)  — pasada #{sim.numero_inversiones}"})
        elif lineal.en_marcha_atras and posicion <= sim.limite_sur:
            lineal.invertir_direccion()
            sim.numero_inversiones += 1
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "INFO",
                                 "msg": f"Auto-reverse ▲  ({posicion:.1f} m ≤ {sim.limite_sur:.0f} m)  — pasada #{sim.numero_inversiones}"})
    else:
        if lineal.posicion_norte >= sim.longitud_campo:
            lineal.stop()
            if lineal.gps:
                lineal.gps.detener_transmision_background()
            sim.registro.append({"t": lineal._tiempo_formateado(), "tipo": "FIN",
                                 "msg": f"Riego completado — {lineal.posicion_norte:.2f} m en {lineal._tiempo_formateado()}"})
            sim.en_marcha  = False
            sim.completado = True
            st.rerun()


def _avanzar_simulacion(sim: SimState) -> None:
    """Orquesta un tick completo: sincroniza config → procesa caja → avanza → gestiona límites."""
    lineal = sim.lineal
    if lineal is None:
        sim.trayectoria_activa = False
        sim.trayectoria_puntos = None
        return

    puntos_tray = _sincronizar_configuracion(sim, lineal)
    _procesar_mensajes_caja(sim, lineal)

    if sim.en_marcha and not sim.completado:
        segundos_por_tick = st.session_state.get("k_simspd", 60)
        _avanzar_tick(sim, lineal, segundos_por_tick, puntos_tray)
        _gestionar_limites(sim, lineal)
    else:
        # Aunque esté pausado, mantenemos los errores de trayectoria actualizados
        _actualizar_errores_trayectoria(sim, lineal, puntos_tray)


# ---------------------------------------------------------------------------
# Helpers de CSV
# ---------------------------------------------------------------------------

def _construir_fila_csv(lineal: Lineal, sim: SimState) -> dict:
    """Construye la fila de datos del tick actual para exportar al CSV."""
    fila = {
        "tiempo_s":       lineal.tiempo_total_segundos,
        "tiempo":         lineal._tiempo_formateado(),
        "posicion_norte": round(lineal.posicion_norte, 3),
        "slow_cart":      lineal.slow_down_cart,
        "slow_end_tower": lineal.slow_down_end_tower,
    }
    for j, sec in enumerate(lineal.secciones):
        fila[f"seccion_{j}_x"] = round(sec.posicion_x, 4)
        fila[f"seccion_{j}_y"] = round(sec.posicion_y, 4)
        if j < lineal.numero_tramos:
            sp = lineal.get_span_info(j)
            fila[f"tramo_{j+1}_longitud_m"]  = round(sp["longitud"], 4)
            fila[f"tramo_{j+1}_deformacion"] = round(lineal.longitud_tramo - sp["longitud"], 4)
            fila[f"tramo_{j+1}_desv_norte"]  = round(sp["desviacion_norte"], 4)
            fila[f"tramo_{j+1}_rumbo_deg"]   = round(sp["angulo_grados"], 4)

    fila["lat_e7"]            = lineal.gps.lat_e7 if lineal.gps else None
    fila["lon_e7"]            = lineal.gps.lon_e7 if lineal.gps else None
    fila["error_distancia_mm"] = round(sim.error_distancia_mm, 1) if sim.error_distancia_mm is not None else None
    fila["error_rumbo_deg"]    = round(sim.error_rumbo_grados, 2) if sim.error_rumbo_grados is not None else None
    return fila


def _escribir_fila_csv(sim: SimState, fila: dict) -> None:
    ruta = sim.get("csv_ruta")
    if not ruta:
        return
    primera_vez = (sim.csv_filas_escritas == 0)
    with open(ruta, "a", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(fila.keys()),
                                  restval="", extrasaction="ignore")
        if primera_vez:
            escritor.writeheader()
        escritor.writerow(fila)
    sim.csv_filas_escritas += 1


# ---------------------------------------------------------------------------
# Helper GPS
# ---------------------------------------------------------------------------

def _get_tramo_gps(lineal: Lineal) -> tuple:
    """Devuelve (tramo_gps, indice_en_secciones) o (None, -1) si no hay GPS configurado."""
    sensor = lineal.gps or lineal.caja_interfaz
    if sensor is None:
        return None, -1
    tramo = sensor.tramo
    try:
        return tramo, lineal.secciones.index(tramo)
    except ValueError:
        return None, -1


# ---------------------------------------------------------------------------
# Bloques HTML reutilizables
# ---------------------------------------------------------------------------

def _html_badge_en_marcha(en_marcha_atras: bool, auto_reverse_activo: bool, numero_inversiones: int) -> str:
    color  = "#ff7b72" if en_marcha_atras else "#3fb950"
    fondo  = "rgba(255,123,114,0.08)" if en_marcha_atras else "rgba(63,185,80,0.08)"
    borde  = "rgba(255,123,114,0.25)" if en_marcha_atras else "rgba(63,185,80,0.25)"
    texto  = "&#9660; MARCHA ATRÁS" if en_marcha_atras else "&#9650; EN MARCHA"
    sufijo = (
        f"&nbsp;<span style='color:#8b949e;font-weight:400;font-size:0.75rem;letter-spacing:1px'>"
        f"AUTO-REVERSE · {numero_inversiones} inv.</span>"
        if auto_reverse_activo else ""
    )
    return (
        f"<div style='display:inline-flex;align-items:center;gap:8px;"
        f"background:{fondo};border:1px solid {borde};"
        f"border-radius:20px;padding:5px 14px;margin:4px 0'>"
        f"<span style='width:8px;height:8px;border-radius:50%;background:{color};"
        f"display:inline-block;box-shadow:0 0 6px {color}'></span>"
        f"<span style='color:{color};font-weight:600;letter-spacing:2px;font-size:0.85rem'>"
        f"{texto}</span>{sufijo}</div>"
    )


def _html_barra_progreso_auto_reverse(
    lineal: Lineal, limite_sur: float, limite_norte: float, numero_inversiones: int
) -> str:
    amplitud         = max(limite_norte - limite_sur, 1.0)
    posicion_acotada = max(limite_sur, min(limite_norte, lineal.posicion_norte))
    porcentaje_barra = (posicion_acotada - limite_sur) / amplitud * 100.0
    color_barra      = "#ff7b72" if lineal.en_marcha_atras else "#3fb950"
    simbolo          = "▼" if lineal.en_marcha_atras else "▲"
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px'>"
        f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;text-transform:uppercase;font-family:monospace'>"
        f"Auto-reverse  ·  {limite_sur:.0f} m — {limite_norte:.0f} m</span>"
        f"<span style='color:{color_barra};font-size:1.5rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{simbolo}&nbsp;{lineal.posicion_norte:.1f}<span style='color:#8b949e;font-size:0.9rem'> m</span></span>"
        f"</div>"
        f"<div style='position:relative;background:#21262d;border-radius:4px;height:8px;margin-bottom:8px'>"
        f"<div style='position:absolute;left:0;top:0;background:rgba(63,185,80,0.12);border-radius:4px;width:{porcentaje_barra:.2f}%;height:100%'></div>"
        f"<div style='position:absolute;top:-3px;left:calc({porcentaje_barra:.2f}% - 7px);width:14px;height:14px;"
        f"border-radius:50%;background:{color_barra};box-shadow:0 0 6px {color_barra}'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:{color_barra};font-size:0.82rem;font-weight:600;font-family:monospace'>{numero_inversiones} inversiones</span>"
        f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>rango {amplitud:.0f} m</span>"
        f"</div></div>"
    )


def _html_barra_progreso_lineal(posicion_norte: float, longitud_campo: float) -> str:
    porcentaje = min(posicion_norte / longitud_campo * 100.0, 100.0)
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px'>"
        f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;text-transform:uppercase;font-family:monospace'>Recorrido del campo</span>"
        f"<span style='color:#e6edf3;font-size:1.5rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{porcentaje:.1f}<span style='color:#8b949e;font-size:0.9rem'>%</span></span>"
        f"</div>"
        f"<div style='background:#21262d;border-radius:4px;height:6px;overflow:hidden;margin-bottom:8px'>"
        f"<div style='background:linear-gradient(90deg,#238636 0%,#3fb950 100%);width:{porcentaje:.2f}%;height:100%;border-radius:4px'></div>"
        f"</div>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span style='color:#3fb950;font-size:0.82rem;font-weight:600;font-family:monospace'>{posicion_norte:.1f} m avanzados</span>"
        f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>meta {longitud_campo:.0f} m</span>"
        f"</div></div>"
    )


def _html_chip_error_trayectoria(etiqueta: str, valor_texto: str) -> str:
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:6px;"
        f"padding:0 12px;display:flex;align-items:center;gap:8px;height:38px;white-space:nowrap'>"
        f"<span style='font-size:0.85rem;color:#8b949e;font-family:monospace'>{etiqueta}</span>"
        f"<span style='font-size:0.85rem;font-weight:700;color:#e6edf3'>{valor_texto}</span>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------

@st.fragment(run_every=1)
def panel_principal():
    sim            = get_sim()
    lineal: Lineal | None = sim.lineal
    longitud_campo = sim.longitud_campo
    es_operador    = st.session_state.get("es_operador", False)

    if es_operador:
        _avanzar_simulacion(sim)
        lineal = sim.lineal

    st.markdown("# Gemelo Digital — Lineal FSS")

    # --- Insignia de estado ---
    if not es_operador and sim.lineal is not None:
        st.markdown(
            "<div style='display:inline-flex;align-items:center;gap:8px;"
            "background:rgba(88,166,255,0.08);border:1px solid rgba(88,166,255,0.25);"
            "border-radius:20px;padding:5px 14px;margin:4px 0'>"
            "<span style='width:8px;height:8px;border-radius:50%;background:#58a6ff;"
            "display:inline-block'></span>"
            "<span style='color:#58a6ff;font-weight:600;letter-spacing:1px;"
            "font-size:0.85rem'>MODO OBSERVADOR — solo lectura</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    if sim.completado:
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:10px;"
            f"background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.25);"
            f"border-radius:20px;padding:6px 16px;margin:4px 0'>"
            f"<span style='color:#3fb950;font-size:1rem'>✓</span>"
            f"<span style='color:#3fb950;font-weight:600;letter-spacing:1px;font-size:0.85rem'>RIEGO COMPLETADO</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>"
            f"· {lineal._tiempo_formateado()} · {lineal.ciclo_actual} ciclos · {lineal.posicion_norte:.1f} m</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif sim.en_marcha:
        st.markdown(
            _html_badge_en_marcha(
                lineal is not None and lineal.en_marcha_atras,
                sim.auto_reverse_activo,
                sim.numero_inversiones,
            ),
            unsafe_allow_html=True,
        )
    elif sim.pausado:
        st.markdown(
            "<div style='display:inline-flex;align-items:center;gap:8px;"
            "background:rgba(227,179,65,0.08);border:1px solid rgba(227,179,65,0.25);"
            "border-radius:20px;padding:5px 14px;margin:4px 0'>"
            "<span style='width:8px;height:8px;border-radius:50%;background:#e3b341;"
            "display:inline-block'></span>"
            "<span style='color:#e3b341;font-weight:600;letter-spacing:2px;font-size:0.85rem'>PAUSADO</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='display:inline-flex;align-items:center;gap:8px;"
            "background:rgba(139,148,158,0.06);border:1px solid #21262d;"
            "border-radius:20px;padding:5px 14px;margin:4px 0'>"
            "<span style='width:8px;height:8px;border-radius:50%;background:#484f58;"
            "display:inline-block'></span>"
            "<span style='color:#8b949e;letter-spacing:1px;font-size:0.85rem'>"
            "Configura el lineal en el panel izquierdo y pulsa INICIAR</span>"
            "</div>",
            unsafe_allow_html=True,
        )

    # --- Métricas principales ---
    columnas_metricas = st.columns(10)
    if lineal:
        porcentaje_recorrido = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        velocidad_teorica    = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        diferencia_velocidad = sim.velocidad_real - velocidad_teorica
        cart_en_slowdown     = lineal.slow_down_cart
        end_en_slowdown      = lineal.slow_down_end_tower

        estado_cart = ("★ ON"  if lineal.tramo_cart.motor_activo else "★ OFF") if cart_en_slowdown else \
                      ("ON"    if lineal.tramo_cart.motor_activo else "OFF")
        estado_end  = ("★ ON"  if lineal.tramo_end.motor_activo  else "★ OFF") if end_en_slowdown else \
                      ("ON"    if lineal.tramo_end.motor_activo  else "OFF")

        columnas_metricas[0].metric("Tiempo campo",  lineal._tiempo_formateado())
        columnas_metricas[1].metric("Ciclo",          str(lineal.ciclo_actual))
        columnas_metricas[2].metric("Posición media", f"{lineal.posicion_norte:.2f} m")
        columnas_metricas[3].metric("Recorrido",      f"{porcentaje_recorrido:.1f} %")
        columnas_metricas[4].metric("Alineación",     "OK" if lineal.esta_alineado else "Corrigiendo")
        columnas_metricas[5].metric("Cart",           estado_cart,
                                     help="★ = en slow_down, sigue al motor rápido" if cart_en_slowdown else None)
        columnas_metricas[6].metric("End-tower",      estado_end,
                                     help="★ = en slow_down, sigue al motor rápido" if end_en_slowdown else None)
        columnas_metricas[7].metric("Vel. real",      f"{sim.velocidad_real:.2f} m/min",
                                     delta=f"{diferencia_velocidad:+.2f} vs teórica", delta_color="normal")
        columnas_metricas[8].metric("Motor ★ activo", f"{lineal.motor_rapido_pct_on:.0f} %",
                                     help="% del último ciclo con el motor rápido encendido")
        columnas_metricas[9].metric("Dirección",      "▼ ATRÁS" if lineal.en_marcha_atras else "▲ ADELANTE")
    else:
        for columna in columnas_metricas:
            columna.metric("—", "—")

    # --- Barra de progreso ---
    if lineal:
        if sim.auto_reverse_activo:
            st.markdown(
                _html_barra_progreso_auto_reverse(lineal, sim.limite_sur, sim.limite_norte, sim.numero_inversiones),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                _html_barra_progreso_lineal(lineal.posicion_norte, longitud_campo),
                unsafe_allow_html=True,
            )

    # --- Métricas GPS ---
    if lineal and lineal.gps:
        gps                = lineal.gps
        indice_seccion_gps = lineal.secciones.index(gps.tramo)
        columnas_gps       = st.columns(4)
        lat                = gps.lat_e7 / 1e7
        lon                = gps.lon_e7 / 1e7
        previo             = sim.coordenadas_gps_previas
        delta_lat          = round(lat - previo["lat"], 7) if previo else None
        delta_lon          = round(lon - previo["lon"], 7) if previo else None

        columnas_gps[0].metric("GPS · Sección", f"TramoIntermedio {indice_seccion_gps}")
        columnas_gps[1].metric("Latitud",  f"{lat:.7f}°", delta=f"{delta_lat:+.7f}°" if delta_lat is not None else None)
        columnas_gps[2].metric("Longitud", f"{lon:.7f}°", delta=f"{delta_lon:+.7f}°" if delta_lon is not None else None)
        columnas_gps[3].metric("Formato ×10⁷", f"{gps.lat_e7}  /  {gps.lon_e7}")
        sim.coordenadas_gps_previas = {"lat": lat, "lon": lon}

    # --- Caja de interfaz Arduino ---
    if lineal and lineal.caja_interfaz:
        caja                = lineal.caja_interfaz
        indice_seccion_caja = lineal.secciones.index(caja.tramo)
        color_safety        = "#3fb950" if caja.safety_ok else "#f85149"
        color_gps_estado    = "#3fb950" if caja.gps_ok   else "#f85149"
        color_cart          = "#ffa657" if caja.slow_down_cart      else "#484f58"
        color_end           = "#ffa657" if caja.slow_down_end_tower else "#484f58"

        columnas_caja = st.columns(6)
        columnas_caja[0].metric("Caja · Sección GPS", f"TramoIntermedio {indice_seccion_caja}")
        columnas_caja[1].metric("GPS enviado", f"{caja.lat_e7} / {caja.lon_e7}",
                                 help=f"{caja.latitud:.7f}°  {caja.longitud:.7f}°  Carr {caja.carr}")
        columnas_caja[2].metric("Safety",     "OK"  if caja.safety_ok else "FAIL")
        columnas_caja[3].metric("GPS status", "OK"  if caja.gps_ok    else "FAIL")
        columnas_caja[4].metric("Slow Cart",  "ON"  if caja.slow_down_cart else "—")
        columnas_caja[5].metric("Slow EndT",  "ON"  if caja.slow_down_end_tower else "—")
        st.markdown(
            f"<div style='display:flex;gap:12px;margin:-12px 0 8px 0;flex-wrap:wrap;align-items:center'>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_safety};font-family:monospace'>"
            f"&#9679; SAFETY {'OK' if caja.safety_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_gps_estado};font-family:monospace'>"
            f"&#9679; GPS {'OK' if caja.gps_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_cart};font-family:monospace'>"
            f"&#9679; SLOW_CART {'ON' if caja.slow_down_cart else 'OFF'}</span>"
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_end};font-family:monospace'>"
            f"&#9679; SLOW_END_TWR {'ON' if caja.slow_down_end_tower else 'OFF'}</span>"
            f"<span style='font-size:0.82rem;color:#484f58;font-family:monospace'>"
            f"último msg: {caja.ultimo_mensaje or '—'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # --- Barra de herramientas: toggle, errores, log, CSV, GPS track ---
    trayectoria_visible = sim.trayectoria_activa or st.session_state.get("k_tray_activa", False)

    if trayectoria_visible:
        col_toggle, col_error_dist, col_error_rumbo, col_log, col_csv, col_gps_track = st.columns([1, 1, 1, 3, 1, 3])
    else:
        col_toggle, col_log, col_csv, col_gps_track = st.columns([1, 3, 1, 4])
        col_error_dist = col_error_rumbo = None

    with col_toggle:
        st.toggle("Vista general", key="k_vista_general",
                  help="OFF → escala 1:1 siguiendo al lineal  ·  ON → campo completo")

    if trayectoria_visible and col_error_dist is not None:
        texto_distancia = f"{sim.error_distancia_mm:.0f} mm" if sim.error_distancia_mm is not None else "—"
        texto_rumbo     = f"{sim.error_rumbo_grados:+.1f}°"  if sim.error_rumbo_grados is not None else "—"
        with col_error_dist:
            st.markdown(_html_chip_error_trayectoria("Δd", texto_distancia), unsafe_allow_html=True)
        with col_error_rumbo:
            st.markdown(_html_chip_error_trayectoria("Δrumbo", texto_rumbo), unsafe_allow_html=True)

    if lineal:
        with col_csv:
            tiene_datos = sim.csv_ruta and sim.csv_filas_escritas > 0
            if tiene_datos and not sim.en_marcha:
                with open(sim.csv_ruta, "rb") as archivo_csv:
                    st.download_button(
                        label="⬇ CSV", data=archivo_csv.read(),
                        file_name=os.path.basename(sim.csv_ruta),
                        mime="text/csv", width="stretch",
                    )

        with col_log:
            if len(sim.registro) > 1_000:
                sim.registro = sim.registro[-1_000:]
            colores_tipo = {
                "START": "#3fb950", "STOP": "#e3b341", "FIN": "#3fb950",
                "CRIT":  "#f85149", "OK":   "#58a6ff", "INFO": "#8b949e",
            }
            with st.expander(f"Registro  ({len(sim.registro)} entradas)", expanded=False):
                for entrada in sim.registro[-60:][::-1]:
                    color = colores_tipo.get(entrada["tipo"], "#8b949e")
                    st.markdown(
                        f"<code style='color:#484f58;font-size:0.75rem'>{entrada['t']}</code>&nbsp;"
                        f"<span style='background:{color}22;color:{color};border-radius:4px;"
                        f"padding:1px 7px;font-size:0.68rem;font-family:monospace;font-weight:700'>"
                        f"{entrada['tipo']}</span>&nbsp;"
                        f"<span style='color:#e6edf3;font-size:0.82rem'>{entrada['msg']}</span>",
                        unsafe_allow_html=True,
                    )

        with col_gps_track:
            if sim.historial_gps:
                with st.expander(f"Track GPS — {len(sim.historial_gps)} lecturas", expanded=False):
                    st.dataframe(sim.historial_gps[::-1], hide_index=True, width="stretch")

    # --- Figura Plotly del campo ---
    posicion_norte = lineal.posicion_norte if lineal is not None else 0.0

    if st.session_state.get("k_tray_activa", False) and lineal is not None:
        lat_fig, lon_fig = get_origen_latlon()
        pts_fig = parse_trayectoria(st.session_state.get("k_tray_input", ""), lat_fig, lon_fig)
        puntos_figura = pts_fig if len(pts_fig) >= 2 else None
    else:
        puntos_figura = sim.trayectoria_puntos

    st.plotly_chart(
        build_figure(
            lineal, longitud_campo, posicion_norte,
            st.session_state.get("k_vista_general", False),
            rastros_secciones=sim.rastros_secciones,
            trayectoria_xy=puntos_figura,
        ),
        width="stretch",
        key="campo_lineal_v2",
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
            "toImageButtonOptions": {"filename": "lineal_fss_v2", "format": "png"},
        },
    )
