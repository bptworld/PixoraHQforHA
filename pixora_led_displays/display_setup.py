"""Local first-install profiles. Credentials never appear in status or logs."""
import asyncio,csv,hashlib,ipaddress,json,os,re,sys,tempfile,time,uuid
from pathlib import Path
from types import SimpleNamespace
from aiohttp import web

IMAGE_SHA='6b173e4b88e171310179c460150c395c29a546803aeacffdc2ce00573bd3ec72'
IMAGE=Path(__file__).with_name('first-install.bin')

class DisplayInstaller:
    def __init__(self,root):
        self.root=Path(root)/'display-setup';self.file=self.root/'profiles.json'
        self.profiles=json.loads(self.file.read_text()) if self.file.exists() else {}
        self.jobs={};self.tasks={}

    def save(self):
        self.root.mkdir(parents=True,exist_ok=True);os.chmod(self.root,0o700)
        temp=self.file.with_suffix('.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(self.profiles,f)
        os.replace(temp,self.file)

    def public(self):
        return [{'id':ident,'name':p['name'],'width':p['width'],'ssid':p['ssid'],'hasPassword':bool(p['password'])} for ident,p in self.profiles.items()]

    def profile(self,ident):
        if ident not in self.profiles:raise ValueError('Choose a saved setup profile.')
        return self.profiles[ident]

    def create(self,data):
        name=data.get('name','');ssid=data.get('ssid','');password=data.get('password','');width=data.get('width')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('Enter a display name (1–80 characters).')
        if not isinstance(ssid,str) or not 1<=len(ssid.encode())<=32 or any(ord(c)<32 for c in ssid):raise ValueError('Enter a Wi-Fi name of at most 32 bytes.')
        if password=='' and data.get('reuseWifi') is True:
            saved=next((p for p in reversed(list(self.profiles.values())) if p['ssid']==ssid),None)
            if not saved:raise ValueError('Enter this network’s Wi-Fi password.')
            password=saved['password']
        if not isinstance(password,str) or any(ord(c)<32 for c in password) or not (password=='' or 8<=len(password.encode())<=63 or re.fullmatch('[0-9a-fA-F]{64}',password)):
            raise ValueError('Use an 8–63 byte Wi-Fi password, a 64-digit hexadecimal key, or leave blank for an open network.')
        if type(width) is not int or width not in (64,128):raise ValueError('Choose 64 × 32 or 128 × 32.')
        if len(self.profiles)>=60:raise ValueError('Remove an unused setup profile before adding another display.')
        ident=uuid.uuid4().hex
        self.profiles[ident]={'name':name.strip(),'ssid':ssid,'password':password,'width':width,'key':uuid.uuid4().hex}
        try:self.save()
        except Exception:self.profiles.pop(ident,None);raise
        return ident

    def image(self,ident):
        p=self.profile(ident);body=bytearray(IMAGE.read_bytes())
        if len(body)!=0x800000 or hashlib.sha256(body).hexdigest()!=IMAGE_SHA:raise ValueError('The bundled first-install firmware failed verification.')
        # Check the actual image partition table before replacing NVS.
        import struct
        partition=next((struct.unpack('<HBBII16sI',body[a:a+32]) for a in range(0x8000,0x9000,32) if body[a:a+2]==b'\xaa\x50' and body[a+12:a+28].rstrip(b'\0')==b'nvs'),None)
        if not partition or partition[3:5]!=(0x9000,0x5000):raise ValueError('Unsupported first-install partition layout.')
        from esp_idf_nvs_partition_gen.nvs_partition_gen import generate
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            folder=Path(folder);os.chmod(folder,0o700)
            with (folder/'settings.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.writer(f);writer.writerow(['key','type','encoding','value'])
                writer.writerows([['pixora','namespace','',''],['ssid','data','string',p['ssid']],['pass','data','string',p['password']],['host','data','string',p['name']],['target','data','string','matrixportal-s3-'+str(p['width'])+'x32'],['pixora-local','namespace','',''],['key','data','string',p['key']],['paired','data','u8',1]])
            # Generator output contains temporary paths only; no credentials.
            generate(SimpleNamespace(input=str(folder/'settings.csv'),output=str(folder/'settings.bin'),outdir=str(folder),size='0x5000',version=2))
            nvs=(folder/'settings.bin').read_bytes()
        if len(nvs)!=0x5000:raise ValueError('Invalid generated Wi-Fi configuration.')
        body[0x9000:0xe000]=nvs
        return bytes(body)

    def ports(self):
        from serial.tools.list_ports import comports
        # Native ESP32-S3 USB and common USB/UART bridges. esptool verifies the
        # chip before any flash write; no arbitrary paths/commands are accepted.
        return [{'port':p.device,'label':p.description+' · '+p.device} for p in comports() if p.vid in (0x303a,0x239a,0x10c4,0x1a86,0x0403)]

    async def flash(self,ident,port):
        self.profile(ident)
        if any(not t.done() for t in self.tasks.values()):raise ValueError('An installation is already running. Keep its USB cable connected.')
        if port not in {p['port'] for p in self.ports()}:raise ValueError('Choose a currently connected USB controller.')
        self.jobs[ident]={'stage':'Preparing firmware','running':True}
        self.tasks[ident]=asyncio.create_task(self._flash(ident,port))

    async def _flash(self,ident,port):
        job=self.jobs[ident]
        try:
            body=await asyncio.to_thread(self.image,ident)
            with tempfile.TemporaryDirectory(dir=self.root) as folder:
                os.chmod(folder,0o700);image=Path(folder)/'install.bin';image.write_bytes(body)
                for verb,args in [('write-flash',['--no-progress','0x0',str(image)]),('verify-flash',['0x0',str(image)])]:
                    job['stage']='Installing firmware — keep USB connected' if verb=='write-flash' else 'Verifying installed firmware'
                    proc=await asyncio.create_subprocess_exec(sys.executable,'-m','esptool','--chip','esp32s3','--port',port,'--baud','460800',verb,*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
                    try:output=await asyncio.wait_for(proc.communicate(),360)
                    except asyncio.TimeoutError:
                        proc.kill();await proc.wait();raise ValueError('USB installation timed out. Check the controller before trying again.')
                    if proc.returncode:raise ValueError('USB installation could not be verified. Check the cable and BOOT/RESET buttons before trying again. It was not retried.')
            job.update(stage='Firmware verified. Waiting for the Wi-Fi address…',verified=True)
            host=await asyncio.to_thread(self.read_ip,port)
            if host:job['host']=host
            job['stage']='Firmware verified. Finish connecting below.' if host else 'Firmware verified. Enter the display’s IP address from your router below to finish.'
        except Exception as exc:
            job.update(stage=str(exc) if isinstance(exc,ValueError) else 'Installation could not finish. Check USB and try again after checking the controller.',error=True)
        finally:job['running']=False

    @staticmethod
    def read_ip(port):
        import serial
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            try:
                with serial.Serial(port,115200,timeout=1) as monitor:
                    while time.monotonic()<deadline:
                        line=monitor.readline(1024).decode('utf-8',errors='replace')
                        match=re.search(r'(?:Wi-Fi connected: |IP=)([0-9.]+)',line)
                        if match:
                            try:
                                address=ipaddress.IPv4Address(match[1])
                                if address.is_private and not address.is_unspecified and not address.is_loopback:return str(address)
                            except ValueError:pass
            except (serial.SerialException,OSError):time.sleep(1)
        return None

    def register(self,app,attach):
        async def payload(request):
            data=await request.json()
            if not isinstance(data,dict):raise ValueError("Use valid setup fields.")
            return data
        async def listing(request):return web.json_response({'profiles':self.public(),'ports':self.ports(),'jobs':self.jobs},headers={'Cache-Control':'no-store'})
        async def create(request):
            data=await payload(request)
            if not isinstance(data,dict):raise ValueError('Use valid setup fields.')
            ident=self.create(data);return web.json_response({'id':ident,'profiles':self.public()})
        async def image(request):
            body=await asyncio.to_thread(self.image,request.match_info['ident'])
            return web.Response(body=body,content_type='application/octet-stream',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="pixora-first-install.bin"','X-Firmware-MD5':hashlib.md5(body).hexdigest()})
        async def flash(request):
            data=await payload(request)
            if data.get('confirmErase') is not True:raise ValueError('Confirm this is a first installation and existing display settings will be replaced.')
            await self.flash(request.match_info['ident'],data.get('port'));return web.json_response({'started':True})
        async def finish(request):
            data=await payload(request);return web.json_response(await attach(self.profile(request.match_info['ident']),data.get('host','')))
        async def delete(request):
            ident=request.match_info['ident']
            if ident in self.tasks and not self.tasks[ident].done():raise ValueError('Wait for the USB installation to finish.')
            self.profile(ident);self.profiles.pop(ident);self.save();return web.json_response({'profiles':self.public()})
        app.router.add_get('/api/setup',listing);app.router.add_post('/api/setup',create)
        app.router.add_post('/api/setup/{ident}/image',image);app.router.add_post('/api/setup/{ident}/flash',flash)
        app.router.add_post('/api/setup/{ident}/finish',finish);app.router.add_delete('/api/setup/{ident}',delete)
        async def close(app):
            # Do not deliberately cancel a flash mid-write during normal shutdown.
            await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        app.on_shutdown.append(close)
