"""Reuse authorized XJCode DPAPI credentials in memory; never export plaintext keys."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
from .xjtu_top import Credentials


def unprotect(raw):
    if os.name!='nt':raise RuntimeError('windows_login_required')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    source=Blob(len(raw),buffer);dest=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    crypt.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype=wintypes.BOOL
    if not crypt.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(dest)):
        raise RuntimeError('xjcode_login_unavailable')
    try:return ctypes.string_at(dest.data,dest.size)
    finally:
        ctypes.memset(dest.data,0,dest.size)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        kernel.LocalFree(dest.data)


def identity(home):
    path=Path(home)/'credentials.dpapi'
    if not path.is_file() or path.stat().st_size>16384:raise RuntimeError('xjcode_login_required')
    value=json.loads(unprotect(path.read_bytes()))
    if not all(isinstance(value.get(k),str) and value[k] for k in ('access_key','secret','account_id')):
        raise ValueError('invalid_xjcode_credentials')
    return value


def credentials(config):
    value=identity(config.xjcode_home)
    fp=hashlib.sha256(value['account_id'].encode()).hexdigest()[:12]
    if not config.xjtu_account_fingerprint or fp!=config.xjtu_account_fingerprint:
        raise RuntimeError('native_account_not_allowed')
    route=json.loads((config.data_dir/'native-route.json').read_text('utf-8'))
    return Credentials(value['access_key'],value['secret'],value['account_id'],route['workspace_id'],'discovered')


def discover(home,workspace=None,endpoint='http://ai.xjtu.edu.cn:30040/',model='qwen3.8-max'):
    """Read-only model discovery in the explicit existing/personal workspace. No key/workspace creation."""
    from .xjtu_top import TopClient
    value=identity(home)
    workspace=workspace or 'personal-'+value['account_id']
    creds=Credentials(value['access_key'],value['secret'],value['account_id'],workspace,'discovered')
    routes=TopClient(creds,url=endpoint,allow_campus_http=True).list_text_models()
    if model not in routes:raise RuntimeError('requested_model_not_granted')
    return {'workspace_id':workspace,'model':model,
            'account_fingerprint':hashlib.sha256(value['account_id'].encode()).hexdigest()[:12]}


def protect(raw):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw);source=Blob(len(raw),buffer);dest=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    crypt.CryptProtectData.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    if not crypt.CryptProtectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(dest)):
        raise RuntimeError('credential_protection_failed')
    try:return ctypes.string_at(dest.data,dest.size)
    finally:
        ctypes.memset(dest.data,0,dest.size)
        kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree(dest.data)


def decode_secret(value,tenant):
    import base64
    from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
    from cryptography.hazmat.primitives.padding import PKCS7
    if value.startswith('$aes-cfb$'):
        raw=base64.b64decode(value[9:],validate=True)
        decrypt=Cipher(algorithms.AES(hashlib.sha256(tenant.encode()).digest()),modes.CFB(raw[:16])).decryptor()
        return (decrypt.update(raw[16:])+decrypt.finalize()).decode('utf-8')
    if value.startswith('$aes-cbc$'):
        key=(tenant.encode('ascii')[:16]).ljust(16,b'0')
        decrypt=Cipher(algorithms.AES(key),modes.CBC(key)).decryptor()
        raw=decrypt.update(bytes.fromhex(value[9:]))+decrypt.finalize()
        unpad=PKCS7(128).unpadder()
        return (unpad.update(raw)+unpad.finalize()).decode('utf-8')
    if value.startswith('$'):raise ValueError('unsupported_platform_key_format')
    return value


def login(home,helper,timeout=300):
    """Reuse the XJCode WebView2 login helper over an owner-only named pipe."""
    if os.name!='nt':raise RuntimeError('windows_login_required')
    import re,subprocess,threading,time,uuid
    from ctypes import wintypes as W
    helper=Path(helper).resolve();home=Path(home).resolve()
    if not helper.is_file():raise RuntimeError('login_helper_missing')
    ensure_webview(helper)
    home.mkdir(parents=True,exist_ok=True)
    nonce=str(uuid.uuid4());pipe='\\\\.\\pipe\\xjcode-login-'+nonce
    # The same-user SID is used rather than a world-readable default pipe DACL.
    sid_text=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8',errors='replace')
    sid=re.search(r'S-1-5-[0-9-]+',sid_text)
    if not sid:raise RuntimeError('windows_identity_unavailable')
    adv=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    descriptor=ctypes.c_void_p()
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[W.LPCWSTR,W.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;;GA;;;'+sid.group()+')',1,ctypes.byref(descriptor),None):
        raise RuntimeError('pipe_security_failed')
    class Security(ctypes.Structure):
        _fields_=[('length',W.DWORD),('descriptor',ctypes.c_void_p),('inherit',W.BOOL)]
    security=Security(ctypes.sizeof(Security),descriptor,False)
    kernel.CreateNamedPipeW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,ctypes.POINTER(Security)]
    kernel.CreateNamedPipeW.restype=W.HANDLE
    kernel.ConnectNamedPipe.argtypes=[W.HANDLE,ctypes.c_void_p]
    kernel.ReadFile.argtypes=[W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p]
    kernel.WriteFile.argtypes=kernel.ReadFile.argtypes
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CancelIoEx.argtypes=[W.HANDLE,ctypes.c_void_p]
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateNamedPipeW(pipe,3|0x80000,0|8,1,32768,32768,0,ctypes.byref(security))
    kernel.LocalFree(descriptor)
    if handle==ctypes.c_void_p(-1).value:raise RuntimeError('login_pipe_failed')
    result={};finished=threading.Event()
    def receive():
        try:
            if not kernel.ConnectNamedPipe(handle,None) and ctypes.get_last_error()!=535:raise RuntimeError('pipe_connect_failed')
            def read(size):
                out=bytearray()
                while len(out)<size:
                    buffer=ctypes.create_string_buffer(size-len(out));count=W.DWORD()
                    if not kernel.ReadFile(handle,buffer,len(buffer),ctypes.byref(count),None) or not count.value:raise RuntimeError('pipe_read_failed')
                    out.extend(buffer.raw[:count.value])
                return bytes(out)
            length=int.from_bytes(read(4),'little')
            if not 1<=length<=16384:raise ValueError('invalid_login_payload')
            payload=json.loads(read(length))
            if payload.get('nonce')!=nonce:raise ValueError('invalid_login_nonce')
            value={'access_key':payload['access_key'],'secret':decode_secret(payload['encrypted_secret'],payload['tenant_id']),
                   'account_id':payload['account_id']}
            if not all(isinstance(v,str) and v for v in value.values()):raise ValueError('invalid_login_identity')
            path=home/'credentials.dpapi';temp=home/'credentials.dpapi.tmp'
            temp.write_bytes(protect(json.dumps(value).encode()));temp.replace(path)
            count=W.DWORD();kernel.WriteFile(handle,ctypes.c_char_p(b'1'),1,ctypes.byref(count),None)
            result['ok']=True
        except Exception as exc:result['error']=type(exc).__name__
        finally:finished.set()
    worker=threading.Thread(target=receive,daemon=True);worker.start()
    process=subprocess.Popen([str(helper),'--pipe',pipe,'--nonce',nonce,'--profile',str(home/'login-profile')],
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline=time.monotonic()+timeout
        while not finished.wait(0.2):
            if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('login_cancelled_or_expired')
        if not result.get('ok'):raise RuntimeError('login_failed')
    finally:
        kernel.CancelIoEx(handle,None);kernel.CloseHandle(handle)
        if process.poll() is None:
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.terminate()


def webview_available():
    import winreg
    suffix=r'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for hive,key in [(winreg.HKEY_CURRENT_USER,'Software\\'+suffix),
                     (winreg.HKEY_LOCAL_MACHINE,'SOFTWARE\\WOW6432Node\\'+suffix)]:
        try:
            with winreg.OpenKey(hive,key) as handle:value=winreg.QueryValueEx(handle,'pv')[0]
            if value and value!='0.0.0.0':return True
        except FileNotFoundError:pass
    return False


def ensure_webview(helper):
    if webview_available():return
    import subprocess
    bootstrap=Path(helper).parent/'MicrosoftEdgeWebview2Setup.exe'
    manifest=Path(helper).parent.parent/'manifest.json'
    if not bootstrap.is_file() or not manifest.is_file():raise RuntimeError('login_runtime_missing')
    entries=json.loads(manifest.read_text('utf-8'))['files']
    expected=next((e['sha256'] for e in entries if e['path']=='bin/MicrosoftEdgeWebview2Setup.exe'),None)
    if not expected or hashlib.sha256(bootstrap.read_bytes()).hexdigest()!=expected:raise RuntimeError('login_runtime_checksum_mismatch')
    result=subprocess.run([str(bootstrap),'/silent','/install'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not webview_available():raise RuntimeError('login_runtime_install_failed')
