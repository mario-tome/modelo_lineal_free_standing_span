import csv
import io
import streamlit as st
from modelo import Lineal, Torre_Intermedia
from constantes import TERRENOS
from trayectoria import get_origen_latlon, parse_trayectoria, calcular_errores
from figura import build_figure


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
        sim_spd_val = state.get("k_simspd", 60)
        lineal.avanza(sim_spd_val)

        if state.tower_trails is not None and len(state.tower_trails) == len(lineal.torres):
            for indice_torre, torre in enumerate(lineal.torres):
                state.tower_trails[indice_torre].append((torre.posicion_x, torre.posicion_y))
            if len(state.tower_trails[0]) > 2000:
                state.tower_trails = [tr[-2000:] for tr in state.tower_trails]

        state.vel_real = (lineal.posicion_norte - state.pos_prev) / (sim_spd_val / 60.0)
        state.pos_prev = lineal.posicion_norte

        # Construir fila CSV
        fila = {
            "tiempo_s":       lineal.tiempo_total_segundos,
            "tiempo":         lineal._tiempo_formateado(),
            "posicion_norte": round(lineal.posicion_norte, 3),
            "slow_cart":      lineal.slow_down_cart,
            "slow_end_tower": lineal.slow_down_end_tower,
        }
        longitud_nominal = lineal.longitud_tramo
        for j, torre in enumerate(lineal.torres):
            fila[f"torre_{j}_x"] = round(torre.posicion_x, 4)
            fila[f"torre_{j}_y"] = round(torre.posicion_y, 4)
            if j < lineal.numero_tramos:
                tramo  = lineal.tramos[j]
                dx     = tramo.torre_derecha.posicion_x - tramo.torre_izquierda.posicion_x
                dy     = tramo.desviacion_norte
                longitud_calculada = round((dx**2 + dy**2) ** 0.5, 4)
                fila[f"tramo_{j+1}_L_calculado"] = longitud_calculada
                fila[f"tramo_{j+1}_deform_m"]    = round(longitud_nominal - longitud_calculada, 4)
                fila[f"tramo_{j+1}_desv_y"]      = round(dy, 4)
                fila[f"tramo_{j+1}_rumbo_deg"]   = round(tramo.angulo_grados, 4)
        if lineal.gps:
            fila["lat_e7"] = lineal.gps.lat_e7
            fila["lon_e7"] = lineal.gps.lon_e7

        if state.get("k_tray_activa", False):
            lat_c, lon_c = get_origen_latlon()
            puntos_tray_c = parse_trayectoria(state.get("k_tray_input", ""), lat_c, lon_c)
            torre_gps_c, indice_gps_c = None, -1
            if lineal.gps:
                torre_gps_c   = lineal.gps.torre
                indice_gps_c  = lineal.torres.index(torre_gps_c)
            elif lineal.caja_interfaz:
                torre_gps_c   = lineal.caja_interfaz.torre
                indice_gps_c  = lineal.torres.index(torre_gps_c)
            if torre_gps_c is not None and len(puntos_tray_c) >= 2:
                trail_c = (state.tower_trails[indice_gps_c]
                           if state.tower_trails and indice_gps_c < len(state.tower_trails) else [])
                error_dist_c, error_rumbo_c = calcular_errores(
                    torre_gps_c.posicion_x, torre_gps_c.posicion_y, puntos_tray_c, trail_c)
                fila["EΔd_mm"]      = round(error_dist_c, 1) if error_dist_c is not None else None
                fila["EΔrumbo_deg"] = round(error_rumbo_c, 2) if error_rumbo_c is not None else None
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
        ar_on   = state.get("k_auto_reverse", False)
        ar_ymin = float(state.get("k_ar_ymin", 0))
        ar_ymax = float(state.get("k_ar_ymax", longitud_campo))

        if ar_on:
            pos = lineal.posicion_norte
            if not lineal.en_marcha_atras and pos >= ar_ymax:
                lineal.invertir_direccion()
                state.ar_pasadas += 1
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "INFO",
                    "msg":  f"Auto-reverse ▼  ({pos:.1f} m ≥ {ar_ymax:.0f} m)  "
                            f"— pasada #{state.ar_pasadas}",
                })
            elif lineal.en_marcha_atras and pos <= ar_ymin:
                lineal.invertir_direccion()
                state.ar_pasadas += 1
                state.log.append({
                    "t":    lineal._tiempo_formateado(),
                    "tipo": "INFO",
                    "msg":  f"Auto-reverse ▲  ({pos:.1f} m ≤ {ar_ymin:.0f} m)  "
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
        lat_e, lon_e = get_origen_latlon()
        puntos_tray_e = parse_trayectoria(state.get("k_tray_input", ""), lat_e, lon_e)
        torre_gps_e, indice_gps_e = None, -1
        if lineal.gps:
            torre_gps_e  = lineal.gps.torre
            indice_gps_e = lineal.torres.index(torre_gps_e)
        elif lineal.caja_interfaz:
            torre_gps_e  = lineal.caja_interfaz.torre
            indice_gps_e = lineal.torres.index(torre_gps_e)
        if torre_gps_e is not None and len(puntos_tray_e) >= 2:
            trail_e = (state.tower_trails[indice_gps_e]
                       if state.tower_trails and indice_gps_e < len(state.tower_trails) else [])
            error_dist_e, error_rumbo_e = calcular_errores(
                torre_gps_e.posicion_x, torre_gps_e.posicion_y, puntos_tray_e, trail_e)
            state.trayectoria_ead_mm     = error_dist_e
            state.trayectoria_erumbo_deg = error_rumbo_e
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
        en_atras       = lineal is not None and lineal.en_marcha_atras
        ar_activo      = state.get("k_auto_reverse", False)
        badge_color    = "#ff7b72" if en_atras else "#3fb950"
        badge_bg       = "rgba(255,123,114,0.08)" if en_atras else "rgba(63,185,80,0.08)"
        badge_border   = "rgba(255,123,114,0.25)" if en_atras else "rgba(63,185,80,0.25)"
        badge_etiqueta = "&#9660; MARCHA ATRÁS" if en_atras else "&#9650; EN MARCHA"
        sufijo_ar = (
            f"&nbsp;<span style='color:#8b949e;font-weight:400;font-size:0.75rem;letter-spacing:1px'>"
            f"AUTO-REVERSE · {state.ar_pasadas} inv.</span>"
            if ar_activo else ""
        )
        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:8px;"
            f"background:{badge_bg};border:1px solid {badge_border};"
            f"border-radius:20px;padding:5px 14px;margin:4px 0'>"
            f"<span style='width:8px;height:8px;border-radius:50%;background:{badge_color};"
            f"display:inline-block;box-shadow:0 0 6px {badge_color}'></span>"
            f"<span style='color:{badge_color};font-weight:600;letter-spacing:2px;font-size:0.85rem'>"
            f"{badge_etiqueta}</span>"
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
        porcentaje  = min(lineal.posicion_norte / longitud_campo * 100.0, 100.0)
        vel_teorica = lineal.velocidad_nominal * lineal.velocidad_porcentaje / 100.0
        vel_real    = state.get("vel_real", 0.0)
        delta_vel   = vel_real - vel_teorica
        columnas_metricas[0].metric("Tiempo campo",    lineal._tiempo_formateado())
        columnas_metricas[1].metric("Ciclo",           str(lineal.ciclo_actual))
        columnas_metricas[2].metric("Posición media",  f"{lineal.posicion_norte:.2f} m")
        columnas_metricas[3].metric("Recorrido",       f"{porcentaje:.1f} %")
        columnas_metricas[4].metric("Alineación",      "OK" if lineal.esta_alineado else "Corrigiendo")
        slow_cart = lineal.slow_down_cart
        slow_end  = lineal.slow_down_end_tower
        valor_cart = ("★ ON" if lineal.guia_izquierda.contactor.esta_cerrado else "★ OFF") if slow_cart else \
                     ("ON"   if lineal.guia_izquierda.contactor.esta_cerrado else "OFF")
        valor_end  = ("★ ON" if lineal.guia_derecha.contactor.esta_cerrado   else "★ OFF") if slow_end else \
                     ("ON"   if lineal.guia_derecha.contactor.esta_cerrado   else "OFF")
        columnas_metricas[5].metric("Guia Izq (Cart)", valor_cart,
                                    help="★ = en slow_down, sigue al motor rápido" if slow_cart else None)
        columnas_metricas[6].metric("End-tower",       valor_end,
                                    help="★ = en slow_down, sigue al motor rápido" if slow_end else None)
        columnas_metricas[7].metric("Vel. real",       f"{vel_real:.2f} m/min",
                                    delta=f"{delta_vel:+.2f} vs teórica",
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
        ar_on_barra = state.get("k_auto_reverse", False)
        ar_ymin_b   = float(state.get("k_ar_ymin", 0))
        ar_ymax_b   = float(state.get("k_ar_ymax", longitud_campo))

        if ar_on_barra:
            rango_ar      = max(ar_ymax_b - ar_ymin_b, 1.0)
            pos_clamped   = max(ar_ymin_b, min(ar_ymax_b, lineal.posicion_norte))
            pct_barra     = (pos_clamped - ar_ymin_b) / rango_ar * 100.0
            color_barra   = "#ff7b72" if lineal.en_marcha_atras else "#3fb950"
            flecha_dir    = "▼" if lineal.en_marcha_atras else "▲"
            texto_pasadas = f"{state.ar_pasadas} inversiones"
            etiqueta_rango = f"{ar_ymin_b:.0f} m — {ar_ymax_b:.0f} m"
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
                f"{flecha_dir}&nbsp;{lineal.posicion_norte:.1f}"
                f"<span style='color:#8b949e;font-size:0.9rem'> m</span></span>"
                f"</div>"
                f"<div style='position:relative;background:#21262d;border-radius:4px;"
                f"height:8px;margin-bottom:8px'>"
                f"<div style='position:absolute;left:0;top:0;"
                f"background:rgba(63,185,80,0.12);border-radius:4px;"
                f"width:{pct_barra:.2f}%;height:100%'></div>"
                f"<div style='position:absolute;top:-3px;"
                f"left:calc({pct_barra:.2f}% - 7px);width:14px;height:14px;"
                f"border-radius:50%;background:{color_barra};"
                f"box-shadow:0 0 6px {color_barra}'></div>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span style='color:{color_barra};font-size:0.82rem;font-weight:600;"
                f"font-family:monospace'>{texto_pasadas}</span>"
                f"<span style='color:#484f58;font-size:0.82rem;font-family:monospace'>"
                f"rango {rango_ar:.0f} m</span>"
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
        gps     = lineal.gps
        gps_idx = lineal.torres.index(gps.torre)
        columnas_gps = st.columns(4)
        ui_lat = gps.lat_e7 / 1e7
        ui_lon = gps.lon_e7 / 1e7
        prev_gps    = state.gps_prev
        delta_lat = round(ui_lat - prev_gps["lat"], 7) if prev_gps else None
        delta_lon = round(ui_lon - prev_gps["lon"], 7) if prev_gps else None
        columnas_gps[0].metric("GPS · Torre",  f"Intermedia {gps_idx}")
        columnas_gps[1].metric("Latitud",      f"{ui_lat:.7f}°",
                               delta=f"{delta_lat:+.7f}°" if delta_lat is not None else None)
        columnas_gps[2].metric("Longitud",     f"{ui_lon:.7f}°",
                               delta=f"{delta_lon:+.7f}°" if delta_lon is not None else None)
        columnas_gps[3].metric("Formato ×10⁷", f"{gps.lat_e7}  /  {gps.lon_e7}")
        state.gps_prev = {"lat": ui_lat, "lon": ui_lon}

    # CAJA DE INTERFAZ
    if lineal and lineal.caja_interfaz:
        caja     = lineal.caja_interfaz
        caja_idx = lineal.torres.index(caja.torre)
        color_safety = "#3fb950" if caja.safety_ok else "#f85149"
        color_gps    = "#3fb950" if caja.gps_ok    else "#f85149"
        color_cart   = "#ffa657" if caja.slow_down_cart      else "#484f58"
        color_end    = "#ffa657" if caja.slow_down_end_tower else "#484f58"
        columnas_caja = st.columns(6)
        columnas_caja[0].metric("Caja · Torre GPS",    f"Intermedia {caja_idx}")
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

    # FILA COMPACTA: CSV · LOG · GPS TRACK
    if lineal:
        col_csv, col_log, col_gps_track = st.columns([1, 2, 4])

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

    # FIGURA
    col_toggle, col_ead, col_erm, _ = st.columns([1, 1, 1, 3])
    with col_toggle:
        st.toggle(
            "Vista general",
            key="k_vista_general",
            help="OFF → escala 1:1 siguiendo al lineal  ·  ON → campo completo",
        )
    if state.get("k_tray_activa", False):
        valor_ead = state.get("trayectoria_ead_mm")
        valor_erm = state.get("trayectoria_erumbo_deg")
        with col_ead:
            st.metric(
                "EΔd",
                f"{valor_ead:.0f} mm" if valor_ead is not None else "—",
                help="Error Δ distancia: desviación perpendicular de la torre GPS "
                     "respecto al segmento de trayectoria más cercano",
            )
        with col_erm:
            st.metric(
                "EΔrumbo",
                f"{valor_erm:+.1f}°" if valor_erm is not None else "—",
                help="Error Δ rumbo: diferencia entre el azimut de movimiento real "
                     "de la torre GPS y el azimut del segmento objetivo "
                     "(0° = norte, + = desviado a la derecha, − = a la izquierda)",
            )

    posicion_norte = lineal.posicion_norte if lineal is not None else 0.0
    trayectoria_figura = None
    if state.get("k_tray_activa", False) and lineal is not None:
        lat_fig, lon_fig = get_origen_latlon()
        puntos_fig = parse_trayectoria(state.get("k_tray_input", ""), lat_fig, lon_fig)
        trayectoria_figura = puntos_fig if len(puntos_fig) >= 2 else None

    st.plotly_chart(
        build_figure(
            lineal, longitud_campo, posicion_norte,
            st.session_state.get("k_vista_general", False),
            tower_trails=state.tower_trails,
            trayectoria_xy=trayectoria_figura,
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
