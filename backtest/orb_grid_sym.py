"""ORB grid backtest for one NSE stock. EDUCATIONAL ONLY: not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 backtest/orb_grid_sym.py POWERGRID [--out DIR]

Tests 10,240 opening-range-breakout settings on Yahoo 5-minute data (last ~60 days),
first 67% of days = train, last 33% = test. Prints JSON: how many settings were positive
in train, how many held up in test ("robust"), the most stable one (ranked by the smaller
of train/test average), and what that setting would have done today.

It also checks data gaps: Yahoo's free 5-minute charts sometimes drop bars (seen on
2026-11-04: 15:15-15:25 missing). "data_gaps" lists the missing slots of the last day,
and days with too many gaps are left out of the test. A missing bar can hide a stop
or a target touch, so check the chart before you trust a result.

Caveats: in-sample tuning over many settings overfits; few trades; one stock; ~3 months;
0.05% cost per trade, no slippage model. A positive backtest is not a promise.
"""
import argparse
import json,itertools,datetime as dt,statistics as st,sys
IST=dt.timezone(dt.timedelta(hours=5,minutes=30))
def load(f):
    r=json.load(open(f))['chart']['result'][0];q=r['indicators']['quote'][0]
    out=[]
    for i,t in enumerate(r['timestamp']):
        if None in (q['open'][i],q['high'][i],q['low'][i],q['close'][i]): continue
        out.append((dt.datetime.fromtimestamp(t,IST),q['open'][i],q['high'][i],q['low'][i],q['close'][i],q['volume'][i] or 0))
    return out
import urllib.request,os
ap=argparse.ArgumentParser(description='ORB grid backtest (educational)')
ap.add_argument('symbol');ap.add_argument('--out',default='backtest_out',help='folder for the full results JSON')
ap.add_argument('--max-gaps',type=int,default=3,help='days missing more 5-min bars than this are skipped')
A=ap.parse_args();SYM=A.symbol.upper();os.makedirs(A.out,exist_ok=True)
def fetch(rng,iv):
    f=os.path.join(A.out,f'{SYM}_{rng}_{iv}.json')
    req=urllib.request.Request(f'https://query2.finance.yahoo.com/v8/finance/chart/{SYM}.NS?range={rng}&interval={iv}',headers={'User-Agent':'Mozilla/5.0'})
    open(f,'wb').write(urllib.request.urlopen(req,timeout=30).read());return f
intr=load(fetch('60d','5m')); daily=load(fetch('2y','1d'))
days={}
for b in intr: days.setdefault(b[0].date(),[]).append(b)
SLOTS=[9*60+15+5*k for k in range(75)]  # 09:15 .. 15:25
def gaps(d):
    have={b[0].hour*60+b[0].minute for b in days[d]}
    return ['%02d:%02d'%divmod(m,60) for m in SLOTS if m not in have]
GAPS={d:gaps(d) for d in days}
dates=sorted(d for d in days if len(GAPS[d])<=A.max_gaps)
skipped=sorted(str(d) for d in days if len(GAPS[d])>A.max_gaps)
# daily context (prior day close based)
dc=[(b[0].date(),b[4]) for b in daily]
def rsi(cl,n=14):
    g=[max(cl[i]-cl[i-1],0) for i in range(1,len(cl))];l=[max(cl[i-1]-cl[i],0) for i in range(1,len(cl))]
    ag=sum(g[:n])/n;al=sum(l[:n])/n;out=[None]*(n+1)
    for i in range(n,len(g)):
        ag=(ag*(n-1)+g[i])/n;al=(al*(n-1)+l[i])/n;out.append(100-100/(1+ag/al) if al else 100)
    return out
cls=[c for _,c in dc];R=rsi(cls)
ctx={}
for i,(d,c) in enumerate(dc):
    if i<20: continue
    ctx[d]=(R[i],c,sum(cls[i-19:i+1])/20)
def prev_ctx(d):
    ks=[k for k in ctx if k<d]; return ctx[max(ks)] if ks else None
pc={d:prev_ctx(d) for d in dates}
def hm(t):return t.hour*60+t.minute
grid=dict(orm=[5,10,15,30],dead=[10*60+30,11*60+30,13*60,14*60],stop=['orlow','ormid','p0.5','p1.0'],tgt=[1,1.5,2,3,'eod'],
          filt=['none','rsi50','sma20','rsi50_75'],side=['long','both'],vol=[0,1.5],buf=[0,0.001])
COST=0.0005
def run(p,ds):
    res=[]
    for d in ds:
        bars=days[d];o=9*60+15;orb=[b for b in bars if hm(b[0])<o+p['orm']]
        if not orb: continue
        hi=max(b[2] for b in orb);lo=min(b[3] for b in orb);mid=(hi+lo)/2
        c=pc[d]
        if c is None: continue
        r,cl,sma=c;f=p['filt']
        okL={'none':True,'rsi50':r>50,'sma20':cl>sma,'rsi50_75':50<r<75}[f]
        okS={'none':True,'rsi50':r<50,'sma20':cl<sma,'rsi50_75':25<r<50}[f]
        rest=[b for b in bars if hm(b[0])>=o+p['orm']]
        av=st.mean([b[5] for b in orb]) or 1
        pos=None
        for k,b in enumerate(rest):
            t=hm(b[0])
            if pos is None:
                if t>p['dead']:break
                vo=p['vol']==0 or b[5]>=p['vol']*av
                if okL and vo and b[4]>hi*(1+p['buf']):
                    e=b[4];s={'orlow':lo,'ormid':mid,'p0.5':e*0.995,'p1.0':e*0.99}[p['stop']]
                    if s>=e: break
                    pos=(1,e,s,None if p['tgt']=='eod' else e+(e-s)*p['tgt']);continue
                if p['side']=='both' and okS and vo and b[4]<lo*(1-p['buf']):
                    e=b[4];s={'orlow':hi,'ormid':mid,'p0.5':e*1.005,'p1.0':e*1.01}[p['stop']]
                    if s<=e: break
                    pos=(-1,e,s,None if p['tgt']=='eod' else e-(s-e)*p['tgt']);continue
            else:
                dr,e,s,tg=pos;x=None
                if dr==1:
                    if b[3]<=s:x=s
                    elif tg and b[2]>=tg:x=tg
                else:
                    if b[2]>=s:x=s
                    elif tg and b[3]<=tg:x=tg
                if x is None and t>=15*60+15:x=b[4]
                if x is not None: res.append(dr*(x-e)/e-COST);pos=None;break
        if pos: dr,e,s,tg=pos;res.append(dr*(rest[-1][4]-e)/e-COST)
    return res
def stats(r):
    if not r:return dict(n=0,exp=0,win=0,tot=0,pf=0,dd=0)
    w=[x for x in r if x>0];l=[-x for x in r if x<=0]
    eq=pk=dd=0
    for x in r: eq+=x;pk=max(pk,eq);dd=max(dd,pk-eq)
    return dict(n=len(r),exp=sum(r)/len(r)*100,win=len(w)/len(r)*100,tot=sum(r)*100,pf=(sum(w)/sum(l)) if l and sum(l)>0 else 99,dd=dd*100)
split=int(len(dates)*0.67);tr,te=dates[:split],dates[split:]
keys=list(grid);out=[]
for vals in itertools.product(*grid.values()):
    p=dict(zip(keys,vals));a=stats(run(p,tr));b=stats(run(p,te));out.append((p,a,b))
json.dump([[p,a,b] for p,a,b in out],open(os.path.join(A.out,f'{SYM.lower()}_orb_results.json'),'w'))
ok=[x for x in out if x[1]['n']>=10]
rob=[x for x in out if x[1]['n']>=10 and x[2]['n']>=5 and x[1]['exp']>0 and x[2]['exp']>0]
res=dict(symbol=SYM,combos=len(out),days=len(dates),first=str(dates[0]),last_date=str(dates[-1]),
 positive_train=sum(1 for x in ok if x[1]['exp']>0),eligible=len(ok),robust=len(rob),
 skipped_gap_days=skipped,data_gaps={'day':str(max(days)),'missing':GAPS[max(days)]},
 note='Educational only, not investment advice. Backtests overfit.')
if rob:
    p,a,b=sorted(rob,key=lambda x:min(x[1]['exp'],x[2]['exp']),reverse=True)[0]
    res.update(best=p,train=a,test=b)
    # today's levels for that setting
    d=max(days);bars=days[d];o=9*60+15;orb=[x for x in bars if hm(x[0])<o+p['orm']]
    hi=max(x[2] for x in orb);lo=min(x[3] for x in orb);mid=(hi+lo)/2
    sig=None
    c=pc.get(d) or prev_ctx(d);r,cl,sma=c;f=p['filt']
    okL={'none':True,'rsi50':r>50,'sma20':cl>sma,'rsi50_75':50<r<75}[f]
    okS={'none':True,'rsi50':r<50,'sma20':cl<sma,'rsi50_75':25<r<50}[f]
    av=st.mean([x[5] for x in orb]) or 1
    for x in bars:
        t=hm(x[0])
        if t<o+p['orm']:continue
        if t>p['dead']:break
        vo=p['vol']==0 or x[5]>=p['vol']*av
        if okL and vo and x[4]>hi*(1+p['buf']):
            e=x[4];s_={'orlow':lo,'ormid':mid,'p0.5':e*0.995,'p1.0':e*0.99}[p['stop']]
            sig=dict(side='LONG',time=str(x[0].time()),entry=round(e,2),stop=round(s_,2),target=None if p['tgt']=='eod' else round(e+(e-s_)*p['tgt'],2));break
        if p['side']=='both' and okS and vo and x[4]<lo*(1-p['buf']):
            e=x[4];s_={'orlow':hi,'ormid':mid,'p0.5':e*1.005,'p1.0':e*1.01}[p['stop']]
            sig=dict(side='SHORT',time=str(x[0].time()),entry=round(e,2),stop=round(s_,2),target=None if p['tgt']=='eod' else round(e-(s_-e)*p['tgt'],2));break
    res.update(today=str(d),or_high=round(hi,2),or_low=round(lo,2),last_price=round(bars[-1][4],2),last_time=str(bars[-1][0].time()),signal=sig)
if GAPS[max(days)]:
    res['warning']='last day is missing %d five-minute bars (%s): a stop or target may have been touched there; check the chart'%(len(GAPS[max(days)]),', '.join(GAPS[max(days)]))
print(json.dumps(res,default=str))
