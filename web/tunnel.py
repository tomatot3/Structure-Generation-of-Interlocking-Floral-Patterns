"""Manage this website's Cloudflare Quick Tunnel without opening a console window."""
from pathlib import Path
import argparse,ctypes,json,os,re,signal,subprocess,time,urllib.request

ROOT=Path(__file__).resolve().parent.parent
STORE=ROOT/'web/.runtime/cloudflare'
STATE=STORE/'tunnel.json'
ORIGIN='http://127.0.0.1:8976'

def read_json(path):return json.loads(path.read_text('utf-8'))
def get(url):
    with urllib.request.urlopen(url,timeout=8) as r:return r.read()
def matches_process(state):
    if os.name!='nt':return False
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,int(state['pid']))
    if not handle:return False
    try:
        size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
        return bool(kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size))) and Path(buffer.value).resolve()==Path(state['executable']).resolve()
    finally:kernel.CloseHandle(handle)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['start','stop','status'])
    parser.add_argument('--cloudflared',type=Path,default=STORE/'cloudflared.exe')
    args=parser.parse_args();STORE.mkdir(parents=True,exist_ok=True)
    state=read_json(STATE) if STATE.exists() else {}
    running=bool(state and matches_process(state))
    if args.command=='stop':
        if running:os.kill(state['pid'],signal.SIGTERM);state['stopped_at']=time.time();STATE.write_text(json.dumps(state,indent=2),'utf-8');print('Stopped this website\'s public tunnel. The local website remains running.')
        else:print('No matching tunnel process is running; nothing stopped.')
        return
    if args.command=='status':
        print(json.dumps({'running':running,'url':state.get('url'),'origin':ORIGIN,'log':state.get('log')},indent=2))
        return
    if running:print('Already running:',state.get('url','still connecting'));return
    health=json.loads(get(ORIGIN+'/api/v1/healthz'))
    if health.get('generation')!='local_cpu' or not health.get('public_mode'):
        raise RuntimeError('Start this website with public mode first: python web/manage.py start --public')
    executable=args.cloudflared.resolve()
    if not executable.is_file():raise RuntimeError('Install the official cloudflared executable or supply --cloudflared.')
    config=STORE/'quick.yml';config.write_text('{}\n','utf-8')
    stamp=time.strftime('%Y%m%d_%H%M%S');log=STORE/f'tunnel_{stamp}.log';console=STORE/f'console_{stamp}.log'
    command=[str(executable),'tunnel','--config',str(config),'--no-autoupdate','--url',ORIGIN,'--metrics','127.0.0.1:18976','--loglevel','info','--logfile',str(log)]
    with console.open('w',encoding='utf-8') as output:
        child=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    state={'pid':child.pid,'executable':str(executable),'origin':ORIGIN,'log':str(log),'console':str(console),'started_at':time.time(),'url':None}
    STATE.write_text(json.dumps(state,indent=2),'utf-8')
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if child.poll() is not None:raise RuntimeError(f'Cloudflare Tunnel exited. Read {console}')
        text=console.read_text('utf-8',errors='replace')+(log.read_text('utf-8',errors='replace') if log.exists() else '')
        matches=re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com',text)
        if matches:
            state['url']=matches[0];STATE.write_text(json.dumps(state,indent=2),'utf-8')
            if 'Registered tunnel connection' in text:
                print('Tunnel connected:',state['url']);return
        time.sleep(.5)
    print('Tunnel is still connecting. State:',STATE)
    if state['url']:print('Assigned URL:',state['url'])

if __name__=='__main__':main()
