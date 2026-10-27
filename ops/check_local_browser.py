"""Headless browser check of the optional local UI, using its real one-use launcher."""
import argparse,json,os,subprocess,sys,threading,time,webbrowser
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# Ensure every owned browser/driver child remains console-free on Windows.
original_popen=subprocess.Popen
if os.name=='nt':
    class HiddenPopen(original_popen):
        def __init__(self,*args,**kwargs):
            kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
            super().__init__(*args,**kwargs)
    subprocess.Popen=HiddenPopen
from self_agent.local_runtime import open_ui,stop,load_local,local_client,wait_service,wait_ready
root=Path(a.root)
client=json.loads((root/'local-client.json').read_text('utf-8'));wait_service(client);wait_ready(client)
ready=threading.Event();captured=[]
def intercept(uri):captured.append(uri);ready.set();return True
webbrowser.open=intercept
thread=threading.Thread(target=open_ui,args=(root,),daemon=True);thread.start()
assert ready.wait(30)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(captured[0]);page.wait_for_url(client['url']+'/',timeout=30000)
    page.locator('#app').wait_for(state='visible')
    assert page.locator('#scope').input_value()=='*'
    assert page.locator('#add-memory').is_visible()
    assert not page.locator('#remote-connect-panel').count()
    assert not page.locator('#inbox-page').count()
    assert not errors,errors
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(root/'browser-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(root/'browser-mobile.png'),full_page=True)
    if not page.evaluate('document.documentElement.scrollWidth<=innerWidth'):
        print(json.dumps(page.evaluate("Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,20).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right}))")))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    cookie=next(x for x in browser.contexts[0].cookies() if x['name']=='sa_session')
    assert cookie['httpOnly'] and cookie['sameSite']=='Strict'
    assert not (root/'ui-ticket.json').exists()
    result={'passed':True,'automatic_local_login':True,'no_remote_pairing_ui':True,'desktop_and_mobile_no_overflow':True,'page_errors':errors}
    (root/'browser-result.json').write_text(json.dumps(result,indent=2),'utf-8')
    print(json.dumps(result))
    browser.close()
thread.join(timeout=3)
