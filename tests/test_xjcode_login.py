"""Windows integration test of the actual protected login transport, with a fixture helper."""
import json,os,subprocess
from pathlib import Path
import pytest
from self_agent.xjcode_auth import login,identity,protect,unprotect

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI/named pipes')

HELPER=r'''
using System;using System.IO;using System.IO.Pipes;using System.Text;using System.Web.Script.Serialization;
class Fixture {
[STAThread] static void Main(string[] a) {
 string pipe=a[Array.IndexOf(a,"--pipe")+1],nonce=a[Array.IndexOf(a,"--nonce")+1];
 using(var p=new NamedPipeClientStream(".",pipe.Substring(pipe.LastIndexOf('\\')+1),PipeDirection.InOut)) {
 p.Connect(10000);
 var obj=new {nonce=NONCE,account_id="fixture-account",tenant_id="fixture-tenant",access_key="fixture-access",encrypted_secret="fixture-secret"};
 byte[] text=Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(obj));
 byte[] len=BitConverter.GetBytes(text.Length);p.Write(len,0,4);p.Write(text,0,text.Length);p.Flush();p.ReadByte();
 }
}
}'''

@pytest.mark.parametrize('valid',[True,False])
def test_login_pipe_and_nonce_preserve_credentials(tmp_path,valid):
    csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not csc.exists():pytest.skip('C# fixture compiler unavailable')
    source=tmp_path/'Fixture.cs';source.write_text(HELPER.replace('NONCE','nonce' if valid else '"wrong"'))
    exe=tmp_path/'Fixture.exe'
    compiled=subprocess.run([str(csc),'/nologo','/target:winexe','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(source)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert compiled.returncode==0,compiled.stdout.decode(errors='replace')
    home=tmp_path/'vault';home.mkdir()
    old=protect(json.dumps({'account_id':'previous-account','access_key':'previous-access','secret':'previous-secret'}).encode())
    (home/'credentials.dpapi').write_bytes(old)
    if valid:
        login(home,exe,timeout=15)
        assert identity(home)['account_id']=='fixture-account'
        assert b'fixture-secret' not in (home/'credentials.dpapi').read_bytes()
    else:
        with pytest.raises(RuntimeError):login(home,exe,timeout=15)
        assert (home/'credentials.dpapi').read_bytes()==old
