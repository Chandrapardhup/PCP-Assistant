import os
import uuid
import json
import requests
from flask import Flask, request, jsonify, Response
from datetime import datetime

# ---------- CONFIG ----------
OPENROUTER_API_KEY = os.environ.get("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")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini")  # change if needed
DATA_FILE = "chat_history.json"

# ---------- APP & Storage ----------
app = Flask(__name__, static_folder=None)

# Load or initialize storage
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            conversations = json.load(f)
        if not isinstance(conversations, dict):
            conversations = {}
    except Exception:
        conversations = {}
else:
    conversations = {}

def save_conversations():
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(conversations, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        print("Error saving conversations:", e)

def make_system_prompt():
    return {
        "role": "system",
        "content": (
            "You are PCP Assistant, a helpful AI assistant. Answer concisely and clearly. "
            "Use Markdown formatting and code blocks where appropriate."
        )
    }

# ---------- HTML / Frontend ----------
HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PCP Assistant</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  :root{
    --bg:#071019;--panel:#081827;--muted:#8aa2bd;--accent:#60a5fa;--green:#34d399;--danger:#f87171;
    --chip:#0f1b2a;--menu:#0b1726;--border:rgba(255,255,255,0.06);
  }
  html,body{height:100%;margin:0;background:
      radial-gradient(900px 500px at 10% 10%, rgba(96,165,250,0.05), transparent),
      linear-gradient(180deg,#071426 0%, #071019 100%); color:#e6eef8;
      font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial}
  .app{display:flex;height:100vh}
  aside{width:300px;padding:16px 14px;background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
        border-right:1px solid var(--border);box-sizing:border-box}
  main{flex:1;display:flex;flex-direction:column}
  header{display:flex;align-items:center;justify-content:space-between;padding:8px 4px}
  h1{color:var(--accent);font-weight:800;margin:0;font-size:18px;letter-spacing:.2px}
  .small{color:var(--muted);font-size:12px}
  #history{margin-top:10px;overflow:auto;max-height:76vh;display:flex;flex-direction:column;gap:6px;padding-right:6px}
  .hist-item{position:relative;display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:12px;color:#c7d7ee;cursor:pointer;
             transition:all .14s;background:transparent}
  .hist-item:hover{background:rgba(96,165,250,0.06)}
  .hist-item.active{background:linear-gradient(90deg, rgba(96,165,250,0.14), rgba(96,165,250,0.06));color:#fff;font-weight:600}
  .hist-title{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .dots{opacity:0;transition:opacity .14s; padding:4px; border-radius:8px}
  .hist-item:hover .dots{opacity:1}
  .menu{display:none;position:absolute;top:36px;right:8px;background:var(--menu);border:1px solid var(--border);
        border-radius:10px;min-width:160px;box-shadow:0 10px 26px rgba(2,6,23,.45);z-index:20}
  .menu.open{display:block}
  .menu-item{padding:10px 12px;font-size:14px;color:#dbe8ff}
  .menu-item:hover{background:rgba(255,255,255,0.06)}
  .menu-item.danger{color:#fecaca}
  #messages{flex:1;overflow:auto;padding:20px 26px;display:flex;flex-direction:column;gap:14px;scroll-behavior:smooth}
  .msg{max-width:72%;padding:14px;border-radius:14px;position:relative;white-space:pre-wrap;word-break:break-word;
       box-shadow:0 8px 22px rgba(2,6,23,0.6);animation:fadeUp .16s ease both}
  .user{margin-left:auto;background:linear-gradient(90deg,#4f46e5,#2563eb);color:white;border-bottom-right-radius:8px}
  .ai{margin-right:auto;background:linear-gradient(180deg,#021220,#0a1b2b);color:#cfe8ff;border-bottom-left-radius:8px}
  @keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
  pre{background:#03121a;padding:12px;border-radius:8px;overflow:auto;color:#bfe1ff;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,"Roboto Mono",monospace}
  .bubble-tools{display:flex;gap:8px;margin-top:10px}
  .chip-btn{border:1px solid var(--border);background:var(--chip);color:#cfe8ff;border-radius:999px;padding:6px 10px;font-size:12px;cursor:pointer}
  .chip-btn:hover{background:#102235}
  .typing{display:flex;gap:8px;align-items:center; padding:12px 14px}
  .dot{width:8px;height:8px;border-radius:999px;background:var(--accent);opacity:0.36;animation:bounce 1.0s infinite ease-in-out}
  .dot:nth-child(2){animation-delay:.1s}.dot:nth-child(3){animation-delay:.2s}
  @keyframes bounce{0%{transform:translateY(0);opacity:.36}40%{transform:translateY(-7px);opacity:1}100%{transform:translateY(0);opacity:.36}}
  .topbar{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--border)}
  .title-input{background:transparent;border:1px dashed rgba(255,255,255,0.09);padding:6px 8px;border-radius:10px;color:#e8f3ff;min-width:240px}
  .title-input:focus{outline:none;border-color:rgba(96,165,250,0.35);background:rgba(255,255,255,0.02)}
  .topic{font-size:12px;color:var(--muted)}
  footer{padding:12px 16px;border-top:1px solid var(--border);display:flex;gap:10px;align-items:center;background:linear-gradient(180deg, rgba(255,255,255,0.01), transparent)}
  .textbox{flex:1;padding:12px 14px;border-radius:999px;background:rgba(255,255,255,0.02);border:1px solid var(--border);color:inherit;min-height:44px;outline:none}
  .btn{padding:10px 14px;border-radius:999px;background:linear-gradient(90deg,var(--green), #10b981);color:#042b1f;font-weight:700;border:none;cursor:pointer;box-shadow:0 10px 26px rgba(16,185,129,0.12)}
  @media(max-width:900px){aside{display:none}}
</style>
</head>
<body>
  <div class="app">
    <aside>
      <header>
        <div>
          <h1>PCP Assistant</h1>
          <div class="small" style="margin-top:4px">Text chat • Local history</div>
        </div>
        <button id="newChatBtn" class="btn" style="padding:8px 12px;background:linear-gradient(90deg,#60a5fa,#2563eb);color:white;">New</button>
      </header>

      <div id="history"></div>
    </aside>

    <main>
      <div class="topbar">
        <div>
          <input id="titleInput" class="title-input" placeholder="Conversation title" />
          <div class="topic" id="topicHint"></div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="small" id="statusHint"></span>
        </div>
      </div>

      <div id="messages" aria-live="polite"></div>

      <form id="composer" onsubmit="return false;">
        <footer>
          <input id="textInput" class="textbox" placeholder="Type a message..." autocomplete="off" />
          <button id="sendBtn" class="btn">Send</button>
        </footer>
      </form>
    </main>
  </div>

<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script>
/* Client logic:
 - History list with 3-dots hover menu (Rename, Delete)
 - New chat, rename, delete
 - Send message -> server -> reveal with fast typing animation
 - Copy button below each bubble (ChatGPT style)
 - Enter to send
*/

const historyEl = document.getElementById('history');
const newChatBtn = document.getElementById('newChatBtn');
const titleInput = document.getElementById('titleInput');
const topicHint = document.getElementById('topicHint');
const messagesEl = document.getElementById('messages');
const textInput = document.getElementById('textInput');
const sendBtn = document.getElementById('sendBtn');
const statusHint = document.getElementById('statusHint');

let chatId = null;
let chats = {}; // id -> {title, messages, updated}

// utilities
const el = (tag, cls, html) => { const d = document.createElement(tag); if(cls) d.className = cls; if(html!==undefined) d.innerHTML = html; return d; };
const escapeHtml = (s) => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function stripHtml(s){ const tmp=document.createElement('div'); tmp.innerHTML = s; return tmp.innerText; }

// ---- History ----
function renderHistory(){
  historyEl.innerHTML = '';
  const ids = Object.keys(chats).sort((a,b)=> (chats[b].updated||0) - (chats[a].updated||0));
  ids.forEach(id=>{
    const item = el('div','hist-item');
    if(id === chatId) item.classList.add('active');

    const title = el('div','hist-title', escapeHtml(chats[id].title || 'New Chat'));
    item.appendChild(title);

    const dots = el('div','dots', `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a9c6ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="19" r="1"></circle>
      </svg>`);
    item.appendChild(dots);

    const menu = el('div','menu');
    menu.innerHTML = `
      <div class="menu-item" data-action="rename">Rename</div>
      <div class="menu-item danger" data-action="delete">Delete</div>
    `;
    item.appendChild(menu);

    dots.addEventListener('click', (e)=> {
      e.stopPropagation();
      // toggle menu
      const open = menu.classList.contains('open');
      closeAllMenus();
      if(!open) menu.classList.add('open');
    });

    menu.addEventListener('click', async (e)=>{
      e.stopPropagation();
      const act = e.target && e.target.getAttribute('data-action');
      if(act === 'rename'){
        const newTitle = prompt('Rename chat:', chats[id].title || 'Chat');
        if(newTitle !== null){
          await renameChatOnServer(id, newTitle.trim() || 'Chat');
          chats[id].title = newTitle.trim() || 'Chat';
          renderHistory();
          if(id === chatId){ titleInput.value = chats[id].title; }
        }
      } else if(act === 'delete'){
        // no popup confirmation per your request; just delete
        await deleteChatOnServer(id);
        delete chats[id];
        if(chatId === id){
          // load another or create new
          const remaining = Object.keys(chats);
          if(remaining.length){
            await loadChat(remaining.sort((a,b)=> (chats[b].updated||0)-(chats[a].updated||0))[0]);
          } else {
            await createNewChat();
          }
        } else {
          renderHistory();
        }
      }
      closeAllMenus();
    });

    item.addEventListener('click', ()=> loadChat(id));
    historyEl.appendChild(item);
  });
}

function closeAllMenus(){
  document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));
}

document.addEventListener('click', closeAllMenus);

// ---- Messages ----
function renderMessages(){
  messagesEl.innerHTML = '';
  if(!chatId || !chats[chatId]) return;
  const conv = chats[chatId].messages || [];
  conv.forEach((m)=>{
    const cls = m.role === 'user' ? 'user' : 'ai';
    const bubble = el('div', 'msg '+cls, (m.role==='assistant' && window.marked) ? marked.parse(m.content) : escapeHtml(m.content).replace(/\n/g,'<br/>'));
    const tools = el('div','bubble-tools');
    const copyBtn = el('button','chip-btn','Copy');
    copyBtn.addEventListener('click', ()=> {
      navigator.clipboard.writeText(stripHtml(bubble.innerHTML));
      copyBtn.textContent = 'Copied!';
      setTimeout(()=> copyBtn.textContent = 'Copy', 1000);
    });
    tools.appendChild(copyBtn);
    bubble.appendChild(tools);
    messagesEl.appendChild(bubble);
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showTyping(){
  const t = el('div','msg ai typing','<div class="dot"></div><div class="dot"></div><div class="dot"></div>');
  messagesEl.appendChild(t);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return t;
}

// ---- Server I/O ----
async function createNewChat(){
  const res = await fetch('/new_chat', { method:'POST' });
  const j = await res.json();
  const id = j.chat_id;
  chats[id] = { title: 'New Chat', messages: [], updated: Date.now() };
  chatId = id;
  titleInput.value = 'New Chat';
  topicHint.textContent = '';
  renderHistory();
  renderMessages();
  titleInput.focus();
  return id;
}

async function loadChat(id){
  if(!id) return;
  chatId = id;
  const res = await fetch(`/get_chat/${id}`);
  const msgs = await res.json();
  chats[id] = chats[id] || { title: 'Chat', messages: [] };
  chats[id].messages = msgs;
  chats[id].updated = Date.now();
  if(!chats[id].title || chats[id].title === 'New Chat'){
    const firstUser = msgs.find(m=>m.role==='user');
    chats[id].title = firstUser ? (firstUser.content.split('\n')[0].slice(0,60)) : (chats[id].title || 'Chat');
  }
  titleInput.value = chats[id].title || 'Chat';
  renderHistory();
  renderMessages();
}

async function renameChatOnServer(id, newTitle){
  await fetch('/rename_chat', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ chat_id: id, title: newTitle })
  });
}

async function deleteChatOnServer(id){
  await fetch(`/delete_chat/${id}`, { method:'DELETE' });
}

// ---- Send / Type animation ----
async function sendMessage(){
  const text = textInput.value.trim();
  if(!text || !chatId) return;

  // add user bubble immediately
  chats[chatId].messages.push({ role:'user', content: text });
  chats[chatId].updated = Date.now();
  renderMessages();
  textInput.value = '';
  messagesEl.scrollTop = messagesEl.scrollHeight;

  const typingNode = showTyping();

  try{
    const res = await fetch('/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ chat_id: chatId, message: text })
    });
    const j = await res.json();

    typingNode.remove();

    if(j.error){
      const msg = (j.error || 'Error').toString();
      const bubble = el('div','msg ai', escapeHtml('Error: ' + msg));
      const tools = el('div','bubble-tools');
      const copyBtn = el('button','chip-btn','Copy');
      copyBtn.addEventListener('click', ()=> {
        navigator.clipboard.writeText('Error: ' + msg);
        copyBtn.textContent='Copied!'; setTimeout(()=> copyBtn.textContent='Copy', 1000);
      });
      tools.appendChild(copyBtn);
      bubble.appendChild(tools);
      messagesEl.appendChild(bubble);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      chats[chatId].messages.push({ role:'assistant', content: 'Error: ' + msg });
      return;
    }

    const reply = j.reply || '';
    // create blank bubble and reveal quickly
    const aiNode = el('div','msg ai','');
    const tools = el('div','bubble-tools');
    const copyBtn = el('button','chip-btn','Copy');
    copyBtn.addEventListener('click', ()=> {
      navigator.clipboard.writeText(stripHtml(aiNode.innerHTML));
      copyBtn.textContent='Copied!'; setTimeout(()=> copyBtn.textContent='Copy', 1000);
    });
    aiNode.appendChild(tools);
    messagesEl.appendChild(aiNode);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    let idx = 0;
    const baseMs = 10; // faster typing (your request)
    function reveal(){
      idx += Math.max(1, Math.floor(reply.length/800)); // adaptive chunk
      const visible = reply.slice(0, idx);
      // Render markdown progressively (simple line breaks first for speed)
      aiNode.firstChild && aiNode.removeChild(aiNode.firstChild); // remove tools temp
      aiNode.innerHTML = (window.marked ? marked.parse(visible) : escapeHtml(visible).replace(/\n/g,'<br/>'));
      aiNode.appendChild(tools);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      if(idx < reply.length){
        setTimeout(reveal, baseMs + Math.floor(Math.random()*6));
      } else {
        chats[chatId].messages.push({ role:'assistant', content: reply });
        chats[chatId].updated = Date.now();
        if(!chats[chatId].title || chats[chatId].title === 'New Chat'){
          const firstUser = chats[chatId].messages.find(m=>m.role==='user');
          if(firstUser){
            const t = firstUser.content.trim().split('\n')[0].slice(0,60);
            chats[chatId].title = t || 'Chat';
            renameChatOnServer(chatId, chats[chatId].title);
          }
        }
        renderHistory();
      }
    }
    reveal();

  }catch(err){
    console.error(err);
    if(typingNode && typingNode.remove) typingNode.remove();
    const bubble = el('div','msg ai', escapeHtml('Network error.'));
    const tools = el('div','bubble-tools');
    const copyBtn = el('button','chip-btn','Copy');
    copyBtn.addEventListener('click', ()=> {
      navigator.clipboard.writeText('Network error.');
      copyBtn.textContent='Copied!'; setTimeout(()=> copyBtn.textContent='Copy', 1000);
    });
    tools.appendChild(copyBtn);
    bubble.appendChild(tools);
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    chats[chatId].messages.push({ role:'assistant', content: 'Network error.' });
  }
}

// ---- Init & events ----
async function loadChatsList(){
  const res = await fetch('/chats');
  const j = await res.json();
  chats = {};
  j.forEach(item => {
    chats[item.chat_id] = { title: item.title || 'Chat', messages: [], updated: item.updated || 0 };
  });
  renderHistory();
}

newChatBtn.addEventListener('click', async ()=> { await createNewChat(); });
sendBtn.addEventListener('click', sendMessage);
textInput.addEventListener('keydown', (e)=> {
  if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); }
});
titleInput.addEventListener('keydown', async (e)=> {
  if(e.key==='Enter'){
    e.preventDefault();
    if(!chatId) return;
    const newTitle = titleInput.value.trim() || 'Chat';
    chats[chatId].title = newTitle;
    await renameChatOnServer(chatId, newTitle);
    renderHistory();
  }
});

window.addEventListener('load', async ()=> {
  await loadChatsList();
  const ids = Object.keys(chats);
  if(ids.length === 0){
    await createNewChat();
  } else {
    const sorted = ids.slice().sort((a,b)=> (chats[b].updated||0) - (chats[a].updated||0));
    await loadChat(sorted[0]);
  }
});
</script>
</body>
</html>
"""

# ---------- Server endpoints ----------

@app.route("/", methods=["GET"])
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/new_chat", methods=["POST"])
def new_chat():
    chat_id = uuid.uuid4().hex
    conversations[chat_id] = {
        "title": "New Chat",
        "messages": [make_system_prompt()],
        "created": datetime.utcnow().isoformat(),
        "updated": datetime.utcnow().timestamp()
    }
    save_conversations()
    return jsonify({"chat_id": chat_id})

@app.route("/chats", methods=["GET"])
def list_chats():
    out = []
    for k, v in conversations.items():
        out.append({
            "chat_id": k,
            "title": v.get("title", "Chat"),
            "updated": v.get("updated", 0)
        })
    return jsonify(out)

@app.route("/get_chat/<chat_id>", methods=["GET"])
def get_chat(chat_id):
    if chat_id not in conversations:
        return jsonify([])
    msgs = conversations[chat_id]["messages"][1:] if len(conversations[chat_id]["messages"])>1 else []
    return jsonify(msgs)

@app.route("/rename_chat", methods=["POST"])
def rename_chat():
    data = request.get_json() or {}
    chat_id = data.get("chat_id")
    title = (data.get("title") or "").strip() or "Chat"
    if chat_id in conversations:
        conversations[chat_id]["title"] = title
        conversations[chat_id]["updated"] = datetime.utcnow().timestamp()
        save_conversations()
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404

@app.route("/delete_chat/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    if chat_id in conversations:
        del conversations[chat_id]
        save_conversations()
        return ("", 204)
    return jsonify({"error": "not found"}), 404

@app.route('/chat', methods=['POST'])
def chat():
    try:
        user_message = request.json.get('message', '').strip()
        if not user_message:
            return jsonify({'error': 'Empty message'}), 400

        # Messages with custom system prompt
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful and creative AI assistant created by Peddoju Chandra Pardhu, "
                    "an innovative developer passionate about AI, drones, and web development. "
                    "Whenever someone asks who created you or about your origin, clearly state that "
                    "you were created by Peddoju Chandra Pardhu and highlight his skills and innovation."
                )
            },
            {
                "role": "user",
                "content": user_message
            }
        ]

        # OpenRouter API call
        headers = {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        }

        data = {
            "model": "openai/gpt-3.5-turbo",
            "messages": messages
        }

        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)

        if response.status_code != 200:
            return jsonify({'error': f"API Error: {response.status_code}", 'details': response.text}), 500

        ai_reply = response.json()['choices'][0]['message']['content']
        return jsonify({'reply': ai_reply})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def call_openrouter(messages):
    """
    Calls OpenRouter chat completions endpoint.
    Raises requests.HTTPError for non-2xx so the caller can surface friendly text.
    """
    if not OPENROUTER_API_KEY:
        # Return a friendly error as if it came from the server; caller formats as assistant bubble
        raise requests.HTTPError("Missing OPENROUTER_API_KEY; set your OpenRouter API key in env.")

    url = f"{OPENROUTER_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 800,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    print("OpenRouter status:", resp.status_code)
    data = resp.json() if resp.content else {}
    resp.raise_for_status()
    assistant = None
    if isinstance(data, dict):
        assistant = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content")
        if assistant is None:
            assistant = data.get("choices", [{}])[0].get("text", "")
    if assistant is None:
        assistant = str(data)
    return assistant

# ---------- Run ----------
if __name__ == "__main__":
    print("OPENROUTER_API_KEY loaded:", bool(OPENROUTER_API_KEY))
    print("Using model:", MODEL)
    app.run(host="0.0.0.0", port=8080, debug=True)
