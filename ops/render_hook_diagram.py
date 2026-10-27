"""Render the README Hook information-flow diagram as SVG and PNG.

Requires Pillow and local Microsoft YaHei / Arial fonts. No service or user data.
"""
from pathlib import Path
from html import escape
import re,math
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/assets'
W,H,S=1600,1120,2
PAPER='#f5f5f0';INK='#252b27';GREEN='#275d45';MUTED='#69776d';LINE='#dce5db';PALE='#eaf1e8'
FONTDIR=Path('C:/Windows/Fonts')
image=Image.new('RGB',(W*S,H*S),PAPER);draw=ImageDraw.Draw(image)
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
 '<title id="title">Self Agent 的 Hook 与记忆闭环</title>',
 '<desc id="desc">SessionStart 和 UserPromptSubmit 检索并注入相关记忆；Stop 将新增对话写入本地队列，后台异步提炼与比较后保存可追溯记忆，供下一次检索。</desc>',
 f'<rect width="{W}" height="{H}" fill="{PAPER}"/>']
fonts={}
def font(cjk,size,bold):
    key=(cjk,size,bold)
    if key not in fonts:
        name=('msyhbd.ttc' if bold else 'msyh.ttc') if cjk else ('arialbd.ttf' if bold else 'arial.ttf')
        fonts[key]=ImageFont.truetype(str(FONTDIR/name),round(size*S))
    return fonts[key]
def runs(text):
    return [(bool(ord(part[0])>127),part) for part in re.findall(r'[\x00-\x7f]+|[^\x00-\x7f]+',text)]
def width(text,size,bold=False):return sum(font(cjk,size,bold).getlength(part)/S for cjk,part in runs(text))
def text(x,y,value,size=26,color=INK,bold=False,maxw=None):
    while maxw and width(value,size,bold)>maxw and size>18:size-=1
    if maxw and width(value,size,bold)>maxw:raise ValueError('Text overflow: '+value)
    offset=0;spans=[]
    for cjk,part in runs(value):
        ft=font(cjk,size,bold)
        draw.text(((x+offset)*S,y*S),part,font=ft,fill=color,anchor='ls')
        spans.append(f'<tspan font-family="{escape("Microsoft YaHei" if cjk else "Arial")}">{escape(part)}</tspan>')
        offset+=ft.getlength(part)/S
    svg.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{700 if bold else 400}">'+''.join(spans)+'</text>')
def box(x,y,w,h,fill='#ffffff',stroke=LINE,radius=20):
    draw.rounded_rectangle((x*S,y*S,(x+w)*S,(y+h)*S),radius=radius*S,fill=fill,outline=stroke,width=2*S)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
def line(points,color=GREEN,dashed=False,arrow=True,thick=3):
    for a,b in zip(points,points[1:]):
        if dashed:
            dx=b[0]-a[0];dy=b[1]-a[1];length=math.hypot(dx,dy)
            for start in range(0,int(length),18):
                end=min(start+10,length)
                draw.line(((a[0]+dx*start/length)*S,(a[1]+dy*start/length)*S,(a[0]+dx*end/length)*S,(a[1]+dy*end/length)*S),fill=color,width=thick*S)
        else:draw.line([(a[0]*S,a[1]*S),(b[0]*S,b[1]*S)],fill=color,width=thick*S)
    svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{color}" stroke-width="{thick}" stroke-linecap="round" stroke-linejoin="round"'+(' stroke-dasharray="10 8"' if dashed else '')+'/>')
    if arrow:
        a,b=points[-2:];angle=math.atan2(b[1]-a[1],b[0]-a[0]);n=12
        triangle=[b,(b[0]-n*math.cos(angle-.5),b[1]-n*math.sin(angle-.5)),(b[0]-n*math.cos(angle+.5),b[1]-n*math.sin(angle+.5))]
        draw.polygon([(x*S,y*S) for x,y in triangle],fill=color)
        svg.append('<polygon points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in triangle)+f'" fill="{color}"/>')
def card(x,y,w,h,title,subtitle,fill=PALE,detail=None):
    box(x,y,w,h,fill)
    text(x+24,y+42,title,28,GREEN,True,maxw=w-48)
    text(x+24,y+80,subtitle,25,INK,maxw=w-48)
    if detail:text(x+24,y+119,detail,22,MUTED,maxw=w-48)

text(76,86,'Self Agent 的 Hook 与记忆闭环',48,GREEN,True)
text(76,134,'开始与提问时取用记忆，回复结束后沉淀信息',28,MUTED)
box(40,180,1520,370)
text(76,222,'取用记忆 · 在模型处理前',30,GREEN,True)
card(76,246,360,100,'01  会话开始 / 恢复','SessionStart')
card(76,416,360,100,'02  每次发送问题','UserPromptSubmit')
card(620,316,380,168,'本机知识库检索','个人记忆 + 当前项目',fill='#ffffff',detail='成熟检索底座 · 范围过滤')
card(1160,316,330,168,'补入模型上下文','本次问题 + 相关记忆',detail='Codex 继续处理任务')
line([(436,296),(530,296),(530,400)],arrow=False)
line([(436,466),(530,466),(530,400)],arrow=False)
line([(530,400),(620,400)])
line([(1000,400),(1160,400)])
text(1022,382,'历史参考',22,MUTED)
box(40,590,1520,390)
text(76,635,'沉淀记忆 · 本轮回复结束后',30,GREEN,True)
card(76,665,300,110,'03  本轮回复结束','Stop')
card(446,665,300,110,'新增对话入队','脱敏 · 本地可靠保存')
card(816,665,300,110,'保存原文并排队','本机后台异步处理',fill='#ffffff')
card(1186,665,300,110,'交晓智原生 API','提炼 · 比较 · 校验',fill='#ffffff')
line([(376,720),(446,720)])
line([(746,720),(816,720)])
line([(1116,720),(1186,720)])
card(816,835,670,112,'SQLite 记忆库 + 可重建检索索引','原文依据 · 适用范围 · 状态 · 版本',fill=PALE)
line([(1336,775),(1336,835)])
text(1095,814,'经校验的记忆',22,MUTED)
text(76,865,'后台整理规则',27,GREEN,True)
text(76,905,'同义合并 · 新偏好替代旧偏好',25,INK)
text(76,944,'临时不长期保存 · 存疑先待确认',25,INK)
# Updated durable records feed the next retrieval, rather than starting a new Hook.
line([(1486,891),(1530,891),(1530,275),(810,275),(810,316)],dashed=True,color='#6d9374')
text(1010,260,'更新后，供下一次检索',23,MUTED)
text(76,1034,'正常完整对话：新会话首轮通常 3 次 Hook，后续每轮通常 2 次。',27,GREEN,True,maxw=1460)
text(76,1077,'恢复 / 上下文压缩可能额外触发；后台提炼不算额外 Hook。需先在客户端信任启用。',23,MUTED,maxw=1460)
svg.append('</svg>')
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'self-agent-hooks.svg').write_text('\n'.join(svg)+'\n','utf8')
image.save(OUT/'self-agent-hooks.png',optimize=True)
print('Rendered docs/assets/self-agent-hooks.svg and self-agent-hooks.png')
