"""Provider-backed standings groups and exact local division filtering."""
import re

SPORTS={'mlb':'baseball/mlb','nba':'basketball/nba','nhl':'hockey/nhl','nfl':'football/nfl','wnba':'basketball/wnba',
        'college_football':'football/college-football','college_baseball':'baseball/college-baseball',
        'mens_college_basketball':'basketball/mens-college-basketball','womens_college_basketball':'basketball/womens-college-basketball',
        'mens_college_hockey':'hockey/mens-college-hockey','womens_college_hockey':'hockey/womens-college-hockey',
        'womens_college_volleyball':'volleyball/womens-college-volleyball'}
SOCCER={'eng.1','usa.1','esp.1','ita.1','ger.1','fra.1','usa.nwsl'}
FANTASY={'fantasy_standings','espn_fantasy_standings','yahoo_fantasy_standings'}

def public_card(card):return 'addons/sports_standings.py' in card.get('files',[])

def configure(cards):
    for card in cards.values():
        if public_card(card):
            card['standingsBrowser']='public'
            if not any(option['key']=='group' for option in card.get('options',[])):
                card.setdefault('options',[]).append({'key':'group','label':'Conference / division','type':'select','default':'auto','choices':[{'value':'auto','label':'Default'}]})
            for option in card.get('options',[]):
                if option['key']=='group':option['label']='Conference / division'
        elif card['id'] in FANTASY:
            card['standingsBrowser']='fantasy'
            if not any(option['key']=='division' for option in card.get('options',[])):
                card.setdefault('options',[]).append({'key':'division','label':'Division','type':'select','default':'all','choices':[{'value':'all','label':'All divisions'}]})

def endpoint(card,options):
    league=card['id'].removesuffix('_standings')
    if card['id']=='sports_standings':league=str(options.get('league','mlb'))
    if league=='soccer':
        selected=str(options.get('soccerLeague','eng.1'))
        if selected not in SOCCER:raise ValueError('Choose an available soccer league.')
        path='soccer/'+selected
    else:
        path=SPORTS.get(league)
        if not path:raise ValueError('Choose an available standings league.')
    return 'https://site.web.api.espn.com/apis/v2/sports/'+path+'/standings'

def group_id(value):
    if not re.fullmatch(r'espn:\d{1,10}',str(value)):raise ValueError('Choose an available standings group.')
    return str(value)[5:]

def choices(data,include_root=False):
    children=data.get('children',[])
    if not children and include_root and (data.get('standings') or {}).get('entries'):children=[data]
    return [{'value':'espn:'+str(node['id']),'label':str(node.get('name') or node.get('abbreviation') or node['id'])}
            for node in sorted(children,key=lambda node:str(node.get('name','')).casefold()) if str(node.get('id','')).isdigit()]

def legacy_match(children,value):
    terms=str(value).lower().replace('_',' ').replace('-',' ').split()
    for node in children:
        text=' '.join(str(node.get(k,'')) for k in ('name','abbreviation','shortName')).lower().replace('-',' ')
        words=text.split()
        if all(term in words for term in terms):return node
    return None

def entries(data):
    direct=(data.get('standings') or {}).get('entries') or []
    if direct:return direct
    rows=[];seen=set()
    for child in data.get('children',[]):
        for row in entries(child):
            team=row.get('team',{});key=team.get('id') or team.get('abbreviation')
            if key not in seen:rows.append(row);seen.add(key)
    return rows

def install(module,ident,options):
    if ident in FANTASY:return install_fantasy(module,ident,options)
    if ident!='sports_standings' and ident.removesuffix('_standings') not in {*SPORTS,'soccer'}:return
    if ident=='sports_standings':shared=module
    else:import sports_standings as shared
    from card_utils import fetch_json_request
    original_pick=shared._pick_child
    selected=str(options.get('group','auto'))
    def fetch(url):
        if selected.startswith('espn:'):
            ident=group_id(selected)
            root=fetch_json_request(url,seconds=1800)
            data=next((node for node in root.get('children',[]) if str(node.get('id'))==ident and (node.get('standings') or {}).get('entries')),None)
            if data is None:data=fetch_json_request(url+'?group='+ident,seconds=1800)
            if str(data.get('id'))!=ident:raise ValueError('Selected standings division is unavailable.')
            return {'children':[{**data,'standings':{'entries':entries(data)}}]}
        data=fetch_json_request(url,seconds=1800)
        return {'children':[data]} if not data.get('children') and (data.get('standings') or {}).get('entries') else data
    def pick(children,value):
        if str(value).startswith('espn:'):
            ident=group_id(value)
            match=next((child for child in children if str(child.get('id'))==ident),None)
            if match is None:raise ValueError('Selected standings division is unavailable.')
            return match
        if value=='auto':match=original_pick(children,value)
        else:
            match=legacy_match(children,value)
            if match is None and str(value).startswith(('al_','nl_')):match=legacy_match(children,str(value)[:2])
            if match is None:raise ValueError('Selected standings group is unavailable.')
        return {**match,'standings':{'entries':entries(match)}} if match else None
    shared._fetch=fetch;shared._pick_child=pick

def install_fantasy(module,ident,options):
    value=options.get('division','all');selected=str('all' if value in ('',None) else value)
    if ident=='fantasy_standings':
        original=module.rosters
        module.rosters=lambda league:[row for row in original(league) if selected=='all' or str(row.get('settings',{}).get('division'))==selected]
    elif ident=='espn_fantasy_standings':
        original=module.fetch_league
        def league(*args,**kwargs):
            data=original(*args,**kwargs)
            return {**data,'teams':[row for row in data.get('teams',[]) if selected=='all' or str(row.get('divisionId'))==selected]}
        module.fetch_league=league
    else:
        import _fantasy_yahoo as helper
        original=helper.parse_team
        def parse(value):
            row=original(value)
            def find(item):
                if isinstance(item,dict):
                    if 'division_id' in item:return item['division_id']
                    for child in item.values():
                        found=find(child)
                        if found is not None:return found
                elif isinstance(item,list):
                    for child in item:
                        found=find(child)
                        if found is not None:return found
            row['division_id']=find(value)
            return row
        helper.parse_team=parse
        original_standings=module.standings
        def filtered(opts):
            rows=original_standings(opts)
            if selected=='all':return rows
            return [{**row,'rank':rank} for rank,row in enumerate((row for row in rows if str(row.get('division_id'))==selected),1)]
        module.standings=filtered

def fantasy_groups(module,ident,options):
    names={};ids=set()
    if ident=='fantasy_standings':
        from _fantasy_sleeper import league,league_id,rosters
        lid=league_id(options)
        if not lid:raise ValueError('Enter your Sleeper league ID first.')
        data=league(lid)
        for row in rosters(lid):
            value=row.get('settings',{}).get('division')
            if value is not None:ids.add(str(value))
        for key,value in (data.get('metadata') or {}).items():
            if re.fullmatch(r'division_\d+',key):names[key[9:]]=value
    elif ident=='espn_fantasy_standings':
        if not module.league_id(options):raise ValueError('Enter your ESPN league ID first.')
        data=module.fetch_league(options)
        for row in data.get('settings',{}).get('scheduleSettings',{}).get('divisions',[]):names[str(row['id'])]=row.get('name')
        ids={str(row['divisionId']) for row in data.get('teams',[]) if row.get('divisionId') is not None}
    else:
        import _fantasy_yahoo as helper
        if not helper.league_key(options) or not helper.access_token(options):raise ValueError('Enter your Yahoo league key and access token first.')
        data=helper.get_json('/league/'+helper.league_key(options)+'/settings',helper.access_token(options),seconds=300)
        def walk(item):
            if isinstance(item,dict):
                if 'division_id' in item and item.get('name'):names[str(item['division_id'])]=item['name']
                for value in item.values():walk(value)
            elif isinstance(item,list):
                for value in item:walk(value)
        walk(data)
        ids={str(row['division_id']) for row in helper.standings(options) if row.get('division_id') is not None}
    ids|=names.keys()
    return {'groups':[{'value':value,'label':str(names.get(value) or 'Division '+value)} for value in sorted(ids)],'message':'' if ids else 'This league has no provider divisions.'}
