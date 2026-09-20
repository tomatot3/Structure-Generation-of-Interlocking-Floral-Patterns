"""Public demo request limits and private-response cache policy."""
from collections import deque
from urllib.parse import urlsplit
import ipaddress,os,time
from fastapi.responses import JSONResponse

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
            group='generation' if path=='/api/v1/jobs' else 'write'
            key=(client,group)
            if key not in buckets and len(buckets)>=10000:
                return JSONResponse({'detail':'Service is busy. Please try again shortly.'},status_code=429)
            times=buckets.setdefault(key,deque())
            while times and times[0]<now-3600:times.popleft()
            minute_limit,hour_limit=(6,30) if group=='generation' else (60,300)
            if len(times)>=hour_limit or sum(t>now-60 for t in times)>=minute_limit:
                return JSONResponse({'detail':'请求较频繁，请稍后再试。 / Too many requests. Please try again later.'},status_code=429,headers={'Retry-After':'60','Cache-Control':'no-store'})
            times.append(now)
            limit=3_000_000 if path=='/api/v1/editor/sessions' else 32_000
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
