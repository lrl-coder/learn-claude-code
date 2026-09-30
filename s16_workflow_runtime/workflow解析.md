这个 `s16 Workflow Runtime` 可以先把它理解成一句话：

> **它给 Agent 系统增加了一个“工作流执行器”：LLM 不再一步一步临时决定流程，而是只触发一次 `Workflow` 工具，然后由预先写好的 Python 工作流负责调用多个子 Agent、并行执行、验证结果、保存进度和断点续跑。** :chatgpt-content-reference{index="0"}

你现在看的代码比较长，但核心其实没那么复杂。

---

## 1. 它到底想解决什么问题？

在前面的普通 Agent Loop 里，大致是：

```text
用户
 ↓
LLM 思考
 ↓
调用工具 A
 ↓
工具结果回到 messages
 ↓
LLM 再思考
 ↓
调用工具 B
 ↓
结果再回 messages
 ↓
LLM 再决定下一步
...
```

也就是说：

> **每一步做什么，都是 LLM 根据上一轮结果临时决定的。**

README 也明确说了，s01～s15 基本都是这种模式：工具结果进入 `messages[]`，然后模型决定下一步。:chatgpt-content-reference{index="1"}

这种方式适合：

```text
先搜索
↓
根据搜索结果决定下一步
↓
如果发现 A，就查 A
如果发现 B，就查 B
```

因为流程本身是不确定的。

但有一些任务的流程其实**提前就知道**。

比如代码审查：

```text
检查 correctness
检查 security
检查 performance
检查 style

↓
每个发现都再验证一次

↓
过滤掉误报

↓
按严重程度排序
```

这个流程根本不需要让 LLM 每一步都重新决定。

所以 s16 的思路就是：

```text
不要把固定流程放在 LLM 的脑子里。

把流程直接写成 Python。
```

README 的标题其实已经点明了：

> **The Model Decides Each Step; a Script Decides the Orchestration**

即：

```text
具体一个步骤做什么 → LLM
整个步骤怎么组织 → Python 工作流脚本
```

---

# 2. 最重要的变化：增加了一个 `Workflow` 工具

s16 给原来的 Agent 增加了一个普通工具：

```python
WORKFLOW_TOOL = {
    "name": "Workflow",
    ...
}
```

它暴露给主 Agent 的参数其实非常少：

```text
Workflow(
    name,
    args,
    resume_from_run_id
)
```

也就是：

```python
{
    "name": "review-changes",
    "args": {
        "changes": "这里是一段代码"
    }
}
```

代码中这个工具定义就在这里。:chatgpt-content-reference{index="2"}

关键点是：

> **主 LLM 并不会生成一段 Python 工作流代码。**

它只能说：

```text
我要运行一个已经注册好的 workflow：
review-changes
```

然后运行时去：

```python
WORKFLOWS
```

里找。

代码里现在注册的是：

```python
WORKFLOWS = {
    "review-changes": (
        SAMPLE_META,
        sample_workflow
    )
}
```

:chatgpt-content-reference{index="3"}

所以整体关系是：

```text
主 Agent
   │
   │ tool_call
   ▼
Workflow(name="review-changes")
   │
   ▼
WORKFLOWS 注册表
   │
   ▼
sample_workflow()
   │
   ├── agent()
   ├── parallel()
   ├── pipeline()
   └── phase()
```

这就是整个 s16 最核心的架构。

---

# 3. `Workflow` 和普通 Tool 最大区别是什么？

普通 Tool 通常是：

```text
一次 tool_call
      ↓
执行一个动作
      ↓
返回一个结果
```

比如：

```text
read_file
search
bash
calculator
```

而这个 `Workflow` 是：

```text
一次 tool_call
      ↓
启动整个 Python workflow
      ↓
里面可能调用 10 个 Agent
      ↓
可能并行
      ↓
可能多阶段执行
      ↓
可能验证结果
      ↓
最终整体返回
```

所以 README 用了一句话：

> `"One tool_use runs an entire orchestration"` :chatgpt-content-reference{index="4"}

这里的 **orchestration** 就是“编排”。

因此：

```text
Workflow
不是“一个 Agent”

Workflow
是“管理多个 Agent 怎么执行的程序”
```

---

# 4. 用代码审查例子看完整流程

这里定义了一个示例 Workflow：

```python
async def sample_workflow(ctx, args):
```

它审查四个维度：

```python
DIMENSIONS = [
    "correctness",
    "security",
    "performance",
    "style"
]
```

:chatgpt-content-reference{index="5"}

完整逻辑可以画成：

```text
                         review-changes
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        correctness         security        performance        style
              │                │                │                │
              ▼                ▼                ▼                ▼
           audit            audit            audit            audit
              │                │                │                │
              ▼                ▼                ▼                ▼
          findings         findings         findings         findings
              │                │                │                │
              ▼                ▼                ▼                ▼
           verify           verify           verify           verify
              │                │                │                │
              └────────────────┼────────────────┘
                               ▼
                      confirmed findings
                               │
                               ▼
                        按 severity 排序
                               │
                               ▼
                            返回结果
```

---

# 5. 第一步：`pipeline(DIMENSIONS, audit, verify)`

这里是核心代码：

```python
results = await ctx.pipeline(
    DIMENSIONS,
    audit,
    verify
)
```

:chatgpt-content-reference{index="6"}

意思是：

对：

```python
["correctness", "security", "performance", "style"]
```

里面每一个元素，都跑：

```text
audit
  ↓
verify
```

所以：

```text
correctness:
    audit → verify

security:
    audit → verify

performance:
    audit → verify

style:
    audit → verify
```

但这里有一个非常重要的特点：

> **不同 item 之间可以并行，而且不需要等大家一起进入下一阶段。**

README 特别强调了：

```text
Item A 可以已经进入 stage 3，
Item B 可能还停在 stage 1。
```

:chatgpt-content-reference{index="7"}

比如：

```text
时间 →
correctness:  audit ── verify ── done
security:     audit ───────── verify ── done
performance:  audit ── verify ───── done
style:        audit ───────────── verify
```

这就是 `pipeline()`。

---

# 6. 那 `parallel()` 又是什么？

这两个最容易混淆。

## `pipeline`

表示：

```text
每一个 item 都有自己的处理流水线。
```

例如：

```text
A: audit → verify
B: audit → verify
C: audit → verify
```

A 不需要等 B 的 audit 完成，就能进入 verify。

---

## `parallel`

则是：

```text
同时启动一批任务
↓
必须等全部任务结束
↓
才能继续
```

代码里：

```python
return await asyncio.gather(
    *[thunk() for thunk in thunks]
)
```

:chatgpt-content-reference{index="8"}

README 把这个叫做：

> **Barrier**

也就是“同步屏障”。:chatgpt-content-reference{index="9"}

例如一个 security audit 找出 3 个问题：

```text
SQL injection
密码明文
权限检查缺失
```

那么 verify 阶段会：

```text
           ┌→ Agent：验证 SQL injection
parallel ──┼→ Agent：验证密码明文
           └→ Agent：验证权限检查缺失
```

三个验证 Agent 同时跑。

然后：

```text
三个都结束
   ↓
收集 verdicts
   ↓
只保留 isReal = true
```

代码就是：

```python
verdicts = await ctx.parallel([...])

confirmed = [
    f
    for f, v in zip(audited["findings"], verdicts)
    if v and v.get("isReal")
]
```

:chatgpt-content-reference{index="10"}

---

# 7. `agent()` 到底是什么？

这里的：

```python
ctx.agent(...)
```

你可以理解为：

> **“调用一次子 LLM”。**

例如：

```python
out = await ctx.agent(
    "Review this change context for security issues...",
    schema=FINDINGS_SCHEMA,
    label="audit:security"
)
```

其实背后最终调用的是：

```python
self.runner.run(...)
```

真实运行时：

```python
OpenAIAgentRunner
```

会调用模型 API：

```python
response = self.client.messages.create(...)
```

:chatgpt-content-reference{index="11"}

所以：

```text
ctx.agent()
     │
     ▼
OpenAIAgentRunner.run()
     │
     ▼
LLM API
     │
     ▼
返回子 Agent 的结果
```

因此，这套系统不是：

```text
Python 自己审查代码
```

而是：

```text
Python 决定：
谁什么时候调用、调用几个、先后关系如何

LLM 决定：
每个具体审查任务的答案是什么
```

这个区别非常重要。

---

# 8. 为什么还搞一个 `schema`？

因为如果你直接问 LLM：

```text
请找出安全问题
```

它可能返回：

```text
我发现以下几个潜在问题：

首先……
其次……
总的来说……
```

下一段 Python 就非常难处理。

所以这里规定：

```python
FINDINGS_SCHEMA
```

要求返回类似：

```json
{
  "findings": [
    {
      "title": "SQL Injection",
      "severity": "high"
    }
  ]
}
```

而 verify Agent 要返回：

```json
{
  "isReal": true,
  "reason": "..."
}
```

对应的 Schema 在代码里有明确定义。:chatgpt-content-reference{index="12"}

所以流程变成：

```text
LLM
 ↓
Structured Output
 ↓
JSON
 ↓
Schema 验证
 ↓
Python 可以直接访问字段
```

比如：

```python
out["findings"]
```

而不是从一大段自然语言里解析。

如果第一次输出不符合 Schema：

```text
第一次失败
   ↓
再请求一次：
Return valid JSON.
   ↓
再验证
   ↓
还是失败 → Workflow 报错
```

这个机制在 `ExecutionState.agent()` 里实现。:chatgpt-content-reference{index="13"}

---

# 9. `phase()` 是干什么的？

这个比较简单。

例如：

```python
ctx.phase("Review")
```

和：

```python
ctx.phase("Verify")
```

它本身不负责执行 Agent。

它只是：

> **告诉 runtime：现在工作流进行到了哪个阶段。**

因此 UI / 控制台可以显示：

```text
Review
 ├─ audit:correctness
 ├─ audit:security
 └─ ...

Verify
 ├─ verify:security:SQL injection
 └─ ...
```

代码中 `phase()` 最终发的是一个：

```python
workflow_phase
```

progress event。:chatgpt-content-reference{index="14"}

所以它主要是：

```text
可观察性 / Progress Tracking
```

不是核心执行逻辑。

---

# 10. 最值得理解的设计：Journal

这是 s16 里另一个非常重要的东西。

每次：

```python
ctx.agent(...)
```

执行完成之后，它都会把结果保存到：

```text
.runtime/
    xxx.journal.jsonl
```

里面。

例如：

```json
{"key": "agent-3829102345", "value": {...}}
{"key": "agent-7382938123", "value": {...}}
{"key": "agent-1092837465", "value": {...}}
```

代码就是：

```python
def record(self, key, value):
    self._f.write(
        json.dumps({"key": key, "value": value}) + "\n"
    )
    self._f.flush()
    self.cache[key] = value
```

:chatgpt-content-reference{index="15"}

它相当于：

```text
Agent 调用级别的 checkpoint
```

---

# 11. 为什么要 Journal？

假设这个 Workflow 有 20 次 LLM 调用。

已经运行：

```text
1 ✓
2 ✓
3 ✓
...
15 ✓

16 正在执行
```

突然：

```text
程序崩了
机器断电了
API 出错了
```

如果没有 journal：

```text
重新开始
↓
1~15 全部重新调用 LLM
```

浪费时间和 token。

有 journal 之后：

```text
重新运行 Workflow
↓
1 查 Journal → 有结果 → 直接复用
2 查 Journal → 有结果 → 直接复用
...
15 查 Journal → 有结果 → 直接复用
16 没结果 → 真正调用 LLM
```

这就是：

```text
resume
```

README 描述得很明确：resume 时会重新执行整个脚本，但没变化的 `agent()` 调用直接命中 journal cache。:chatgpt-content-reference{index="16"}

注意这一点很重要：

> **Resume 不是“从 Python 第 123 行继续跑”。**

而是：

```text
Python Workflow 从头执行
↓
走到 agent()
↓
计算它的 key
↓
已经做过？
    ↓ yes
直接读缓存
    ↓ no
真的调用模型
```

这和 LangGraph checkpoint 的思想有一点类似，但这里实现得非常轻量。

---

# 12. 它怎么知道“这是之前那个 Agent 调用”？

靠：

```python
key = self.journal.key(
    "agent",
    label,
    prompt,
    schema
)
```

它会根据：

```text
kind
label
prompt
schema
```

生成稳定 hash。:chatgpt-content-reference{index="17"}

例如：

```text
agent
+
audit:security
+
"Review this change context for security issues..."
+
FINDINGS_SCHEMA
```

生成：

```text
agent-1234567890
```

下一次 resume：

```text
输入完全一样
↓
hash 一样
↓
Journal 中发现已经存在
↓
直接复用
```

为什么不能简单用：

```text
第1个 Agent
第2个 Agent
第3个 Agent
```

作为 key？

因为有并发：

```text
A、B、C 同时执行
```

每次谁先完成是不确定的。

所以：

```text
completion #1
```

不能稳定对应某个 Agent。

README 专门强调了这个原因。:chatgpt-content-reference{index="18"}

---

# 13. `.runtime` 里保存了什么？

每次 Workflow 大概有：

```text
.runtime/

wf_xxx.json
wf_xxx.output.json
wf_xxx.journal.jsonl
wf_xxx.lock
```

README 对这几个文件也有说明。:chatgpt-content-reference{index="19"}

分别可以理解成：

```text
snapshot
    当前 workflow 的状态、参数、task 信息

output
    最终输出

journal
    已经完成的 agent() 调用

lock
    防止同一个 workflow run
    被两个进程同时 resume
```

所以整个恢复机制其实是：

```text
                run_id
                  │
     ┌────────────┼─────────────┐
     ▼            ▼             ▼
 snapshot      journal        output
 参数/状态     子调用结果       最终结果
```

---

# 14. `run_id` 和 `task_id` 是什么？

每次启动 workflow 都创建一个：

```text
run_id
```

类似：

```text
wf_review-changes_a93f28c319fdab12
```

它代表：

> **这一次具体的 Workflow 执行实例。**

然后：

```python
task_id = f"local_workflow_{run_id}"
```

相当于系统里的任务 ID。

所以：

```text
Workflow definition
review-changes
```

可以运行很多次：

```text
run 1
run 2
run 3
```

每次都有自己的：

```text
run_id
journal
snapshot
output
```

---

# 15. `WorkflowTool.call()` 是整个 runtime 的入口

这部分可以把它理解成总控函数。

核心步骤是：

```python
async def call(...):
    validate_meta(meta)
    check_permission(meta)

    创建 / 验证 run_id

    获取 workflow lock

    ↓

    _call_locked(...)
```

:chatgpt-content-reference{index="20"}

而 `_call_locked()` 做：

```text
① 判断是否 resume

② 打开 journal

③ 创建 task

④ 保存 snapshot

⑤ 创建 ExecutionState

⑥ 执行：
   result = await script_fn(ctx, args)

⑦ 保存 output

⑧ 更新 snapshot

⑨ 发 task_notification
```

对应代码就在这里。:chatgpt-content-reference{index="21"}

因此可以把它理解成：

```text
WorkflowTool
      │
      │ 创建运行环境
      ▼
ExecutionState
      │
      │ 提供 agent / parallel / pipeline
      ▼
sample_workflow
      │
      ▼
多个子 Agent
```

---

# 16. `ExecutionState` 是什么？

这个类其实非常关键。

```python
class ExecutionState:
```

你可以把它理解为：

> **Workflow 脚本的“运行上下文”。**

Workflow 本身不能直接随便干很多事情，而是通过：

```python
ctx.agent()
ctx.parallel()
ctx.pipeline()
ctx.phase()
ctx.log()
ctx.workflow()
```

操作 runtime。:chatgpt-content-reference{index="22"}

它内部拿着：

```text
task
journal
runner
budget
args
limits
```

所以架构实际上是：

```text
sample_workflow
      │
      │ ctx
      ▼
ExecutionState
      │
      ├── runner  → 调 LLM
      ├── journal → 保存结果
      ├── budget  → 控制 token
      ├── task    → 记录进度
      └── limits  → 控制并发/Agent 数量
```

也就是说，`ExecutionState` 是 Workflow 和底层 Runtime 之间的接口层。

---

# 17. 为什么还要 `Budget` 和 `ExecutionLimits`？

因为 Workflow 可以：

```text
pipeline
  ↓
parallel
  ↓
agent
  ↓
agent
  ↓
agent
...
```

如果写坏了，很容易疯狂调用模型。

所以它设置了：

```python
AGENT_CAP = 1000
CONCURRENCY = 8
```

:chatgpt-content-reference{index="23"}

意思是：

```text
一次 workflow 最多 1000 次 agent 调用
同时最多跑 8 个
```

此外还有：

```python
Budget
```

控制 token。

例如：

```python
args = {
    "budget": 10000
}
```

如果继续调用 Agent 会超过 10000：

```text
直接终止 workflow
```

代码中 `Budget.add()` 会检查这个限制。:chatgpt-content-reference{index="24"}

所以这属于：

```text
Runtime Guard
```

防止 Workflow 失控。

---

# 18. 它怎么接回原来的 s15 Agent Harness？

s16 并没有重新写一个 Agent 系统。

它是在原来的 s15 上：

```text
多加一个 Workflow 工具
```

代码里：

```python
base_assemble = host.assemble_tool_pool
```

然后包装成：

```python
def assemble_with_workflow():
    tools, handlers = base_assemble()

    tools.append(WORKFLOW_TOOL)
    handlers["Workflow"] = run_workflow_sync

    return tools, handlers
```

:chatgpt-content-reference{index="25"}

所以主 Agent 原来能看到：

```text
read_file
write_file
bash
...
```

现在再多看到：

```text
Workflow
```

因此：

```text
s15

User
 ↓
Agent loop
 ↓
Tool
 ↓
Agent loop
```

变成：

```text
s16

User
 ↓
Agent loop
 ↓
 ├── 普通 Tool
 │
 └── Workflow
        ↓
     Python orchestration
        ↓
     Agent × N
```

README 也明确说：

> s16 **不替代 main loop**，而是在 tool layer 暴露 `Workflow`。:chatgpt-content-reference{index="26"}

---

# 19. 一次真实请求大概怎么走？

假设用户说：

```text
帮我 review 这段代码。
```

整个系统可能这样：

```text
① 用户
   │
   ▼
② 主 Agent

   主 Agent 判断：
   这个任务适合 review-changes workflow

   │
   ▼
③ tool_call

Workflow({
    name: "review-changes",
    args: {
        changes: "..."
    }
})

   │
   ▼
④ WorkflowTool.call()

验证 metadata
检查权限
创建 run_id
创建 task
打开 journal

   │
   ▼
⑤ sample_workflow()

pipeline([
  correctness,
  security,
  performance,
  style
])

   │
   ├── audit correctness → LLM
   ├── audit security    → LLM
   ├── audit performance → LLM
   └── audit style       → LLM

   │
   ▼
⑥ 每个 finding 再 verify

   ├── verify finding 1 → LLM
   ├── verify finding 2 → LLM
   └── verify finding 3 → LLM

   │
   ▼
⑦ 过滤 false positive

isReal=false → 删除
isReal=true  → 保留

   │
   ▼
⑧ 按 severity 排序

high
medium
low

   │
   ▼
⑨ 保存

journal
snapshot
output

   │
   ▼
⑩ Workflow Tool 返回主 Agent

{
    "result": {
        "confirmed": [...]
    },
    "task": {...}
}

   │
   ▼
⑪ 主 Agent 给用户最终回答
```

这就是整个 s16。

---

# 20. 所以它和普通 Agent / Subagent / Workflow 到底是什么关系？

你可以用这个层级记：

```text
Main Agent
负责：
理解用户到底要干什么
决定是否使用 Workflow

        │
        ▼

Workflow
负责：
整个固定任务流程怎么编排

        │
        ▼

Subagent
负责：
其中某一个具体智能任务

        │
        ▼

LLM
负责：
真正生成该步骤的答案
```

例如：

```text
Main Agent：
“用户想做 code review”

Workflow：
“那我按照
 correctness / security / performance / style
 → audit
 → verify
 → merge
 → sort
 执行”

Subagent：
“我只负责检查 security”

LLM：
生成 security 检查结果
```

---

# 21. 为什么这种设计比“全交给 Agent”好？

不是说 Workflow 一定比普通 Agent 好，而是两者适合不同任务。

### 普通 Agent Loop

适合：

```text
下一步依赖上一阶段发现
流程无法事先确定
```

例如：

```text
帮我排查服务器为什么启动失败
```

可能：

```text
先看 log
↓
发现端口问题
↓
查端口
```

也可能：

```text
先看 log
↓
发现数据库问题
↓
检查数据库
```

这时候 LLM 自己决定下一步很好。

---

### Workflow

适合：

```text
流程已经明确
大量重复步骤
需要并发
需要稳定结构
需要断点续跑
```

例如：

```text
代码 Review
文档批量审核
100 个数据逐项分析
多个 Agent 投票
Research → Verify → Summarize
```

README 列出的三个主要需求就是：

```text
Parallelism
Stable result structure
Recoverability
```

:chatgpt-content-reference{index="27"}

---

# 22. 你可以把 s16 记成这张图

```text
                         用户请求
                            │
                            ▼
                       Main Agent
                            │
                   选择一个 Workflow
                            │
                            ▼
                  ┌───────────────────┐
                  │  Workflow Tool    │
                  └─────────┬─────────┘
                            │
                     查 WORKFLOWS
                            │
                            ▼
                  ┌───────────────────┐
                  │ Python Workflow   │
                  │                   │
                  │ pipeline          │
                  │ parallel          │
                  │ phase             │
                  │ agent             │
                  └─────────┬─────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
         Agent 1          Agent 2         Agent 3
            │               │               │
            └───────────────┼───────────────┘
                            │
                            ▼
                         Journal
                     保存每次 agent 结果
                            │
                            ▼
                       最终 Workflow
                          result
                            │
                            ▼
                       Main Agent
                            │
                            ▼
                           用户
```

所以这份代码最核心的并不是某一个函数，而是一个架构思想：

> **把“智能”和“编排”分离。**
>
> **LLM 负责每个需要判断、分析、生成的步骤；Python 负责整个任务的执行顺序、并行关系、数据传递、结构验证、预算控制和断点恢复。**

你尤其可以记住它和前面普通 Agent 的这组区别：

```text
普通 Agent：
LLM 决定“下一步干什么”。

s16 Workflow：
Python 已经决定“先做什么、后做什么、哪些并行”；
LLM 只负责完成其中需要智能的具体步骤。
```

这正是 README 对 s15 → s16 变化的总结：主循环没有被替换，只是新增了一个由脚本预先声明 orchestration、并且支持恢复的 Workflow runtime。:chatgpt-content-reference{index="28"}