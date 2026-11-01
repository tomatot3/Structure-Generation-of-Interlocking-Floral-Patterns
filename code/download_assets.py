"""Download, assemble and extract the generated floral-scroll asset archive."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,json,shutil,time,urllib.request,zipfile

REPOSITORY='tomatot3/Structure-Generation-of-Interlocking-Floral-Patterns'
PARTS='archives/generated_assets_20261101'
ROOT=Path(__file__).resolve().parent.parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root',type=Path,default=ROOT)
    p.add_argument('--parts-dir',type=Path,help='Use already downloaded parts from this directory.')
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--archive-only',action='store_true')
    a=p.parse_args();a.output_root=a.output_root.resolve();a.output_root.mkdir(parents=True,exist_ok=True)
    local=a.parts_dir or ROOT/PARTS
    if (local/'index.json').exists():info=json.loads((local/'index.json').read_text('utf-8'))
    else:
        url=f'https://raw.githubusercontent.com/{REPOSITORY}/main/{PARTS}/index.json'
        with urllib.request.urlopen(url,timeout=60)as r:info=json.load(r)
    cache=a.output_root/'.downloads/generated_assets_20261101';cache.mkdir(parents=True,exist_ok=True)
    def download(part):
        name=part['file'];size=part['size'];existing=local/name
        if existing.exists()and existing.stat().st_size==size:return existing
        dest=cache/name
        if dest.exists()and dest.stat().st_size==size:return dest
        temp=dest.with_suffix('.downloading')
        url=f'https://media.githubusercontent.com/media/{REPOSITORY}/main/{PARTS}/{name}'
        for attempt in range(3):
            try:
                offset=temp.stat().st_size if temp.exists()else 0
                request=urllib.request.Request(url,headers={'Range':f'bytes={offset}-'}if offset else {})
                with urllib.request.urlopen(request,timeout=60)as response:
                    mode='ab'if offset and response.status==206 else 'wb'
                    with temp.open(mode)as out:shutil.copyfileobj(response,out,1024*1024)
                if temp.stat().st_size!=size:raise RuntimeError(f'Incomplete download: {name}')
                temp.replace(dest);print('Downloaded',name,flush=True);return dest
            except Exception:
                if attempt==2:raise
                time.sleep(2)
    with ThreadPoolExecutor(max_workers=max(1,min(8,a.workers)))as pool:files=list(pool.map(download,info['parts']))
    archive=a.output_root/'archives'/info['archive_name'];archive.parent.mkdir(exist_ok=True)
    temp=archive.with_suffix('.assembling')
    with temp.open('wb')as out:
        for part in files:
            with part.open('rb')as inp:shutil.copyfileobj(inp,out,1024*1024)
    if temp.stat().st_size!=info['archive_size']:raise RuntimeError('Assembled archive size differs')
    with zipfile.ZipFile(temp)as z:
        if len([n for n in z.namelist()if n.endswith('/structure.json')])!=1128:raise RuntimeError('Unexpected archive contents')
        if not a.archive_only:
            for name in z.namelist():
                if not(a.output_root/name).resolve().is_relative_to(a.output_root):raise RuntimeError('Unsafe archive path')
            z.extractall(a.output_root)
    temp.replace(archive)
    print('Archive:',archive)
    if not a.archive_only:print('Extracted 1,128 structures and 500 structure-rendering pairs to',a.output_root)

if __name__=='__main__':main()
