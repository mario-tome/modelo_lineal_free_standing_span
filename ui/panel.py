import csv
import io
import math
import streamlit as st
from modelo import Lineal
from logica.constantes import TERRENOS
from logica.trayectoria import get_origen_latlon, parse_trayectoria, calcular_errores
from ui.figura import build_figure


@st.fragment(run_every=1)
def panel_principal():
    state          = st.session_state
    lineal: Lineal | None = state.lineal
    longitud_campo = state.longitud_campo

    # Sincronizar parámetros live con el modelo
    if lineal is not None:
        lineal.set_speed(state.get("k_vpct", 50))
        ruido_live = TERRENOS.get(state.get("k_terreno", "Normal"), 0.012)
        lineal.guia_izquierda.ruido_lateral = ruido_live
        lineal.guia_derecha.ruido_lateral   = ruido_live

    # Caja de interfaz: propagar flags y detectar cambios de estado
    if state.running and lineal is not None and lineal.caja_interfaz:
        caja  = lineal.caja_interfaz
        prev  = state.caja_slow_prev

        if caja.slow_down_cart != prev["cart"]:
            prev["cart"] = caja.slow_down_cart
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_CART ON — Cart ralentizado, giro gradual hacia izquierda"
                        if caja.slow_down_cart else "SLOW_DOWN_CART OFF — Cart a velocidad normal"),
            })
        if caja.slow_down_end_tower != prev["end"]:
            prev["end"] = caja.slow_down_end_tower
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "INFO",
                "msg": ("SLOW_DOWN_END_TOWER ON — End-tower ralentizado, giro gradual hacia derecha"
                        if caja.slow_down_end_tower else "SLOW_DOWN_END_TOWER OFF — End-tower a velocidad normal"),
            })

        lineal.slow_down_cart      = caja.slow_down_cart
        lineal.slow_down_end_tower = caja.slow_down_end_tower

        if not caja.safety_ok and prev["safety"]:
            prev["safety"] = False
            lineal.stop()
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "CRIT",
                "msg": "SAFETY_FAIL — parada de emergencia",
            })
            state.running = False
            state.paused  = True
        elif caja.safety_ok and not prev["safety"]:
            prev["safety"] = True
            state.log.append({
                "t": lineal._tiempo_formateado(), "tipo": "OK",
                "msg": "SAFETY_OK — seguridad restaurada (reanuda manualmente)",
            })

    # Avance de simulación
    if state.running and not state.finished and lineal is not None:
        segundos_simulacion = state.get("k_simspd", 60)
        lineal.avanza(segundos_simulacion)

        if state.tower_trails is not None and len(state.tower_trails) == len(lineal.torres):
            for idx, torre in enumerate(lineal.torres):
                trail = state.tower_trails[idx]
                xn, yn = torre.posicion_x, torre.posicion_y
                # Solo guardar si la torre se movió ≥ 0.5 m desde el último punto registrado.
                # Así el trail cubre siempre toda la ruta real sin importar k_simspd.
                if not trail or math.hypot(xn - trail[-1][0], yn - trail[-1][1]) >= 0.5:
                    trail.append((xn, yn))
            if len(state.tower_trails[0]) > 20_000:
                state.tower_trails = [tr[-20_000:] for tr in state.tower_trails]

        state.vel_real = (lineal.posicion_norte - state.pos_prev) / (segundos_simulacion / 60.0)
        state.pos_prev = lineal.posicion_norte

        # Construir fila CSV
        fila = {
            "tiempo_s":       lineal.tiempo_total_segundos,
            "tiempo":         lineal._tiempo_formateado(),
            "posicion_norte": round(lineal.posicion_norte, 3),
            "slow_cart":      lineal.slow_down_cart,
            "slow_end_tower": lineal.slow_down_end_tower,
        }
        longitud_tramo_nominal = lineal.longitud_tramo
        for j, torre in enumerate(lineal.torres):
            fila[f"torre_{j}_x"] = round(torre.posicion_x, 4)
            fila[f"torre_{j}_y"] = round(torre.posicion_y, 4)
            if j < lineal.numero_tramos:
                tramo   = lineal.tramos[j]
                delta_x = tramo.torre_derecha.posicion_x - tramo.torre_izquierda.posicion_x
                delta_y = tramo.desviacion_norte
                longitud_calculada = round((delta_x**2 + delta_y**2) ** 0.5, 4)
                fila[f"tramo_{j+1}_L_calculado"] = longitud_calculada
                fila[f"tramo_{j+1}_deform_m"]    = round(longitud_tramo_nominal - longitud_calculada, 4)
                fila[f"tramo_{j+1}_desv_y"]      = round(delta_y, 4)
                fila[f"tramo_{j+1}_rumbo_deg"]   = round(tramo.angulo_grados, 4)
        if lineal.gps:
            fila["lat_e7"] = lineal.gps.lat_e7
            fila["lon_e7"] = lineal.gps.lon_e7

        if state.get("k_tray_activa", False):
            lat_origen, lon_origen = get_origen_latlon()
            puntos_trayectoria     = parse_trayectoria(state.get("k_tray_input", ""), lat_origen, lon_origen)
            torre_gps, indice_torre_gps = None, -1
            if lineal.gps:
                torre_gps       = lineal.gps.torre
                indice_torre_gps = lineal.torres.index(torre_gps)
            elif lineal.caja_interfaz:
                torre_gps       = lineal.caja_interfaz.torre
                indice_torre_gps = lineal.torres.index(torre_gps)
            if torre_gps is not None and len(puntos_trayectoria) >= 2:
                historial_torre = (state.tower_trails[indice_torre_gps]
                                   if state.tower_trails and indice_torre_gps < len(state.tower_trails) else [])
                error_distancia, error_rumbo = calcular_errores(
                    torre_gps.posicion_x, torre_gps.posicion_y, puntos_trayectoria, historial_torre)
                fila["EΔd_mm"]      = round(error_distancia, 1) if error_distancia is not None else None
                fila["EΔrumbo_deg"] = round(error_rumbo, 2)     if error_rumbo     is not None else None
            else:
                fila["EΔd_mm"] = fila["EΔrumbo_deg"] = None
        state.historial.append(fila)

        if lineal.gps:
            state.gps_track.append({
                "Tiempo":    lineal._tiempo_formateado(),
                "LAT ×10⁷": lineal.gps.lat_e7,
                "LON ×10⁷": lineal.gps.lon_e7,
                "Lat (°)":   round(lineal.gps.latitud, 7),
                "Lon (°)":   round(lineal.gps.longitud, 7),
            })
            if len(state.gps_track) > 20:
                state.gps_track = state.gps_track[-20:]

        # Log: cambios de alineación en tramos
        tramos_ok = [t.esta_alineado for t in lineal.tramos]
        if state.tramos_ok_prev is not None:
            for j, (estado_prev, estado_actual) in enumerate(zip(state.tramos_ok_prev, tramos_ok)):
                if estado_prev and not estado_actual:
                    state.log.append({
                        "t":    lineal._tiempo_formateado(),
                        "tipo": "CRIT",
                        "msg":  f"Tramo {j+1} desalineado  ({lineal.tramos[j].desviacion_norte:+.3f} m)",
                    })
                elif not estado_prev and estado_actual:
                    state.log.append({
                        "t":    lineal._tiempo_formateado(),
                        "tipo": "OK",
                        "msg":  f"Tramo {j+1} recuperado",
                    })
        state.tramos_ok_prev = tramos_ok

        # Auto-reverse o parada al llegar al límite del campo
        auto_reverse = state.get("k_auto_reverse", False)
        limite_sur   = float(state.get("k_ar_ymin", 0))
        limite_norte = float(state.get("k_ar_ymax", longitud_campo))

        if auto_reverse:
            pos = lineal.posicion_norte
            if not lineal.en_marcha_atras and pos >= limite_norte:
                lineal.invertir_direccion()
                state.ar_pasadas += 1
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "INFO",
                    "msg":  f"Auto-reverse ▼  ({pos:.1f} m ≥ {limite_norte:.0f} m)  "
                            f"— pasada #{state.ar_pasadas}",
                })
            elif lineal.en_marcha_atras and pos <= limite_sur:
                lineal.invertir_direccion()
                state.ar_pasadas += 1
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "INFO",
                    "msg":  f"Auto-reverse ▲  ({pos:.1f} m ≤ {limite_sur:.0f} m)  "
                            f"— pasada #{state.ar_pasadas}",
                })
        else:
            if lineal.posicion_norte >= longitud_campo:
                lineal.stop()
                if lineal.gps:
                    lineal.gps.detener_transmision_background()
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "FIN",
                    "msg":  f"Riego completado — {lineal.posicion_norte:.2f} m en {lineal._tiempo_formateado()}",
                })
                state.running  = False
                state.finished = True
                st.rerun()
                return

    # Errores de trayectoria: calculados en cada refresco (running o parado)
    if state.get("k_tray_activa", False) and lineal is not None:
        lat_origen, lon_origen = get_origen_latlon()
        puntos_trayectoria     = parse_trayectoria(state.get("k_tray_input", ""), lat_origen, lon_origen)
        torre_gps, indice_torre_gps = None, -1
        if lineal.gps:
            torre_gps        = lineal.gps.torre
            indice_torre_gps = lineal.torres.index(torre_gps)
        elif lineal.caja_interfaz:
            torre_gps        = lineal.caja_interfaz.torre
            indice_torre_gps = lineal.torres.index(torre_gps)
        if torre_gps is not None and len(puntos_trayectoria) >= 2:
            historial_torre = (state.tower_trails[indice_torre_gps]
                               if state.tower_trails and indice_torre_gps < len(state.tower_trails) else [])
            error_distancia, error_rumbo = calcular_errores(
                torre_gps.posicion_x, torre_gps.posicion_y, puntos_trayectoria, historial_torre)
            state.trayectoria_ead_mm     = error_distancia
            state.trayectoria_erumbo_deg = error_rumbo
        else:
            state.trayectoria_ead_mm = state.trayectoria_erumbo_deg = None
    else:
        state.trayectoria_ead_mm = state.trayectoria_erumbo_deg = None

    # CABECERA
    st.markdown("# Gemelo Digital Lineal")

    if state.finished:
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:10px;"
            f"background:rgba(63,185,80,0.08);border:1px solid rgba(63,185,80,0.25);"
            f"border-radius:20px;padding:6px 16px;margin:4px 0'>"
            f"<span style='color:#3fb950;font-size:1rem'>✓</span>"
            f"<span style='color:#3fb950;font-weight:600;letter-spacing:1px;font-size:0.85rem'>RIEGO COMPLETADO</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>·</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>{lineal._tiempo_formateado()}</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>·</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>{lineal.ciclo_actual} ciclos</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>·</span>"
            f"<span style='color:#8b949e;font-size:0.8rem'>{lineal.posicion_norte:.1f} m</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif state.running:
        en_marcha_atras = lineal is not None and lineal.en_marcha_atras
        auto_reverse    = state.get("k_auto_reverse", False)
        color           = "#ff7b72" if en_marcha_atras else "#3fb950"
        fondo           = "rgba(255,123,114,0.08)" if en_marcha_atras else "rgba(63,185,80,0.08)"
        borde           = "rgba(255,123,114,0.25)" if en_marcha_atras else "rgba(63,185,80,0.25)"
        texto_estado    = "&#9660; MARCHA ATRÁS" if en_marcha_atras else "&#9650; EN MARCHA"
        sufijo_ar = (
            f"&nbsp;<span style='color:#8b949e;font-weight:400;font-size:0.75rem;letter-spacing:1px'>"
            f"AUTO-REVERSE · {state.ar_pasadas} inv.</span>"
            if auto_reverse else ""
        )
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:8px;"
            f"background:{fondo};border:1px solid {borde};"
            f"border-radius:20px;padding:5px 14px;margin:4px 0'>"
            f"<span style='width:8px;height:8px;border-radius:50%;background:{color};"
            f"display:inline-block;box-shadow:0 0 6px {color}'></span>"
            f"<span style='color:{color};font-weight:600;letter-spacing:2px;font-size:0.85rem'>"
            f"{texto_estado}</span>"
            f"{sufijo_ar}"
            f"</div>",
            unsafe_allow_html=True,
        )
    elif state.paused:
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
        porcentaje       = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        velocidad_teorica = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        velocidad_real    = state.get("vel_real", 0.0)
        diferencia_velocidad = velocidad_real - velocidad_teorica
        columnas_metricas[0].metric("Tiempo campo",    lineal._tiempo_formateado())
        columnas_metricas[1].metric("Ciclo",           str(lineal.ciclo_actual))
        columnas_metricas[2].metric("Posición media",  f"{lineal.posicion_norte:.2f} m")
        columnas_metricas[3].metric("Recorrido",       f"{porcentaje:.1f} %")
        columnas_metricas[4].metric("Alineación",      "OK" if lineal.esta_alineado else "Corrigiendo")
        cart_ralentizada = lineal.slow_down_cart
        end_ralentizada  = lineal.slow_down_end_tower
        estado_cart = ("★ ON" if lineal.guia_izquierda.contactor.esta_cerrado else "★ OFF") if cart_ralentizada else \
                      ("ON"   if lineal.guia_izquierda.contactor.esta_cerrado else "OFF")
        estado_end  = ("★ ON" if lineal.guia_derecha.contactor.esta_cerrado   else "★ OFF") if end_ralentizada else \
                      ("ON"   if lineal.guia_derecha.contactor.esta_cerrado   else "OFF")
        columnas_metricas[5].metric("Guia Izq (Cart)", estado_cart,
                                    help="★ = en slow_down, sigue al motor rápido" if cart_ralentizada else None)
        columnas_metricas[6].metric("End-tower",       estado_end,
                                    help="★ = en slow_down, sigue al motor rápido" if end_ralentizada else None)
        columnas_metricas[7].metric("Vel. real",       f"{velocidad_real:.2f} m/min",
                                    delta=f"{diferencia_velocidad:+.2f} vs teórica",
                                    delta_color="normal")
        columnas_metricas[8].metric("Motor ★ activo",  f"{lineal.motor_rapido_pct_on:.0f} %",
                                    help="% del último ciclo completo (60 s sim.) con el motor rápido encendido")
        columnas_metricas[9].metric("Dirección",
                                    "▼ ATRÁS" if lineal.en_marcha_atras else "▲ ADELANTE",
                                    help="S = alternar marcha atrás / avance normal")
    else:
        for col in columnas_metricas:
            col.metric("—", "—")

    # BARRA DE PROGRESO
    if lineal:
        auto_reverse = state.get("k_auto_reverse", False)
        limite_sur   = float(state.get("k_ar_ymin", 0))
        limite_norte = float(state.get("k_ar_ymax", longitud_campo))

        if auto_reverse:
            amplitud_rango   = max(limite_norte - limite_sur, 1.0)
            posicion_en_rango = max(limite_sur, min(limite_norte, lineal.posicion_norte))
            porcentaje_barra  = (posicion_en_rango - limite_sur) / amplitud_rango * 100.0
            color_barra       = "#ff7b72" if lineal.en_marcha_atras else "#3fb950"
            simbolo_direccion = "▼" if lineal.en_marcha_atras else "▲"
            texto_pasadas     = f"{state.ar_pasadas} inversiones"
            etiqueta_rango    = f"{limite_sur:.0f} m — {limite_norte:.0f} m"
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
                f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
                f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
                f"margin-bottom:10px'>"
                f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;"
                f"text-transform:uppercase;font-family:monospace'>"
                f"Auto-reverse  ·  {etiqueta_rango}</span>"
                f"<span style='color:{color_barra};font-size:1.5rem;font-weight:700;"
                f"font-family:monospace;line-height:1'>"
                f"{simbolo_direccion}&nbsp;{lineal.posicion_norte:.1f}"
                f"<span style='color:#8b949e;font-size:0.9rem'> m</span></span>"
                f"</div>"
                f"<div style='position:relative;background:#21262d;border-radius:4px;"
                f"height:8px;margin-bottom:8px'>"
                f"<div style='position:absolute;left:0;top:0;"
                f"background:rgba(63,185,80,0.12);border-radius:4px;"
                f"width:{porcentaje_barra:.2f}%;height:100%'></div>"
                f"<div style='position:absolute;top:-3px;"
                f"left:calc({porcentaje_barra:.2f}% - 7px);width:14px;height:14px;"
                f"border-radius:50%;background:{color_barra};"
                f"box-shadow:0 0 6px {color_barra}'></div>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span style='color:{color_barra};font-size:0.82rem;font-weight:600;"
                f"font-family:monospace'>{texto_pasadas}</span>"
                f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>"
                f"rango {amplitud_rango:.0f} m</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
                f"padding:14px 20px 10px 20px;margin:8px 0 16px 0'>"
                f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
                f"margin-bottom:10px'>"
                f"<span style='color:#8b949e;font-size:0.72rem;letter-spacing:2px;"
                f"text-transform:uppercase;font-family:monospace'>Recorrido del campo</span>"
                f"<span style='color:#e6edf3;font-size:1.5rem;font-weight:700;font-family:monospace;"
                f"line-height:1'>{porcentaje:.1f}"
                f"<span style='color:#8b949e;font-size:0.9rem'>%</span></span>"
                f"</div>"
                f"<div style='background:#21262d;border-radius:4px;height:6px;overflow:hidden;"
                f"margin-bottom:8px'>"
                f"<div style='background:linear-gradient(90deg,#238636 0%,#3fb950 100%);"
                f"width:{porcentaje:.2f}%;height:100%;border-radius:4px'></div>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span style='color:#3fb950;font-size:0.82rem;font-weight:600;font-family:monospace'>"
                f"{lineal.posicion_norte:.1f} m avanzados</span>"
                f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>"
                f"meta {longitud_campo:.0f} m</span>"
                f"</div></div>",
                unsafe_allow_html=True,
            )

    # MÉTRICAS GPS
    if lineal and lineal.gps:
        gps              = lineal.gps
        indice_torre_gps = lineal.torres.index(gps.torre)
        columnas_gps     = st.columns(4)
        latitud          = gps.lat_e7 / 1e7
        longitud         = gps.lon_e7 / 1e7
        gps_anterior     = state.gps_prev
        cambio_latitud   = round(latitud  - gps_anterior["lat"], 7) if gps_anterior else None
        cambio_longitud  = round(longitud - gps_anterior["lon"], 7) if gps_anterior else None
        columnas_gps[0].metric("GPS · Torre",  f"Intermedia {indice_torre_gps}")
        columnas_gps[1].metric("Latitud",      f"{latitud:.7f}°",
                               delta=f"{cambio_latitud:+.7f}°" if cambio_latitud is not None else None)
        columnas_gps[2].metric("Longitud",     f"{longitud:.7f}°",
                               delta=f"{cambio_longitud:+.7f}°" if cambio_longitud is not None else None)
        columnas_gps[3].metric("Formato ×10⁷", f"{gps.lat_e7}  /  {gps.lon_e7}")
        state.gps_prev = {"lat": latitud, "lon": longitud}

    # CAJA DE INTERFAZ
    if lineal and lineal.caja_interfaz:
        caja             = lineal.caja_interfaz
        indice_torre_caja = lineal.torres.index(caja.torre)
        color_safety     = "#3fb950" if caja.safety_ok else "#f85149"
        color_gps        = "#3fb950" if caja.gps_ok    else "#f85149"
        color_cart       = "#ffa657" if caja.slow_down_cart      else "#484f58"
        color_end        = "#ffa657" if caja.slow_down_end_tower else "#484f58"
        columnas_caja    = st.columns(6)
        columnas_caja[0].metric("Caja · Torre GPS",    f"Intermedia {indice_torre_caja}")
        columnas_caja[1].metric("GPS enviado",
                                f"{caja.lat_e7} / {caja.lon_e7}",
                                help=f"{caja.latitud:.7f}°  {caja.longitud:.7f}°  Carr {caja.carr}")
        columnas_caja[2].metric("Safety",     "OK" if caja.safety_ok else "FAIL")
        columnas_caja[3].metric("GPS status", "OK" if caja.gps_ok    else "FAIL")
        columnas_caja[4].metric("Slow Cart",  "ON" if caja.slow_down_cart      else "—")
        columnas_caja[5].metric("Slow EndT",  "ON" if caja.slow_down_end_tower else "—")
        st.markdown(
            f"<div style='display:flex;gap:8px;margin:-12px 0 8px 0;flex-wrap:wrap'>"
            f"<span style='font-size:0.72rem;color:{color_safety};font-family:monospace'>"
            f"&#9679; SAFETY {'OK' if caja.safety_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.72rem;color:{color_gps};font-family:monospace'>"
            f"&#9679; GPS {'OK' if caja.gps_ok else 'FAIL'}</span>"
            f"<span style='font-size:0.72rem;color:{color_cart};font-family:monospace'>"
            f"&#9679; SLOW_CART {'ON' if caja.slow_down_cart else 'OFF'}</span>"
            f"<span style='font-size:0.72rem;color:{color_end};font-family:monospace'>"
            f"&#9679; SLOW_END_TWR {'ON' if caja.slow_down_end_tower else 'OFF'}</span>"
            f"<span style='font-size:0.72rem;color:#484f58;font-family:monospace'>"
            f"último msg: {caja.ultimo_mensaje or '—'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # FIGURA: vista general · CSV · Log · GPS track  [· Δd · Δrumbo si trayectoria activa]
    _tray_on = state.get("k_tray_activa", False)
    if _tray_on:
        col_toggle, col_ead, col_erm, col_csv, col_log, col_gps_track = st.columns([1, 1, 1, 1, 2, 3])
    else:
        col_toggle, col_csv, col_log, col_gps_track = st.columns([1, 1, 2, 4])
        col_ead = col_erm = None

    with col_toggle:
        st.toggle(
            "Vista general",
            key="k_vista_general",
            help="OFF → escala 1:1 siguiendo al lineal  ·  ON → campo completo",
        )

    if _tray_on and col_ead is not None:
        valor_ead = state.get("trayectoria_ead_mm")
        valor_erm = state.get("trayectoria_erumbo_deg")
        _ead_str = f"{valor_ead:.0f} mm" if valor_ead is not None else "—"
        _erm_str = f"{valor_erm:+.1f}°"  if valor_erm is not None else "—"
        with col_ead:
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;border-radius:6px;"
                f"padding:0 12px;display:flex;align-items:center;gap:8px;height:38px;"
                f"white-space:nowrap' title='Desviación perpendicular de la torre GPS "
                f"respecto al segmento de trayectoria más cercano'>"
                f"<span style='font-size:0.85rem;color:#8b949e;font-family:monospace'>Δd</span>"
                f"<span style='font-size:0.85rem;font-weight:700;color:#e6edf3'>{_ead_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col_erm:
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;border-radius:6px;"
                f"padding:0 12px;display:flex;align-items:center;gap:8px;height:38px;"
                f"white-space:nowrap' title='Diferencia entre el azimut de movimiento real "
                f"de la torre GPS y el azimut del segmento objetivo "
                f"(0° = norte, + = desviado a la derecha, − = a la izquierda)'>"
                f"<span style='font-size:0.85rem;color:#8b949e;font-family:monospace'>Δrumbo</span>"
                f"<span style='font-size:0.85rem;font-weight:700;color:#e6edf3'>{_erm_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    if lineal:
        with col_csv:
            if state.historial:
                buf = io.StringIO()
                todos_los_campos = list(dict.fromkeys(
                    campo for fila in state.historial for campo in fila.keys()
                ))
                writer = csv.DictWriter(buf, fieldnames=todos_los_campos, restval="")
                writer.writeheader()
                writer.writerows(state.historial)
                st.download_button(
                    label="⬇ CSV",
                    data=buf.getvalue(),
                    file_name="simulacion_lineal.csv",
                    mime="text/csv",
                    width="stretch",
                )

        with col_log:
            colores_tipo = {
                "START": "#3fb950", "STOP": "#e3b341", "FIN": "#3fb950",
                "CRIT":  "#f85149", "OK":   "#58a6ff", "INFO": "#8b949e",
            }
            entradas = state.log[-60:][::-1]
            with st.expander(f"Log  ({len(state.log)} entradas)", expanded=False):
                for entrada in entradas:
                    color_entrada = colores_tipo.get(entrada["tipo"], "#8b949e")
                    st.markdown(
                        f"<code style='color:#484f58;font-size:0.75rem'>{entrada['t']}</code>&nbsp;"
                        f"<span style='background:{color_entrada}22;color:{color_entrada};border-radius:4px;"
                        f"padding:1px 7px;font-size:0.68rem;font-family:monospace;"
                        f"font-weight:700'>{entrada['tipo']}</span>&nbsp;"
                        f"<span style='color:#e6edf3;font-size:0.82rem'>{entrada['msg']}</span>",
                        unsafe_allow_html=True,
                    )

        with col_gps_track:
            if state.gps_track:
                with st.expander(f"Track GPS — {len(state.gps_track)} lecturas", expanded=False):
                    st.dataframe(
                        state.gps_track[::-1],
                        hide_index=True,
                        width="stretch",
                    )

    posicion_norte = lineal.posicion_norte if lineal is not None else 0.0
    puntos_figura  = None
    if state.get("k_tray_activa", False) and lineal is not None:
        lat_fig, lon_fig = get_origen_latlon()
        puntos_fig       = parse_trayectoria(state.get("k_tray_input", ""), lat_fig, lon_fig)
        puntos_figura    = puntos_fig if len(puntos_fig) >= 2 else None

    st.plotly_chart(
        build_figure(
            lineal, longitud_campo, posicion_norte,
            st.session_state.get("k_vista_general", False),
            tower_trails=state.tower_trails,
            trayectoria_xy=puntos_figura,
        ),
        width="stretch",
        key="campo_pivot",
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
            "toImageButtonOptions": {"filename": "lineal_fss", "format": "png"},
        },
    )
