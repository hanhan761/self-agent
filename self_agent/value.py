"""Conservative admission checks for context-free acknowledgements, never manual notes."""
import re

def low_value_reason(content):
    text=re.sub(r'\s+','',content).strip('。.!！ ')
    text=re.sub(r'^(?:用户|我)?(?:希望|要求|需要|想要|请)','',text)
    if re.fullmatch(r'(?:默认|以后)?(?:采用|使用|选择|考虑|换用)?(?:一个|某个|某种)?(?:更|更加|较|更为)?(?:高级|好|好的|先进|优质|合适|最优)的?(?:方案|方法|策略|办法)',text):
        return 'vague'
    if re.fullmatch(r'(?:按|按照|沿用|保留|采用|继续)(?:这个|那个|当前|上述|前面|刚才|这套|那套|之前)的?(?:版本|方案|方式|做法|效果|配置)(?:即可|就行|执行|进行)?',text):
        return 'vague'
    if re.fullmatch(r'(?:用户|我)?(?:刚刚|刚|已经|已)?(?:重启了?|重新打开了?|打开了?|登录了?)(?:Codex|codex|ClaudeCode|浏览器|本文件夹|这个文件夹|该文件夹|页面|软件|窗口|交晓智)(?:了|成功)?',text):
        return 'one_off'
    if re.fullmatch(r'(?:生成和修改必要的配置文件|修改生产域名DNS|关闭或替换现有生产服务|每天记录一下|总数还是[0-9]+个|达到上限的[，,]?可以适当增加上限|失败的处理一下断点续算|没有实现[，,]?没有对齐的[，,]?你逐一实现一下)',text):
        return 'vague'
    if re.fullmatch(r'剩下[0-9]+个节点我们可以用',text):
        return 'one_off'
    return None

def automatic_rejection(source,item):
    return low_value_reason(item['content']) if source.get('kind') in ('conversation','history') else None

VALUE_GUIDANCE = '''
长期记忆必须能帮助未来助手作出具体不同的选择，且脱离当前聊天仍读得懂。有用户原话并不等于值得长期保留。
“采用更高级的方案”“按这个版本来”“试试看”“我重启了”这类只有程度、指代或即时操作而没有实际规则的内容不保存。
不要把临时权限、运行进度、瞬时剩余资源、当前截图的观察结果当成稳定事实。未知人物身份、数字或完成状态不能从助手回复补入。
只留下操作名称、数量或催办话语却缺少对象、理由、条件的条目不保存。分片缺少前置标题时，不得把“必须确认”列表中的单个操作转成已获授权的决定；缺少完整条件就省略。
具体的项目功能、技术约束、可复用做法、明确的交互偏好，即使只用于一个项目也有长期价值，保留其项目范围。
涉及“这张图/当前版本/之前方案”的指令，只有输入中给出实际要求且能独立表达时才提炼；不能只记录“保留这个方式”。
助手回复只能帮助理解用户的话，不能仅凭助手的完成汇报、推断或建议输出候选用户事实。
用户主动手写的记忆具有明确保留意图；自动提炼只输出经原话支持、具体可复用的独立信息点，宁可返回空列表。
'''
