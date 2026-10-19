"""Verify the actual Docker COPY payload, rather than importing checkout files."""
import ast,os,shlex,shutil,subprocess,sys,tempfile
from pathlib import Path
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
with tempfile.TemporaryDirectory() as folder:
    packed=Path(folder)/'app';packed.mkdir()
    for line in (APP/'Dockerfile').read_text().splitlines():
        if not line.startswith('COPY '):continue
        fields=shlex.split(line)[1:];destination=fields[-1]
        if not destination.startswith('/app/'):continue
        for name in fields[:-1]:
            source=APP/name;target=packed/source.name
            if source.is_dir():shutil.copytree(source,target)
            else:shutil.copyfile(source,target)
    modules={p.stem for p in APP.glob('*.py')}
    for path in packed.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_bytes())):
            imports=[a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import) else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else []
            for module in imports:
                if module in modules:assert (packed/(module+'.py')).is_file(),f'{path.name} imports unpackaged runtime {module}'
    code="import card_updates; from app import make_app; from card_store import CardStore; from studio import Studio; print('Packaged runtime imports passed')"
    result=subprocess.run([sys.executable,'-c',code],cwd=packed,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert (packed/'card_updates.py').is_file()
    print('Docker payload passed: all local runtime imports and lazy card_updates import are present; isolated /app imports use only packaged files.')
