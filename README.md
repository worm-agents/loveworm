# 🪱 LoveWorm

Dashboard local para manejar Tinder: swipes con pausas, galería de tus matches ordenada por interés y
borradores de mensajes escritos por Claude que solo se envían cuando vos los aprobás.

## Qué hace

- **Bot de swipes**: likes y dislikes con un ratio y pausas al azar entre cada uno. Se puede detener en cualquier momento.
- **Galería**: una card por persona con todas sus fotos, cómo es según su bio y lo que contó, y de qué hablaron.
- **Orden por interés**: Claude le pone a cada persona un puntaje de 0 a 100. Arriba quedan quienes pasaron su
  Instagram o propusieron salir; abajo, quienes nunca respondieron.
- **Matches nuevos**: los matches sin chat, con su bio y un primer mensaje sugerido.
- **Borradores con aprobación**: Claude sugiere el primer mensaje o la respuesta siguiendo las instrucciones de la
  configuración. Nada se envía sin que toques **Enviar** y lo confirmes.
- **Piloto automático** (opcional): en los pocos chats que automatiza, escribe y envía solo, con una demora al azar
  antes de cada respuesta, solo dentro de tu horario de envío y con un tope por día. Hasta que sale, lo podés descartar.
- **Swipes diarios**: una meta de likes por día, en tandas con pausas al azar dentro de una franja horaria. Antes de
  cada tanda consulta cuántos likes te deja Tinder.

Instagram está en pausa: la web ya no expone los DMs por su API y la lectura por pantalla todavía no es confiable
(`INSTAGRAM_ENABLED` en `loveworm/dashboard/worker.py`).

## Cómo funciona

- Todo corre en tu máquina. El servidor escucha solo en `127.0.0.1:5000`.
- Abre un Chrome propio (`undetected-chromedriver`) con un perfil guardado en `chrome_profile/`. El login lo hacés
  vos a mano la primera vez; la contraseña nunca pasa por el código.
- Los chats y matches se leen con la API de Tinder Web usando esa sesión del navegador, con pausas entre requests,
  y solo se vuelven a bajar los chats que cambiaron.
- Los análisis y borradores usan el CLI de [Claude Code](https://claude.com/claude-code) (`claude -p`) con tu
  suscripción, sin herramientas y sin guardar sesión. Reciben solo el nombre, la bio y el texto del chat.
- Chats, análisis y configuración se guardan en `data/`, que no se sube al repo.

> ⚠️ Automatizar Tinder va contra sus términos de uso y puede terminar en el bloqueo de la cuenta. Usalo con
> moderación y bajo tu responsabilidad.

## Requisitos

- Windows, Python 3.12+ y Google Chrome
- [Claude Code](https://claude.com/claude-code) instalado y logueado (`claude` en el PATH)

## Uso

```powershell
git clone https://github.com/worm-agents/loveworm.git
cd loveworm
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m loveworm.dashboard
```

Abrí http://127.0.0.1:5000 y tocá **Iniciar**. Si no estás logueado, iniciá sesión en el Chrome que se abre
(Log in → Google). Después el dashboard trae tus chats y empieza a analizarlos.

El Chrome del bot corre **en segundo plano**: queda fuera de la vista y nunca se pone adelante mientras usás la
compu (solo aparece si hay que iniciar sesión). **Ver Chrome** en la barra de arriba lo muestra y lo vuelve a
ocultar. Se puede apagar en Configuración → Arranque.

Antes de prender los borradores, completá en **Configuración**:

- **Sobre vos**: qué hacés, dónde vivís, qué te gusta. Claude lo usa para tener de qué hablar.
- **Para salir**: los días en que podés tener una cita, tu zona y lugares que puede proponer. Claude solo
  propone esos días y esos lugares.
- **Instrucciones**: el tono y lo que querés evitar.

`abrir_dashboard.ps1` levanta el servidor si no está corriendo y abre el dashboard; sirve para un acceso directo.

Para que las automatizaciones corran sin tocar nada: corré `install_task.ps1` una vez (crea la tarea
"LoveWorm - Dashboard", que levanta el servidor al iniciar sesión) y prendé **Abrir Chrome solo al iniciar el
dashboard** en Configuración.

## Estructura

```
loveworm/
  dashboard/       servidor Flask, worker del bot y la página (templates/index.html)
  helpers/
    tinder_api.py  lectura de chats y envío de mensajes con la sesión del navegador
    llm.py         análisis de personas y borradores con `claude -p`
    instagram_web.py  lector de Instagram por pantalla (en pausa)
    ...            helpers de Selenium heredados de TinderBotz (login, swipes, perfil)
  session.py       sesión de Chrome y acciones del bot
```

## Créditos

Basado en [TinderBotz](https://github.com/frederikme/TinderBotz) de Frederik Mees (licencia MIT, ver `LICENSE.txt`).
