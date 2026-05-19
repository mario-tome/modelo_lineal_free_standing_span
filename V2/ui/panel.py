
import csv, math, os
import streamlit as st
from V2.modelos import Lineal
from V2.logica.constantes import TERRENOS
from V2.logica.estado import get_sim, SimState
from V2.logica.trayectoria import get_origen_latlon, parse_trayectoria, calcular_errores
from V2.ui.figura import build_figure


def _escribir_fila_csv(sim: SimState, fila: dict) -> None:
    ruta = sim.get("csv_ruta")
    if not ruta:
        return
    primera_vez = (sim.csv_filas_escritas == 0)
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fila.keys()), restval="", extrasaction="ignore")
        if primera_vez:
            writer.writeheader()
        writer.writerow(fila)
    sim.csv_filas_escritas += 1


def _avanzar_simulacion(sim: SimState) -> None:
    """Avanza un tick y actualiza datos derivados. Solo sesión operador."""
    lineal = sim.lineal
    if lineal is None:
        sim.trayectoria_activa    = False
        sim.trayectoria_puntos_xy = None
        return

    ui = st.session_state

    if ui.get("k_tray_activa", False):
        lat_t, lon_t = get_origen_latlon()
        puntos_tray = parse_trayectoria(ui.get("k_tray_input", ""), lat_t, lon_t)
        if len(puntos_tray) >= 2:
            sim.trayectoria_activa    = True
            sim.trayectoria_puntos_xy = puntos_tray
        else:
            sim.trayectoria_activa    = False
            sim.trayectoria_puntos_xy = None
            puntos_tray = []
    else:
        sim.trayectoria_activa    = False
        sim.trayectoria_puntos_xy = None
        puntos_tray = []

    lineal.set_speed(ui.get("k_vpct", 50))
    nivel_patinaje = TERRENOS.get(ui.get("k_terreno", "Normal"), 0.012)
    lineal.tramo_cart.ruido_lateral = nivel_patinaje
    lineal.tramo_end.ruido_lateral  = nivel_patinaje
    interferencia_mm = float(ui.get("k_interferencia_gps_mm", 0))
    if lineal.gps:
        lineal.gps.interferencia_gps_mm = interferencia_mm
    elif lineal.caja_interfaz:
        lineal.caja_interfaz.interferencia_gps_mm = interferencia_mm

    sim.sim_auto_reverse = bool(ui.get("k_auto_reverse", False))
    sim.sim_ar_ymin = float(ui.get("k_ar_ymin", 0))
    sim.sim_ar_ymax = float(ui.get("k_ar_ymax", sim.longitud_campo))

    if lineal.caja_interfaz:
        caja = lineal.caja_interfaz
        prev = sim.caja_slow_prev

        if sim.running:
            if caja.slow_down_cart != prev["cart"]:
                prev["cart"] = caja.slow_down_cart
                sim.log.append({
                    "t": lineal._tiempo_formateado(), "tipo": "INFO",
                    "msg": ("SLOW_DOWN_CART ON — Cart ralentizado, giro gradual hacia izquierda"
                            if caja.slow_down_cart
                            else "SLOW_DOWN_CART OFF — Cart a velocidad normal"),
                })
            if caja.slow_down_end_tower != prev["end"]:
                prev["end"] = caja.slow_down_end_tower
                sim.log.append({
                    "t": lineal._tiempo_formateado(), "tipo": "INFO",
                    "msg": ("SLOW_DOWN_END_TOWER ON — End-tower ralentizado, giro gradual hacia derecha"
                            if caja.slow_down_end_tower
                            else "SLOW_DOWN_END_TOWER OFF — End-tower a velocidad normal"),
                })
            lineal.slow_down_cart      = caja.slow_down_cart
            lineal.slow_down_end_tower = caja.slow_down_end_tower

        if not caja.safety_ok and prev.get("safety", True):
            prev["safety"] = False
            lineal.stop()
            sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "CRIT", "msg": "SAFETY_FAIL — parada de emergencia"})
            sim.running = False; sim.paused = True; sim.motivo_pausa = "safety_fail"
        elif caja.safety_ok and not prev.get("safety", True):
            prev["safety"] = True
            sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "OK", "msg": "SAFETY_OK — seguridad restaurada (reanuda manualmente)"})

        if not caja.gps_ok and prev.get("gps", True):
            prev["gps"] = False
            if sim.running:
                lineal.stop(); sim.running = False; sim.paused = True
                sim.motivo_pausa = "gps_fail"
            sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "CRIT", "msg": "GPS_FAIL — señal GPS perdida, simulación pausada"})
        elif caja.gps_ok and not prev.get("gps", True):
            prev["gps"] = True
            sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "OK", "msg": "GPS_OK — señal GPS restaurada"})
            if sim.paused and sim.motivo_pausa == "gps_fail":
                lineal.start(); caja.iniciar()
                sim.running = True; sim.paused = False; sim.motivo_pausa = None
                sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "START", "msg": "Reanudación automática tras recuperar GPS"})

    if sim.running and not sim.finished:
        segundos_por_tick = ui.get("k_simspd", 60)
        lineal.avanza(segundos_por_tick)

        if sim.tower_trails is not None and len(sim.tower_trails) == len(lineal.secciones):
            for idx, sec in enumerate(lineal.secciones):
                trail = sim.tower_trails[idx]
                xn, yn = sec.posicion_x, sec.posicion_y
                if not trail or math.hypot(xn - trail[-1][0], yn - trail[-1][1]) >= 0.5:
                    trail.append((xn, yn))
            if len(sim.tower_trails[0]) > 20_000:
                sim.tower_trails = [tr[-20_000:] for tr in sim.tower_trails]

        sim.vel_real = (lineal.posicion_norte - sim.pos_prev) / (segundos_por_tick / 60.0)
        sim.pos_prev = lineal.posicion_norte

        fila = {
            "tiempo_s":       lineal.tiempo_total_segundos,
            "tiempo":         lineal._tiempo_formateado(),
            "posicion_norte": round(lineal.posicion_norte, 3),
            "slow_cart":      lineal.slow_down_cart,
            "slow_end_tower": lineal.slow_down_end_tower,
        }
        longitud_nominal = lineal.longitud_tramo
        for j, sec in enumerate(lineal.secciones):
            fila[f"seccion_{j}_x"] = round(sec.posicion_x, 4)
            fila[f"seccion_{j}_y"] = round(sec.posicion_y, 4)
            if j < lineal.numero_tramos:
                sp = lineal.get_span_info(j)
                fila[f"tramo_{j+1}_L_calculado"] = round(sp["longitud"], 4)
                fila[f"tramo_{j+1}_deform_m"]    = round(longitud_nominal - sp["longitud"], 4)
                fila[f"tramo_{j+1}_desv_y"]      = round(sp["desviacion_norte"], 4)
                fila[f"tramo_{j+1}_rumbo_deg"]   = round(sp["angulo_grados"], 4)

        fila["lat_e7"]      = lineal.gps.lat_e7 if lineal.gps else None
        fila["lon_e7"]      = lineal.gps.lon_e7 if lineal.gps else None
        fila["EΔd_mm"]      = None
        fila["EΔrumbo_deg"] = None

        if sim.trayectoria_activa and puntos_tray:
            tramo_gps, indice_gps = _get_tramo_gps(lineal, sim)
            if tramo_gps is not None:
                historial = (sim.tower_trails[indice_gps]
                             if sim.tower_trails and indice_gps < len(sim.tower_trails) else [])
                error_distancia, error_rumbo = calcular_errores(
                    tramo_gps.posicion_x, tramo_gps.posicion_y,
                    puntos_tray, historial, lineal.en_marcha_atras,
                )
                fila["EΔd_mm"]      = round(error_distancia, 1) if error_distancia is not None else None
                fila["EΔrumbo_deg"] = round(error_rumbo, 2)     if error_rumbo is not None else None

        _escribir_fila_csv(sim, fila)

        if lineal.gps:
            sim.gps_track.append({
                "Tiempo":    lineal._tiempo_formateado(),
                "LAT ×10⁷": lineal.gps.lat_e7,
                "LON ×10⁷": lineal.gps.lon_e7,
                "Lat (°)":   round(lineal.gps.latitud, 7),
                "Lon (°)":   round(lineal.gps.longitud, 7),
            })
            if len(sim.gps_track) > 20:
                sim.gps_track = sim.gps_track[-20:]

        tramos_ok = [lineal.get_span_alineado(j) for j in range(lineal.numero_tramos)]
        if sim.tramos_ok_prev is not None:
            for j, (estado_previo, estado_actual) in enumerate(zip(sim.tramos_ok_prev, tramos_ok)):
                if estado_previo and not estado_actual:
                    sp = lineal.get_span_info(j)
                    sim.log.append({
                        "t": lineal._tiempo_formateado(), "tipo": "CRIT",
                        "msg": f"Tramo {j+1} desalineado  ({sp['desviacion_norte']:+.3f} m)",
                    })
                elif not estado_previo and estado_actual:
                    sim.log.append({
                        "t": lineal._tiempo_formateado(), "tipo": "OK",
                        "msg": f"Tramo {j+1} recuperado",
                    })
        sim.tramos_ok_prev = tramos_ok

        auto_reverse_activo = sim.sim_auto_reverse
        limite_sur   = sim.sim_ar_ymin
        limite_norte = sim.sim_ar_ymax

        if auto_reverse_activo:
            posicion = lineal.posicion_norte
            if not lineal.en_marcha_atras and posicion >= limite_norte:
                lineal.invertir_direccion()
                sim.ar_pasadas += 1
                sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "INFO",
                                 "msg": f"Auto-reverse ▼  ({posicion:.1f} m ≥ {limite_norte:.0f} m)  — pasada #{sim.ar_pasadas}"})
            elif lineal.en_marcha_atras and posicion <= limite_sur:
                lineal.invertir_direccion()
                sim.ar_pasadas += 1
                sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "INFO",
                                 "msg": f"Auto-reverse ▲  ({posicion:.1f} m ≤ {limite_sur:.0f} m)  — pasada #{sim.ar_pasadas}"})
        else:
            if lineal.posicion_norte >= sim.longitud_campo:
                lineal.stop()
                if lineal.gps:
                    lineal.gps.detener_transmision_background()
                sim.log.append({"t": lineal._tiempo_formateado(), "tipo": "FIN",
                                 "msg": f"Riego completado — {lineal.posicion_norte:.2f} m en {lineal._tiempo_formateado()}"})
                sim.running = False; sim.finished = True
                st.rerun()
                return

    if sim.trayectoria_activa and puntos_tray:
        tramo_gps, indice_gps = _get_tramo_gps(lineal, sim)
        if tramo_gps is not None:
            historial = (sim.tower_trails[indice_gps]
                         if sim.tower_trails and indice_gps < len(sim.tower_trails) else [])
            error_distancia, error_rumbo = calcular_errores(
                tramo_gps.posicion_x, tramo_gps.posicion_y,
                puntos_tray, historial, lineal.en_marcha_atras,
            )
            sim.trayectoria_ead_mm     = error_distancia
            sim.trayectoria_erumbo_deg = error_rumbo
        else:
            sim.trayectoria_ead_mm = sim.trayectoria_erumbo_deg = None
    else:
        sim.trayectoria_ead_mm = sim.trayectoria_erumbo_deg = None


def _get_tramo_gps(lineal: Lineal, sim) -> tuple:
    """Devuelve (tramo_gps, indice) o (None, -1)."""
    if lineal.gps:
        tramo = lineal.gps.tramo
        try:
            return tramo, lineal.secciones.index(tramo)
        except ValueError:
            return None, -1
    if lineal.caja_interfaz:
        tramo = lineal.caja_interfaz.tramo
        try:
            return tramo, lineal.secciones.index(tramo)
        except ValueError:
            return None, -1
    return None, -1


def _html_badge_en_marcha(en_marcha_atras: bool, auto_reverse_activo: bool, numero_inversiones: int) -> str:
    color = "#ff7b72" if en_marcha_atras else "#3fb950"
    fondo = "rgba(255,123,114,0.08)" if en_marcha_atras else "rgba(63,185,80,0.08)"
    borde = "rgba(255,123,114,0.25)" if en_marcha_atras else "rgba(63,185,80,0.25)"
    texto = "&#9660; MARCHA ATRÁS" if en_marcha_atras else "&#9650; EN MARCHA"
    sufijo_auto_reverse = (
        f"&nbsp;<span style='color:#8b949e;font-weight:400;font-size:0.75rem;letter-spacing:1px'>"
        f"AUTO-REVERSE · {numero_inversiones} inv.</span>" if auto_reverse_activo else ""
    )
    return (
        f"<div style='display:inline-flex;align-items:center;gap:8px;"
        f"background:{fondo};border:1px solid {borde};"
        f"border-radius:20px;padding:5px 14px;margin:4px 0'>"
        f"<span style='width:8px;height:8px;border-radius:50%;background:{color};"
        f"display:inline-block;box-shadow:0 0 6px {color}'></span>"
        f"<span style='color:{color};font-weight:600;letter-spacing:2px;font-size:0.85rem'>"
        f"{texto}</span>{sufijo_auto_reverse}</div>"
    )


def _html_barra_progreso_auto_reverse(
    lineal: Lineal, limite_sur: float, limite_norte: float, numero_inversiones: int
) -> str:
    amplitud = max(limite_norte - limite_sur, 1.0)
    posicion_acotada = max(limite_sur, min(limite_norte, lineal.posicion_norte))
    porcentaje_barra = (posicion_acotada - limite_sur) / amplitud * 100.0
    color_barra = "#ff7b72" if lineal.en_marcha_atras else "#3fb950"
    simbolo_direccion = "▼" if lineal.en_marcha_atras else "▲"
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
        f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px'>"
        f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;text-transform:uppercase;font-family:monospace'>"
        f"Auto-reverse  ·  {limite_sur:.0f} m — {limite_norte:.0f} m</span>"
        f"<span style='color:{color_barra};font-size:1.5rem;font-weight:700;font-family:monospace;line-height:1'>"
        f"{simbolo_direccion}&nbsp;{lineal.posicion_norte:.1f}<span style='color:#8b949e;font-size:0.9rem'> m</span></span>"
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


@st.fragment(run_every=1)
def panel_principal():
    sim = get_sim()
    lineal: Lineal | None = sim.lineal
    longitud_campo = sim.longitud_campo
    es_operador = st.session_state.get("_is_operator", False)

    if es_operador:
        _avanzar_simulacion(sim)
        lineal = sim.lineal

    st.markdown("# Gemelo Digital Lineal")

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

    if sim.finished:
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:10px;"
            f"background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.25);"
            f"border-radius:20px;padding:6px 16px;margin:4px 0'>"
            f"<span style='color:#3fb950;font-size:1rem'>✓</span>"
            f"<span style='color:#3fb950;font-weight:600;letter-spacing:1px;font-size:0.85rem'>RIEGO COMPLETADO</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>· {lineal._tiempo_formateado()} · {lineal.ciclo_actual} ciclos · {lineal.posicion_norte:.1f} m</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif sim.running:
        en_marcha_atras     = lineal is not None and lineal.en_marcha_atras
        auto_reverse_activo = sim.sim_auto_reverse
        st.markdown(
            _html_badge_en_marcha(en_marcha_atras, auto_reverse_activo, sim.ar_pasadas),
            unsafe_allow_html=True,
        )
    elif sim.paused:
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

    # MÉTRICAS PRINCIPALES
    columnas_metricas = st.columns(10)
    if lineal:
        porcentaje_recorrido = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        velocidad_teorica    = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        velocidad_real       = sim.vel_real
        diferencia_velocidad = velocidad_real - velocidad_teorica
        cart_en_slowdown     = lineal.slow_down_cart
        end_en_slowdown      = lineal.slow_down_end_tower
        estado_cart = ("★ ON"  if lineal.tramo_cart.motor_activo else "★ OFF") if cart_en_slowdown else \
                      ("ON"    if lineal.tramo_cart.motor_activo else "OFF")
        estado_end  = ("★ ON"  if lineal.tramo_end.motor_activo  else "★ OFF") if end_en_slowdown else \
                      ("ON"    if lineal.tramo_end.motor_activo  else "OFF")

        columnas_metricas[0].metric("Tiempo campo", lineal._tiempo_formateado())
        columnas_metricas[1].metric("Ciclo", str(lineal.ciclo_actual))
        columnas_metricas[2].metric("Posición media", f"{lineal.posicion_norte:.2f} m")
        columnas_metricas[3].metric("Recorrido", f"{porcentaje_recorrido:.1f} %")
        columnas_metricas[4].metric("Alineación", "OK" if lineal.esta_alineado else "Corrigiendo")
        columnas_metricas[5].metric("Cart", estado_cart,
                                     help="★ = en slow_down, sigue al motor rápido" if cart_en_slowdown else None)
        columnas_metricas[6].metric("End-tower", estado_end,
                                     help="★ = en slow_down, sigue al motor rápido" if end_en_slowdown else None)
        columnas_metricas[7].metric("Vel. real", f"{velocidad_real:.2f} m/min",
                                     delta=f"{diferencia_velocidad:+.2f} vs teórica", delta_color="normal")
        columnas_metricas[8].metric("Motor ★ activo", f"{lineal.motor_rapido_pct_on:.0f} %",
                                     help="% del último ciclo completo con el motor rápido encendido")
        columnas_metricas[9].metric("Dirección", "▼ ATRÁS" if lineal.en_marcha_atras else "▲ ADELANTE")
    else:
        for columna in columnas_metricas:
            columna.metric("—", "—")

    # BARRA DE PROGRESO
    if lineal:
        auto_reverse_activo = sim.sim_auto_reverse
        limite_sur   = sim.sim_ar_ymin
        limite_norte = sim.sim_ar_ymax

        if auto_reverse_activo:
            st.markdown(
                _html_barra_progreso_auto_reverse(lineal, limite_sur, limite_norte, sim.ar_pasadas),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                _html_barra_progreso_lineal(lineal.posicion_norte, longitud_campo),
                unsafe_allow_html=True,
            )

    # MÉTRICAS GPS
    if lineal and lineal.gps:
        gps = lineal.gps
        indice_seccion_gps = lineal.secciones.index(gps.tramo)
        columnas_gps = st.columns(4)
        lat = gps.lat_e7 / 1e7
        lon = gps.lon_e7 / 1e7
        gps_anterior = sim.gps_prev
        delta_lat = round(lat - gps_anterior["lat"], 7) if gps_anterior else None
        delta_lon = round(lon - gps_anterior["lon"], 7) if gps_anterior else None
        columnas_gps[0].metric("GPS · Sección", f"TramoIntermedio {indice_seccion_gps}")
        columnas_gps[1].metric("Latitud",  f"{lat:.7f}°", delta=f"{delta_lat:+.7f}°" if delta_lat is not None else None)
        columnas_gps[2].metric("Longitud", f"{lon:.7f}°", delta=f"{delta_lon:+.7f}°" if delta_lon is not None else None)
        columnas_gps[3].metric("Formato ×10⁷", f"{gps.lat_e7}  /  {gps.lon_e7}")
        sim.gps_prev = {"lat": lat, "lon": lon}

    # CAJA DE INTERFAZ
    if lineal and lineal.caja_interfaz:
        caja = lineal.caja_interfaz
        indice_seccion_caja = lineal.secciones.index(caja.tramo)
        color_safety = "#3fb950" if caja.safety_ok else "#f85149"
        color_gps    = "#3fb950" if caja.gps_ok else "#f85149"
        color_cart   = "#ffa657" if caja.slow_down_cart else "#484f58"
        color_end    = "#ffa657" if caja.slow_down_end_tower else "#484f58"
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
            f"<span style='font-size:0.92rem;font-weight:700;color:{color_gps};font-family:monospace'>"
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

    trayectoria_visible = sim.trayectoria_activa or st.session_state.get("k_tray_activa", False)

    if trayectoria_visible:
        col_toggle, col_error_distancia, col_error_rumbo, col_log, col_csv, col_gps_track = st.columns([1, 1, 1, 3, 1, 3])
    else:
        col_toggle, col_log, col_csv, col_gps_track = st.columns([1, 3, 1, 4])
        col_error_distancia = col_error_rumbo = None

    with col_toggle:
        st.toggle("Vista general", key="k_vista_general",
                  help="OFF → escala 1:1 siguiendo al lineal  ·  ON → campo completo")

    if trayectoria_visible and col_error_distancia is not None:
        error_distancia_mm = sim.trayectoria_ead_mm
        error_rumbo_grados = sim.trayectoria_erumbo_deg
        texto_distancia = f"{error_distancia_mm:.0f} mm" if error_distancia_mm is not None else "—"
        texto_rumbo     = f"{error_rumbo_grados:+.1f}°"  if error_rumbo_grados is not None else "—"
        with col_error_distancia:
            st.markdown(_html_chip_error_trayectoria("Δd", texto_distancia), unsafe_allow_html=True)
        with col_error_rumbo:
            st.markdown(_html_chip_error_trayectoria("Δrumbo", texto_rumbo), unsafe_allow_html=True)

    if lineal:
        with col_csv:
            tiene_datos = sim.csv_ruta and sim.csv_filas_escritas > 0
            if tiene_datos and not sim.running:
                with open(sim.csv_ruta, "rb") as f:
                    csv_bytes = f.read()
                st.download_button(
                    label="⬇ CSV", data=csv_bytes,
                    file_name=os.path.basename(sim.csv_ruta),
                    mime="text/csv", width="stretch",
                )

        with col_log:
            if len(sim.log) > 1_000:
                sim.log = sim.log[-1_000:]
            colores_tipo = {
                "START": "#3fb950", "STOP": "#e3b341", "FIN": "#3fb950",
                "CRIT":  "#f85149", "OK":   "#58a6ff", "INFO": "#8b949e",
            }
            entradas_recientes = sim.log[-60:][::-1]
            with st.expander(f"Log  ({len(sim.log)} entradas)", expanded=False):
                for entrada in entradas_recientes:
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
            if sim.gps_track:
                with st.expander(f"Track GPS — {len(sim.gps_track)} lecturas", expanded=False):
                    st.dataframe(sim.gps_track[::-1], hide_index=True, width="stretch")

    posicion_norte = lineal.posicion_norte if lineal is not None else 0.0

    if st.session_state.get("k_tray_activa", False) and lineal is not None:
        lat_fig, lon_fig = get_origen_latlon()
        pts_fig = parse_trayectoria(st.session_state.get("k_tray_input", ""), lat_fig, lon_fig)
        puntos_figura = pts_fig if len(pts_fig) >= 2 else None
    else:
        puntos_figura = sim.trayectoria_puntos_xy

    st.plotly_chart(
        build_figure(
            lineal, longitud_campo, posicion_norte,
            st.session_state.get("k_vista_general", False),
            tower_trails=sim.tower_trails,
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
