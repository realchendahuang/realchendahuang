# 给 AI Agent 的落地提示词：Neofetch 风格 GitHub Profile

> 直接整段复制给 Claude Code / Cursor / Codex / ZCode 等任意能跑 shell 和 git 的 agent。

---

## 任务

把我的 GitHub 个人主页做成 neofetch 风格：左边一棵 ASCII 字符画头像，右边一栏终端风格的个人信息与实时统计，整体是一张会自动每天更新的 SVG 图片，随系统深/浅色主题自动切换。

参考实现：https://github.com/DietrichGebert/DietrichGebert
我的账号：**<填你的 GitHub 用户名>**

## 最终产物

```
<用户名>/<用户名>/            ← 仓库名必须和用户名完全一致，GitHub 才会识别成 profile README
├── README.md                 仅 5 行 <picture> 标签，不含任何 markdown 文本
├── img/
│   ├── dark.svg              840×500，深色配色
│   └── light.svg             840×500，浅色配色（同内容，换调色板）
├── update_profile.py         纯标准库，无第三方依赖
├── tools/ascii_avatar.py     头像 → 字符画的可复现工具
└── .github/workflows/stats.yml
```

## 一、SVG 规格（严格照抄，这是视觉一致的关键）

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="840" height="500" viewBox="0 0 840 500"
     font-family="Consolas, Menlo, monospace" font-size="13px">
<rect x="0.5" y="0.5" width="839" height="499" rx="10" fill="{bg}" stroke="{border}"/>
```

- **ASCII 区**：`x=10`，行距 15px，整体垂直居中 —— `y_top = 40 + (500 - 40 - 行数*15) / 2`
- **信息区**：`x=390`，行距 21px，从 `y=45` 起
- **信息列宽 W=56 字符**，用 `.` 补空对齐：`dots = W - len(key) - len(value) - 3`
- 每行文字用 `<text xml:space="preserve">` + `<tspan fill="...">` 分段着色

调色板（照搬 GitHub 自身色值，才能和页面无缝）：

| token | 用途 | dark | light |
|---|---|---|---|
| bg | 背景 | `#0d1117` | `#ffffff` |
| border | 边框 | `#30363d` | `#d0d7de` |
| art | 字符画 | `#8b949e` | `#57606a` |
| h | 标题/用户名 | `#58a6ff` | `#0969da` |
| k | 键名 | `#ffa657` | `#953800` |
| v | 值 | `#c9d1d9` | `#24292f` |
| d | 补点/分隔 | `#484f58` | `#afb8c1` |
| g | 绿色（+行） | `#3fb950` | `#1a7f37` |
| r | 红色（-行） | `#f85149` | `#cf222e` |

信息区建议字段：`OS / Uptime / Host / Kernel / IDE`、`Languages.Programming / Languages.Real / Currently`、`─ Contact ─`（Email / Site / X）、`─ GitHub Stats ─`（Repos{Contributed} | Stars、Commits | Followers、Lines of Code）。

**不要编造用户的个人信息**（生日、爱好、公司）。缺的字段就问，或者干脆删掉那一行。

## 二、ASCII 头像生成

**别直接灰度映射**，绝大多数自拍会糊成一团。按下面的顺序做：

### 1. 抠背景（关键）

判据是「蓝色 且 够亮」，两个条件缺一不可：

```python
blue   = (b - r) > 12                        # 天空/海面偏蓝
lit    = lum > 90                            # 亮区
sky    = blue AND lit
bright = lum > 235                           # 白云/过曝
fg     = NOT (sky OR bright)                 # 人物
```

**为什么必须加 `lum > 90`**：黑头发和黑 T 恤的 RGB 都很低，蓝通道反而略高于红（例如 `rgb(22,26,37)` 的 `b-r = 15`），只判 `b-r` 会把整个人抠没，只剩一张脸浮着。这个坑一定会踩。

如果仍然有孤岛（右下角误判），用连通域取最大块再排除其余。

### 2. 灰度映射

```python
chars = '@%#*+=-:. '        # 暗 → 密，像铅笔素描
v = (gray / 255) ** 0.45    # gamma 抬暗部，否则整张图太淡
index = int(v * (len(chars) - 1) + 0.5)
```

用 `@%#*+=-:. `（暗=密）而不是 ` .:-=+*#%@`（亮=密）：人物若是深色主体，前者才不会让主体镂空。

### 3. 尺寸与裁剪框

字符在 13px 等宽字体下实际宽度约 **7.9px**，行高 15px。所以要视觉不变形：

```
裁剪框宽高比 = (列数 × 7.9) / (行数 × 15)
```

**列数上限 46**。超过就会压到 `x=390` 的信息栏上（50 列时实测会盖住 Email/Site 几行）。推荐 **45 列 × 23 行**，对应裁剪框比例约 `1.03`。

**裁完检查包围盒是否居中**：算出所有非空行的最左/最右列，中心应接近 `列数/2`。偏了就调 `x` 属性，不要重做 art。

### 4. 输出格式

去掉首尾空行，每行 `rstrip()`，写成 Python raw string 贴进 `ART = r"""..."""`，并加一条自检：

```python
assert max(len(l) for l in ART.strip("\n").split("\n")) <= 46
```

把这套算法留在 `tools/ascii_avatar.py` 里，方便以后换头像重跑。

## 三、数据抓取（GitHub GraphQL）

```graphql
query {
  user(login: "<用户名>") {
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC) {
      totalCount
      nodes { name stargazerCount isFork }
    }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {
      totalCount
    }
  }
}
```

- **Commits**：按年循环查 `contributionsCollection(from,to)`，累加 `totalCommitContributions + restrictedContributionsCount`
- **Lines of Code**：REST 的 `stats/contributors` 对 Actions token 永远返回 202，**必须走 GraphQL** 遍历每个仓库 `defaultBranchRef` 上 `author: {id: 用户ID}` 的 commit history，累加 `additions/deletions`。仓库多的话必须加并发（`ThreadPoolExecutor(max_workers=8)`）和重试（网络抖动会让个别仓库静默丢失，数字少一大截）
- **Repos 数**：用 REST `/users/<用户名>` 的 `public_repos`。GraphQL 的 `totalCount` 含私有仓库，会和主页显示的公开数对不上

### 口径必须统一（血泪）

`GITHUB_TOKEN`（Actions 自带）**看不到私有仓库**，PAT 才能。如果本地用 PAT 跑、CI 用 GITHUB_TOKEN 跑，每天数字会在两个量级之间来回跳。

做法：显式加 `privacy: PUBLIC`，除非用户配了 `ACCESS_TOKEN`：

```python
def repo_scope():
    return "" if os.environ.get("ACCESS_TOKEN") else ", privacy: PUBLIC"
```

想显示私有仓库的代码量，就在仓库 Secrets 里加 `ACCESS_TOKEN`（classic PAT，勾 `repo`），脚本自动切到全量口径。

## 四、Actions

```yaml
name: Update profile stats
on:
  schedule:
    - cron: "17 4 * * *"
  workflow_dispatch:
permissions:
  contents: write
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python update_profile.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ACCESS_TOKEN: ${{ secrets.ACCESS_TOKEN }}
      - run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --staged --quiet || git commit -m "chore: refresh profile stats"
          git push
```

还需要一步 API 设置，否则 push 会 403：

```bash
gh api -X PUT repos/<用户名>/<用户名>/actions/permissions/workflow \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=false
```

## 五、部署

1. `git init` → commit → `gh repo create <用户名>/<用户名> --public --source=. --push`
2. 打开仓库页，右侧若出现 **“is now a special repository / Share to Profile”**，**必须点一下那个按钮**，否则主页不会挂载 README（新版 GitHub 的行为，光有仓库不够）
3. `gh workflow run stats.yml` 手动触发一次，确认跑通
4. 打开 `https://github.com/<用户名>` 肉眼验收

## 六、已知坑清单

| 症状 | 原因 | 解法 |
|---|---|---|
| 头像只剩一张脸浮着 | 黑发/黑衣 `b-r > 12` 被当成蓝天抠掉 | 蓝色判据加 `lum > 90` |
| 改完 `ART` 主页没变化 | 只改了脚本没重新生成 SVG | **必须**先跑 `python3 update_profile.py` 再 commit |
| 换了内容线上还是旧的 | `github.com/.../raw/` 的 camo 缓存可达数小时 | 换文件名/路径（如 `img/dark.svg`），URL 变了缓存立即失效 |
| workflow 显示 "No workflows found" | 索引异常（`update.yml` 实测卡住） | 改个文件名（如 `stats.yml`）重新推 |
| 数字每天在两个量级跳 | 本地 PAT 与 CI 的 GITHUB_TOKEN 可见范围不同 | 统一 `privacy: PUBLIC` 口径 |
| 字符画压住右侧信息栏 | 超过 46 列 | 收窄列数，或左移 `x` |
| 头像不居中 | 包围盒中心 ≠ 列宽中心 | 算包围盒，调 `<text x>` |

## 七、验收

- [ ] `https://github.com/<用户名>` 顶部出现 README 面板，左边人形、右边信息栏
- [ ] 切系统深/浅色主题，两张 SVG 正确切换
- [ ] `gh run list` 显示最近一次 Action 成功，且 commit 了新的 SVG
- [ ] 页面上的 Stars / Commits / Followers 与 GitHub 实际数字一致
- [ ] 本地跑 `python3 update_profile.py` 与 CI 跑出的数字一致（口径没分裂）
