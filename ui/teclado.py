import os
import streamlit as st
import streamlit.components.v1 as components

_DIRECTORIO_KBD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "giro_kbd")
os.makedirs(_DIRECTORIO_KBD, exist_ok=True)
with open(os.path.join(_DIRECTORIO_KBD, "index.html"), "w", encoding="utf-8") as _f:
    _f.write("""
        <!DOCTYPE html><html><head><script>
            var _init = false;
            var _st   = {left: false, right: false, reverse: false};

            function _send() {
                window.parent.postMessage({
                    isStreamlitMessage: true,
                    type: 'streamlit:setComponentValue',
                    value: {left: _st.left, right: _st.right, reverse: _st.reverse},
                    dataType: 'json'
                }, '*');
            }

            window.addEventListener('message', function(ev) {
                if (!ev.data || ev.data.type !== 'streamlit:render') return;

                if (!_init) {
                    _init = true;
                    window.parent.document.addEventListener('keydown', function(e) {
                        if (e.repeat) return;
                        var ch = false;
                        if (e.key === '<')              { _st.left    = true;          ch = true; }
                        if (e.key === '-')              { _st.right   = true;          ch = true; }
                        if (e.key.toLowerCase() === 'r'){ _st.reverse = !_st.reverse;  ch = true; }
                        if (ch) _send();
                    });

                    window.parent.document.addEventListener('keyup', function(e) {
                        var ch = false;
                        if (e.key === '<') { _st.left  = false; ch = true; }
                        if (e.key === '-') { _st.right = false; ch = true; }
                        if (ch) _send();
                    });
                }

                window.parent.postMessage(
                    {isStreamlitMessage: true, type: 'streamlit:setFrameHeight', height: 0}, '*');
            });

            window.parent.postMessage(
                {isStreamlitMessage: true, type: 'streamlit:componentReady', apiVersion: 1}, '*');
        </script></head><body></body></html>""")

_giro_kbd = components.declare_component("pivot_giro_kbd", path=_DIRECTORIO_KBD)


def manejar_teclado():
    from logica.estado import get_sim
    sim = get_sim()

    estado_teclado = _giro_kbd(default=None)

    # El componente de teclado se renderiza para todas las sesiones (necesario para
    # el DOM), pero solo el operador puede modificar el estado de la simulación.
    # Sin este guard, el teclado del observador (con left=False, right=False) machaca
    # los flags slow_down que pone la caja Arduino en la sesión del operador.
    if not st.session_state.get("_is_operator", False):
        return

    if not isinstance(estado_teclado, dict):
        return

    # Marcha atrás (tecla R) — el flag de toggle es per-sesión
    kbd_reverse_ahora  = estado_teclado.get("reverse", False)
    kbd_reverse_previo = st.session_state.marcha_atras_kbd
    if kbd_reverse_ahora != kbd_reverse_previo:
        st.session_state.marcha_atras_kbd = kbd_reverse_ahora
        if sim.lineal and sim.running:
            lineal = sim.lineal
            lineal.invertir_direccion()
            sim.log.append({
                "t":    lineal._tiempo_formateado(),
                "tipo": "INFO",
                "msg":  "MARCHA ATRÁS activada" if lineal.en_marcha_atras else "Avance normal activado",
            })

    # Ralentización por teclado: < → Cart  /  - → End-tower
    if sim.lineal and sim.running:
        lineal = sim.lineal
        ralentizar_cart = bool(estado_teclado.get("left",  False))
        ralentizar_end  = bool(estado_teclado.get("right", False))

        if ralentizar_cart != lineal.slow_down_cart or ralentizar_end != lineal.slow_down_end_tower:
            lineal.slow_down_cart      = ralentizar_cart
            lineal.slow_down_end_tower = ralentizar_end
            if ralentizar_cart:
                mensaje = "Teclado < — Cart ralentizado, giro gradual hacia izquierda"
            elif ralentizar_end:
                mensaje = "Teclado - — End-tower ralentizado, giro gradual hacia derecha"
            else:
                mensaje = "Teclado liberado — velocidad normal"
            sim.log.append({
                "t":    lineal._tiempo_formateado(),
                "tipo": "INFO",
                "msg":  mensaje,
            })
