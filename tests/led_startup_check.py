"""Restart recovery preserves pause intent and never replays uncertain messages."""
import asyncio,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pixora_led_displays'))
sys.path.insert(0,str(ROOT/'pixora_led_displays/custom_components/pixora_local'))
from studio import Studio

async def main():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);boot='1'*16;offline=False;starts=[]
        class Client:
            async def info(self):
                if offline:raise ValueError('offline')
                return {'id':'panel','localDecks':True,'bootId':boot,'width':128}
        studio=Studio({'session':object()},root,lambda ident:Client(),lambda:[])
        studio.data['decks']['deck']={'items':[{'enabled':True}]}
        studio.data['devices']['panel']={'deck':'deck','playing':True,'bootId':boot}
        async def player(ident):
            starts.append(ident)
            await asyncio.Event().wait()
        async def monitor(ident):await asyncio.Event().wait()
        with patch.object(studio,'player',player),patch.object(studio,'monitor',monitor):
            # HA startup while offline preserves the saved running state.
            offline=True
            watcher=asyncio.create_task(studio.watch_display('panel'))
            async def until(predicate):
                async with asyncio.timeout(3):
                    while not predicate():await asyncio.sleep(.01)
            await until(lambda:studio.runtime.get('panel',{}).get('status')=='Waiting for display to reconnect…')
            assert studio.data['devices']['panel']['playing'] and not starts
            offline=False
            await until(lambda:len(starts)==1)
            watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
            assert len(starts)==1
            await studio.recover_display('panel',await Client().info());await asyncio.sleep(0)
            assert len(starts)==1,'A status check restarted a running deck'
            # A new boot replaces the old player, without requiring Play.
            boot='2'*16
            await studio.recover_display('panel',await Client().info());await asyncio.sleep(0)
            assert len(starts)==2 and studio.data['devices']['panel']['bootId']==boot
            # An uncertain deck write stays blocked on the same boot.
            await studio.stop('panel',remember=False)
            studio.data['devices']['panel']['playing']=False
            studio.pipeline.errors['panel']='Deck delivery could not be confirmed. It was not retried.'
            studio.pipeline.blocked.add('panel')
            await studio.recover_display('panel',await Client().info());assert len(starts)==2
            boot='3'*16
            await studio.recover_display('panel',await Client().info());await asyncio.sleep(0)
            assert len(starts)==3 and 'panel' not in studio.pipeline.errors
            # Priority-message uncertainty is retained even across a reboot.
            await studio.stop('panel',remember=False)
            studio.data['devices']['panel']['playing']=False
            studio.pipeline.errors['panel']='Previous priority delivery was interrupted; it was not resent.'
            boot='4'*16
            await studio.recover_display('panel',await Client().info())
            assert len(starts)==3 and 'panel' in studio.pipeline.errors
            studio.pipeline.errors.clear();studio.pipeline.blocked.clear()
            await studio.stop('panel')
            boot='5'*16
            await studio.recover_display('panel',await Client().info())
            assert len(starts)==3 and not studio.data['devices']['panel']['resume_on_boot']
            # Pause during a slow preflight must win over startup recovery.
            gate=asyncio.Event();entered=asyncio.Event()
            async def slow_info():entered.set();await gate.wait();return {'id':'panel','localDecks':True,'bootId':boot}
            with patch.object(Client,'info',lambda self:slow_info()):
                pending=asyncio.create_task(studio.play('panel'));await entered.wait()
                await studio.stop('panel');gate.set();await pending
            assert len(starts)==3 and not studio.data['devices']['panel']['playing']
            await studio.save()
            saved=json.loads(studio.file.read_text());assert saved['devices']['panel']['resume_on_boot'] is False
        await studio.shutdown()
    print('Startup recovery passed: offline HA startup, panel reboot, no same-boot replay, priority uncertainty, explicit pause and pause during preflight.')

asyncio.run(main())
