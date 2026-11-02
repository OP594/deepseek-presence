# deepseek-presence

用 DeepSeek 驱动的 QQ 陪伴机器人，给它搭「长期在场」的骨架：它有自己的作息、会写日记、会自己发说说、掉线了会自己爬起来，还有一个一键看它的窗口。

**presence = 在场**。目标是让它不像一个等你提问的工具，而像一个一直待在那儿的人：它会自己过日子，隔一阵主动找你，你不在的时候也在。

这里只有**壳**：没有角色设定、没有聊天记录、没有任何人的账号信息。人格、记忆、房子都是你自己填的。

模型默认走 DeepSeek：`deepseek-v4-pro` 当对话主模型，`deepseek-v4.1-flash` 干识图、压缩、写日记这类杂活——分工省钱，回复也稳。在 AstrBot 里配 key 即可；接口是 OpenAI 兼容的，换别家也能跑。

> Windows 专用。依赖 AstrBot 4.29.x。Linux 需要自己写 systemd 单元，脚本逻辑是通的。

## 它由什么组成

```
QQ 客户端（你登的号）
   └─ SnowLuma / NapCat（OneBot v11 实现，暴露 HTTP 3000、WS 3001）
        └─ AstrBot（对话主体，6185 / 6199）
             ├─ 人格、会话、长期记忆
             └─ 插件（见下）
scripts/  ← 这套东西
   ├─ keeper/keeper_loop   看护：谁死了补谁
   ├─ diary                她写日记
   ├─ qzone_daemon         自己发说说、改签名
   ├─ qzone_comments       盯说说下的评论，递给她
   ├─ webproxy             给 AstrBot 网页自动带登录态
   ├─ room_app / room_page 看她的屋子
   ├─ backup / backup_loop 备份
   ├─ watchdog             QQ 在线检查
   ├─ keepawake / wakeguard 防睡眠、唤醒后补一次检查
   └─ gui                  一个窗口看状态、对话、记忆、屋子
```

**AstrBot 和 SnowLuma 是这个项目的主体**，本仓库只是给它俩加的那层「长期在场」的壳（看护、日记、说说、评论、屋子、代理、备份、GUI）。它们不在仓库里，需要单独装。

## 装之前要有

1. **Windows 10/11**
2. **Python 3.11+**，并建好虚拟环境：`python -m venv deps\venv`
3. **[AstrBot](https://github.com/AstrBotDevs/AstrBot) 4.29.x**（AGPL-3.0），装在 `deps\astrbot-home`，跑在 6185
4. **[SnowLuma](https://github.com/SnowLuma/SnowLuma)**（或 NapCat），装在 `deps\SnowLuma`，OneBot HTTP 开在 3000
5. 一个能用的 LLM key（DeepSeek、智谱、方舟都行），填在 AstrBot 里

目录长这样：

```
<项目根>\
├─ config.json          ← 从 config.example.json 复制，改这个
├─ scripts\
├─ deps\
│   ├─ venv\
│   ├─ astrbot-home\
│   └─ SnowLuma\
├─ data\      （运行时自动建）
├─ logs\
└─ out\
```

## 装

```bat
copy config.example.json config.json
```

然后改 `config.json`：

| 字段 | 填什么 |
| --- | --- |
| `name` | 她叫什么，窗口标题和备份文件名用它 |
| `owner_qq` | 你的 QQ 号 |
| `self_qq` | 机器人的 QQ 号 |
| `umo` | 私聊会话 ID，形如 `snowluma:FriendMessage:123456` |
| `persona_id` | AstrBot 里的人格 id，一般 `default` |

把仓库里的五个插件放进 AstrBot 的插件目录：

```bat
xcopy /E /I plugins deps\astrbot-home\data\plugins
```

装依赖：

```bat
deps\venv\Scripts\pip install -r requirements.txt
```

开机自启（可选）：把 `scripts\start-all.vbs` 放进
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`。

## 用

```bat
scripts\start-gui.bat        打开窗口
scripts\start-all.bat        拉起 AstrBot + 全部后台（开机自启走这个）
```

命令行也行：

```bat
deps\venv\Scripts\python scripts\gui.py 状态
deps\venv\Scripts\python scripts\gui.py 对话 昨天
deps\venv\Scripts\python scripts\gui.py 家
```

## 人格

`persona.example.md` 是个模板，写清了她怎么说话、不能说什么、有哪些工具。把 `(名字)` 换掉，然后写进 AstrBot 的人格里（WebUI → 人格，或直接改数据库 `personas.system_prompt`）。

**忌语不要手写进人格。** `scripts/style_sync.py` 会从 `data/style_rules.json` 生成人格里「不要说的话」那一节，插件出口也读同一个文件——改一处，两边一起变。

## 来源与致谢

这套壳本身不发明轮子：机器人框架、QQ 接入、记忆、生图、作息、主动消息，绝大部分来自别人的开源项目。
**本仓库只包含 `scripts/` 下的那批脚本**，下面这些都不在仓库里，需要你自己装。

### 运行平台

| 项目 | 作用 | 出处 | 许可 |
| --- | --- | --- | --- |
| **AstrBot** | 对话主体：人格、会话、插件、WebUI | [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot) | AGPL-3.0 |
| **SnowLuma** | QQ NT 接入，提供 OneBot v11（HTTP / WS） | [SnowLuma/SnowLuma](https://github.com/SnowLuma/SnowLuma) | 自定义 EULA（见其仓库） |

SnowLuma 也可以换成 NapCat 等其它 OneBot v11 实现，脚本只依赖 OneBot 协议。

### AstrBot 插件（来自 GitHub，需自己装）

| 插件 | 作者 | 出处 | 许可 | 用途 |
| --- | --- | --- | --- | --- |
| `astrbot_plugin_proactive_chat` | DBJD-CR | [Pancakes-Labs/astrbot_plugin_proactive_chat](https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat) | AGPL-3.0 | 主动消息 |
| `astrbot_plugin_shoubanhua` | shskjw | [shskjw/astrbot_plugin_shoubanhua](https://github.com/shskjw/astrbot_plugin_shoubanhua) | AGPL-3.0 | 文生图 / 图生图 |
| `astrbot_plugin_virtual_activity` | Kasenoon | [Kasenoon/astrbot_plugin_virtual_activity](https://github.com/Kasenoon/astrbot_plugin_virtual_activity) | MIT | 她的屋子、家具、活动 |
| `astrbot_plugin_sugar_debounce` | SucRoseZT | [SucRoseZT/astrbot_plugin_sugar_debounce](https://github.com/SucRoseZT/astrbot_plugin_sugar_debounce) | MIT | 多图 / 图文合并成一条 |

### 随仓库附带的插件（`plugins/`）

这五个是自己写的，MIT，跟着仓库一起发布：

| 插件 | 作用 |
| --- | --- |
| `astrbot_plugin_fish_memory` | 长期记忆：提炼事实、写反思、回话前带上；忌语过滤（读 `data/style_rules.json`） |
| `astrbot_plugin_file_reader` | 收到文件自动读（PDF / Word / Excel / PPT / 网页 / 代码），长文件分段读完给结论 |
| `astrbot_plugin_recall_guard` | 撤回的消息不回复，也不留在上下文里 |
| `astrbot_plugin_room_nudge` | 隔一段时间提醒她动动屋子 |
| `astrbot_plugin_time_sense` | 让她知道距上次对话过了多久 |

它们假定目录结构是 `deps/astrbot-home/data/plugins/<插件>/`，项目根在往上五层。
换布局要改各自 `main.py` 顶部的 `ASTRBOT_DIR` / `QQ_DIR`。

### 本仓库的代码

`scripts/` 下的脚本（看护、日记、说说、评论、代理、备份、GUI、屋子渲染）是为这个项目写的，
依赖 Python 标准库 + `pillow` + `websocket-client`。
行为上参考了上面那些插件，但**没有拷贝它们的源代码**；唯一的例外见下面的“本地补丁”。

### 本地补丁声明

作者在自己的机器上对这些第三方插件做过改动，**改动不在本仓库**：

- `astrbot_plugin_virtual_activity`：新增了一个 `decorate_room` 工具，让人格里的工具列表能真的给她添家具
- `astrbot_plugin_shoubanhua`：注释掉了若干用不上的工具注册（PDF、批量处理、人设自拍等）

clone 下来后用原版插件，这些工具不存在，人格里对应的那句会调不到——按需删掉或自己加补丁。

另外 `plugins/` 里的是脱敏版：作者自用版本里有些行为（比如和本地小屋、说说的联动）被简化过，以仓库里这份为准。

### 许可提示

本仓库是 MIT，但**运行时要装的 AstrBot 和部分插件是 AGPL-3.0**。
如果你的使用方式构成“通过网络提供修改版服务”，AGPL 可能要求你公开自己的改动；
本仓库的脚本是独立进程、通过 HTTP / 数据库与 AstrBot 通信，作者的理解是不构成衍生作品，但这不是法律意见。

## 已知边界

- 强绑 AstrBot 4.29.x 的表结构和接口，跨大版本会坏
- Windows 专用：`powercfg` 防睡眠、vbs 隐藏启动、`robocopy` 都是 Windows 的
- 那几个插件之间的联动是「按约定」的，不是标准接口；换插件要改代码
- 机器人账号有风控风险，慢一点、少一点、别群发

## License

MIT
