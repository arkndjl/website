import numpy as np, collections, random
import prem as P
AV=[[20,0],[30,.4],[40,1.7],[50,3.7],[60,5.0],[65,6.3],[70,7.2],[75,8.1],[80,10.1]]
def av(fv):
    for (f0,a0),(f1,a1) in zip(AV,AV[1:]):
        if fv<=f1: return a0+(a1-a0)*max(0,fv-f0)/(f1-f0)
    return 10.1
L=P.live
ws=[r for r in L if r.get('sav') is not None]
savK=sum(av(r['fv']) for r in ws)/sum(r['sav'] for r in ws); print('savK',round(savK,3),'n sav',len(ws))
play=lambda r:.5+.5*min(1,(r.get('snaps') or 0)/250)
def worth(r,mode,w=.5):
    f=av(r['fv']); s=savK*max(0,r['sav']) if r.get('sav') is not None else f
    v={'fv':f,'sav':s,'max':max(f,s),'blend':w*f+(1-w)*s}[mode]
    return (v+.4)*play(r)
V=P.V
print('QBs valued',sum(1 for r in V if r['pos']=='QB'),'with sav',sum(1 for r in V if r['pos']=='QB' and r.get('sav') is not None))
for pos in ['QB','RB','WR','TE','OL','EDGE','DL','LB','CB','S','ALL']:
    S=[r for r in V if pos=='ALL' or r['pos']==pos]
    out=[]
    for mode in ('fv','sav','max','blend'):
        e=np.array([np.log(r['nil'])-np.log(worth(r,mode)) for r in S])
        if pos=='ALL':
            # remove position means
            g=collections.defaultdict(list)
            for r,x in zip(S,e): g[r['pos']].append(x)
            m={k:np.mean(v) for k,v in g.items()}; e=np.array([x-m[r['pos']] for r,x in zip(S,e)])
        out.append(f'{mode} sd {e.std():.3f}')
    c=np.corrcoef([np.log(r['nil']) for r in S],[r['fv'] for r in S])[0,1]; S2=[r for r in S if r.get('sav') is not None]
    c2=np.corrcoef([np.log(r['nil']) for r in S2],[r['sav'] for r in S2])[0,1] if len(S2)>3 else float('nan')
    print(f'{pos:5s} n {len(S):3d}  '+'  '.join(out)+f'  | r(logOn3,FV) {c:+.2f} r(logOn3,sav) {c2:+.2f}')
