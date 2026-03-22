const CONFIG = {
    API_BASE: "http://localhost:8000",
    SESSION_ID: "session_" + Math.random().toString(36).substr(2, 9)
};

const chatContainer = document.getElementById('chat-container');
const chatForm = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const loader = document.getElementById('loader');
const pathDisplay = document.getElementById('path-display');
const sessionDisplay = document.getElementById('session-display');

// ЭЛЕМЕНТЫ НАСТРОЕК
const tempInput = document.getElementById('setting-temperature');
const toppInput = document.getElementById('setting-topp');
const iterInput = document.getElementById('setting-iterations');

// Обновление цифр на слайдерах
tempInput.addEventListener('input', (e) => document.getElementById('val-temperature').innerText = e.target.value);
toppInput.addEventListener('input', (e) => document.getElementById('val-topp').innerText = e.target.value);
iterInput.addEventListener('input', (e) => document.getElementById('val-iterations').innerText = e.target.value);

// Обработка нажатия Enter в поле ввода
userInput.addEventListener('keydown', (e) => {
    // Проверяем, что нажат Enter и НЕ зажат Shift
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault(); // Предотвращаем стандартный перенос строки
        chatForm.requestSubmit(); // Вызываем событие отправки формы
    }
});

// Авто-высота текстового поля при печати
userInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
});

async function updateState() {
    sessionDisplay.innerText = CONFIG.SESSION_ID;
    try {
        const res = await fetch(`${CONFIG.API_BASE}/api/system/state/${CONFIG.SESSION_ID}`);
        const data = await res.json();
        pathDisplay.innerText = data.current_path;
        document.getElementById('model-name').innerText = data.model;
    } catch (err) {
        console.error("State update failed", err);
    }
}

function appendMessage(role, content) {
    const div = document.createElement('div');
    div.className = `flex flex-col ${role === 'user' ? 'items-end' : 'items-start'} mb-4`;

    const textContent = content || "";

    div.innerHTML = `
        <span class="text-xs text-slate-500 uppercase font-bold mb-1">${role}</span>
        <div class="p-3 rounded-lg ${role === 'user' ? 'bg-blue-600' : 'bg-slate-800'} max-w-[90%] prose prose-invert">
            ${role === 'user' ? textContent : marked.parse(textContent)}
        </div>
    `;
    chatContainer.appendChild(div);
    div.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = userInput.value.trim();
    if (!text) return;

    appendMessage('user', text);
    userInput.value = '';
    loader.classList.remove('hidden');

    // СОБИРАЕМ НАСТРОЙКИ С ФРОНТЕНДА
    const requestPayload = {
        message: text,
        session_id: CONFIG.SESSION_ID,
        temperature: parseFloat(tempInput.value),
        top_p: parseFloat(toppInput.value),
        max_iterations: parseInt(iterInput.value)
    };

    try {
        const res = await fetch(`${CONFIG.API_BASE}/api/chat`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(requestPayload)
        });
        const data = await res.json();
        if (data.status === 'success') {
            appendMessage('assistant', data.response);
            pathDisplay.innerText = data.current_path;
        }
    } catch (err) {
        appendMessage('assistant', "❌ Connection error");
    } finally {
        loader.classList.add('hidden');
    }
});

document.getElementById('clear-btn').addEventListener('click', async () => {
    if(confirm("Очистить историю?")) {
        await fetch(`${CONFIG.API_BASE}/api/system/clear-history?session_id=${CONFIG.SESSION_ID}`, {method: 'POST'});
        chatContainer.innerHTML = '';
    }
});

updateState();