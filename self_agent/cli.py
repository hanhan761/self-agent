import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
from .config import Config,private_root


def private_file(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(value,'utf-8');path.chmod(0o600)

def main():
    parser=argparse.ArgumentParser(prog='self-agent')
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--username',default='admin')
    user=sub.add_parser('create-user');user.add_argument('username');user.add_argument('--admin',action='store_true')
    serve=sub.add_parser('serve');serve.add_argument('--host');serve.add_argument('--port',type=int)
    connect=sub.add_parser('connect');connect.add_argument('--url',required=True);connect.add_argument('--token-file',required=True);connect.add_argument('--proxy',help='Explicit optional HTTP(S) network proxy')
    install=sub.add_parser('install-client');install.add_argument('--client',choices=['claude','codex'],required=True)
    setup_cmd=sub.add_parser('setup');setup_cmd.add_argument('--url',default='https://self-agent.matterswarm.com');setup_cmd.add_argument('--client',choices=['auto','codex','claude','both'],default='auto');setup_cmd.add_argument('--pair-code-stdin',action='store_true');setup_cmd.add_argument('--proxy');setup_cmd.add_argument('--local',action='store_true');setup_cmd.add_argument('--model-cache');setup_cmd.add_argument('--xjcode-home')
    for operation in ('status','repair','uninstall','stop-local','open'):
        local_cmd=sub.add_parser(operation);local_cmd.add_argument('--root')
    sub.add_parser('mcp')
    hook=sub.add_parser('hook');hook.add_argument('--client',choices=['claude','codex'],required=True)
    sub.add_parser('inventory-local')
    sub.add_parser('backup-local')
    verify=sub.add_parser('verify-local-backup');verify.add_argument('archive');verify.add_argument('--key-file',required=True)
    exp=sub.add_parser('export');exp.add_argument('file');exp.add_argument('--password-file',required=True)
    restore=sub.add_parser('restore');restore.add_argument('file');restore.add_argument('--password-file',required=True)
    import_cmd=sub.add_parser('import-recent');import_cmd.add_argument('--days',type=int,default=30);import_cmd.add_argument('--project-dir',default=os.getcwd())
    args=parser.parse_args()
    if args.command in ('init','create-user'):
        from .store import Store
        from .auth import Auth
        config=Config.load();config.prepare()
        store=Store(config.data_dir/'memory.sqlite3')
        try:
            password=secrets.token_urlsafe(20)
            uid=Auth(store).create_user(args.username,password,getattr(args,'admin',False) or args.command=='init')
            key=Auth(store).issue_key(uid,'initial-client')
            token_file=config.data_dir/(args.username+'.token')
            private_file(token_file,key)
            access=config.data_dir/(args.username+'.access.json')
            private_file(access,json.dumps({'username':args.username,'password':password,'token_file':str(token_file)},ensure_ascii=False,indent=2))
            print(json.dumps({'created':True,'access_file':str(access),'user_id':uid}))
        finally:store.close()
    elif args.command=='serve':
        import uvicorn
        from .server import create_app
        from .lock import ProcessLock
        config=Config.load()
        if args.host:config.host=args.host
        if args.port:config.port=args.port
        config.prepare()
        with ProcessLock(config.data_dir/'server.lock'):
            uvicorn.run(create_app(config),host=config.host,port=config.port,access_log=False,log_level='warning')
    elif args.command=='connect':
        from urllib.parse import urlparse
        import httpx
        parsed=urlparse(args.url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise ValueError('invalid_service_url')
        if args.proxy:
            proxy_url=urlparse(args.proxy)
            if proxy_url.scheme not in ('http','https') or not proxy_url.hostname or proxy_url.username or proxy_url.password:raise ValueError('invalid_proxy_url')
        token_file=Path(args.token_file).resolve()
        token=token_file.read_text('utf-8').strip()
        with httpx.Client(trust_env=False,follow_redirects=False,proxy=args.proxy) as client:
            response=client.get(args.url.rstrip('/')+'/api/me',headers={'Authorization':'Bearer '+token},timeout=10)
            response.raise_for_status()
        values={'url':args.url.rstrip('/'),'token_file':str(token_file)}
        if args.proxy:values['proxy']=args.proxy
        private_file(private_root()/'client.json',json.dumps(values))
        print(json.dumps({'connected':True,'username':response.json()['username']}))
    elif args.command=='setup':
        if args.local:
            from .local_runtime import setup_local
            result=setup_local(args.client,model_cache=args.model_cache,xjcode_home=args.xjcode_home)
        else:
            from .onboarding import setup
            result=setup(args.url,args.client,sys.stdin.readline().strip() if args.pair_code_stdin else None,args.proxy)
        print(json.dumps(result,ensure_ascii=False))
    elif args.command in ('status','repair','uninstall','stop-local','open'):
        from . import local_runtime
        operation='stop' if args.command=='stop-local' else 'open_ui' if args.command=='open' else args.command
        print(json.dumps(getattr(local_runtime,operation)(args.root),ensure_ascii=False))
    elif args.command=='install-client':
        from .install import install_client
        print(json.dumps(install_client(args.client),ensure_ascii=False))
    elif args.command=='mcp':
        from .mcp_server import main as mcp_main
        mcp_main()
    elif args.command=='hook':
        from .hooks import main as hook_main
        hook_main(args.client)
    elif args.command=='inventory-local':
        from .local_backup import inventory
        files=inventory()
        print(json.dumps({'files':len(files),'bytes':sum(p.stat().st_size for p in files.values())}))
    elif args.command=='backup-local':
        from .local_backup import backup_local,verify_local_backup
        result=backup_local()
        result['verification']=verify_local_backup(result['archive'],result['key_file'])
        print(json.dumps(result,ensure_ascii=False))
    elif args.command=='verify-local-backup':
        from .local_backup import verify_local_backup
        print(json.dumps(verify_local_backup(args.archive,args.key_file)))
    elif args.command in ('export','restore'):
        from .client import request
        from .archive import encrypt_backup,decrypt_backup
        password=Path(args.password_file).read_text('utf-8').strip()
        if args.command=='export':
            data=request('GET','/v1/export',timeout=60)
            destination=Path(args.file)
            if destination.exists():raise ValueError('backup_file_already_exists')
            destination.write_bytes(encrypt_backup(data,password));destination.chmod(0o600)
            print(json.dumps({'exported':True,'file':str(destination.resolve())}))
        else:
            data=decrypt_backup(Path(args.file).read_bytes(),password)
            print(json.dumps(request('POST','/v1/restore',body=data,timeout=60)))
    elif args.command=='import-recent':
        from .importer import import_recent
        print(json.dumps(import_recent(args.project_dir,args.days),ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'message':'操作未完成，请检查配置或服务状态。'}),file=sys.stderr)
        raise SystemExit(1)
