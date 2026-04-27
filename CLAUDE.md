Analiza el siguiente proyecto para así tener un contexto del mismo en tu memoria, ya que a
  continuación te voy a pedir una serie de mejoras y/o funcionalidades nuevas las cuales vas a
  llevar a cabo SIEMPRE bajo el rol de: Desarrollador Senior Python y las especificaciones de:
  código limpio, fácil de entender por alguien que no tenga conocimientos en programación y
  comentarios cortos pero que aporten valor (es decir como está ahora, nada de complejidad ni deuda
  técnica). El caso, es que tras el análisis verás que este proyecto trata de la creación de un
  gemelo digital EXACTO a un pívot lineal. Cuál es su finalidad? básicamente es para complementar a
  un proyecto de GUIADO GPS el cual hace ir de forma recta al lineal por una recta/curva (sucesion
  de puntos) que el compañero decida. Y por tanto como verás en el código ya que ya está
  funcional, desde la UI el usuario en el sidebar selecciona "Caja de interfaz Arduino", y la torre
  intermedia que decida emitirá por puerto serie las coordenadas GPS que tiene la torre y la caja
  de guiado gps verá como corregir la posicion de lineal mediante ordenes de ralentización de las
  torres guías. Dicha caja de guiado comunica con una caja de interfaz la cual va conectada al
  equipo que ejecuta streamlit run app.py. El caso es que aunque ahora funcione la comunicación y
  guiado tenemos una serie de problemas con la logica de movimiento del lineal, y aqui es donde vas
  a entrar TÚ. Pero primero como te he comentado necesito que analices el código para tener un
  mejor conexto. Como verás, principalmente se divide en modelo.py con la logica de un lineal, y
  app.py con la interfeaz web la cual está refactorizada en las carpetas /logica y /ui. Cuando
  termines dicho analisis, te pondré en contexto de lo que no funciona correctamente y hay que
  arreglar