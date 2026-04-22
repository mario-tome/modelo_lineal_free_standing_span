import math
import plotly.graph_objects as go
from modelo import Lineal, Torre_Guia, Torre_Intermedia


def _color_tramo(tramo) -> str:
    if not tramo.esta_alineado:
        return "#f85149"
    angulo = abs(tramo.angulo_grados)
    if angulo < 0.5:
        return "#3fb950"
    return "#e3b341"


def _estilo_torre(lineal: Lineal, i: int):
    torre         = lineal.torres[i]
    numero_torres = len(lineal.torres)
    if i == 0:
        return "#f78166", "square", "CART", 20
    if i == numero_torres - 1:
        return "#d2a8ff", "square", "END", 20
    if isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
        return "#ffa657", "star", f"I{i}★", 18
    if i <= lineal.indice_tramo_rigido:
        return "#58a6ff", "circle", f"I{i}", 14
    return "#56d364", "circle", f"I{i}", 14


def build_figure(lineal: Lineal | None, longitud_campo: float, pos_norte: float = 0.0,
                 vista_general: bool = False, tower_trails: list | None = None,
                 trayectoria_xy: list | None = None) -> go.Figure:
    if lineal is None:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#0a1f10",
            height=560, margin=dict(l=0, r=0, t=0, b=0),
            annotations=[dict(
                text="Configura el lineal en el panel izquierdo y pulsa  INICIAR",
                xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                font=dict(size=15, color="#8b949e"),
            )],
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        return fig

    ancho_campo, alto_campo = lineal.longitud_total, longitud_campo
    trazos, formas, anotaciones = [], [], []

    _ANCHO_INTERIOR_PX = 960
    _ALTO_INTERIOR_PX  = 660
    _MARGEN_VERTICAL   = 140

    pad_x  = ancho_campo * 0.06
    pad_y  = max(20.0, ancho_campo * 0.05)

    if not vista_general:
        rango_x_metros = ancho_campo + 2 * pad_x
        alto_viewport  = rango_x_metros * _ALTO_INTERIOR_PX / _ANCHO_INTERIOR_PX - 2 * pad_y
        alto_viewport  = max(alto_viewport, ancho_campo * 0.25)
        rango_total_y  = alto_viewport + 2 * pad_y

        if rango_total_y >= alto_campo + 2 * pad_y:
            y_lo = -pad_y
            y_hi = alto_campo + pad_y
        else:
            y_lo = pos_norte - alto_viewport * 0.30 - pad_y
            y_hi = y_lo + rango_total_y
            if y_lo < -pad_y:
                y_lo = -pad_y
                y_hi = y_lo + rango_total_y
            if y_hi > alto_campo + pad_y:
                y_hi = alto_campo + pad_y
                y_lo = y_hi - rango_total_y

        rango_y_metros = y_hi - y_lo
        altura_figura  = int(_ANCHO_INTERIOR_PX * rango_y_metros / rango_x_metros) + _MARGEN_VERTICAL
        altura_figura  = max(400, min(altura_figura, 950))
        usar_scaleanchor = True
    else:
        y_lo = -alto_campo * 0.20
        y_hi = alto_campo + alto_campo * 0.20
        altura_figura    = 620
        usar_scaleanchor = False

    formas.append(dict(type="rect", xref="x", yref="y",
        x0=0, y0=0, x1=ancho_campo, y1=alto_campo,
        fillcolor="#0a1f10", line=dict(color="#30363d", width=1), layer="below"))

    min_y = min(t.posicion_y for t in lineal.torres)
    if min_y > 0.1:
        formas.append(dict(type="rect", xref="x", yref="y",
            x0=0, y0=0, x1=ancho_campo, y1=min_y,
            fillcolor="rgba(63,185,80,0.10)", line=dict(width=0), layer="below"))

    paso_filas = max(2, int((y_hi - y_lo) / 40))
    gx, gy = [], []
    for y in range(0, int(alto_campo) + 1, paso_filas):
        gx += [0, ancho_campo, None]; gy += [y, y, None]
    trazos.append(go.Scatter(x=gx, y=gy, mode="lines",
        line=dict(color="rgba(255,255,255,0.04)", width=1),
        hoverinfo="skip", showlegend=False))

    vx, vy = [], []
    for i in range(lineal.numero_tramos + 1):
        xv = i * lineal.longitud_tramo
        vx += [xv, xv, None]; vy += [0, alto_campo, None]
    trazos.append(go.Scatter(x=vx, y=vy, mode="lines",
        line=dict(color="rgba(255,255,255,0.04)", width=1, dash="dot"),
        hoverinfo="skip", showlegend=False))

    indice_rigido = lineal.indice_tramo_rigido
    rx1 = lineal.torres[indice_rigido].posicion_x
    rx2 = lineal.torres[indice_rigido + 1].posicion_x
    formas.append(dict(type="rect", xref="x", yref="paper",
        x0=rx1, y0=0, x1=rx2, y1=1,
        fillcolor="rgba(255,166,87,0.07)",
        line=dict(color="rgba(255,166,87,0.30)", width=1, dash="dot"),
        layer="below"))

    anotaciones.append(dict(
        x=(rx1 + rx2) / 2, y=1.0,
        text="TRAMO RIGIDO",
        showarrow=False,
        font=dict(color="#ffa657", size=13, family="monospace"),
        bgcolor="rgba(13,17,23,0.6)",
        bordercolor="#ffa657", borderwidth=1,
        xref="x", yref="paper",
        yanchor="top",
    ))

    if tower_trails:
        for indice_torre in range(len(lineal.torres)):
            trail_torre = tower_trails[indice_torre] if indice_torre < len(tower_trails) else []
            if len(trail_torre) < 2:
                continue
            color_torre, _, _, _ = _estilo_torre(lineal, indice_torre)
            trazos.append(go.Scatter(
                x=[p[0] for p in trail_torre],
                y=[p[1] for p in trail_torre],
                mode="lines",
                line=dict(color=color_torre, width=1.5),
                opacity=0.35,
                hoverinfo="skip",
                showlegend=False,
            ))

    COLOR_TRAYECTORIA = "#79c0ff"
    if trayectoria_xy and len(trayectoria_xy) >= 2:
        tx = [p[0] for p in trayectoria_xy]
        ty = [p[1] for p in trayectoria_xy]
        trazos.append(go.Scatter(
            x=tx, y=ty,
            mode="lines",
            line=dict(color=COLOR_TRAYECTORIA, width=2, dash="dot"),
            hoverinfo="skip",
            showlegend=False,
        ))
        trazos.append(go.Scatter(
            x=tx, y=ty,
            mode="markers+text",
            text=[f"P{i+1}" for i in range(len(trayectoria_xy))],
            textposition="top center",
            textfont=dict(color=COLOR_TRAYECTORIA, size=11, family="monospace"),
            marker=dict(
                color=COLOR_TRAYECTORIA, size=10, symbol="diamond",
                line=dict(color="#0d1117", width=1.5),
            ),
            hovertemplate=[
                f"<b>P{i+1}</b><br>X = {p[0]:.1f} m<br>Y = {p[1]:.1f} m<extra></extra>"
                for i, p in enumerate(trayectoria_xy)
            ],
            showlegend=False,
        ))

    for idx, tramo in enumerate(lineal.tramos):
        x1 = tramo.torre_izquierda.posicion_x
        y1 = tramo.torre_izquierda.posicion_y
        x2 = tramo.torre_derecha.posicion_x
        y2 = tramo.torre_derecha.posicion_y
        angulo = tramo.angulo_grados
        color  = _color_tramo(tramo)

        hover = (
            f"<b>Tramo {idx + 1}{'  [RIGIDO]' if tramo.es_rigido else ''}</b><br>"
            f"Angulo:    <b>{angulo:+.3f} grd</b><br>"
            f"Desviacion: {tramo.desviacion_norte:+.3f} m<br>"
            f"Estado: {'OK' if tramo.esta_alineado else 'DESVIADO'}"
            f"<extra></extra>"
        )

        if tramo.es_rigido:
            trazos.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color="#ffa657", width=28), opacity=0.15,
                hoverinfo="skip", showlegend=False))
            trazos.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=8),
                hovertemplate=hover, showlegend=False))
            trazos.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color="#ffa657", width=3, dash="dash"),
                hoverinfo="skip", showlegend=False))
        else:
            trazos.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=14), opacity=0.12,
                hoverinfo="skip", showlegend=False))
            trazos.append(go.Scatter(x=[x1, x2], y=[y1, y2], mode="lines",
                line=dict(color=color, width=4),
                hovertemplate=hover, showlegend=False))

        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        borde_anotacion = "#ffa657" if tramo.es_rigido else color
        encabezado = f"T{idx + 1}  FSS" if tramo.es_rigido else f"T{idx + 1}"
        anotaciones.append(dict(
            x=mx, y=my,
            text=(
                f"<b>{encabezado}</b><br>"
                f"{angulo:+.2f}°<br>"
                f"{tramo.desviacion_norte:+.3f} m"
            ),
            showarrow=False,
            font=dict(color=color, size=11, family="monospace"),
            bgcolor="rgba(13,17,23,0.82)",
            bordercolor=borde_anotacion, borderwidth=1,
            borderpad=5,
            xref="x", yref="y",
            align="center",
        ))

    numero_torres = len(lineal.torres)
    gps_idx       = lineal.torres.index(lineal.gps.torre) if lineal.gps else -1
    for i, torre in enumerate(lineal.torres):
        color, simbolo, etiqueta, tamanio = _estilo_torre(lineal, i)

        if i == 0:
            nombre = "Guia Izq (Cart)"
        elif i == numero_torres - 1:
            nombre = "End-tower"
        elif isinstance(torre, Torre_Intermedia) and torre.es_motor_rapido:
            nombre = f"Intermedia {i}  [Motor Rapido — extremo der tramo rigido]"
        elif i <= lineal.indice_tramo_rigido:
            nombre = f"Intermedia {i}  [cascada izquierda]"
        else:
            nombre = f"Intermedia {i}  [cascada derecha]"

        contactor_cerrado = torre.contactor.esta_cerrado

        en_slow_down = (
            isinstance(torre, Torre_Guia) and (
                (i == 0                      and lineal.slow_down_cart)      or
                (i == len(lineal.torres) - 1 and lineal.slow_down_end_tower)
            )
        )

        if isinstance(torre, Torre_Guia):
            if en_slow_down:
                texto_contactor = f"Contactor: {'ON' if contactor_cerrado else 'OFF'}  (sigue motor rápido)"
            else:
                texto_contactor = f"Contactor: {'ON' if contactor_cerrado else 'OFF'}  (set speed {torre.contactor.duty_cycle*100:.0f}%)"
        else:
            texto_contactor = f"Contactor: {'ON — desalineada' if contactor_cerrado else 'OFF — alineada'}"

        hover_gps = ""
        if i == gps_idx:
            g = lineal.gps
            hover_gps = (
                f"<br><span style='color:#58d68d'>&#128225; GPS</span><br>"
                f"LAT: <b>{g.lat_e7}</b><br>"
                f"LON: <b>{g.lon_e7}</b>"
            )
        hover = (
            f"<b>{nombre}</b><br>"
            f"X = {torre.posicion_x:.0f} m<br>"
            f"Y = {torre.posicion_y:.3f} m<br>"
            f"{texto_contactor}"
            f"{hover_gps}"
            f"<extra></extra>"
        )

        borde_color = "#3fb950" if contactor_cerrado else "#484f58"

        if isinstance(torre, Torre_Guia):
            if en_slow_down:
                if contactor_cerrado:
                    texto_estado, color_estado = "Motor ON  ·  (sigue rápido)", "#e3b341"
                else:
                    texto_estado, color_estado = "Motor OFF  ·  (sigue rápido)", "#8b949e"
            else:
                texto_estado   = f"Speed {torre.contactor.duty_cycle*100:.0f}%  {'ON' if contactor_cerrado else 'OFF'}"
                color_estado   = color
        else:
            if contactor_cerrado:
                texto_estado, color_estado = "Corrigiendo  ·  Motor ON", "#e3b341"
            else:
                texto_estado, color_estado = "Alineada  ·  Motor OFF", "#3fb950"

        trazos.append(go.Scatter(
            x=[torre.posicion_x], y=[torre.posicion_y], mode="markers",
            marker=dict(color=color, size=tamanio + 14, opacity=0.18, symbol=simbolo),
            hoverinfo="skip", showlegend=False))

        trazos.append(go.Scatter(
            x=[torre.posicion_x], y=[torre.posicion_y],
            mode="markers",
            marker=dict(color=color, size=tamanio, symbol=simbolo,
                        line=dict(color=borde_color, width=2)),
            hovertemplate=hover,
            showlegend=False))

        desplazamiento_y = -90 if i % 2 == 0 else 90
        if i == gps_idx:
            desplazamiento_y = 90
        anotaciones.append(dict(
            x=torre.posicion_x, y=torre.posicion_y,
            xref="x", yref="y",
            text=f"<b>{etiqueta}</b>  X={torre.posicion_x:.2f} m  Y={torre.posicion_y:.2f} m<br>{texto_estado}",
            showarrow=True,
            arrowhead=2, arrowwidth=1.5, arrowsize=0.7,
            arrowcolor=color,
            ax=0, ay=desplazamiento_y,
            font=dict(color=color_estado, size=13, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor=color_estado, borderwidth=1, borderpad=10,
            align="center",
        ))

    if lineal.gps is not None:
        gps    = lineal.gps
        gps_x, gps_y = gps.torre.posicion_x, gps.torre.posicion_y

        trazos.append(go.Scatter(
            x=[gps_x], y=[gps_y], mode="markers",
            marker=dict(color="#58d68d", size=42, opacity=0.15, symbol="circle"),
            hoverinfo="skip", showlegend=False,
        ))
        trazos.append(go.Scatter(
            x=[gps_x], y=[gps_y], mode="markers",
            marker=dict(color="#58d68d", size=12, symbol="circle-cross-open",
                        line=dict(color="#58d68d", width=2.5)),
            hovertemplate=(
                f"<b>GPS</b><br>"
                f"LAT: <b>{gps.lat_e7}</b><br>"
                f"LON: <b>{gps.lon_e7}</b><br>"
                f"{gps.latitud:.7f}°,  {gps.longitud:.7f}°"
                f"<extra></extra>"
            ),
            showlegend=False,
        ))
        anotaciones.append(dict(
            x=gps_x, y=gps_y, xref="x", yref="y",
            text=f"<b>GPS</b><br>{gps.latitud:.5f}°<br>{gps.longitud:.5f}°",
            showarrow=True,
            arrowhead=2, arrowwidth=1.5, arrowsize=0.7, arrowcolor="#58d68d",
            ax=0, ay=-100,
            font=dict(color="#58d68d", size=13, family="monospace"),
            bgcolor="rgba(22,27,34,0.92)",
            bordercolor="#58d68d", borderwidth=1, borderpad=10,
            align="center",
        ))

    pasos_nice = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
    paso_ticks = next((s for s in pasos_nice if alto_campo / s <= 15), 1000)
    valores_tick = list(range(0, int(alto_campo) + paso_ticks + 1, paso_ticks))

    fig = go.Figure(data=trazos)
    config_eje_y = dict(
        title=dict(text="Norte  (metros)", font=dict(color="#8b949e", size=12)),
        gridcolor="#1a2332", zeroline=False,
        range=[y_lo, y_hi],
        tickmode="array", tickvals=valores_tick,
        tickfont=dict(color="#8b949e"), ticksuffix=" m",
    )
    config_eje_x = dict(
        title=dict(text="Oeste  —  Este  (metros)", font=dict(color="#8b949e", size=12)),
        gridcolor="#1a2332", zeroline=False,
        range=[-pad_x, ancho_campo + pad_x],
        tickfont=dict(color="#8b949e"), ticksuffix=" m",
    )
    if usar_scaleanchor:
        config_eje_y["scaleanchor"] = "x"
        config_eje_y["scaleratio"]  = 1
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0a1f10",
        height=altura_figura,
        margin=dict(l=70, r=40, t=90, b=50),
        xaxis=config_eje_x,
        yaxis=config_eje_y,
        shapes=formas,
        annotations=anotaciones,
        hovermode="closest",
        dragmode="pan",
    )
    return fig
