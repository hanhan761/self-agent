"""Explicit native model pool, bounded cooldowns and payload-free durable status."""
import hashlib,json,time,re,math
from .spool import atomic_json

class ModelPool:
    def __init__(self,config):
        self.config=config
        self.enabled=config.xjtu_auto_switch
        if not isinstance(self.enabled,bool) or not isinstance(config.xjtu_backup_models,(list,tuple)):raise ValueError('invalid_native_model_pool')
        names=[config.xjtu_model,*(config.xjtu_backup_models if self.enabled else ())]
        if len(names)>5 or any(not isinstance(n,str) or not re.fullmatch(r'[\w.-]{1,128}',n) for n in names):
            raise ValueError('invalid_native_model_pool')
        self.names=list(dict.fromkeys(names))
        self.active=None;self.models={};self.events=[];self.scope=None;self.account_until=0
        self.path=config.data_dir/'model-health.json'

    def bind(self,credentials,endpoint):
        scope=hashlib.sha256(json.dumps([getattr(credentials,'account_id',''),getattr(credentials,'workspace_id',''),endpoint,self.names],ensure_ascii=False).encode()).hexdigest()
        if self.scope==scope:return
        self.scope=scope;self.models={};self.events=[];self.active=None;self.account_until=0
        if not self.enabled or not self.path.is_file():return
        try:
            if self.path.stat().st_size>65536:raise ValueError('oversized')
            value=json.loads(self.path.read_text('utf8'))
            if value.get('scope')!=scope:return
            self.models={n:{k:v for k,v in m.items() if k in ('until','failures','reason','last_success','last_validated','last_failure')}
                         for n,m in value.get('models',{}).items() if n in self.names and isinstance(m,dict)}
            for m in self.models.values():
                for key in ('until','last_success','last_validated','last_failure'):
                    if key in m and (not isinstance(m[key],(int,float)) or not math.isfinite(m[key]) or m[key]<0):raise ValueError('invalid_timestamp')
                if not isinstance(m.get('failures',0),int) or not 0<=m.get('failures',0)<=100:raise ValueError('invalid_failures')
                if m.get('reason','') not in ('','provider_request_failed','model_quality_rejected','account_unavailable','rate_limited'):raise ValueError('invalid_reason')
            self.active=value.get('active') if value.get('active') in self.names else None
            self.events=[{'at':e['at'],'from':e['from'],'to':e['to'],'reason':e['reason']} for e in value.get('events',[])[-10:]
                         if isinstance(e,dict) and e.get('from') in self.names and e.get('to') in self.names and e.get('reason') in ('model_not_granted','provider_request_failed','rate_limited','model_quality_rejected','preferred_recovered') and isinstance(e.get('at'),(float,int)) and math.isfinite(e['at']) and e['at']>=0]
            self.account_until=value.get('account_until',0)
            if not isinstance(self.account_until,(int,float)) or not math.isfinite(self.account_until) or self.account_until<0:raise ValueError('invalid_account_cooldown')
        except (ValueError,TypeError,KeyError,AttributeError,OSError):
            self.models={};self.events=[];self.active=None;self.account_until=0

    def save(self):
        if self.enabled and self.scope:
            atomic_json(self.path,{'scope':self.scope,'active':self.active,'models':self.models,'events':self.events[-10:],'account_until':self.account_until})

    def select(self,routes):
        now=time.time()
        if self.account_until>now:return None,'account_unavailable'
        available=[n for n in self.names if n in routes]
        choices=[n for n in available if not self.enabled or self.models.get(n,{}).get('until',0)<=now]
        if not choices:return None,'models_cooling_down' if available else 'model_not_granted'
        selected=choices[0]
        if self.active and self.active!=selected:
            reason='preferred_recovered' if selected==self.names[0] else self.models.get(self.active,{}).get('reason') or 'model_not_granted'
            self.events.append({'at':now,'from':self.active,'to':selected,'reason':reason});self.events=self.events[-10:]
        changed=self.active!=selected;self.active=selected
        if changed:self.save()
        return routes[selected],''

    def failure(self,model,reason='provider_request_failed',retry_after=0):
        if not self.enabled:return
        now=time.time();old=self.models.get(model,{});failures=min(100,old.get('failures',0)+1)
        self.models[model]={**old,'failures':failures,'reason':reason,'last_failure':now,'until':now+max(min(900,60*2**min(failures-1,4)),retry_after)}
        if reason=='account_unavailable':self.account_until=now+60
        self.save()

    def success(self,model,validated=False):
        old=self.models.get(model,{})
        # A late in-flight success must not cancel a newer cooldown.
        self.models[model]={**old,'last_success':time.time()}
        if validated:self.models[model]['last_validated']=time.time()
        if old.get('until',0)<=time.time() and (validated or old.get('reason')!='model_quality_rejected'):self.models[model].update(until=0,reason='',failures=0)
        self.save()

    def status(self,routes):
        now=time.time()
        return {'auto_switch':self.enabled,'preferred_model':self.names[0],'active_model':self.active,
                'models':[{'name':n,'granted':n in routes,'cooldown_until':self.models.get(n,{}).get('until',0),
                           'reason':self.models.get(n,{}).get('reason',''),'last_success':self.models.get(n,{}).get('last_success'),
                           'last_validated':self.models.get(n,{}).get('last_validated'),'last_failure':self.models.get(n,{}).get('last_failure')} for n in self.names],
                'switches':list(self.events[-10:])}
