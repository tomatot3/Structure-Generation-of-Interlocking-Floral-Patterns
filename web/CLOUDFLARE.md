# Optional temporary access on Windows

The tunnel helper exposes the local website through Cloudflare Quick Tunnel. Install the official `cloudflared` Windows executable and supply its path. From the repository root:

```bash
python web/manage.py start --public --inkscape inkscape
python web/tunnel.py start --cloudflared C:/tools/cloudflared.exe
python web/tunnel.py status
```

The helper reports the assigned URL. The website and tunnel processes must remain running; a later start can receive a different URL. Runtime state, logs and process IDs are stored in the ignored `web/.runtime/cloudflare/` directory.

Stop the tunnel while keeping the local website running:

```bash
python web/tunnel.py stop
```

To stop the website as well, run `python web/manage.py stop`.
