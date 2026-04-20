desarrollame una funcion python para calcular la siguiente situacion:

tengo un movil que avanza por una trayectoria circular
esa circunferencia está definida por un centro conocido y un radio conocido que la funcion recibe como parametros (x_c, y_c, r)
la función toma además como parametro un punto inicial pertenciente a la circunferencia  que tambien toma como parametro (x_i, y_i)
la función debe devolver una posición final (x_f, y_f) resultante de haber mi movil avanzado una distancia (d) a lo largo de la circunferencia anteriormente caracterizada

escribe una función facilmente entendible por un ingeniero no experto en matematicas, pero si eficiente en geometria

---

import math

def avanzar_en_circunferencia(x_c, y_c, r, x_i, y_i, d):
    """
    Calcula la posición final de un móvil que avanza una distancia d
    a lo largo de una circunferencia.

    Parámetros:
        x_c, y_c : centro de la circunferencia
        r        : radio de la circunferencia
        x_i, y_i : punto inicial (debe pertenecer a la circunferencia)
        d        : distancia recorrida a lo largo del arco (positiva = sentido antihorario,
                                                            negativa = sentido horario)

    Retorna:
        (x_f, y_f) : posición final sobre la circunferencia
    """

    # --- Paso 1: Calcular el ángulo inicial ---
    # El punto inicial visto desde el centro tiene un ángulo determinado.
    # atan2 nos da ese ángulo en radianes respecto al eje X.
    angulo_inicial = math.atan2(y_i - y_c, x_i - x_c)

    # --- Paso 2: Calcular cuánto ángulo corresponde a la distancia d ---
    # En una circunferencia, arco = radio × ángulo (en radianes)
    # Despejando: ángulo = arco / radio
    angulo_recorrido = d / r

    # --- Paso 3: Calcular el ángulo final ---
    angulo_final = angulo_inicial + angulo_recorrido

    # --- Paso 4: Convertir el ángulo final a coordenadas cartesianas ---
    x_f = x_c + r * math.cos(angulo_final)
    y_f = y_c + r * math.sin(angulo_final)

    return x_f, y_f