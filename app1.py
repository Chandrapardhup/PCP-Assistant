import os
import uuid
import json
import requests
import base64
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, Response, render_template, session, redirect, url_for
from supabase import create_client, Client
from flask import session, redirect
from image_generator import ImageService
from huggingface_models import FreeImageModels

# Load environment variables
def load_env_file():
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")
    except FileNotFoundError:
        print(".env file not found, using environment variables")

load_env_file()

# ---------- CONFIG ----------
SUPABASE_URL = secrets.SUPABASE_URL
SUPABASE_KEY = secrets.SUPABASE_KEY
OPENROUTER_API_KEY =secrets.OPENROUTER_API_KEY
OPENROUTER_BASE_URL =secrets.OPENROUTER_BASE_URL
MODEL = "openai/gpt-4o-mini"
DATA_FILE = "chat_history.json"

image_gen = ImageService()
free_models = FreeImageModels()

# Validate required environment variables
if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Missing Supabase credentials!")
    print("Please set SUPABASE_URL and SUPABASE_KEY in your .env file")
    exit(1)

# ---------- Supabase Client ----------
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase client initialized successfully")
except Exception as e:
    print(f"❌ Failed to initialize Supabase client: {e}")
    exit(1)

# ---------- Flask App ----------
app = Flask(__name__, static_folder=None)
app.secret_key = "your-secret-key-here-change-in-production"  # ADD THIS LINE
# Load or initialize storage for chat history (for backward compatibility)
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

# ---------- Database Functions ----------

def create_user(email, username, password):
    """Create a new user in Supabase"""
    try:
        print(f"Creating user: {email}, {username}")
        
        # Check if email already exists
        existing_email = supabase.table("users").select("id").eq("email", email).execute()
        if existing_email.data:
            print("❌ Email already exists")
            return None, "Email already registered"
        
        # Check if username already exists
        existing_username = supabase.table("users").select("id").eq("username", username).execute()
        if existing_username.data:
            print("❌ Username already exists")
            return None, "Username already taken"
        
        # Create user
        response = supabase.table("users").insert({
            "email": email,
            "username": username,
            "password_hash": password  # In production, use proper hashing like bcrypt
        }).execute()
        
        print(f"Supabase response: {response}")
        
        if response.data and len(response.data) > 0:
            print("✅ User created successfully")
            return response.data[0], None
        else:
            print("❌ No data returned from Supabase")
            return None, "Registration failed - no data returned"
            
    except Exception as e:
        print(f"❌ Error creating user: {str(e)}")
        return None, f"Registration error: {str(e)}"

def authenticate_user(email, password):
    """Authenticate user against Supabase"""
    try:
        print(f"Authenticating user: {email}")
        
        response = supabase.table("users").select("*").eq("email", email).eq("password_hash", password).execute()
        
        print(f"Auth response: {response}")
        
        if response.data and len(response.data) > 0:
            print("✅ User authenticated successfully")
            return response.data[0], None
        else:
            print("❌ Invalid credentials")
            return None, "Invalid email or password"
            
    except Exception as e:
        print(f"❌ Error authenticating user: {str(e)}")
        return None, f"Authentication error: {str(e)}"

def get_user_by_email(email):
    """Get user by email"""
    try:
        response = supabase.table("users").select("*").eq("email", email).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting user by email: {e}")
        return None

def create_password_reset_token(user_id):
    """Create a password reset token"""
    try:
        token = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)
        
        response = supabase.table("password_reset_tokens").insert({
            "user_id": user_id,
            "token": token,
            "expires_at": expires_at.isoformat()
        }).execute()
        
        if response.data:
            return token
        return None
    except Exception as e:
        print(f"Error creating reset token: {e}")
        return None

# ---------- Chat Storage Functions ----------

def get_user_conversations(user_id):
    """Get all conversations for a user"""
    try:
        response = supabase.table("conversations").select("*, messages(*)").eq("user_id", user_id).order("updated_at", desc=True).execute()
        return response.data
    except Exception as e:
        print(f"Error getting conversations: {e}")
        return []

def create_conversation(user_id, title="New Chat"):
    """Create a new conversation for a user"""
    try:
        response = supabase.table("conversations").insert({
            "user_id": user_id,
            "title": title
        }).execute()
        
        if response.data:
            conversation_id = response.data[0]['id']
            # Add system prompt as first message
            supabase.table("messages").insert({
                "conversation_id": conversation_id,
                "role": "system",
                "content": make_system_prompt()["content"]
            }).execute()
            
            return conversation_id
        return None
    except Exception as e:
        print(f"Error creating conversation: {e}")
        return None

def get_conversation_messages(conversation_id):
    """Get all messages for a conversation"""
    try:
        response = supabase.table("messages").select("*").eq("conversation_id", conversation_id).order("created_at").execute()
        return response.data
    except Exception as e:
        print(f"Error getting messages: {e}")
        return []

def add_message(conversation_id, role, content):
    """Add a message to a conversation"""
    try:
        response = supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "role": role,
            "content": content
        }).execute()
        
        # Update conversation updated_at timestamp
        supabase.table("conversations").update({
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", conversation_id).execute()
        
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error adding message: {e}")
        return None

def update_conversation_title(conversation_id, title):
    """Update conversation title"""
    try:
        response = supabase.table("conversations").update({
            "title": title,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", conversation_id).execute()
        
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating conversation: {e}")
        return None

def delete_conversation(conversation_id):
    """Delete a conversation and all its messages"""
    try:
        response = supabase.table("conversations").delete().eq("id", conversation_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting conversation: {e}")
        return False
def create_password_reset_token(user_id):
    """Create a password reset token and store it in database"""
    try:
        token = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=24)  # Token valid for 24 hours
        
        # Store token in database
        response = supabase.table("password_reset_tokens").insert({
            "user_id": user_id,
            "token": token,
            "expires_at": expires_at.isoformat(),
            "used": False
        }).execute()
        
        if response.data:
            return token
        return None
    except Exception as e:
        print(f"Error creating reset token: {e}")
        return None

def get_valid_reset_token(token):
    """Get a valid reset token from database"""
    try:
        response = supabase.table("password_reset_tokens").select("*, users(*)").eq("token", token).eq("used", False).execute()
        
        if response.data and len(response.data) > 0:
            token_data = response.data[0]
            expires_at = datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
            
            # Check if token is still valid
            if datetime.utcnow() < expires_at:
                return token_data
        return None
    except Exception as e:
        print(f"Error getting reset token: {e}")
        return None

def mark_token_used(token):
    """Mark a reset token as used"""
    try:
        response = supabase.table("password_reset_tokens").update({
            "used": True
        }).eq("token", token).execute()
        return True
    except Exception as e:
        print(f"Error marking token as used: {e}")
        return False

def update_user_password(user_id, new_password):
    """Update user's password"""
    try:
        response = supabase.table("users").update({
            "password_hash": new_password
        }).eq("id", user_id).execute()
        return True
    except Exception as e:
        print(f"Error updating password: {e}")
        return False


# ---------- HTML / Frontend ----------

HTML = r"""<!doctype html>
<html lang="en">
<head>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.246/pdf.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.4.2/mammoth.browser.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/tesseract.js@4.1.1/dist/tesseract.min.js"></script>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PCP Assistant</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  /* Bottom menu styles */
  .menu-item:hover {
      background: rgba(255,255,255,0.06);
  }
  
  .menu-item.danger:hover {
      background: rgba(239, 68, 68, 0.2);
  }
  :root{
    --bg:#071019;--panel:#081827;--muted:#8aa2bd;--accent:#60a5fa;--green:#34d399;--danger:#f87171;
    --chip:#0f1b2a;--menu:#0b1726;--border:rgba(255,255,255,0.06);
  }
  html,body{height:100%;margin:0;background:
      radial-gradient(900px 500px at 10% 10%, rgba(96,165,250,0.05), transparent),
      linear-gradient(180deg,#071426 0%, #071019 100%); color:#e6eef8;
      font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial}
  .app{display:flex;height:100vh}
  aside{display:flex;flex-direction:column;justify-content:space-between;width:350px;padding:16px 14px;background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
        border-right:1px solid var(--border);box-sizing:border-box}
  main{flex:1;display:flex;flex-direction:column}
  header{display:flex;flex-direction:column;align-items:start;justify-content:space-between;padding:10px 8px}
  h1{color:var(--accent);font-weight:800;margin:0;font-size:18px;letter-spacing:.2px}
  .small{color:var(--muted);font-size:12px}
  #history{flex:1;padding:10px 10px;margin-top:10px;overflow-y:auto;max-height:76vh;display:flex;flex-direction:column;gap:6px;padding-right:6px}
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
  .msg{max-width:60%;padding:14px;border-radius:14px;position:relative;white-space:pre-wrap;word-break:break-word;
       box-shadow:0 8px 22px rgba(2,6,23,0.6);animation:fadeUp .16s ease both}
  .user{margin-left:auto;background:linear-gradient(90deg,#4f46e5,#2563eb);color:white;border-bottom-right-radius:8px}
  .ai{margin-right:auto;background:linear-gradient(180deg,#021220,#0a1b2b);color:#cfe8ff;border-bottom-left-radius:8px}
  @keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
  pre{background:#03121a;padding:12px;border-radius:8px;overflow:auto;color:#bfe1ff;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,"Roboto Mono",monospace}
  .bubble-tools{display:flex;gap:8px;margin-top:2px}
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
  /* Image bubble styling like ChatGPT */
.msg.ai.image-msg {
    display: inline-block;        /* shrink-wrap */
    padding: 0;
    max-width: 400px;             /* optional max width */
    border-radius: 12px;
    background: #0a1b2b;          /* dark background */
    box-shadow: 0 4px 12px rgba(2,6,23,0.4);
    margin: 2px 0;
}

.msg.ai.image-msg img {
    display: block;
    width: 100%;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}

.msg.ai.image-msg .bubble-tools {
    display: flex;
    justify-content: center;

    gap: 30px;
    
    border-top: 1px solid rgba(255,255,255,0.1);
    border-bottom-left-radius: 6px;
    border-bottom-right-radius: 6px;
    background: #0a1b2b;
}
.modernUploadBtn {
  background-color: #2a2b32;
  color: #fff;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.3s;
}
.modernUploadBtn:hover {
  background-color: #3b3c45;
}
.chip-btn {
    font-size: 12px;
    justify-self:center;
    padding: 2px 4px;
    
    border-radius: 8px;
    border: none;
    cursor: pointer;
    background: #1f2a3a;
    color: #cfe8ff;
    transition: background 0.2s;
}

.chip-btn:hover {
    background: #3a4a5a;
}

</style>
</head>
<body>
  <div class="app">
    <aside>
      <header>
        <div>
          <h1 style="font-size:40px">PCP Assistant</h1>
        </div>
        <button id="newChatBtn" class="btn" style="width:300px;padding:8px 12px;background:linear-gradient(90deg,#60a5fa,#2563eb);color:white;">New</button>
      </header>
      <h2 class="recent" style="padding-left:5pxtext-align:start;color:white margin-top:10px">Recent Chats</h2>
      <div id="history"></div>
       
    <!-- User Info & Logout Section -->
    <div class="user-section" style="padding: 12px; border-top: 1px solid var(--border);">
        <div style="display: flex; align-items: center; gap: 20px; padding: 8px 12px; background: rgba(255,255,255,0.05); border-radius: 12px;">
            <div style="width: 32px;height: 32px; border-radius: 50%; background: linear-gradient(135deg, #60a5fa, #3b82f6); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 14px;" id="userAvatar">
                U
            </div>
            <div style="flex: 1; min-width: 0;">
                <div style="font-size: 14px; font-weight: 600; color: white;" id="userName">Loading...</div>
                <div style="font-size: 12px; color: var(--muted);" id="userEmail">Loading...</div>
            
            </div>
            <div>
            <button id="logoutBtn" style="background: transparent; border: 1px solid var(--danger); color: var(--danger); padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 12px; transition: all 0.2s;">
                Logout
            </button>
            </div>
        </div>
    </div>
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
            <div id="fileUploadSection" style="margin-bottom:10px;">
  <label for="fileInput" class="modernUploadBtn">📁Add File</label>
  <input type="file" id="fileInput" multiple style="display:none;" />
  <span id="fileStatus" style="margin-left:10px;color:gray;">No file uploaded</span>
  <button id="extractBtn" class="modernUploadBtn" style="margin-left:10px;">Extract Text</button>
</div>

            <input id="textInput" class="textbox" placeholder="Type a message..." autocomplete="off" />
            <button id="sendBtn" class="btn">Send</button>
        </footer>
        <!-- Image Generation Section -->
<div style="padding: 12px; border-top: 1px solid var(--border); background: rgba(255,255,255,0.02);">
    <div style="display: flex; gap: 8px; margin-bottom: 8px;">
        <input type="text" id="imagePrompt"
               placeholder="Describe the image you want to create..." 
               class="textbox" style="flex: 1;">
        <input type="hidden" id="imageModel" value="flux">
        <button id="generateImageBtn" class="btn" 
            style="background: linear-gradient(90deg, #ec4899, #8b5cf6); width: 50%;">
        🎨 Generate Image
    </button>
    </div>
    
</div>
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
document.getElementById('fileInput').addEventListener('change', () => {
    const files = document.getElementById('fileInput').files;
    if (files.length) {
        document.getElementById('fileStatus').innerText = files.length + " file(s) selected: " + files[0].name;
    } else {
        document.getElementById('fileStatus').innerText = "No file uploaded";
    }
});
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
    // Combine uploaded file text with user input


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

// ---- User Info & Logout ----
async function loadUserInfo() {
    try {
        const response = await fetch('/user-info');
        if (response.ok) {
            const userData = await response.json();
            
            document.getElementById('userName').textContent = userData.username;
            document.getElementById('userEmail').textContent = userData.email;
            document.getElementById('userAvatar').textContent = userData.username.charAt(0).toUpperCase();
        } else {
            throw new Error('Failed to fetch user info');
        }
    } catch (error) {
        console.log('Failed to load user info:', error);
        // Show generic info
        document.getElementById('userName').textContent = 'User';
        document.getElementById('userEmail').textContent = 'Welcome to PCP Assistant';
    }
}

// Logout functionality
document.getElementById('logoutBtn').addEventListener('click', function() {
    if (confirm('Are you sure you want to logout?')) {
        window.location.href = '/logout';
    }
});

// Update your existing window load event to include user info
window.addEventListener('load', async ()=> {
    await loadUserInfo();  // Add this line
    await loadChatsList();
    const ids = Object.keys(chats);
    if(ids.length === 0){
        await createNewChat();
    } else {
        const sorted = ids.slice().sort((a,b)=> (chats[b].updated||0) - (chats[a].updated||0));
        await loadChat(sorted[0]);
    }
});

// Image Generation
document.getElementById('generateImageBtn').addEventListener('click', async function() {
    const prompt = document.getElementById('imagePrompt').value.trim();
    const model = document.getElementById('imageModel').value;
    
    if (!prompt) {
        showNotification('Please enter an image description', 'error');
        return;
    }
    
    const btn = this;
    const originalText = btn.innerHTML;
    btn.innerHTML = '🎨 Generating...';
    btn.disabled = true;
    
    try {
        const response = await fetch('/generate-image', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ 
                prompt: prompt,
                model: model
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Create image message
                        const imgMsg = document.createElement('div');
            imgMsg.classList.add('msg', 'ai', 'image-msg'); // special class for image

            imgMsg.innerHTML = `
                <img src="${data.image_url}" 
                    alt="Generated Image" 
                    onerror="this.style.display='none'">
                <div class="bubble-tools">
                    <button class="chip-btn" onclick="downloadImage('${data.image_url}', '${prompt.replace(/[^a-z0-9]/gi, '_')}')">
                        💾 Download
                    </button>
                    <button class="chip-btn" onclick="regenerateImage('${prompt}', 'flux')">
                        🔄 Regenerate
                    </button>
                </div>
            `;
            messagesEl.appendChild(imgMsg);
            messagesEl.scrollTop = messagesEl.scrollHeight;

            // Clear prompt
            document.getElementById('imagePrompt').value = '';
            
            showNotification('Image generated successfully!', 'success');
        } else {
            showNotification(data.error || 'Failed to generate image', 'error');
        }
        // 🧠 Auto-rename chat from AI's first reply
        if (chats[chatId] && (!chats[chatId].title || chats[chatId].title === "New Chat")) {
            const aiTitle = (data.reply || "")
                .split(" ")
                .slice(0, 6)
                .join(" ")
                .replace(/[^\w\s]/g, "")
                .trim();

            chats[chatId].title = aiTitle || "Chat";
            chats[chatId].updated = Date.now();
            saveChats();
            renderHistory();
        }

    } catch (error) {
        console.error('Image generation failed:', error);
        showNotification('Network error. Please try again.', 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
});

// Download image
function downloadImage(dataUrl, filename) {
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = `pcp_${filename}_${Date.now()}.jpg`;
    link.click();
}

// Regenerate image
function regenerateImage(prompt, model) {
    document.getElementById('imagePrompt').value = prompt;
    document.getElementById('imageModel').value = model;
    document.getElementById('generateImageBtn').click();
}

// Enter key for image prompt
document.getElementById('imagePrompt').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        document.getElementById('generateImageBtn').click();
    }
});
let uploadedText = ''; // stores extracted text

// Update status when file selected
document.getElementById('fileInput').addEventListener('change', () => {
    const files = document.getElementById('fileInput').files;
    if (files.length) {
        document.getElementById('fileStatus').innerText = files.length + " file(s) selected: " + files[0].name;
    } else {
        document.getElementById('fileStatus').innerText = "No file uploaded";
    }
});

// Extract text when button clicked
document.getElementById('extractBtn').addEventListener('click', async () => {
    const files = document.getElementById('fileInput').files;
    if (!files.length) return alert('Please select a file first!');

    uploadedText = '';
    document.getElementById('fileStatus').innerText = 'Extracting text...';

    for (const file of files) {
        const ext = file.name.split('.').pop().toLowerCase();

        if (ext === 'txt') {
            uploadedText += await file.text() + '\n';
        } 
        else if (ext === 'pdf') {
            const pdfjsLib = window['pdfjs-dist/build/pdf'];
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.246/pdf.worker.min.js';
            const arrayBuffer = await file.arrayBuffer();
            const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
            for (let i = 1; i <= pdf.numPages; i++) {
                const page = await pdf.getPage(i);
                const content = await page.getTextContent();
                uploadedText += content.items.map(item => item.str).join(' ') + '\n';
            }
        } 
        else if (ext === 'docx') {
            const arrayBuffer = await file.arrayBuffer();
            const result = await mammoth.extractRawText({ arrayBuffer });
            uploadedText += result.value + '\n';
        } 
        else if (['jpg','jpeg','png'].includes(ext)) {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            await new Promise(resolve => {
                reader.onload = async () => {
                    const { data: { text } } = await Tesseract.recognize(reader.result, 'eng');
                    uploadedText += text + '\n';
                    resolve();
                };
            });
        } 
        else {
            uploadedText += `Unsupported file type: ${file.name}\n`;
        }
    }

    document.getElementById('fileStatus').innerText = 'Text extracted! You can now ask questions.';
    console.log('Extracted text:', uploadedText); // you can feed this to your chat system
});

uploadedText = ''; // reset after answering if needed

</script>
</body>
</html>
"""


# ---------- Authentication Routes ----------

# ---------- Authentication Routes ----------

@app.route('/')
def root():
    
    return redirect('/login')

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect('/chat')
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not all([email, username, password]):
            return jsonify({'success': False, 'error': 'All fields are required'}), 400
        
        # Check if user exists
        existing_user = supabase.table("users").select("*").eq("email", email).execute()
        if existing_user.data:
            return jsonify({'success': False, 'error': 'User already exists'}), 400
        
        # Create user
        response = supabase.table("users").insert({
            "email": email,
            "username": username, 
            "password_hash": password
        }).execute()
        
        if response.data:
            session['user_id'] = response.data[0]['id']
            session['username'] = username
            session['email'] = email
            
            return jsonify({
                'success': True,
                'message': 'Registration successful',
                'user': {
                    'id': response.data[0]['id'],
                    'username': username,
                    'email': email
                }
            })
        
        return jsonify({'success': False, 'error': 'Registration failed'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    """Handle user login with remember me"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        remember_me = data.get('remember_me', False)
        
        if not all([email, password]):
            return jsonify({'success': False, 'error': 'Email and password are required'}), 400
        
        # Authenticate user
        response = supabase.table("users").select("*").eq("email", email).eq("password_hash", password).execute()
        
        if response.data and len(response.data) > 0:
            user = response.data[0]
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['email'] = user['email']
            
            # Set session permanence based on remember me
            if remember_me:
                session.permanent = True
                # Set longer session lifetime (30 days)
                app.permanent_session_lifetime = timedelta(days=30)
            else:
                session.permanent = False
                # Default session lifetime (browser session)
                app.permanent_session_lifetime = timedelta(hours=1)
            
            return jsonify({
                'success': True,
                'message': 'Login successful',
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'email': user['email']
                }
            })
        
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ---------- Chat Routes (Protected) ----------

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/chat')
@login_required
def chat_interface():
    return HTML

# ---------- Personal Chat Storage Functions ----------

def get_user_conversations(user_id):
    """Get all conversations for a specific user"""
    try:
        # Store conversations in Supabase with user_id
        response = supabase.table("conversations").select("*").eq("user_id", user_id).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting user conversations: {e}")
        return []

def create_user_conversation(user_id, title="New Chat"):
    """Create a new conversation for a specific user"""
    try:
        response = supabase.table("conversations").insert({
            "user_id": user_id,
            "title": title,
            "messages": [make_system_prompt()],
            "created": datetime.utcnow().isoformat(),
            "updated": datetime.utcnow().timestamp()
        }).execute()
        
        if response.data:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error creating user conversation: {e}")
        return None

# ---------- Modified Chat Endpoints for Personal Chats ----------
@app.route('/generate-image', methods=['POST'])
@login_required
def generate_image():
    """Generate image from text prompt"""
    try:
        data = request.get_json()
        prompt = data.get('prompt', '').strip()
        model = data.get('model', 'flux')
        
        if not prompt:
            return jsonify({'success': False, 'error': 'Prompt is required'}), 400
        
        print(f"🎨 Image generation request: {prompt}")
        
        # Generate image
        image_b64 = free_models.generate_image(prompt, model)
        
        if image_b64:
            return jsonify({
                'success': True,
                'image_url': f"data:image/jpeg;base64,{image_b64}",
                'prompt': prompt,
                'model': model
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to generate image. Try again.'}), 500
        
    except Exception as e:
        print(f"❌ Image generation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/image-models')
@login_required
def get_image_models():
    """Get available image models"""
    return jsonify({
        'success': True,
        'models': free_models.get_available_models()
    })

@app.route('/new_chat', methods=["POST"])
@login_required
def new_chat():
    user_id = session['user_id']
    
    # Use Supabase for personal chats
    conversation_id = create_user_conversation(user_id)
    
    if conversation_id:
        return jsonify({"chat_id": conversation_id})
    
    # Fallback to local storage
    chat_id = uuid.uuid4().hex
    conversations[chat_id] = {
        "title": "New Chat",
        "messages": [make_system_prompt()],
        "created": datetime.utcnow().isoformat(),
        "updated": datetime.utcnow().timestamp(),
        "user_id": user_id  # Track which user owns this chat
    }
    save_conversations()
    return jsonify({"chat_id": chat_id})

@app.route("/chats", methods=["GET"])
@login_required
def list_chats():
    user_id = session['user_id']
    out = []
    
    # Get chats from Supabase
    supabase_chats = get_user_conversations(user_id)
    for chat in supabase_chats:
        out.append({
            "chat_id": chat['id'],
            "title": chat.get('title', 'New Chat'),
            "updated": chat.get('updated', 0)
        })
    
    # Also include local chats for this user (for backward compatibility)
    for k, v in conversations.items():
        if v.get('user_id') == user_id:  # Only show user's own chats
            out.append({
                "chat_id": k,
                "title": v.get("title", "Chat"),
                "updated": v.get("updated", 0)
            })
    
    return jsonify(out)

@app.route("/get_chat/<chat_id>", methods=["GET"])
@login_required
def get_chat(chat_id):
    user_id = session['user_id']
    
    # First check if it's a Supabase chat
    supabase_chat = supabase.table("conversations").select("*").eq("id", chat_id).eq("user_id", user_id).execute()
    if supabase_chat.data:
        messages = supabase_chat.data[0].get('messages', [])
        return jsonify(messages[1:] if len(messages) > 1 else [])
    
    # Fallback to local storage
    if chat_id in conversations and conversations[chat_id].get('user_id') == user_id:
        msgs = conversations[chat_id]["messages"][1:] if len(conversations[chat_id]["messages"])>1 else []
        return jsonify(msgs)
    
    return jsonify([])

@app.route('/reset-password')
def reset_password_page():
    """Serve the reset password page"""
    token = request.args.get('token')
    
    if not token:
        return "Invalid or missing reset token", 400
    
    # Verify token is valid
    token_data = get_valid_reset_token(token)
    if not token_data:
        return "Invalid or expired reset token", 400
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reset Password - PCP Assistant</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                font-family: 'Inter', sans-serif;
            }}
        </style>
    </head>
    <body>
        <div class="bg-white/10 backdrop-blur-lg rounded-2xl p-8 max-w-md w-full mx-4 border border-white/20">
            <div class="text-center mb-6">
                <h1 class="text-2xl font-bold text-white">Reset Password</h1>
                <p class="text-blue-100 mt-2">Create a new password for your account</p>
            </div>
            
            <form id="resetPasswordForm" class="space-y-4">
                <input type="hidden" id="resetToken" value="{token}">
                
                <div>
                    <label class="text-white text-sm block mb-2">New Password</label>
                    <input type="password" id="newPassword" 
                           class="w-full p-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-blue-200 focus:outline-none focus:border-blue-400"
                           placeholder="Enter new password" required>
                </div>
                
                <div>
                    <label class="text-white text-sm block mb-2">Confirm Password</label>
                    <input type="password" id="confirmPassword" 
                           class="w-full p-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-blue-200 focus:outline-none focus:border-blue-400"
                           placeholder="Confirm new password" required>
                </div>
                
                <button type="submit" class="w-full py-3 bg-gradient-to-r from-green-500 to-emerald-600 text-white font-semibold rounded-xl hover:from-green-600 hover:to-emerald-700 transition-all">
                    Reset Password
                </button>
            </form>
            
            <div id="message" class="mt-4 text-center hidden"></div>
        </div>
        
        <script>
            document.getElementById('resetPasswordForm').addEventListener('submit', async function(e) {{
                e.preventDefault();
                
                const token = document.getElementById('resetToken').value;
                const newPassword = document.getElementById('newPassword').value;
                const confirmPassword = document.getElementById('confirmPassword').value;
                const messageDiv = document.getElementById('message');
                
                if (newPassword !== confirmPassword) {{
                    showMessage('Passwords do not match', 'error');
                    return;
                }}
                
                if (newPassword.length < 6) {{
                    showMessage('Password must be at least 6 characters', 'error');
                    return;
                }}
                
                try {{
                    const response = await fetch('/reset-password', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify({{
                            token: token,
                            new_password: newPassword
                        }})
                    }});
                    
                    const data = await response.json();
                    
                    if (data.success) {{
                        showMessage(data.message, 'success');
                        document.getElementById('resetPasswordForm').reset();
                        setTimeout(() => {{
                            window.location.href = '/login';
                        }}, 2000);
                    }} else {{
                        showMessage(data.error, 'error');
                    }}
                }} catch (error) {{
                    showMessage('Network error. Please try again.', 'error');
                }}
            }});
            
            function showMessage(message, type) {{
                const messageDiv = document.getElementById('message');
                messageDiv.textContent = message;
                messageDiv.className = `mt-4 text-center ${{type === 'success' ? 'text-green-400' : 'text-red-400'}}`;
                messageDiv.classList.remove('hidden');
            }}
        </script>
    </body>
    </html>
    """

@app.route('/reset-password', methods=['POST'])
def reset_password():
    """Handle password reset"""
    try:
        data = request.get_json()
        token = data.get('token')
        new_password = data.get('new_password')
        
        if not all([token, new_password]):
            return jsonify({'success': False, 'error': 'Token and new password are required'}), 400
        
        # Verify token is valid
        token_data = get_valid_reset_token(token)
        if not token_data:
            return jsonify({'success': False, 'error': 'Invalid or expired reset token'}), 400
        
        # Update user's password
        if update_user_password(token_data['user_id'], new_password):
            # Mark token as used
            mark_token_used(token)
            
            return jsonify({
                'success': True,
                'message': 'Password has been reset successfully. You can now login with your new password.'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to reset password'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route("/rename_chat", methods=["POST"])
@login_required
def rename_chat():
    data = request.get_json() or {}
    chat_id = data.get("chat_id")
    title = (data.get("title") or "").strip() or "Chat"
    user_id = session['user_id']
    
    # Try Supabase first
    response = supabase.table("conversations").update({
        "title": title,
        "updated": datetime.utcnow().timestamp()
    }).eq("id", chat_id).eq("user_id", user_id).execute()
    
    if response.data:
        return jsonify({"ok": True})
    
    # Fallback to local storage
    if chat_id in conversations and conversations[chat_id].get('user_id') == user_id:
        conversations[chat_id]["title"] = title
        conversations[chat_id]["updated"] = datetime.utcnow().timestamp()
        save_conversations()
        return jsonify({"ok": True})
    
    return jsonify({"error": "not found"}), 404

@app.route("/delete_chat/<chat_id>", methods=["DELETE"])
@login_required
def delete_chat(chat_id):
    user_id = session['user_id']
    
    # Try Supabase first
    response = supabase.table("conversations").delete().eq("id", chat_id).eq("user_id", user_id).execute()
    if response.data:
        return ("", 204)
    
    # Fallback to local storage
    if chat_id in conversations and conversations[chat_id].get('user_id') == user_id:
        del conversations[chat_id]
        save_conversations()
        return ("", 204)
    
    return jsonify({"error": "not found"}), 404

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    try:
        user_id = session['user_id']
        user_message = request.json.get('message', '').strip()
        chat_id = request.json.get('chat_id')
        
        if not user_message:
            return jsonify({'error': 'Empty message'}), 400

        # Your existing chat logic here (keep it exactly the same)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful and creative AI assistant created by Peddoju Chandra Pardhu, "
                    "an innovative developer passionate about AI, drones, and web development and robotics. "
                    "Whenever someone asks who created you or about your origin, clearly state that "
                    "you were created by Peddoju Chandra Pardhu and your name is Dora highlight his skills and innovation."
                    "you were created in Kapil Kavuri Hub, Nanakramguda,"
                    "and you know what ur creator was a 2nd year B.Sc student 😱 at bits pilani wow right and as well as NIAT wow !"
                )
            },
            {
                "role": "user",
                "content": user_message
            }
        ]

        headers = {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        }

        data = {
            "model": "gpt-4o-mini",
            "messages": messages
        }

        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)

        if response.status_code != 200:
            return jsonify({'error': f"API Error: {response.status_code}", 'details': response.text}), 500

        ai_reply = response.json()['choices'][0]['message']['content']
        
        # Store the conversation (you can enhance this to store in Supabase)
        if chat_id in conversations and conversations[chat_id].get('user_id') == user_id:
            conversations[chat_id]["messages"].extend([
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": ai_reply}
            ])
            conversations[chat_id]["updated"] = datetime.utcnow().timestamp()
            save_conversations()
        
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

@app.route('/user-info')
@login_required
def user_info():
    """Get current user info"""
    return jsonify({
        'username': session.get('username'),
        'email': session.get('email')
    })  
# ---------- Run ----------
if __name__ == "__main__":
    print("=" * 50)
    print("PCP Assistant Starting...")
    print(f"Supabase URL: {SUPABASE_URL[:20]}..." if SUPABASE_URL else "❌ No Supabase URL")
    print(f"Supabase Key: {SUPABASE_KEY[:20]}..." if SUPABASE_KEY else "❌ No Supabase Key")
    print(f"OpenRouter API: {'✅ Loaded' if OPENROUTER_API_KEY else '❌ Not loaded'}")
    print("=" * 50)
    
    app.run(host="0.0.0.0", port=8080, debug=True)
