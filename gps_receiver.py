"""
GPS RECEIVER — ejecutar en el Mac receptor
==========================================
Escucha el puerto serie y muestra las coordenadas GPS del lineal en tiempo real.

Uso en Mac:
    python gps_receiver.py /dev/tty.usbserial-XXXX

Para saber el nombre exacto del puerto en Mac, ejecuta primero:
    ls /dev/tty.usb*
"""

import serial
import sys

PUERTO   = sys.argv[1] if len(sys.argv) > 1 else "/dev/tty.usbserial-0001"
BAUDRATE = 9600


def parsear(linea: str):
    """Extrae lat y lon del mensaje LAT:XXXXXXX,LON:YYYYYYY y los convierte a grados."""
    try:
        partes = dict(p.split(":") for p in linea.strip().split(","))
        lat_e7 = int(partes["LAT"])
        lon_e7 = int(partes["LON"])
        return lat_e7 / 1e7, lon_e7 / 1e7
    except Exception:
        return None, None


def main():
    print(f"Abriendo {PUERTO} a {BAUDRATE} baudios...")
    try:
        ser = serial.Serial(
            PUERTO, BAUDRATE,
            timeout=2, rtscts=False, dsrdtr=False, xonxoff=False,
        )
    except serial.SerialException as e:
        print(f"ERROR: {e}")
        print("\nPuertos disponibles en Mac — ejecuta en otra terminal:")
        print("    ls /dev/tty.usb*")
        sys.exit(1)

    print(f"Conectado. Esperando coordenadas GPS del lineal...\n")
    print(f"{'Mensaje raw':<35}  {'Latitud':>14}  {'Longitud':>14}")
    print("-" * 68)

    try:
        while True:
            linea = ser.readline().decode("utf-8", errors="replace").strip()
            if not linea:
                continue
            lat, lon = parsear(linea)
            if lat is not None:
                print(f"{linea:<35}  {lat:>14.7f}°  {lon:>14.7f}°")
            else:
                print(f"[msg desconocido] {linea}")
    except KeyboardInterrupt:
        print("\nDetenido.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
