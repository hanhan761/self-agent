"""Native rate receipt parser reused from the installed jiaoxiaozhi skill; no payload logging."""
import datetime as dt,email.utils,hashlib,json,math,time
WRAPPED_MESSAGE='internal error: model response failed: [SSE] resp status code expects 200 but got 429'
KNOWN_DIMENSIONS={'Throttling.RateQuota':'requests','LimitRequests':'requests','limit_requests':'requests','Throttling.AllocationQuota':'tokens','insufficient_quota':'tokens','Throttling.BurstRate':'burst','limit_burst_rate':'burst'}
def retry_after_seconds(value,now=None):
 if value is None:return 0.0
 now=time.time() if now is None else now
 try:seconds=float(value)
 except (ValueError,TypeError):
  try:
   stamp=email.utils.parsedate_to_datetime(str(value))
   if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=dt.timezone.utc)
   seconds=stamp.timestamp()-now
  except (ValueError,TypeError,OverflowError):return 0.0
 return max(0.0,seconds) if math.isfinite(seconds) else 0.0

def rate_receipt(http_status,body=b'',headers=None,now=None):
 if isinstance(body,str):body=body.encode('utf8')
 if not isinstance(body,bytes):raise TypeError('body must be bytes or text')
 headers=headers or {};code=None;wrapped=False
 try:
  value=json.loads(body);error=value.get('ResponseMetadata',{}).get('Error') or value.get('error',{})
  if isinstance(error,dict):
   code=error.get('Code',error.get('code'))
   wrapped=http_status==500 and code=='InternalError.Error' and error.get('Message',error.get('message'))==WRAPPED_MESSAGE
 except (ValueError,TypeError,AttributeError):pass
 limited=http_status==429 or wrapped
 retry_value=next((v for k,v in headers.items() if k.lower()=='retry-after'),None)
 return {'gateway_http_status':http_status,'limited':limited,'upstream_reported_status':429 if wrapped else None,
         'source':'ResponseMetadata.Error.Message' if wrapped else 'http_status' if http_status==429 else None,
         'dimension':KNOWN_DIMENSIONS.get(code,'unknown') if limited else None,'provider_code':code if code in KNOWN_DIMENSIONS or code=='InternalError.Error' else None,
         'retry_after_seconds':retry_after_seconds(retry_value,now),'body_sha256':hashlib.sha256(body).hexdigest(),'body_bytes':len(body)}
