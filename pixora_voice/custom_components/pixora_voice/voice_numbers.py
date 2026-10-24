"""Small English numeric vocabulary shared by local request parsers."""
import re,math
ONES=dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),range(20)))
TENS=dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10)))
def number(text):
 text=str(text).strip().lower().replace('-',' ')
 try:
  value=float(text)
  return value if math.isfinite(value) else None
 except ValueError:pass
 parts=text.split()
 if parts==['one','hundred']:return 100
 if len(parts)==1:return ONES.get(parts[0],TENS.get(parts[0]))
 if len(parts)==2 and parts[0] in TENS and parts[1] in ONES and ONES[parts[1]]<10:return TENS[parts[0]]+ONES[parts[1]]
 return None
