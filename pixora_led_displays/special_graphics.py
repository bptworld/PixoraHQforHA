"""Allowlisted local graphic tests; never execute arbitrary browser renderer names."""
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
    favorite=options.get('favoriteTeam','TEST');label=str(favorite)
    for option in card.get('options',[]):
        if option['key']=='favoriteTeam':
            for choice in option.get('choices',[]):
                if isinstance(choice,dict) and choice.get('value')==favorite:label=choice['label'];break
    team={'_width':width,'abbreviation':favorite,'displayName':label,'color':'668CFF','alternateColor':'FFFFFF','winnerName':'Test Winner','playerName':'Test Player','roundNumber':2,'destination':'Destination','event':'Weather Alert'}
    if key=='landingGraphicTarget' and str(options.get(key,'device'))=='device':body=module._landing_animation_body(width);timing=None
    elif test['renderer']=='etsy_order':body=module._new_order_animation({'newest_total':12.5,'newest_currency':'USD'},options);timing=None
    elif test['renderer']=='flight_alert':
        import io
        image=module._draw_alert('TEST ALERT','AA123',test['label'],width=width);out=io.BytesIO();image.save(out,'PNG');body=out.getvalue();timing=None
    else:body,timing=renderer_body(module,{**test,'team':team},width)
    return {'body':base64.b64encode(artwork(body,width,timing,True)).decode(),'duration':6,'kind':test['kind'],'once':True}
