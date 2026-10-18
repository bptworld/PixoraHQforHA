"""Local quiet-clock artwork and schedule boundaries; no provider requests."""
import io
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from PIL import Image,ImageDraw,ImageFont


def now(settings):return datetime.now(ZoneInfo(settings.get('timezone','UTC')))


def active(config,current):
    if not config.get('quiet'):return False
    start,end=config.get('quietStart','22:00'),config.get('quietEnd','06:00')
    if start==end:return False
    clock=current.strftime('%H:%M')
    return start<=clock<end if start<end else clock>=start or clock<end


def boundary(config,current):
    if not config.get('quiet') or config.get('quietStart','22:00')==config.get('quietEnd','06:00'):return None
    values=[]
    for day in range(3):
        for value in (config.get('quietStart','22:00'),config.get('quietEnd','06:00')):
            hour,minute=map(int,value.split(':'))
            target=(current+timedelta(days=day)).replace(hour=hour,minute=minute,second=0,microsecond=0)
            seconds=target.timestamp()-current.timestamp()
            if seconds>0:values.append(seconds)
    return min(values)


def clock(width,current,settings,assets):
    image=Image.new('RGB',(width,32));draw=ImageDraw.Draw(image)
    def line(value,top,bottom,size,color):
        for pixels in range(size,5,-1):
            try:face=ImageFont.truetype(str(assets/'fonts/PixelifySans-Bold.ttf'),pixels)
            except OSError:face=ImageFont.load_default(size=pixels)
            box=face.getbbox(value)
            if box[2]-box[0]<=width-4 and box[3]-box[1]<=bottom-top+1:break
        draw.text(((width-box[2]+box[0])//2-box[0],top+(bottom-top+1-box[3]+box[1])//2-box[1]),value,font=face,fill=color)
    twelve=str(settings.get('timeFormat','12'))!='24'
    value=current.strftime('%I:%M').lstrip('0') if twelve else current.strftime('%H:%M')
    line(value,1,21,26 if width==128 else 23,(190,205,255))
    footer=current.strftime('%a %b %d').upper()+(current.strftime(' %p') if twelve else '')
    line(footer,25,30,8,(125,145,185))
    output=io.BytesIO();image.save(output,'PNG');return output.getvalue()
