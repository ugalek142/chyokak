from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Dict, List
import json
import sqlite3
from datetime import datetime
import bcrypt

app = FastAPI()

class UserCredentials(BaseModel):
    username: str
    password: str

# Инициализация БД
def init_db():
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        chat_id TEXT,
        user_id INTEGER,
        text TEXT,
        timestamp TEXT,
        type TEXT DEFAULT 'text',
        image_data TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY,
        message_id INTEGER,
        user_id INTEGER,
        emoji TEXT,
        FOREIGN KEY (message_id) REFERENCES messages (id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        UNIQUE(message_id, user_id, emoji)
    )''')
    conn.commit()
    conn.close()

init_db()

# Функции для работы с БД
def get_user_id(username: str) -> int:
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    return user[0] if user else None

def save_message(chat_id: str, user_id: int, text: str, timestamp: str, msg_type: str = 'text', image_data: str = None):
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (chat_id, user_id, text, timestamp, type, image_data) VALUES (?, ?, ?, ?, ?, ?)",
              (chat_id, user_id, text, timestamp, msg_type, image_data))
    message_id = c.lastrowid
    conn.commit()
    conn.close()
    return message_id

def load_messages(chat_id: str) -> List[dict]:
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT m.id, m.chat_id, u.username, m.text, m.timestamp, m.type, m.image_data
        FROM messages m
        JOIN users u ON m.user_id = u.id
        WHERE m.chat_id = ?
        ORDER BY m.timestamp
    """, (chat_id,))
    messages = [{"id": row[0], "chat_id": row[1], "user": row[2], "text": row[3], "timestamp": row[4], "type": row[5], "image_data": row[6]} for row in c.fetchall()]
    conn.close()
    return messages

def save_reaction(message_id: int, user_id: int, emoji: str):
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("INSERT INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
              (message_id, user_id, emoji))
    conn.commit()
    conn.close()

def load_reactions(chat_id: str) -> Dict[str, Dict[str, List[str]]]:
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("""
        SELECT m.timestamp, r.emoji, u.username
        FROM reactions r
        JOIN messages m ON r.message_id = m.id
        JOIN users u ON r.user_id = u.id
        WHERE m.chat_id = ?
    """, (chat_id,))
    reactions = {}
    for row in c.fetchall():
        timestamp, emoji, username = row
        if timestamp not in reactions:
            reactions[timestamp] = {}
        if emoji not in reactions[timestamp]:
            reactions[timestamp][emoji] = []
        reactions[timestamp][emoji].append(username)
    conn.close()
    return reactions

# Раздача статических файлов (фронтенд)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse('static/index.html')

# Зарегистрированные пользователи теперь в БД

# Активные соединения и пользователи
connections: Dict[str, List[WebSocket]] = {}
users: Dict[str, Dict[str, WebSocket]] = {}  # chat_id -> {username: websocket}

# История сообщений теперь в БД

# Реакции теперь в БД

# Пользователи, которые печатают: chat_id -> set of usernames
typing_users: Dict[str, set] = {}


@app.post("/register")
async def register_user(credentials: UserCredentials):
    username = credentials.username
    password = credentials.password
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        return {"message": "Usuario registrado exitosamente"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    finally:
        conn.close()


@app.post("/login")
async def login_user(credentials: UserCredentials):
    username = credentials.username
    password = credentials.password
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    if user and bcrypt.checkpw(password.encode('utf-8'), user[1].encode('utf-8')):
        return {"message": "Login exitoso", "username": username}
    raise HTTPException(status_code=401, detail="Credenciales inválidas")


@app.get("/login")
async def login_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - MiniChat</title>
        <style>
            body { font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f0f0; }
            .container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
            input { display: block; margin: 10px 0; padding: 10px; width: 100%; }
            button { padding: 10px; background: #007bff; color: white; border: none; cursor: pointer; width: 100%; }
            button:hover { background: #0056b3; }
            .link { text-align: center; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Iniciar Sesión</h2>
            <form id="loginForm">
                <input type="text" id="username" placeholder="Usuario" required>
                <input type="password" id="password" placeholder="Contraseña" required>
                <button type="submit">Iniciar Sesión</button>
            </form>
            <div class="link"><a href="/register">¿No tienes cuenta? Regístrate</a></div>
        </div>
        <script>
            document.getElementById('loginForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const response = await fetch('/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                if (response.ok) {
                    localStorage.setItem('username', username);
                    window.location.href = '/';
                } else {
                    alert('Credenciales inválidas');
                }
            });
        </script>
    </body>
    </html>
    """)


@app.get("/register")
async def register_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Register - MiniChat</title>
        <style>
            body { font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f0f0; }
            .container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
            input { display: block; margin: 10px 0; padding: 10px; width: 100%; }
            button { padding: 10px; background: #28a745; color: white; border: none; cursor: pointer; width: 100%; }
            button:hover { background: #218838; }
            .link { text-align: center; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Registrarse</h2>
            <form id="registerForm">
                <input type="text" id="username" placeholder="Usuario" required>
                <input type="password" id="password" placeholder="Contraseña" required>
                <button type="submit">Registrarse</button>
            </form>
            <div class="link"><a href="/login">¿Ya tienes cuenta? Inicia sesión</a></div>
        </div>
            <script>
            document.getElementById('registerForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const response = await fetch('/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                if (response.ok) {
                    alert('Usuario registrado. Ahora inicia sesión.');
                    window.location.href = '/login';
                } else {
                    alert('Error al registrar usuario');
                }
            });
        </script>
    </body>
    </html>
    """)


async def broadcast_user_list(chat_id: str):
    """Отправляет список пользователей всем в чате"""
    user_list = [{"username": user, "status": "online"} for user in users.get(chat_id, {}).keys()]
    response = {
        "type": "user_list",
        "payload": {"users": user_list}
    }
    for connection in connections.get(chat_id, []):
        await connection.send_text(json.dumps(response))


async def broadcast_reactions(chat_id: str, message_timestamp: str):
    """Отправляет реакции на сообщение всем в чате"""
    reactions_data = load_reactions(chat_id)
    reaction_data = reactions_data.get(message_timestamp, {})
    response = {
        "type": "reactions_update",
        "payload": {
            "chat_id": chat_id,
            "message_timestamp": message_timestamp,
            "reactions": reaction_data
        }
    }
    for connection in connections.get(chat_id, []):
        await connection.send_text(json.dumps(response))


async def broadcast_typing(chat_id: str):
    """Отправляет статус печати всем в чате"""
    typing_list = list(typing_users.get(chat_id, set()))
    response = {
        "type": "typing_update",
        "payload": {
            "chat_id": chat_id,
            "typing_users": typing_list
        }
    }
    for connection in connections.get(chat_id, []):
        await connection.send_text(json.dumps(response))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    current_chat = None
    current_user = None

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")
            payload = message.get("payload", {})

            # Инициализация пользователя
            if msg_type == "join":
                username = payload.get("user", "anonymous")
                user_id = get_user_id(username)
                if user_id:
                    current_user = username
                else:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Usuario no registrado"}))
                    continue

            # Смена чата
            elif msg_type == "switch_chat" and current_user:
                new_chat = payload["chat_id"]
                if current_chat:
                    # Удалить из старого чата
                    if websocket in connections.get(current_chat, []):
                        connections[current_chat].remove(websocket)
                    if current_user in users.get(current_chat, {}):
                        del users[current_chat][current_user]
                        if current_user in typing_users.get(current_chat, set()):
                            typing_users[current_chat].remove(current_user)
                        await broadcast_user_list(current_chat)
                        await broadcast_typing(current_chat)
                # Присоединиться к новому
                current_chat = new_chat
                connections.setdefault(current_chat, []).append(websocket)
                users.setdefault(current_chat, {})
                users[current_chat][current_user] = websocket
                typing_users.setdefault(current_chat, set())

                # Отправить историю из БД
                messages = load_messages(current_chat)
                await websocket.send_text(json.dumps({
                    "type": "history",
                    "payload": {
                        "chat_id": current_chat,
                        "messages": messages
                    }
                }))
                # Отправить реакции из БД
                reactions_data = load_reactions(current_chat)
                for msg_timestamp, msg_reactions in reactions_data.items():
                    await websocket.send_text(json.dumps({
                        "type": "reactions_update",
                        "payload": {
                            "chat_id": current_chat,
                            "message_timestamp": msg_timestamp,
                            "reactions": msg_reactions
                        }
                    }))
                await broadcast_user_list(current_chat)
                await broadcast_typing(current_chat)

            # Отправка сообщения
            elif msg_type == "send_message" and current_chat and current_user:
                user_id = get_user_id(current_user)
                text = payload.get("text", "")
                timestamp = datetime.utcnow().isoformat()
                msg_id = save_message(current_chat, user_id, text, timestamp)
                msg = {
                    "id": msg_id,
                    "chat_id": current_chat,
                    "user": current_user,
                    "text": text,
                    "timestamp": timestamp,
                    "type": "text"
                }

                response = {
                    "type": "new_message",
                    "payload": msg
                }

                # Рассылка всем в чате
                for connection in connections.get(current_chat, []):
                    await connection.send_text(json.dumps(response))

            # Добавление реакции
            elif msg_type == "add_reaction" and current_chat and current_user:
                message_timestamp = payload.get("message_timestamp")
                emoji = payload.get("emoji")
                if message_timestamp is not None and emoji:
                    # Найти message_id по timestamp
                    conn = sqlite3.connect('chat.db')
                    c = conn.cursor()
                    c.execute("SELECT id FROM messages WHERE chat_id = ? AND timestamp = ?", (current_chat, message_timestamp))
                    msg_row = c.fetchone()
                    conn.close()
                    if msg_row:
                        message_id = msg_row[0]
                        user_id = get_user_id(current_user)
                        save_reaction(message_id, user_id, emoji)
                        # Отправляем обновление всем участникам чата
                        reactions_data = load_reactions(current_chat)
                        for connection in connections.get(current_chat, []):
                            await connection.send_text(json.dumps({
                                "type": "reactions_update",
                                "chat_id": current_chat,
                                "message_timestamp": message_timestamp,
                                "reactions": reactions_data.get(message_timestamp, {})
                            }))

            # Начало печати
            elif msg_type == "typing_start" and current_chat and current_user:
                typing_users.setdefault(current_chat, set()).add(current_user)
                await broadcast_typing(current_chat)

            # Окончание печати
            elif msg_type == "typing_stop" and current_chat and current_user:
                if current_chat in typing_users and current_user in typing_users[current_chat]:
                    typing_users[current_chat].remove(current_user)
                    await broadcast_typing(current_chat)

            # Отправка изображения
            elif msg_type == "send_image" and current_chat and current_user:
                image_data = payload.get("image_data")  # base64
                user_id = get_user_id(current_user)
                timestamp = datetime.utcnow().isoformat()
                msg_id = save_message(current_chat, user_id, "", timestamp, "image", image_data)
                msg = {
                    "id": msg_id,
                    "chat_id": current_chat,
                    "user": current_user,
                    "text": "",
                    "image_data": image_data,
                    "timestamp": timestamp,
                    "type": "image"
                }
                response = {
                    "type": "new_message",
                    "payload": msg
                }
                for connection in connections.get(current_chat, []):
                    await connection.send_text(json.dumps(response))

    except WebSocketDisconnect:
        if current_chat and websocket in connections.get(current_chat, []):
            connections[current_chat].remove(websocket)
            if current_user in users.get(current_chat, {}):
                del users[current_chat][current_user]
                if current_user in typing_users.get(current_chat, set()):
                    typing_users[current_chat].remove(current_user)
                await broadcast_user_list(current_chat)
                await broadcast_typing(current_chat)
