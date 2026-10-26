import os,subprocess,sys,json
settings=os.environ.copy()
settings.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never',GCM_GUI_PROMPT='false')
settings['PATH']='C:/Program Files/Git/cmd;C:/Program Files/Git/mingw64/bin;'+settings.get('PATH','')
r=subprocess.run(['C:/Program Files/Git/cmd/git.exe','-c','http.proxy=http://127.0.0.1:7890',*sys.argv[1:]],env=settings,capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
print(json.dumps({'code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}))
raise SystemExit(r.returncode)
