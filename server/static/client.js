(() => {
  const wsUrl = (location.protocol === 'https:') ? 'wss://' + location.host + '/ws' : 'ws://' + location.host + '/ws';
  let socket = null;
  let currentUser = '';
  let currentChat = null;
  let joinedChats = new Set();
  let messageElements = []; // Для реакций

  const $userName = document.getElementById('user-name');
  const $userAvatar = document.getElementById('user-avatar');
  const $chatName = document.getElementById('chat-name');
  const $chatStatus = document.getElementById('chat-status');
  const $chatList = document.getElementById('chat-list');
  const $messages = document.getElementById('messages');
  const $text = document.getElementById('text');
  const $send = document.getElementById('send');
  const $emojiBtn = document.getElementById('emoji-btn');
  const $emojiPicker = document.getElementById('emoji-picker');
  const $newChat = document.getElementById('new-chat');
  const $newChatModal = document.getElementById('new-chat-modal');
  const $newChatId = document.getElementById('new-chat-id');
  const $createChat = document.getElementById('create-chat');
  const $search = document.getElementById('search');
  const $themeToggle = document.getElementById('theme-toggle');
  const $fileBtn = document.getElementById('file-btn');
  const $fileInput = document.getElementById('file-input');
  const $typingIndicator = document.getElementById('typing-indicator');

  function getAvatarInitials(name) {
    return name.charAt(0).toUpperCase();
  }

  function addChatToList(chatId) {
    if (document.querySelector(`[data-chat-id="${chatId}"]`)) return;
    const chatItem = document.createElement('div');
    chatItem.className = 'chat-item';
    chatItem.dataset.chatId = chatId;
    chatItem.innerHTML = `
      <img src="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='50' fill='%23ddd'/><text x='50' y='65' text-anchor='middle' fill='%23666' font-size='40'>${getAvatarInitials(chatId)}</text></svg>" alt="${chatId}">
      <div class="chat-info">
        <div class="chat-name">${escapeHtml(chatId)}</div>
        <div class="last-msg">Nuevo chat</div>
      </div>
      <div class="chat-time">${new Date().toLocaleTimeString()}</div>
    `;
    chatItem.addEventListener('click', () => switchChat(chatId));
    $chatList.appendChild(chatItem);
  }

  function switchChat(chatId) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      alert('No conectado');
      return;
    }
    currentChat = chatId;
    socket.send(JSON.stringify({ type: 'switch_chat', payload: { chat_id: chatId } }));
    document.querySelectorAll('.chat-item').forEach(item => item.classList.remove('active'));
    document.querySelector(`[data-chat-id="${chatId}"]`).classList.add('active');
    $chatName.textContent = chatId;
    $messages.innerHTML = '';
    $chatStatus.textContent = 'Cargando...';
    messageElements = [];
  }

  function addMessage(msg, index = null) {
    const isOwn = msg.user === currentUser;
    const messageEl = document.createElement('div');
    messageEl.className = `message ${isOwn ? 'own' : 'other'}`;
    messageEl.dataset.index = index !== null ? index : messageElements.length;
    messageEl.dataset.timestamp = msg.timestamp;

    let content = '';
    if (msg.type === 'image') {
      content = `<div class="image-msg"><img src="${msg.image_data}" alt="Image"></div>`;
    } else {
      content = formatMessage(escapeHtml(msg.text));
    }

    messageEl.innerHTML = `
      ${!isOwn ? `<div class="avatar">${getAvatarInitials(msg.user)}</div>` : ''}
      <div class="bubble">
        ${!isOwn ? `<div class="sender">${escapeHtml(msg.user)}</div>` : ''}
        <div>${content}</div>
        <div class="time">${new Date(msg.timestamp).toLocaleTimeString()}</div>
        <div class="reactions" data-index="${messageEl.dataset.index}"></div>
      </div>
      ${isOwn ? `<div class="avatar">${getAvatarInitials(msg.user)}</div>` : ''}
    `;

    // Добавить обработчик реакции
    messageEl.querySelector('.bubble').addEventListener('click', (e) => {
      if (e.target.classList.contains('reaction')) return;
      showReactionPicker(msg.timestamp);
    });

    $messages.appendChild(messageEl);
    $messages.scrollTop = $messages.scrollHeight;
    messageElements.push(messageEl);

    // Sound notification for new messages
    if (!isOwn) {
      playNotificationSound();
    }
  }

  function showReactionPicker(messageTimestamp) {
    const reactions = ['👍', '❤️', '😂', '😢', '😡', '🔥', '🎉'];
    const picker = document.createElement('div');
    picker.className = 'reaction-picker';
    picker.innerHTML = reactions.map(r => `<button>${r}</button>`).join('');
    picker.style.position = 'absolute';
    picker.style.background = 'white';
    picker.style.border = '1px solid #ddd';
    picker.style.borderRadius = '10px';
    picker.style.padding = '5px';
    picker.style.display = 'flex';
    picker.style.gap = '5px';

    picker.addEventListener('click', (e) => {
      if (e.target.tagName === 'BUTTON') {
        socket.send(JSON.stringify({
          type: 'add_reaction',
          payload: { message_timestamp: messageTimestamp, emoji: e.target.textContent }
        }));
        document.body.removeChild(picker);
      }
    });

    document.body.appendChild(picker);
    const rect = messageElements[messageElements.length - 1].getBoundingClientRect(); // Simplificar, usar último
    picker.style.left = rect.left + 'px';
    picker.style.top = (rect.top - 40) + 'px';

    setTimeout(() => document.body.removeChild(picker), 3000);
  }

  function updateReactions(chatId, messageTimestamp, reactions) {
    const messageEl = document.querySelector(`[data-timestamp="${messageTimestamp}"]`);
    if (!messageEl) return;
    const reactionsEl = messageEl.querySelector('.reactions');
    reactionsEl.innerHTML = '';
    for (const [emoji, users] of Object.entries(reactions)) {
      const reactionEl = document.createElement('span');
      reactionEl.className = 'reaction';
      reactionEl.textContent = `${emoji} ${users.length}`;
      reactionsEl.appendChild(reactionEl);
    }
  }

  function updateTypingIndicator(typingUsers) {
    if (typingUsers.length > 0) {
      $typingIndicator.textContent = `${typingUsers.join(', ')} ${typingUsers.length === 1 ? 'está' : 'están'} escribiendo...`;
      $typingIndicator.style.display = 'block';
    } else {
      $typingIndicator.style.display = 'none';
    }
  }

  function updateLastMessage(chatId, text, timestamp) {
    const chatItem = document.querySelector(`[data-chat-id="${chatId}"]`);
    if (chatItem) {
      chatItem.querySelector('.last-msg').textContent = text.length > 30 ? text.substring(0, 30) + '...' : text;
      chatItem.querySelector('.chat-time').textContent = new Date(timestamp).toLocaleTimeString();
    }
  }

  function updateUserList(users) {
    const $userList = document.getElementById('user-list');
    $userList.innerHTML = '';
    users.forEach(user => {
      const li = document.createElement('li');
      li.textContent = `${user.username} (${user.status})`;
      $userList.appendChild(li);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function formatMessage(text) {
    // Simple markdown-like formatting
    return text
      .replace(/\*(.*?)\*/g, '<strong>$1</strong>')
      .replace(/_(.*?)_/g, '<em>$1</em>')
      .replace(/\n/g, '<br>');
  }

  function playNotificationSound() {
    // Simple beep sound
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    oscillator.frequency.setValueAtTime(800, audioContext.currentTime);
    oscillator.type = 'sine';
    gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.2);
  }

  function connect(userName) {
    currentUser = userName;
    $userName.textContent = userName;
    $userAvatar.textContent = getAvatarInitials(userName);
    socket = new WebSocket(wsUrl);

    socket.addEventListener('open', () => {
      // Отправить join для инициализации пользователя
      socket.send(JSON.stringify({ type: 'join', payload: { user: currentUser } }));
    });

    socket.addEventListener('message', (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'history') {
          data.payload.messages.forEach((msg, idx) => addMessage(msg, idx));
        } else if (data.type === 'new_message') {
          const msg = data.payload;
          addMessage(msg);
          updateLastMessage(msg.chat_id, msg.text || '[Imagen]', msg.timestamp);
        } else if (data.type === 'user_list') {
          updateUserList(data.payload.users);
        } else if (data.type === 'reactions_update') {
          updateReactions(data.payload.chat_id, data.payload.message_timestamp, data.payload.reactions);
        } else if (data.type === 'typing_update') {
          updateTypingIndicator(data.payload.typing_users);
        }
      } catch (e) {
        console.warn('Invalid message', e, ev.data);
      }
    });

    socket.addEventListener('close', () => {
      alert('Conexión cerrada');
      $send.disabled = true;
    });

    socket.addEventListener('error', () => {
      alert('Error de conexión');
    });
  }

  $newChat.addEventListener('click', () => {
    $newChatModal.classList.add('show');
  });

  $createChat.addEventListener('click', () => {
    const chatId = $newChatId.value.trim();
    if (chatId) {
      addChatToList(chatId);
      switchChat(chatId);
      $newChatModal.classList.remove('show');
      $newChatId.value = '';
    }
  });

  $send.addEventListener('click', () => {
    if (!socket || socket.readyState !== WebSocket.OPEN || !currentChat) {
      alert('No conectado o chat no seleccionado');
      return;
    }
    const text = $text.value.trim();
    if (!text) {
      alert('Ingresa un mensaje');
      return;
    }
    const payload = { text, user: currentUser };
    socket.send(JSON.stringify({ type: 'send_message', payload }));
    $text.value = '';
    socket.send(JSON.stringify({ type: 'typing_stop' }));
  });

  $text.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $send.click();
  });

  $text.addEventListener('input', () => {
    if ($text.value.trim()) {
      socket.send(JSON.stringify({ type: 'typing_start' }));
    } else {
      socket.send(JSON.stringify({ type: 'typing_stop' }));
    }
  });

  $emojiBtn.addEventListener('click', () => {
    $emojiPicker.classList.toggle('show');
  });

  $emojiPicker.addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') {
      $text.value += e.target.textContent;
      $emojiPicker.classList.remove('show');
      $text.focus();
    }
  });

  $search.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    document.querySelectorAll('.chat-item').forEach(item => {
      const name = item.querySelector('.chat-name').textContent.toLowerCase();
      item.style.display = name.includes(query) ? 'flex' : 'none';
    });
  });

  $themeToggle.addEventListener('click', () => {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    $themeToggle.textContent = newTheme === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('theme', newTheme);
  });

  $fileBtn.addEventListener('click', () => {
    $fileInput.click();
  });

  $fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = () => {
        socket.send(JSON.stringify({
          type: 'send_image',
          payload: { image_data: reader.result, user: currentUser }
        }));
      };
      reader.readAsDataURL(file);
    }
  });

  document.getElementById('logout').addEventListener('click', () => {
    localStorage.removeItem('username');
    window.location.href = '/login';
  });

  // Загрузить тему
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
  $themeToggle.textContent = savedTheme === 'dark' ? '☀️' : '🌙';

  // Inicializar
  const userName = localStorage.getItem('username');
  if (!userName) {
    window.location.href = '/login';
    return;
  }
  connect(userName);

})();
