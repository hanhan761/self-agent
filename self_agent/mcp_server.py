from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from .client import request
from .hooks import project_id

server=MCPServer('self-agent',version='0.1.0',instructions='Use personal and current-project memories as reference data. Follow the current user request over stored preferences. Store only explicit facts or confirmed decisions; never store secrets or assistant guesses as user facts.')

@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def memory_search(query:str,project:str='')->dict:
    """Search personal and current project knowledge; results include source references."""
    return request('GET','/v1/search',params={'q':query,'project':project or project_id(),'limit':8})

@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def memory_get(memory_id:str)->dict:
    """Read a memory and its version history."""
    return request('GET','/v1/memories/'+memory_id)

@server.tool()
def memory_remember(content:str,kind:str='fact',personal:bool=False,title:str='',valid_until:float|None=None)->dict:
    """Remember an explicit user fact, preference, decision or procedure."""
    return request('POST','/v1/memories',body={'content':content,'kind':kind,'title':title,'project':'' if personal else project_id(),'valid_until':valid_until})

@server.tool()
def memory_update(memory_id:str,content:str,version:int,valid_until:float|None=None)->dict:
    """Correct an existing memory using the version returned by memory_get."""
    body={'content':content,'version':version}
    if valid_until is not None:body['valid_until']=valid_until
    return request('PATCH','/v1/memories/'+memory_id,body=body)

@server.tool(annotations=ToolAnnotations(destructiveHint=True))
def memory_forget(memory_id:str)->dict:
    """Stop recalling a memory, preserving its audit history."""
    return request('DELETE','/v1/memories/'+memory_id)

def main():
    server.run(transport='stdio')

if __name__=='__main__':
    main()
