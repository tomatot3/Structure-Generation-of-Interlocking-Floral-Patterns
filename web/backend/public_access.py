"""Public demo request limits and private-response cache policy."""
from collections import deque
from urllib.parse import urlsplit
import ipaddress,os,re,time
from fastapi.responses import JSONResponse

APPEARANCE_BODY_LIMITS={
    # Base64 images, portable projects/structure packages and browser-made GLB.
    'import':25_000_000,'restore':25_000_000,'structure':25_000_000,'preview-3d':25_000_000,
    # Current edits include parent deformation chains; recovery also sends brushes.
    'preview':3_000_000,'recover':3_000_000,'objects':3_000_000,
    'svg':3_000_000,'repeat':3_000_000,'condition':3_000_000,'export':3_000_000,
    'save':3_000_000,'version-save':3_000_000,
}
APPEARANCE_PROCESSING={'import','restore','structure','recover','objects','version-open','condition','export'}
RATE_LIMITS={'generation':(6,30),'write':(60,300),'appearance-preview':(180,3600),'appearance-processing':(12,120)}

def install_public_access(app,runtime):
    enabled=os.environ.get('PAPERA_PUBLIC_MODE')=='1'
    buckets={}
    last_cleanup=0.0
    @app.middleware('http')
    async def public_access(request,call_next):
        nonlocal last_cleanup
        path=request.url.path
        if enabled and request.method in {'POST','PUT','PATCH','DELETE'}:
            origin=request.headers.get('origin')
            if origin and urlsplit(origin).netloc!=request.headers.get('host'):
                return JSONResponse({'detail':'Cross-origin writes are not allowed.'},status_code=403)
            client=request.headers.get('cf-connecting-ip') or (request.client.host if request.client else 'unknown')
            try:client=str(ipaddress.ip_address(client))
            except ValueError:client='unknown'
            now=time.monotonic()
            if now-last_cleanup>60:
                for key in list(buckets):
                    if not buckets[key] or buckets[key][-1]<now-3600:buckets.pop(key,None)
                last_cleanup=now
            match=re.fullmatch(r'/api/v1/appearance/projects/[a-f0-9]{32}/([a-z0-9-]+)',path)
            action=match[1] if match else None
            group='generation' if path=='/api/v1/jobs' else 'write'
            if action=='preview':
                # Dragging is local; release, keyboard edits and view changes
                # request a server preview. These must not spend import/generation quota.
                group='appearance-preview'
            elif action in APPEARANCE_PROCESSING or path in {'/api/v1/appearance/projects','/api/v1/appearance/cup-example'}:
                group='appearance-processing'
            key=(client,group)
            if key not in buckets and len(buckets)>=10000:
                return JSONResponse({'detail':'Service is busy. Please try again shortly.'},status_code=429)
            times=buckets.setdefault(key,deque())
            while times and times[0]<now-3600:times.popleft()
            minute_limit,hour_limit=RATE_LIMITS[group]
            if len(times)>=hour_limit or sum(t>now-60 for t in times)>=minute_limit:
                return JSONResponse({'detail':'请求较频繁，请稍后再试。 / Too many requests. Please try again later.'},status_code=429,headers={'Retry-After':'60','Cache-Control':'no-store'})
            times.append(now)
            limit=APPEARANCE_BODY_LIMITS.get(action,3_000_000 if path=='/api/v1/editor/sessions' else 32_000)
            chunks=[];size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>limit:return JSONResponse({'detail':'Request body is too large.'},status_code=413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        response.headers['Referrer-Policy']='same-origin'
        if path.startswith('/api/v1/editor/'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['Vary']='Cookie'
        elif path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response
