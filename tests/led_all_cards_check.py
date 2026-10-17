"""Audit every catalog card in a fresh dependency-only directory, at both S3 sizes.
Provider traffic is blocked; this verifies packaging/runtime dependencies, not live APIs.
"""
import argparse,base64,concurrent.futures,hashlib,importlib.util,io,json,os,subprocess,sys,tempfile,traceback,urllib.error,urllib.request
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]


def worker(root,card,width):
    os.chdir(root);sys.dont_write_bytecode=True
    missing=set()
    original_exists=Path.exists;original_is_file=Path.is_file
    def tracked(method,path):
        result=method(path)
        if not result and path.suffix.lower() in ('.py','.ttf','.png','.jpg','.webp','.gif','.svg'):
            missing.add(str(path))
        return result
    Path.exists=lambda p:tracked(original_exists,p)
    Path.is_file=lambda p:tracked(original_is_file,p)
    def offline(*args,**kwargs):raise urllib.error.URLError('Offline dependency audit')
    urllib.request.urlopen=offline
    import socket
    socket.create_connection=offline
    options={o['key']:o.get('default','') for o in card.get('options',[])}
    request={'root':str(root),'module':card['module'],'width':width,'protocol':2,'options':options,'events':False,'dwell':1,
        'settings':{'timezone':'America/New_York','defaultTimezone':'America/New_York','defaultZipCode':'01826','temperatureUnits':'F'},
        'ha_state':{'entity_id':'sensor.audit','state':'42','attributes':{'friendly_name':'Audit sensor'}}}
    spec=importlib.util.spec_from_file_location('audit_worker',ROOT/'pixora_led_displays/card_worker.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    try:
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):result=module.run(request)
        if result['body']:
            with Image.open(io.BytesIO(base64.b64decode(result['body']))) as image:assert image.size==(width,32)
        return {'card':card['id'],'width':width,'status':'skip' if result['skip'] else 'ok','missing':sorted(missing)}
    except Exception as exc:
        return {'card':card['id'],'width':width,'status':'provider_unavailable' if isinstance(exc,urllib.error.URLError) else 'error','reason':type(exc).__name__+': '+str(exc),'trace':traceback.format_exc(),'missing':sorted(missing)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker');parser.add_argument('--card');parser.add_argument('--width',type=int);parser.add_argument('--source',default='D:/planner/.build-tmp/led-public-card-source');args=parser.parse_args()
    catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text())
    cards={c['id']:c for c in catalog['cards']}
    if args.worker:
        print(json.dumps(worker(Path(args.worker),cards[args.card],args.width)));return
    names=sorted(catalog['files']);queries=''.join(catalog['commit']+':'+catalog['files'][n].get('source_path','cards/'+n)+'\n' for n in names).encode()
    raw=subprocess.check_output(['git','-C',args.source,'cat-file','--batch'],input=queries);position=0;blobs={}
    for name in names:
        end=raw.index(b'\n',position);size=int(raw[position:end].split()[-1]);body=raw[end+1:end+1+size];position=end+size+2
        assert len(body)==catalog['files'][name]['size'] and hashlib.sha256(body).hexdigest()==catalog['files'][name]['sha256'],name
        blobs[name]=body
    results=[]
    with tempfile.TemporaryDirectory() as temp:
        base=Path(temp);shared=base/'blobs';shared.mkdir()
        for name,body in blobs.items():
            path=shared/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        def audit(card,width):
            root=base/(card['id']+'-'+str(width));root.mkdir()
            for name in card['files']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);os.link(shared/name,path)
            try:
                result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(root),'--card',card['id'],'--width',str(width)],capture_output=True,text=True,timeout=35)
                if result.returncode:return {'card':card['id'],'width':width,'status':'worker_error','reason':result.stderr[-2000:]}
                return json.loads(result.stdout.splitlines()[-1])
            except subprocess.TimeoutExpired:return {'card':card['id'],'width':width,'status':'timeout'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(audit,c,w) for c in cards.values() for w in (64,128)]
            for count,future in enumerate(concurrent.futures.as_completed(futures),1):
                result=future.result();results.append(result)
                if result['status'] not in ('ok','skip','provider_unavailable'):print(result['card'],result['width'],result['status'],result.get('reason',''),flush=True)
                if count%40==0:print(str(count)+'/'+str(len(futures))+' checked',flush=True)
    report=Path('D:/planner/.build-tmp/led-all-cards-audit.json');report.write_text(json.dumps(results,indent=2),encoding='utf-8')
    counts={status:sum(r['status']==status for r in results) for status in set(r['status'] for r in results)}
    print(json.dumps(counts,sort_keys=True));print('Full report: '+str(report))
    if any(r['status'] not in ('ok','skip','provider_unavailable') for r in results):sys.exit(1)


if __name__=='__main__':main()
