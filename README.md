# deepseek-presence

用 DeepSeek 驱动的 QQ 陪伴机器人，给它搭「长期在场」的骨架：它有自己的作息、会写日记、会自己发说说、掉线了会自己爬起来，还有一个一键看它的窗口。

**presence = 在场**。目标是让它不像一个等你提问的工具，而像一个一直待在那儿的人：它会自己过日子，隔一阵主动找你，你不在的时候也在。

这里只有**壳**：没有角色设定、没有聊天记录、没有任何人的账号信息。人格、记忆、房子都是你自己填的。

模型默认走 DeepSeek（`deepseek-chat` / `deepseek-reasoner`），在 AstrBot 里配 key 即可；接口是 OpenAI 兼容的，换别家也能跑。

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

## 装之前要有

1. **Windows 10/11**
2. **Python 3.11+**，并建好虚拟环境：`python -m venv deps\venv`
3. **AstrBot 4.29.x**，装在 `deps\astrbot-home`，跑在 6185
4. **SnowLuma**（或 NapCat），装在 `deps\SnowLuma`，OneBot HTTP 开在 3000
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

## 需要的 AstrBot 插件（不在本仓库）

这些是别人写的，各自有 license，请自行安装：

| 插件 | 用途 | 必需 |
| --- | --- | --- |
| `astrbot_plugin_fish_memory` | 长期记忆 + 工具注入 + 忌语过滤 | 是 |
| `astrbot_plugin_virtual_activity` | 她的屋子、家具、活动 | 可选 |
| `astrbot_plugin_proactive_chat` | 主动消息 | 可选 |
| `astrbot_plugin_sugar_debounce` | 多图合并 | 可选 |
| 任意生图插件 | 画图工具 | 可选 |

`diary.py`、`qzone_*.py` 依赖 AstrBot 的数据库表结构（`personas`、`conversations`）和 OneBot 的 `get_qzone_msg_list` 等接口。换版本或换客户端时，先跑一遍看日志。

## 已知边界

- 强绑 AstrBot 4.29.x 的表结构和接口，跨大版本会坏
- Windows 专用：`powercfg` 防睡眠、vbs 隐藏启动、`robocopy` 都是 Windows 的
- 那几个插件之间的联动是「按约定」的，不是标准接口；换插件要改代码
- 机器人账号有风控风险，慢一点、少一点、别群发

## License

MIT
