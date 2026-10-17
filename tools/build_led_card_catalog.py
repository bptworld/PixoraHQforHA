"""Build metadata-only catalog from the verified public MIT Pixora cards checkout."""
import ast,hashlib,json,subprocess,sys
from pathlib import Path
source=Path(sys.argv[1]).resolve();cards=source/'cards'
commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
registry=json.loads((cards/'registry.json').read_text(encoding='utf-8'))
modules={p.stem:p for p in cards.glob('*.py')}|{p.stem:p for p in (cards/'addons').glob('*.py')}
def dependencies(path,seen):
 if path in seen:return
 seen.add(path)
 for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
  names=[a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import) else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else []
  for name in names:
   if name in modules:dependencies(modules[name],seen)
  # Several public sports cards load a sibling animation module by file path.
  if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='with_name' and node.args and isinstance(node.args[0],ast.Constant):
   sibling=node.args[0].value
   if isinstance(sibling,str) and sibling.endswith('.py'):
    target=path.with_name(sibling)
    if target.parent!=path.parent or not target.is_file():raise ValueError('Missing or invalid sibling dependency '+sibling)
    dependencies(target,seen)
  if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module' and node.args and isinstance(node.args[0],ast.Constant):
   name=str(node.args[0].value).split('.')[0]
   if name in modules:dependencies(modules[name],seen)
external={}
for card in registry['cards']:
 name=card['url'].rsplit('/',1)[-1];path=cards/'addons'/name
 if not path.is_file():raise ValueError('Missing public card '+name)
 deps=set();dependencies(path,deps)
 deps.update(p for p in (cards/'assets/fonts').rglob('*') if p.is_file())
 deps.add(cards/'LICENSE')
 # Small shared artwork; card preview thumbnails remain remote catalog images.
 deps.update(p for p in (cards/'assets').glob('*') if p.is_file())
 for option in card.get('options',[]):
  if any(word in option['key'].lower() for word in ('token','secret','password','apikey','api_key')):option['type']='password'
 card['module']=name[:-3]
 card['files']=[p.relative_to(cards).as_posix() for p in sorted(deps)]
 if name in ('disney.py','disney_park_hours.py'):
  for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
   if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.endswith('.png') and '/' not in node.value:
    local='assets/park-art/'+node.value;remote='graphics/assets/'+node.value
    if not (source/remote).is_file():raise ValueError('Missing park artwork '+remote)
    external[local]=remote;card['files'].append(local)
  card['files']=sorted(set(card['files']))
 card['previewUrl']='https://raw.githubusercontent.com/bptworld/pixora/'+commit+'/cards/assets/previews/'+card['id']+'.webp'
 card.pop('url',None)
 if card['id']=='home_assistant_entity':card['options']=[o for o in card.get('options',[]) if o['key'] not in ('host','token')]
paths={name for card in registry['cards'] for name in card['files']}
# Hash immutable repository blobs, not checkout bytes altered by core.autocrlf.
names=sorted(paths)
queries=''.join(commit+':'+external.get(name,'cards/'+name)+'\n' for name in names).encode('utf-8')
blobs=subprocess.check_output(['git','-C',str(source),'cat-file','--batch'],input=queries)
position=0;registry['files']={}
for name in names:
 end=blobs.index(b'\n',position);header=blobs[position:end].split()
 if len(header)!=3 or header[1]!=b'blob':raise ValueError('Missing public Git blob '+name)
 size=int(header[2]);body=blobs[end+1:end+1+size];position=end+size+2
 registry['files'][name]={'sha256':hashlib.sha256(body).hexdigest(),'size':len(body)}
 if name in external:registry['files'][name]['source_path']=external[name]
imported_helpers={name for card in registry['cards'] for name in card['files'] if name.endswith('.py') and name != 'addons/'+card['module']+'.py'}
registry['shared_files']=[name for name in sorted(paths) if name in imported_helpers or name in ('card_utils.py','event_sport_utils.py','LICENSE') or (name.startswith('assets/') and not name.startswith('assets/park-art/')) or name.startswith('addons/_')]
registry['commit']=commit
out=Path(__file__).resolve().parents[1]/'pixora_led_displays/card_catalog.json'
out.write_text(json.dumps(registry,indent=2)+'\n',encoding='utf-8')
print('Metadata only:',len(registry['cards']),'cards,',len(paths),'downloadable public dependency files; revision',commit)
