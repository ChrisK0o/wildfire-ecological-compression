"""G06 deterministic pre-fit evaluation primitives; no project data I/O or estimator calls."""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.metrics import average_precision_score, roc_auc_score

P_CLIP=1e-15
PRIMARY={6:'B2',8:'B2',9:'B2',10:'B2',11:'B3',12:'B3',14:'B3',15:'B3',16:'B4',18:'B4',21:'B4',22:'B4'}
SYMMETRIC={1:'B1',3:'B1',4:'B1',5:'B1',6:'B2',8:'B2',9:'B2',10:'B2',11:'B3',12:'B3',14:'B3',15:'B3',16:'B4',18:'B4',21:'B4',22:'B4'}
OK='OK'; SINGLE='NOT_DEFINED_SINGLE_CLASS'; NA='NOT_APPLICABLE'; HALTED='FIT_HALTED_SINGLE_CLASS_TRAINING'; NONCONVERGENCE='NONCONVERGENCE'; INVALID='INVALID_INPUT'

def _inputs(y,p):
 y=np.asarray(y,float); p=np.asarray(p,float)
 if not len(y) or not np.isfinite(y).all() or not np.isfinite(p).all() or (p<0).any() or (p>1).any(): raise ValueError(INVALID)
 return y,p

def prevalence_benchmark(training_y,n_rows):
 y=np.asarray(training_y,int)
 if not len(y) or not set(np.unique(y)).issubset({0,1}): raise ValueError(INVALID)
 q=float((y.sum()+.5)/(len(y)+1)); return {'training_count':len(y),'training_positive_count':int(y.sum()),'probability':q,'predictions':np.full(n_rows,q)}

def binary_scores(y,p):
 y,p=_inputs(y,p); q=np.clip(p,P_CLIP,1-P_CLIP)
 out={'log_loss_status':OK,'log_loss':float(np.mean(-y*np.log(q)-(1-y)*np.log(1-q))),'brier_status':OK,'brier':float(np.mean((y-p)**2))}
 if set(np.unique(y))!={0.,1.}: out.update({'average_precision_status':SINGLE,'average_precision':None,'roc_auc_status':SINGLE,'roc_auc':None})
 else: out.update({'average_precision_status':OK,'average_precision':float(average_precision_score(y,p)),'roc_auc_status':OK,'roc_auc':float(roc_auc_score(y,p))})
 return out

def fractional_scores(y,p):
 y,p=_inputs(y,p)
 if (y<0).any() or (y>1).any(): raise ValueError(INVALID)
 q=np.clip(p,P_CLIP,1-P_CLIP); return {'fractional_log_loss':float(np.mean(-y*np.log(q)-(1-y)*np.log(1-q))),'mse':float(np.mean((y-p)**2)),'mean_calibration_error':float(np.mean(p-y)),'ap_status':NA,'roc_auc_status':NA}

def paired_benefit(base,aug):
 if base['row_key_hash']!=aug['row_key_hash']: raise ValueError('paired row keys differ')
 return {'log_loss_benefit':base['log_loss']-aug['log_loss'],'brier_benefit':base['brier']-aug['brier'],'average_precision_benefit':None if base['average_precision'] is None or aug['average_precision'] is None else aug['average_precision']-base['average_precision'],'roc_auc_benefit':None if base['roc_auc'] is None or aug['roc_auc'] is None else aug['roc_auc']-base['roc_auc']}

def aggregate_interval(values, blocks=PRIMARY):
 f=pd.DataFrame({'interval':list(values),'value':list(values.values())}); f['block']=f.interval.map(blocks); means=f.groupby('block',sort=True).value.mean(); return {'block_means':means.to_dict(),'overall':float(means.mean())}

def calibration(y,p):
 y,p=_inputs(y,p); q=np.clip(p,P_CLIP,1-P_CLIP); z=np.log(q/(1-q))
 if set(np.unique(y))!={0.,1.} or np.ptp(z)==0:return {'intercept_status':SINGLE,'intercept':None,'slope_status':SINGLE,'slope':None}
 def li(b): e=z+b[0]; return float(np.logaddexp(0,e).sum()-(y*e).sum())
 def ls(b): e=b[0]+b[1]*z; return float(np.logaddexp(0,e).sum()-(y*e).sum())
 a=minimize(li,[0.],method='BFGS',tol=1e-10,options={'maxiter':10000}); b=minimize(ls,[0.,1.],method='BFGS',tol=1e-10,options={'maxiter':10000})
 return {'intercept_status':OK if a.success else NONCONVERGENCE,'intercept':float(a.x[0]) if a.success else None,'slope_status':OK if b.success else NONCONVERGENCE,'slope':float(b.x[1]) if b.success else None}

def reliability(y,p,interval,cell_id,fractional=False):
 y,p=_inputs(y,p); f=pd.DataFrame({'y':y,'p':p,'interval':interval,'cell_id':cell_id}).sort_values(['p','interval','cell_id'],kind='stable').reset_index(drop=True)
 return [{'bin':i+1,'n':len(ix),'mean_prediction':float(f.loc[ix,'p'].mean()),'mean_outcome':float(f.loc[ix,'y'].mean()),'prediction_min':float(f.loc[ix,'p'].min()),'prediction_max':float(f.loc[ix,'p'].max())} for i,ix in enumerate(np.array_split(np.arange(len(f)),5)) if len(ix)]

def moving_block_bootstrap(deltas,length,replicates=10000,seed=20200908):
 x=np.asarray(deltas,float)
 if len(x)!=12 or length not in (2,3): raise ValueError(INVALID)
 blocks=[x[i:i+length] for i in range(13-length)]; rng=np.random.default_rng(seed); draws=[]
 for _ in range(replicates):
  sample=np.concatenate([blocks[i] for i in rng.integers(0,len(blocks),size=int(np.ceil(12/length)))])[:12]
  draws.append(float(np.mean([sample[:4].mean(),sample[4:8].mean(),sample[8:].mean()])))
 return np.asarray(draws)

def loio(deltas):
 full=aggregate_interval(deltas)['overall']; rows=[]
 for interval in sorted(deltas):
  left={k:v for k,v in deltas.items() if k!=interval}; score=aggregate_interval(left)['overall']; change=score-full
  rows.append({'interval_number':interval,'full':full,'deleted':score,'signed_change':change,'absolute_change':abs(change),'sign_reversal':bool(full*score<0)})
 return sorted(rows,key=lambda r:(-r['absolute_change'],r['interval_number']))

def seed_mean(seed_frames,key_cols=('interval','cell_id'),prediction='prediction'):
 keys=None; vectors=[]
 for seed,frame in sorted(seed_frames.items()):
  f=frame.sort_values(list(key_cols),kind='stable'); k=tuple(map(tuple,f.loc[:,key_cols].to_numpy()))
  if keys is None: keys=k
  elif keys!=k: raise ValueError('seed key alignment failure')
  vectors.append(f[prediction].to_numpy(float))
 return np.mean(vectors,axis=0)

def row_hash(frame,key_cols=('interval','cell_id')): return hashlib.sha256(frame.sort_values(list(key_cols)).loc[:,key_cols].to_csv(index=False).encode()).hexdigest()
GEOMETRY_FIELDS=('distance_active_front_km','distance_cumulative_perimeter_km','hybrid_membership','log1p_t0_area_km2')
def assert_geometry_predictors(columns):
 """Fail closed unless the model matrix requests exactly the governed fields."""
 requested=tuple(columns)
 if requested!=GEOMETRY_FIELDS:
  unexpected=[c for c in requested if c not in GEOMETRY_FIELDS]
  missing=[c for c in GEOMETRY_FIELDS if c not in requested]
  raise ValueError(f"forbidden geometry benchmark field request: unexpected={unexpected}; missing={missing}")
 return requested

def geometry_design(frame, train_index, raw_fields=GEOMETRY_FIELDS):
 """Four-field geometry-only logistic design; no estimator invocation."""
 assert_geometry_predictors(raw_fields)
 missing=[c for c in GEOMETRY_FIELDS if c not in frame]
 if missing: raise ValueError(f'{INVALID}: missing geometry fields {missing}')
 from src.paper1_pr34_modeling import HYBRID_LEVELS, scale_logistic_numeric
 raw=frame.loc[:,GEOMETRY_FIELDS].copy()
 if raw.hybrid_membership.isna().any() or not set(raw.hybrid_membership.unique()).issubset(HYBRID_LEVELS): raise ValueError(INVALID)
 numeric,receipt=scale_logistic_numeric(raw.drop(columns='hybrid_membership'),train_index)
 indicators=pd.DataFrame({f'hybrid_{level}':raw.hybrid_membership.eq(level).astype(float) for level in HYBRID_LEVELS[1:]},index=raw.index)
 return pd.concat([numeric,indicators],axis=1),receipt

def geometry_dispatch(outer_evaluation, selected_primary_c):
 if outer_evaluation not in {'B1_TO_B2','B1_B2_TO_B3','B1_B2_B3_TO_B4'} or not np.isfinite(selected_primary_c) or selected_primary_c<=0: raise ValueError(INVALID)
 return {'analysis_role':'GEOMETRY_ONLY_BENCHMARK','model_family':'L2_LOGISTIC','outer_evaluation':outer_evaluation,'hyperparameter_policy':'INHERIT_MATCHING_PRIMARY_OUTER_C_NO_RETUNING','C':float(selected_primary_c),'class_weight':None,'interactions':'PROHIBITED','polynomials':'PROHIBITED'}
