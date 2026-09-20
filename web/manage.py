"""Install Python requirements and manage the local research website."""
from pathlib import Path
import argparse,json,os,signal,subprocess,sys,time,urllib.request,shutil
ROOT=Path(__file__).resolve().parent.parent;RUNTIME=ROOT/'web/.runtime';RUNTIME.mkdir(exist_ok=True)
STATE=RUNTIME/'server.json';SETTINGS=RUNTIME/'settings.json'
def get(url):
 with urllib.request.urlopen(url+'/api/v1/healthz',timeout=3) as r:return json.load(r)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['install','start','stop','status','thumbnails']);p.add_argument('--port',type=int,default=8976);p.add_argument('--inkscape');p.add_argument('--public',action='store_true',help='Enable public-demo request limits');a=p.parse_args()
 settings=json.loads(SETTINGS.read_text('utf-8')) if SETTINGS.exists() else {}
 if a.inkscape:settings['inkscape']=a.inkscape;SETTINGS.write_text(json.dumps(settings),'utf-8')
 if a.public:settings['public_mode']=True;SETTINGS.write_text(json.dumps(settings),'utf-8')
 if a.command=='install':
  subprocess.run([sys.executable,'-m','pip','install','--target',str(RUNTIME/'packages'),'-r',str(ROOT/'code/requirements.txt'),'-r',str(ROOT/'web/backend/requirements-lock.txt')],check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0);return
 if a.command=='thumbnails':
  env={**os.environ,'PYTHONPATH':str(RUNTIME/'packages')}
  subprocess.run([sys.executable,str(ROOT/'web/scripts/build_thumbnails.py')],check=True,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0);return
 state=json.loads(STATE.read_text('utf-8')) if STATE.exists() else {'url':f'http://127.0.0.1:{a.port}'}
 if a.command=='status':
  try:print(state['url'],get(state['url']))
  except Exception:print('Not running')
  return
 if a.command=='stop':
  info=get(state['url'])
  if info.get('server_pid')!=state.get('pid'):raise RuntimeError('The recorded process does not match the website. Nothing was stopped.')
  os.kill(state['pid'],signal.SIGTERM);STATE.unlink(missing_ok=True);print('Stopped');return
 if not (ROOT/'web/frontend/dist/index.html').exists():raise RuntimeError('Build the frontend first: cd web/frontend, pnpm install, pnpm run build')
 url=f'http://127.0.0.1:{a.port}'
 try:
  info=get(url)
  if info.get('generation')=='local_cpu':print('Already running:',url);return
 except Exception:pass
 executable=a.inkscape or settings.get('inkscape') or shutil.which('inkscape')
 if not executable:raise RuntimeError('Supply --inkscape with the Inkscape executable path.')
 env={**os.environ,'PAPERA_INKSCAPE':str(executable),'PAPERA_PORT':str(a.port),'PYTHONIOENCODING':'utf-8','PAPERA_PUBLIC_MODE':'1' if settings.get('public_mode') else '0'}
 with (RUNTIME/'server.log').open('a',encoding='utf-8') as log:
  child=subprocess.Popen([sys.executable,str(ROOT/'web/backend/app.py')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0,start_new_session=os.name!='nt')
  for _ in range(30):
   if child.poll() is not None:raise RuntimeError('The website could not start. See web/.runtime/server.log')
   try:
    info=get(url)
    if info.get('server_pid')==child.pid:break
   except Exception:pass
   time.sleep(.25)
  else:raise RuntimeError('The website did not become ready. See web/.runtime/server.log')
 STATE.write_text(json.dumps({'pid':child.pid,'url':url},indent=2),'utf-8');print('Website ready:',url)
if __name__=='__main__':main()
