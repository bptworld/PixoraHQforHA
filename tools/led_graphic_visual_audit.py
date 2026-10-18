"""Render every special scene with real assets for pixel-level visual review.

Set LED_CARD_SOURCE to the verified downloaded cards directory. Pass an output
folder as the first argument. Sheets mark the 64+128+64 and 64+64+64 wall seams.
Outputs stay outside the repository; failed renders stop the audit.
"""
import os,sys,json,importlib.util,io,re,base64
from pathlib import Path
from PIL import Image,ImageOps,ImageSequence,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('LED_CARD_SOURCE','D:/planner/.build-tmp/led-public-card-source/cards'))
OUT=Path(sys.argv[1] if len(sys.argv)>1 else 'D:/planner/.build-tmp/led-visual-audit');OUT.mkdir(parents=True,exist_ok=True)
os.chdir(SOURCE);sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(SOURCE),str(SOURCE/'addons')]
from special_graphics import tests_for
import card_utils
card_utils.warm_priority_graphic=lambda *a,**k:None
catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text(encoding='utf-8'))
def sport(card):
 ident=card['id']
 return 'football' if ident in ('nfl','ufl','cfl','college_football') else 'hockey' if 'hockey' in ident or ident=='nhl' else 'basketball' if 'basketball' in ident or ident in ('nba','wnba','nba_g_league') else 'baseball' if 'baseball' in ident or 'softball' in ident or ident=='mlb' else 'soccer' if ident in ('soccer','fifa_world_cup') else 'lacrosse' if 'lacrosse' in ident else 'volleyball' if 'volleyball' in ident else ident
cases={};modules={}
for card in catalog['cards']:
 tests=tests_for(card)
 if not tests:continue
 spec=importlib.util.spec_from_file_location('visual_'+card['module'],SOURCE/'addons'/(card['module']+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules[card['id']]=module
 specs=list(tests.values())
 if card['id'] in ('nfl','ufl'):specs += [{'renderer':'_render_score_animation_frames','kind':k} for k in ('touchdown','field_goal','safety','score','win')]
 if card['id']=='nhl':specs += [{'renderer':'_render_goal_animation_frames','kind':k} for k in ('goal','hat_trick','win')]
 if card['id']=='mlb':specs += [{'renderer':'_render_run_animation_frames','kind':k} for k in ('run','home_run','grand_slam','rbi','walk_off','win','now_batting','inning_start','inning_end')]
 if card['id']=='nba':specs += [{'renderer':'render_score_alert_frames','kind':k} for k in ('bucket','three','free_throw','win')]
 if card['id']=='launch_countdown':specs += [{'renderer':'_render_launch_animation_frames','kind':'shake'}]
 for test in specs:
  name=test['renderer'];fn=getattr(module,name,None)
  if not callable(fn) and name=='_render_score_alert_frames':fn=getattr(module,'render_score_alert_frames',None)
  identity=(str(fn.__code__.co_filename),fn.__name__,sport(card),test['kind']) if callable(fn) else (card['id'],name,test['kind'])
  if identity not in cases:cases[identity]={'card':card,'module':module,'spec':test,'fn':fn,'sport':sport(card),'cards':[]}
  cases[identity]['cards'].append(card['id'])
from graphic_layout import install
for module in modules.values():install(module)
for case in cases.values():
 name=case['spec']['renderer'];case['fn']=getattr(case['module'],name,None) or getattr(case['module'],'render_score_alert_frames',None)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',13)
manifest=[];pages={}
for number,case in enumerate(cases.values()):
 card,module,test,fn=case['card'],case['module'],case['spec'],case['fn']
 for profile,width,scale in [('64',64,4),('128',128,3),('wall',256,2),('wall192',192,2)]:
  team={'_width':width,'_wall':profile.startswith('wall'),'_sport':case['sport'],'abbreviation':'BOS','displayName':'Boston Bruins','color':'FFB81C','alternateColor':'FFFFFF','logo':'https://a.espncdn.com/i/teamlogos/nhl/500/bos.png','playerName':'ALEXANDER OVECHKIN','playerHeadshot':'https://a.espncdn.com/i/headshots/nhl/players/full/4268466.png','playerLogo':'https://a.espncdn.com/i/teamlogos/nhl/500/bos.png','winnerName':'ALEXANDER VOLKANOVSKI','headshot':'https://a.espncdn.com/i/headshots/nhl/players/full/4268466.png','winnerHeadshot':'https://a.espncdn.com/i/headshots/nhl/players/full/4268466.png','winnerFlag':'https://a.espncdn.com/i/teamlogos/nhl/500/bos.png','roundNumber':5,'destination':'SAN FRANCISCO INTERNATIONAL','event':'Severe Thunderstorm Warning','leftName':'ALEXANDER VOLKANOVSKI','rightName':'ISLAM MAKHACHEV'}
  options={'_width':width,'_target':'matrixportal-s3-'+str(width)+'x32'}
  try:
   if test['renderer']=='etsy_order':result=module._new_order_animation({'newest_total':12345.67,'newest_currency':'USD'},options)
   elif test['renderer']=='flight_alert':result=([module._draw_alert({'delayAlerts':'FLIGHT ALERT','gateAlerts':'GATE CHANGE','landedAlerts':'LANDED','nearAlerts':'PLANE NEAR'}[test['kind']],'AA1234','SAN FRANCISCO INTERNATIONAL',width=width)],[3000])
   elif card['id']=='flight_track' and not profile.startswith('wall'):result=module._landing_animation_body(width)
   else:result=fn(team,test['kind'])
   if isinstance(result,(bytes,bytearray)):
    with Image.open(io.BytesIO(result)) as im:
     raw=[f.convert('RGBA') for f in ImageSequence.Iterator(im)];timing=[100]*len(raw)
   else:raw,timing=result[:2]
   sizes=sorted(set(f.size for f in raw));frames=[]
   for f in raw:
    rgba=f.convert('RGBA');frames.append(ImageOps.pad(Image.alpha_composite(Image.new('RGBA',rgba.size,'black'),rgba).convert('RGB'),(width,32),color='black'))
   ident=f'{number:03d}-{card["id"]}-{test["kind"]}-{profile}'
   frames[0].save(OUT/(ident+'.webp'),'WEBP',save_all=True,append_images=frames[1:],duration=timing,loop=0,lossless=True,method=0)
   sample=[min(len(frames)-1,int((len(frames)-1)*t)) for t in (.2,.45,.7,1)]
   row=Image.new('RGB',(180+4*(width*scale+8),32*scale+34),'#142035');draw=ImageDraw.Draw(row)
   for j,line in enumerate([card['id'],test['kind'],profile+' '+str(len(frames))+' frames']):draw.text((5,5+j*17),line,font=font,fill='white')
   for col,index in enumerate(sample):
    frame=frames[index].resize((width*scale,32*scale),Image.Resampling.NEAREST);left=180+col*(width*scale+8);row.paste(frame,(left,24));draw.text((left,3),'frame '+str(index),font=font,fill='white')
    if profile.startswith('wall'):
     for seam in ((64,192) if width==256 else (64,128)):draw.line((left+seam*scale,24,left+seam*scale,24+32*scale-1),fill='#ff00ff',width=1)
   pages.setdefault(profile,[]).append(row)
   manifest.append({'id':ident,'card':card['id'],'cards':sorted(set(case['cards'])),'kind':test['kind'],'renderer':test['renderer'],'profile':profile,'width':width,'frames':len(frames),'durations':timing,'original_sizes':sizes,'samples':sample})
  except Exception as e:
   print('FAILED',card['id'],test,profile,repr(e),flush=True);raise
 print(number,card['id'],test['kind'],flush=True)
for profile,rows in pages.items():
 for page,start in enumerate(range(0,len(rows),8)):
  chunk=rows[start:start+8];sheet=Image.new('RGB',(max(r.width for r in chunk),sum(r.height+5 for r in chunk)),'#070b14');y=0
  for row in chunk:sheet.paste(row,(0,y));y+=row.height+5
  sheet.save(OUT/(f'sheet-{profile}-{page:02d}.png'))
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
from html import escape
sections=[]
for number,case in enumerate(cases.values()):
 entries=[item for item in manifest if item['id'].startswith(f'{number:03d}-')]
 figures=[]
 for item in entries:
  if item['profile'].startswith('wall') and item['card'] in ('etsy_shop','flight_watchlist'):continue
  label={'64':'64 x 32','128':'128 x 32','wall':'64 + 128 + 64 wall','wall192':'64 + 64 + 64 wall'}[item['profile']]
  figures.append(f'<figure><figcaption>{label}</figcaption><img loading="lazy" width="{item["width"]*3}" height="96" src="{escape(item["id"])}.webp" alt="{escape(item["card"]+" "+item["kind"])}"></figure>')
 sections.append(f'<section><h2>{escape(case["card"]["name"] if "name" in case["card"] else case["card"]["id"])}: {escape(case["spec"]["kind"])}</h2><div>'+''.join(figures)+'</div></section>')
(OUT/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Special graphic visual audit</title><style>body{background:#080e18;color:#edf3ff;font:16px system-ui;margin:24px}section{border-top:1px solid #476184;padding:16px 0}section>div{display:flex;flex-wrap:wrap;gap:16px}figure{margin:0;max-width:100%;overflow:auto}figcaption{margin-bottom:8px;color:#a7c5ff}img{image-rendering:pixelated;background:black}h2{font-size:18px}</style><h1>Special graphic visual audit</h1><p>62 scenes. Device previews and supported three-device walls. Long names and large totals exercise the layout limits. Animations use the local hub renderer.</p>'+''.join(sections),encoding='utf-8')
print('DONE',len(cases),'scenes',len(manifest),'rendered profiles',flush=True)
