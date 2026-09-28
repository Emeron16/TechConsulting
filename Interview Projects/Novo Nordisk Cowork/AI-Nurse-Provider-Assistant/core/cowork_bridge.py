"""File queue implementing only the completion calls used by this prototype.
The active Cowork session reads jobs and supplies fresh outputs. No model API.
"""
from __future__ import annotations
import argparse,fcntl,json,os,re,secrets,time
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parent.parent
QUEUE=ROOT/'cowork-queue'

def setup():QUEUE.mkdir(exist_ok=True)
def save(p,value):
    tmp=p.with_name(p.name+'.'+secrets.token_hex(4)+'.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(p)
def lock():
    setup();f=open(QUEUE/'.lock','a');fcntl.flock(f,fcntl.LOCK_EX);return f
def session_status():
    try:s=json.loads((QUEUE/'session.json').read_text())
    except (FileNotFoundError,json.JSONDecodeError):s={}
    s['active']=s.get('state') not in (None,'stopped') and time.time()-s.get('at',0)<(300 if s.get('state')=='processing' else 65)
    return s
def heartbeat(state):save(QUEUE/'session.json',{'state':state,'at':time.time()})
def next_job(wait):
    setup();end=time.monotonic()+min(wait,45)
    while time.monotonic()<end:
        with lock():
            if (QUEUE/'STOP').exists():heartbeat('stopped');print('{"stop":true}');return
            heartbeat('waiting')
            for f in sorted(QUEUE.glob('*.job.json'),key=lambda f:f.stat().st_mtime):
                j=json.loads(f.read_text())
                if j['status']=='queued':
                    j.update(status='processing',started_at=time.time());save(f,j);heartbeat('processing');print(json.dumps(j));return
        time.sleep(1)
    print('{"idle_timeout":true}')
def validate_shape(value,schema,path='response'):
    # The two generated application schemas use this deliberately small subset.
    kind=schema.get('type')
    good={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'number':isinstance(value,(int,float)) and not isinstance(value,bool),'integer':isinstance(value,int) and not isinstance(value,bool),'boolean':isinstance(value,bool),'null':value is None}
    if kind and not good.get(kind,False):raise ValueError(path+': expected '+kind)
    if 'enum' in schema and value not in schema['enum']:raise ValueError(path+': invalid enum')
    if kind=='object':
        for key in schema.get('required',[]):
            if key not in value:raise ValueError(path+': missing '+key)
        for key,part in schema.get('properties',{}).items():
            if key in value:validate_shape(value[key],part,path+'.'+key)
    if kind=='array':
        for i,item in enumerate(value):validate_shape(item,schema['items'],path+'['+str(i)+']')
def complete(jid,output_file):
    if not re.fullmatch('[a-f0-9]{24}',jid):raise ValueError('Invalid job ID')
    with lock():
        f=QUEUE/(jid+'.job.json');j=json.loads(f.read_text())
        if j['status']!='processing':raise ValueError('Job is no longer processing')
        result=json.loads(Path(output_file).read_text())
        if j['format']=='text':
            if not isinstance(result.get('text'),str) or not result['text'].strip():raise ValueError('Expected nonempty text')
        else:
            validate_shape(result,j['schema'])
        save(QUEUE/(jid+'.result.json'),result)
        j.update(status='completed',finished_at=time.time());save(f,j);heartbeat('waiting')
    print('Validated response saved')
def fail(message):
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx(suppress_warning=True):
            st.error(message); st.stop()
    except ImportError:pass
    raise RuntimeError(message)
class CoworkClient:
    def __init__(self):
        self.chat=SimpleNamespace(completions=self)
        self.beta=SimpleNamespace(chat=SimpleNamespace(completions=self))
    def _request(self,messages,response_format=None):
        if not session_status()['active']:fail('Cowork is not listening. Start the full-app session in Cowork, then submit again.')
        setup();jid=secrets.token_hex(12);path=QUEUE/(jid+'.job.json')
        j={'job_id':jid,'status':'queued','created_at':time.time(),'synthetic_demo_only':True,'format':response_format.__name__ if response_format else 'text','schema':response_format.model_json_schema() if response_format else None,'messages':messages}
        save(path,j);end=time.monotonic()+240
        display=None
        try:
            import streamlit as st
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx(suppress_warning=True):display=st.empty()
        except ImportError:pass
        try:
            while time.monotonic()<end:
                with lock():
                    current=json.loads(path.read_text())
                    if current['status']=='completed':return json.loads((QUEUE/(jid+'.result.json')).read_text())
                    if current['status']=='failed':fail(current.get('error','Cowork could not complete this step'))
                if display:display.info('Cowork: '+('reviewing this step…' if current['status']=='processing' else 'waiting to process this step…'))
                time.sleep(1)
            with lock():
                current=json.loads(path.read_text())
                if current['status']=='completed':return json.loads((QUEUE/(jid+'.result.json')).read_text())
                current.update(status='failed',error='Cowork response timed out. Restart the demo session before retrying.');save(path,current)
            fail('Cowork response timed out. Restart the demo session before retrying.')
        finally:
            if display:display.empty()
    def parse(self,*,messages,response_format,**kwargs):
        result=response_format.model_validate(self._request(messages,response_format))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])
    def create(self,*,messages,**kwargs):
        result=self._request(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result['text']))])
def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('next');s.add_argument('--wait',type=int,default=45)
    s=sub.add_parser('complete');s.add_argument('job_id');s.add_argument('output_file')
    sub.add_parser('stop');sub.add_parser('start')
    a=p.parse_args();setup()
    if a.cmd=='next':next_job(a.wait)
    elif a.cmd=='complete':complete(a.job_id,a.output_file)
    elif a.cmd=='stop':heartbeat('stopped')
    elif a.cmd=='start':
        (QUEUE/'STOP').unlink(missing_ok=True);heartbeat('waiting');print('Session initialized')
if __name__=='__main__':main()
