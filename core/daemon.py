"""Long-lived HTTP daemon for FRIDAY."""
from __future__ import annotations
import json, os, signal, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .memory import FridayMemory
from .llm_engine import LLMEngine
from .tool_registry import ToolRegistry
from .agent_loop import AgentLoop
from tools import memory_tools

class FridayDaemon:
    def __init__(self, host='127.0.0.1', port=8765, token=None, pid_file=None):
        self.host, self.port, self.token = host, port, token or os.getenv('FRIDAY_DAEMON_TOKEN')
        self.pid_file = Path(pid_file or os.getenv('FRIDAY_PID_FILE','friday.pid'))
        self.lock = threading.RLock(); self.memory=FridayMemory(); self.engine=LLMEngine()
        self.registry=ToolRegistry(); memory_tools.bind_memory(self.memory); self.registry.auto_discover()
        from .skills import SkillManager
        self.skills=SkillManager(self.registry); self.registry._skill_manager=self.skills
        from tools import skill_tools
        skill_tools.bind_manager(self.skills)
        self.agent=AgentLoop(self.engine,self.registry,self.memory); self.server=None
    def status(self):
        return {'version': __import__('config').FRIDAY_VERSION,'pid':os.getpid(),'tools':len(self.registry.tools),'model':self.engine.get_model_status()}
    def serve(self):
        self.pid_file.parent.mkdir(parents=True,exist_ok=True)
        if self.pid_file.exists():
            try:
                old=int(self.pid_file.read_text()); os.kill(old,0)
                raise RuntimeError(f'daemon already running (pid {old})')
            except ProcessLookupError: pass
            except ValueError: pass
        self.pid_file.write_text(str(os.getpid()))
        daemon=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def auth(self):
                return not daemon.token or self.headers.get('Authorization','') == 'Bearer '+daemon.token
            def send(self, code, obj):
                raw=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def do_GET(self):
                if self.path=='/health': return self.send(200,{'ok':True,'pid':os.getpid()})
                if not self.auth(): return self.send(401,{'error':'unauthorized'})
                if self.path=='/status': return self.send(200,daemon.status())
                if self.path=='/profile':
                    from tools.profile_tools import get_profile
                    return self.send(200, {'profile': get_profile()})
                if self.path=='/voice':
                    return self.send(200, {'browser_speech_input': True, 'browser_speech_output': True, 'elevenlabs': bool(os.getenv('ELEVENLABS_API_KEY') and os.getenv('ELEVENLABS_VOICE_ID'))})
                if self.path=='/':
                    html=b'''<html><head><title>FRIDAY</title><meta name="viewport" content="width=device-width"></head><body><h1>F.R.I.D.A.Y.</h1><p>Online.</p><input id="q" placeholder="Ask FRIDAY" size="50"><button onclick="ask()">Send</button><button onclick="listen()">Speak</button><pre id="out"></pre><script>
async function ask(t){t=t||document.getElementById('q').value;if(!t)return;let r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:t})});let j=await r.json();document.getElementById('out').textContent=j.reply||j.error||'';if(window.speechSynthesis&&j.reply)speechSynthesis.speak(new SpeechSynthesisUtterance(j.reply));}
function listen(){let R=window.SpeechRecognition||window.webkitSpeechRecognition;if(!R){alert('Speech input is not supported by this browser');return}let r=new R;r.lang='en-US';r.onresult=e=>ask(e.results[0][0].transcript);r.start()}
</script></body></html>'''
                    self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(html))); self.end_headers(); self.wfile.write(html); return
                self.send(404,{'error':'not found'})
            def do_POST(self):
                if not self.auth(): return self.send(401,{'error':'unauthorized'})
                if self.path in ('/telegram/webhook','/slack/events'):
                    try:
                        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                        if self.path.endswith('telegram/webhook'):
                            text=((data.get('message') or {}).get('text') or '')
                            sid='telegram:'+str((data.get('message') or {}).get('chat',{}).get('id','unknown'))
                        else:
                            if data.get('type') == 'url_verification': return self.send(200, {'challenge':data.get('challenge','')})
                            text=data.get('event',{}).get('text',''); sid='slack:'+str(data.get('event',{}).get('user','unknown'))
                        if not text: return self.send(200, {'ok':True})
                        with daemon.lock: reply=daemon.agent.run(text,sid)
                        return self.send(200, {'reply':reply})
                    except Exception as e: return self.send(400, {'error':str(e)})
                if self.path!='/chat': return self.send(404,{'error':'not found'})
                try:
                    data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))); text=data.get('message',data.get('text','')); sid=data.get('session_id','daemon')
                    if not text: return self.send(400,{'error':'message is required'})
                    with daemon.lock: reply=daemon.agent.run(text,sid)
                    self.send(200,{'reply':reply,'session_id':sid})
                except Exception as e: self.send(500,{'error':str(e)})
        self.server=ThreadingHTTPServer((self.host,self.port),Handler)
        def stop(*_): self.server.shutdown()
        signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
        try: self.server.serve_forever()
        finally:
            self.server.server_close()
            try: self.pid_file.unlink()
            except FileNotFoundError: pass

def run_daemon(**kwargs): FridayDaemon(**kwargs).serve()
