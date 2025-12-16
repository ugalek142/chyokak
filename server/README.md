# MiniChat

Una aplicación de chat estilo WhatsApp con servidor FastAPI y WebSockets.

## Características

- Interfaz similar a WhatsApp con sidebar de chats
- Mensajes con burbujas y avatares
- Múltiples chats por ID
- Lista de usuarios en línea
- Selector de emojis
- Mensajes en tiempo real
- Cliente web y CLI

## Instalación y ejecución

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload
```

El servidor estará disponible en http://localhost:8000

## Uso

1. Abre http://localhost:8000 en tu navegador
2. Ingresa tu nombre cuando se te pida
3. Haz clic en "Nuevo Chat" para crear un chat
4. Selecciona un chat de la lista para unirse
5. Escribe mensajes y envíalos

## Cliente CLI

```bash
python client.py --host localhost --port 8000 --chat global --name alice
```
