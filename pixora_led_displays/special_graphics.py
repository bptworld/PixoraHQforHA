"""Allowlisted local graphic tests; never execute arbitrary browser renderer names."""

def test_team(module,card,options,width):
    from urllib.parse import urlsplit,urlunsplit,quote
    from card_utils import fetch_json_request
    favorite=str(options.get('favoriteTeam') or 'TEST')
    label=next((choice['label'] for option in card.get('options',[]) if option['key']=='favoriteTeam'
                for choice in option.get('choices',[]) if isinstance(choice,dict) and choice.get('value')==favorite),favorite)
    team={'_width':width,'abbreviation':favorite,'displayName':label,'color':'668CFF','alternateColor':'FFFFFF',
          'winnerName':'Test Winner','playerName':'Test Player','roundNumber':2,'destination':'Destination','event':'Weather Alert'}
    ident=card['id']
    team['_sport']=('football' if ident in ('nfl','ufl','cfl','college_football') else 'hockey' if 'hockey' in ident or ident=='nhl' else 'basketball' if 'basketball' in ident or ident in ('nba','wnba','nba_g_league') else 'baseball' if 'baseball' in ident or 'softball' in ident or ident=='mlb' else 'soccer' if ident in ('soccer','fifa_world_cup') else 'lacrosse' if 'lacrosse' in ident else 'volleyball' if 'volleyball' in ident else ident)
    warning=''
    source=urlsplit(str(getattr(module,'_URL','')))
    if any(option['key']=='favoriteTeam' for option in card.get('options',[])):
        if source.hostname=='site.api.espn.com' and source.path.endswith('/scoreboard'):
            url=urlunsplit(('https',source.hostname,source.path.removesuffix('/scoreboard')+'/teams/'+quote(favorite,safe=''),'',''))
            try:
                data=fetch_json_request(url,seconds=86400).get('team',{})
                if not isinstance(data,dict) or not data:raise ValueError('No team artwork')
                team.update({key:data[key] for key in ('id','abbreviation','displayName','shortDisplayName','color','alternateColor','logos') if key in data})
                logos=data.get('logos') or []
                team['logo']=data.get('logo') or next((logo.get('href') for logo in logos if isinstance(logo,dict) and logo.get('href')),'')
                if not team['logo']:warning='Team logo was unavailable; the test uses fallback artwork.'
            except Exception:warning='Team artwork could not be loaded from its provider; the test uses fallback artwork.'
        else:warning='Team artwork is unavailable for this test; fallback artwork is used.'
    return team,warning
def tests_for(card):
    ident=card['id'];result={}
    football=ident in ('nfl','college_football','cfl','ufl')
    for option in card.get('options',[]):
        key=option['key'];kind=None;renderer='_render_score_alert_frames'
        if key=='scoreAnimationTarget':
            kind='touchdown' if football else 'goal' if 'lacrosse' in ident else 'point' if 'volleyball' in ident else 'three'
            if football:renderer='_render_score_animation_frames'
        elif key=='runAnimationTarget':kind='run';renderer='_render_run_animation_frames'
        elif key=='goalAnimationTarget':kind='goal';renderer='_render_goal_animation_frames'
        elif key in ('startPeriodAnimationTarget','endPeriodAnimationTarget'):
            kind=('period_' if ident=='nhl' else 'quarter_')+('start' if key.startswith('start') else 'end')
            if football or ident=='nhl':renderer='render_score_alert_frames'
        elif key in ('gameStartAnimationTarget','gameEndAnimationTarget','halfStartAnimationTarget','halfEndAnimationTarget'):
            kind={'gameStartAnimationTarget':'game_start','gameEndAnimationTarget':'game_end','halfStartAnimationTarget':'half_start','halfEndAnimationTarget':'half_end'}[key]
            renderer='_render_run_animation_frames' if ident=='mlb' else '_render_goal_animation_frames'
        elif key in ('scoringPlayAnimationTarget','homeRunAnimationTarget','walkOffAnimationTarget','nowBattingAnimationTarget'):
            kind={'scoringPlayAnimationTarget':'rbi','homeRunAnimationTarget':'home_run','walkOffAnimationTarget':'walk_off','nowBattingAnimationTarget':'now_batting'}[key];renderer='_render_run_animation_frames'
        elif ident=='ufc' and key.endswith('AnimationTarget'):
            kind={'fightStartAnimationTarget':'fight_start','roundStartAnimationTarget':'round_start','roundEndAnimationTarget':'round_end','knockoutAnimationTarget':'knockout','submissionAnimationTarget':'submission','decisionAnimationTarget':'decision','winAnimationTarget':'win'}.get(key);renderer='_render_moment_animation_frames'
        elif key=='winAnimationTarget':
            kind='win';renderer='_render_score_animation_frames' if football else '_render_goal_animation_frames' if ident in ('nhl','soccer','fifa_world_cup') else '_render_score_alert_frames'
        elif key=='landingGraphicTarget':kind='landing';renderer='_render_landing_wall_frames'
        elif key=='launchAnimationTarget':kind='liftoff';renderer='_render_launch_animation_frames'
        elif ident=='weather_alert' and key.endswith('AlertTarget'):kind=key.removesuffix('AlertTarget');renderer='_render_weather_alert_frames'
        elif ident=='flight_watchlist' and key in ('delayAlerts','landedAlerts','gateAlerts','nearAlerts'):kind=key;renderer='flight_alert'
        if kind:result[key]={'kind':kind,'renderer':renderer,'label':option['label']}
    if ident=='etsy_shop':result['newOrder']={'kind':'new_order','renderer':'etsy_order','label':'New order'}
    return result

def render_test(module,card,key,options,width):
    from card_worker import artwork,renderer_body
    import base64
    test=tests_for(card).get(key)
    if not test:raise ValueError('Choose a special graphic for this card.')
    team,warning=test_team(module,card,options,width)
    if str(options.get(key,'device')) in ('group','group_wall','wall') or str(options.get(key,'')).startswith('group:'):
        team['_wall']=True
    if key=='landingGraphicTarget' and str(options.get(key,'device'))=='device':body=module._landing_animation_body(width);timing=None
    elif test['renderer']=='etsy_order':body=module._new_order_animation({'newest_total':12.5,'newest_currency':'USD'},options);timing=None
    elif test['renderer']=='flight_alert':
        import io
        image=module._draw_alert('TEST ALERT','AA123',test['label'],width=width);out=io.BytesIO();image.save(out,'PNG');body=out.getvalue();timing=None
    else:body,timing=renderer_body(module,{**test,'team':team},width)
    return {'body':base64.b64encode(artwork(body,width,timing,True)).decode(),'duration':6,'kind':test['kind'],'once':True,**({'warning':warning} if warning else {})}


def event_group(spec,options,card,groups):
    """Resolve a wall event to its saved group; never pick an arbitrary group."""
    kind=str(spec.get('kind') or spec.get('type') or '')
    matches=[key for key,test in tests_for(card).items() if test['kind']==kind]
    if not matches:
        aliases={'field_goal':'scoreAnimationTarget','safety':'scoreAnimationTarget','score':'scoreAnimationTarget',
                 'bucket':'scoreAnimationTarget','free_throw':'scoreAnimationTarget','grand_slam':'homeRunAnimationTarget',
                 'inning_start':'gameStartAnimationTarget','quarter_start':'startPeriodAnimationTarget',
                 'quarter_end':'endPeriodAnimationTarget','period_start':'startPeriodAnimationTarget',
                 'period_end':'endPeriodAnimationTarget','shake':'launchAnimationTarget'}
        key=aliases.get(kind)
        if key in options:matches=[key]
    targets={str(options[key]) for key in matches if key in options}
    if spec.get('groupId'):targets={'group:'+str(spec['groupId'])}
    if not targets:
        targets={str(value) for value in options.values() if str(value).startswith('group:')}
    if len(targets)!=1:raise ValueError('Choose a specific display group for this special graphic.')
    target=targets.pop()
    if target.startswith('group:'):
        if target[6:] not in groups:raise ValueError('The selected graphic group is unavailable for this display.')
        return groups[target[6:]]
    if target in ('group','group_wall','wall') and len(groups)==1:return next(iter(groups.values()))
    raise ValueError('Choose a specific display group for this special graphic.')


SCORING_TARGETS={'scoreAnimationTarget','goalAnimationTarget','runAnimationTarget',
                 'scoringPlayAnimationTarget','homeRunAnimationTarget','walkOffAnimationTarget'}

def configure_scoring_choices(cards):
    for card in cards.values():
        for option in card.get('options',[]):
            if option['key'] in SCORING_TARGETS:
                choices=option.setdefault('choices',[])
                if not any((c if isinstance(c,str) else c.get('value'))=='none' for c in choices):
                    choices.insert(0,{'value':'none','label':'Do not show'})

def scoring_disabled(card,options,spec):
    if not card:return False
    kind=str(spec.get('kind') or spec.get('type') or '')
    keys=[key for key,test in tests_for(card).items() if test['kind']==kind]
    aliases={'score':'scoreAnimationTarget','field_goal':'scoreAnimationTarget','safety':'scoreAnimationTarget',
             'bucket':'scoreAnimationTarget','free_throw':'scoreAnimationTarget','two':'scoreAnimationTarget',
             'grand_slam':'homeRunAnimationTarget'}
    if not keys and kind in aliases:keys=[aliases[kind]]
    return any(key in SCORING_TARGETS and options.get(key)=='none' for key in keys)
