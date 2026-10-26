"""Bounded conversation envelopes; never cut serialized role/evidence data."""
from datetime import datetime
import hashlib,json,math,time


def timestamp(value,default=None):
    if value is None:return default
    try:
        result=float(value) if isinstance(value,(int,float)) else datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError):raise ValueError('invalid_message_time') from None
    if not math.isfinite(result) or result<0 or result>time.time()+300:raise ValueError('invalid_message_time')
    return result


def batches(messages,limit=12000):
    if not isinstance(messages,list) or not messages or len(messages)>2000:raise ValueError('invalid_messages')
    batch=[]
    for number,message in enumerate(messages):
        if not isinstance(message,dict) or message.get('role') not in ('user','assistant') or not isinstance(message.get('content'),str):raise ValueError('invalid_message')
        content=message['content']
        if len(content)>120000:raise ValueError('message_too_large')
        identity=str(message.get('id') or hashlib.sha256((str(number)+json.dumps(message,sort_keys=True)).encode()).hexdigest())
        if len(identity)>160:identity=hashlib.sha256(identity.encode()).hexdigest()
        observed=timestamp(message.get('observed_at'))
        # Small fragments leave room for JSON escaping and metadata.
        for part,start in enumerate(range(0,len(content),1500)):
            row={'id':identity+':'+str(part),'role':message['role'],'content':content[start:start+1500],'observed_at':observed}
            proposed=batch+[row]
            if batch and len(json.dumps(proposed,ensure_ascii=False))>limit:
                yield batch;batch=[]
            batch.append(row)
    if batch:yield batch
