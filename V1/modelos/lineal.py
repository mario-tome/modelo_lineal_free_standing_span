import math
from .componentes import (
    Torre_Guia,
    Torre_Intermedia,
    Tramo,
    GPS,
    CajaInterfaz,
)

class Lineal:
    DURACION_CICLO = 60  # segundos por ciclo de duty cycle de las torres guía

    def __init__(self,
                 numero_tramos: int = 5,
                 longitud_tramo: float = 50.0,
                 velocidad_porcentaje: float = 50.0,
                 velocidad_nominal: float = 3.0,
                 ruido_lateral: float = 0.0):

        if numero_tramos < 3:
            raise ValueError(
                "El lineal Free Standing Span necesita mínimo 3 tramos"
            )

        self.numero_tramos = numero_tramos
        self.longitud_tramo = longitud_tramo
        self.velocidad_porcentaje = velocidad_porcentaje
        self.velocidad_nominal = velocidad_nominal

        # Tramo rígido es el tramo central del lineal
        self.indice_tramo_rigido = numero_tramos // 2

        # Torre más rápida: extremo derecho del tramo rígido
        self.indice_torre_motor_rapido = self.indice_tramo_rigido + 1

        # Crear listas de torres
        self.torres = []

        # Torres guía en el extremo izquierdo 
        self.torres.append(Torre_Guia(
            posicion_x = 0.0,
            posicion_y = 0.0,
            longitud_tramo = longitud_tramo,
            velocidad_nominal = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje,
            ruido_lateral = ruido_lateral,
        ))

        # Torres intermedias (la más rápida es la del extremo derecho del tramo rígido)
        for i in range(1, numero_tramos):
            es_rapida = (i == self.indice_torre_motor_rapido)
            self.torres.append(Torre_Intermedia(
                posicion_x = longitud_tramo * i,
                posicion_y = 0.0,
                longitud_tramo = longitud_tramo,
                velocidad_nominal = velocidad_nominal,
                es_motor_rapido = es_rapida
            ))

        # Torre guía en el extremo derecho
        self.torres.append(Torre_Guia(
            posicion_x = longitud_tramo * numero_tramos,
            posicion_y = 0.0,
            longitud_tramo = longitud_tramo,
            velocidad_nominal = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje,
            ruido_lateral = ruido_lateral,
        ))

        # Crear tramos entre torres (tramo rígido el central)
        self.tramos = []
        for i in range(numero_tramos):
            es_rigido = (i == self.indice_tramo_rigido)
            self.tramos.append(Tramo(self.torres[i], self.torres[i + 1], es_rigido=es_rigido))

        self.guia_izquierda = self.torres[0] # Cart
        self.guia_derecha = self.torres[-1] # End-tower

        # Contadores de tiempo y ciclos para simular el duty cycle de las torres guía
        self.tiempo_total_segundos = 0
        self.ciclo_actual = 0
        self._segundo_en_ciclo = 0
        self._en_marcha = False # el lineal comienza parado

        self._segundos_motor_rapido_on = 0 # segundos ON del motor rápido en el ciclo actual
        self.motor_rapido_pct_on = 0.0 # % ON del motor rápido en el último ciclo completo

        # Dirección de marcha (1 = avance, -1 = marcha atrás)
        self.direccion: int = 1

        # Ralentización: True = ese extremo sigue al motor rápido en vez de su duty cycle
        self.slow_down_cart: bool = False
        self.slow_down_end_tower: bool = False

        # GPS y caja de interfaz (se asignan con asignar_gps() / asignar_caja())
        self.gps: GPS | None = None
        self.caja_interfaz: CajaInterfaz | None = None


    def asignar_gps(self,
                    indice_torre: int,
                    lat_origen: float,
                    lon_origen: float,
                    puerto_serial: str = None,
                    baudrate: int = 9600,
                    verbose_consola: bool = False):

        """Asigna un GPS a la torre intermedia indicada (indice entre 1 y N-1)."""
        if not (1 <= indice_torre <= self.numero_tramos - 1):
            raise ValueError(
                f"indice_torre debe estar entre 1 y {self.numero_tramos - 1} "
                f"(solo torres intermedias)"
            )

        torre = self.torres[indice_torre]
        if not isinstance(torre, Torre_Intermedia):
            raise ValueError(f"La torre {indice_torre} no es una Torre_Intermedia")

        self.gps = GPS(torre, lat_origen, lon_origen, puerto_serial, baudrate, verbose_consola)

    def asignar_caja(self,
                     indice_torre: int,
                     lat_origen: float,
                     lon_origen: float,
                     puerto_serial: str,
                     carr: int = 2):

        """Conecta la caja de interfaz Arduino a la torre intermedia indicada."""
        if not (1 <= indice_torre <= self.numero_tramos - 1):
            raise ValueError(
                f"indice_torre debe estar entre 1 y {self.numero_tramos - 1}"
            )

        self.caja_interfaz = CajaInterfaz(
            torre = self.torres[indice_torre],
            lat_origen = lat_origen,
            lon_origen = lon_origen,
            puerto_serial = puerto_serial,
            carr = carr,
        )

    def start(self):
        """Pone el lineal en marcha"""
        self._en_marcha = True

    def stop(self):
        """Detiene el lineal. El tiempo sigue corriendo pero ninguna torre avanza"""
        self._en_marcha = False
        self.guia_izquierda.contactor.abrir()
        self.guia_derecha.contactor.abrir()

    def invertir_direccion(self):
        """Alterna entre avance (norte) y marcha atrás (sur)"""
        self.direccion *= -1

    @property
    def en_marcha_atras(self) -> bool:
        """True cuando el lineal está en marcha atrás (dirección sur)"""
        return self.direccion == -1

    def set_speed(self, velocidad_porcentaje: float):
        """Cambia el duty cycle de ambas torres guía en % durante la simulación"""
        self.velocidad_porcentaje = max(0.0, min(100.0, velocidad_porcentaje))
        dc = self.velocidad_porcentaje / 100.0
        self.guia_izquierda.contactor.duty_cycle = dc
        self.guia_derecha.contactor.duty_cycle   = dc

    @property
    def rumbo(self) -> float:
        """
        Rumbo actual del lineal en radianes desde el norte
        Permite que las guías avancen en la dirección correcta aunque el lineal no vaya recto al norte
        """
        # normalizar el vector para evitar problemas de división por cero
        dx = self.guia_derecha.posicion_x - self.guia_izquierda.posicion_x
        dy = self.guia_derecha.posicion_y - self.guia_izquierda.posicion_y
        
        # lineal alineado no hay dirección definida, se asume rumbo 0 (norte)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0
        
        # devuelve el ángulo entre el eje x positivo y el vector (dx, dy) 
        # como el rumbo se mide desde el norte (eje y positivo) se invierten los argumentos y se niega dy para que el ángulo 0 corresponda al norte
        return math.atan2(-dy, dx)

    def avanza(self, segundos: int = 1):
        """Avanza la simulación el número de segundos indicado"""
        for _ in range(segundos):
            self.tiempo_total_segundos += 1
            self._segundo_en_ciclo = self.tiempo_total_segundos % self.DURACION_CICLO

            if self._segundo_en_ciclo == 0:
                self.ciclo_actual += 1
                self.motor_rapido_pct_on = self._segundos_motor_rapido_on / self.DURACION_CICLO * 100.0
                self._segundos_motor_rapido_on = 0

            if not self._en_marcha:
                continue # el tiempo sigue pero las torres no avanzan

            # calcular el rumbo actual para que las guías avancen
            rumbo = self.rumbo

            # Leer estado de ralentización
            _slow_cart = self.slow_down_cart
            _slow_end  = self.slow_down_end_tower

            # Duty cycle normal para las guías
            self.guia_izquierda.contactor.actualizar_duty_cycle(
                self._segundo_en_ciclo, self.DURACION_CICLO)
            self.guia_derecha.contactor.actualizar_duty_cycle(
                self._segundo_en_ciclo, self.DURACION_CICLO)

            # Torre rápida: su contactor marca el ritmo del motor en modo slow_down
            torre_rapida = self.torres[self.indice_torre_motor_rapido]

            if _slow_cart and not _slow_end:
                # SLOW_DOWN_CART: Cart copia el ON/OFF del motor rápido
                if torre_rapida.contactor.esta_cerrado:
                    self.guia_izquierda.contactor.cerrar()
                else:
                    self.guia_izquierda.contactor.abrir()
                self.guia_izquierda.avanzar(1, self.direccion, rumbo)
                self.guia_derecha.avanzar(1, self.direccion, rumbo)

            elif _slow_end and not _slow_cart:
                # SLOW_DOWN_END_TOWER: End-tower copia el ON/OFF del motor rápido
                if torre_rapida.contactor.esta_cerrado:
                    self.guia_derecha.contactor.cerrar()
                else:
                    self.guia_derecha.contactor.abrir()
                self.guia_derecha.avanzar(1, self.direccion, rumbo)
                self.guia_izquierda.avanzar(1, self.direccion, rumbo)

            else:
                # Sin slow_down activo avance normal por duty cycle
                self.guia_izquierda.avanzar(1, self.direccion, rumbo)
                self.guia_derecha.avanzar(1, self.direccion, rumbo)

            # Cada intermedia sigue su posición ideal en la diagonal avanzando sobre un arco de circunferencia centrado en la torre de al lado
            x_cart = self.torres[0].posicion_x
            y_cart = self.torres[0].posicion_y
            x_end  = self.torres[-1].posicion_x
            y_end  = self.torres[-1].posicion_y
            numero_intervalos = len(self.torres) - 1
            indice_rigido = self.indice_tramo_rigido

            # Lado izquierdo: torres 1..indice_rigido, pivote = vecino izquierdo ya actualizado
            for i in range(1, indice_rigido + 1):
                torre_pivote = self.torres[i - 1]
                x_objetivo = x_cart + (x_end - x_cart) * i / numero_intervalos
                y_objetivo = y_cart + (y_end - y_cart) * i / numero_intervalos
                
                self.torres[i].seguir(
                    x_objetivo, y_objetivo, 1, self.direccion,
                    torre_pivote.posicion_x, torre_pivote.posicion_y, rumbo
                )

            # Lado derecho: torres (N-1)..indice_rigido+1, pivote = vecino derecho ya actualizado
            for i in range(numero_intervalos - 1, indice_rigido, -1):
                torre_pivote = self.torres[i + 1]
                x_objetivo   = x_cart + (x_end - x_cart) * i / numero_intervalos
                y_objetivo   = y_cart + (y_end - y_cart) * i / numero_intervalos
                
                self.torres[i].seguir(
                    x_objetivo, y_objetivo, 1, self.direccion,
                    torre_pivote.posicion_x, torre_pivote.posicion_y, rumbo
                )

            self._actualizar_fss()

            if self.torres[self.indice_torre_motor_rapido].contactor.esta_cerrado:
                self._segundos_motor_rapido_on += 1


    @property
    def posicion_norte(self) -> float:
        """Posición media del lineal en el eje norte"""
        return sum(t.posicion_y for t in self.torres) / len(self.torres)

    @property
    def longitud_total(self) -> float:
        """Longitud total del lineal de extremo a extremo"""
        return self.numero_tramos * self.longitud_tramo

    @property
    def esta_alineado(self) -> bool:
        """True si todos los tramos están dentro de la tolerancia de alineación"""
        return all(t.esta_alineado for t in self.tramos)


    def _actualizar_fss(self):
        """
        Corrige el tramo rígido central: 
        promedia las posiciones que fijaron los dos lados y recoloca ambas torres del FSS paralelas al eje Cart - End-tower (manteniendo longitud_tramo)
        También actualiza angulo_referencia de todos los tramos para que el display sea correcto cuando el lineal avanza en diagonal
        """
        indice_rigido       = self.indice_tramo_rigido
        torre_izquierda_fss = self.torres[indice_rigido]
        torre_derecha_fss   = self.torres[indice_rigido + 1]

        x_centro = (torre_izquierda_fss.posicion_x + torre_derecha_fss.posicion_x) / 2.0
        y_centro = (torre_izquierda_fss.posicion_y + torre_derecha_fss.posicion_y) / 2.0

        # Vector unitario a lo largo del lineal completo (Cart - End-tower)
        dx = self.guia_derecha.posicion_x - self.guia_izquierda.posicion_x
        dy = self.guia_derecha.posicion_y - self.guia_izquierda.posicion_y
        long_total = math.sqrt(dx * dx + dy * dy)
        
        if long_total < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux = dx / long_total
            uy = dy / long_total

        media = self.longitud_tramo / 2.0
        torre_izquierda_fss.posicion_x = x_centro - ux * media
        torre_izquierda_fss.posicion_y = y_centro - uy * media
        torre_derecha_fss.posicion_x   = x_centro + ux * media
        torre_derecha_fss.posicion_y   = y_centro + uy * media

        # Actualiza ángulo de referencia de todos los tramos 
        angulo_ref = math.degrees(math.atan2(dy, dx))
        for tramo in self.tramos:
            tramo.angulo_referencia = angulo_ref

    def _tiempo_formateado(self) -> str:
        """Devuelve el tiempo total transcurrido en formato Hh Mm Ss"""
        h = self.tiempo_total_segundos // 3600
        m = (self.tiempo_total_segundos % 3600) // 60
        s = self.tiempo_total_segundos % 60
        return f"{h:02d}h {m:02d}m {s:02d}s"
