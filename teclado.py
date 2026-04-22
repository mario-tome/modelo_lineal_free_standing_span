import os
import time
import streamlit as st
import streamlit.components.v1 as components

_DIRECTORIO_KBD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "giro_kbd")
os.makedirs(_DIRECTORIO_KBD, exist_ok=True)
with open(os.path.join(_DIRECTORIO_KBD, "index.html"), "w", encoding="utf-8") as _f:
    _f.write("""<!DOCTYPE html><html><head><script>
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
    estado_teclado = _giro_kbd(default=None)
    if not isinstance(estado_teclado, dict):
        return

    # Marcha atrás (tecla R)
    kbd_reverse_ahora  = estado_teclado.get("reverse", False)
    kbd_reverse_previo = st.session_state.marcha_atras_kbd
    if kbd_reverse_ahora != kbd_reverse_previo:
        st.session_state.marcha_atras_kbd = kbd_reverse_ahora
        if st.session_state.lineal and st.session_state.running:
            lineal = st.session_state.lineal
            lineal.invertir_direccion()
            texto_direccion = "MARCHA ATRÁS activada" if lineal.en_marcha_atras else "Avance normal activado"
            st.session_state.log.append({
                "t":    lineal._tiempo_formateado(),
                "tipo": "INFO",
                "msg":  texto_direccion,
            })

    # Ralentización por teclado: < → ralentiza Cart  /  - → ralentiza End-tower
    if st.session_state.lineal and st.session_state.running:
        lineal       = st.session_state.lineal
        slow_cart_kbd = bool(estado_teclado.get("left",  False))
        slow_end_kbd  = bool(estado_teclado.get("right", False))

        if slow_cart_kbd != lineal.slow_down_cart or slow_end_kbd != lineal.slow_down_end_tower:
            lineal.slow_down_cart      = slow_cart_kbd
            lineal.slow_down_end_tower = slow_end_kbd
            if slow_cart_kbd:
                mensaje = "Teclado < — Cart ralentizado, giro gradual hacia izquierda"
            elif slow_end_kbd:
                mensaje = "Teclado - — End-tower ralentizado, giro gradual hacia derecha"
            else:
                mensaje = "Teclado liberado — velocidad normal"
            st.session_state.log.append({
                "t":    lineal._tiempo_formateado(),
                "tipo": "INFO",
                "msg":  mensaje,
            })
