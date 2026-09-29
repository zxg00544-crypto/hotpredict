# config_path 占位化修复计划（2026-09-29 打包遗留项）

> 来源：双版本打包终审遗留（parked）。用户指令：config_path 占位化修复。
> 现状取证：两 zip 内 `热点预判/config.example.yaml` 含真实机路径
> `config_path: C:\Users\Admin\.config\opencode\opencode.json`——该键不在
> `CONFIG_SECRET_KEYS` 6 密钥键集合内，`sanitize_yaml` 不替换，机路径原样入包。
> 同时 README / tests 等处可能也含该路径字面量，须全包扫描定案。

## 全局约束（与事故修复计划相同的红线，此处重申）

- 密钥红线：任何真实密钥值不得出现在报告/输出/commit（占位符与路径不含密钥，但扫描结论只报计数不报值）。
- 测试命令：`python -X utf8 -m unittest discover -s tests`，当前基线 **125 OK**。
- 中文/已有文件禁 edit 工具：read → 内存替换 → write（UTF-8 无 BOM）。
- commit 前缀 `热点预判:`，只 add 本任务文件；工作树 unrelated 改动禁碰。
- 禁止改测试断言/删测试凑绿；`tests/test_llm_client.py` 里的真实路径是**测试夹具**（功能依赖本机文件存在），不在本任务修复范围，禁止改动其行为。
- `打包/` 在 .gitignore 中，zip 不入 git（重打产物只落盘）。

## Task 1: make_package.py config_path 占位化 + 重打两包 + 报告同步

### 1.1 打包器修改（`tools/make_package.py`）

1. 新增机路径占位规则（独立于 `CONFIG_SECRET_KEYS`，不冒充密钥键）：
   - 建议结构：`MACHINE_PATH_KEYS = {"config_path": "opencode.json路径(仅本地取key用,新机器请改)"}`（措辞可调，但必须是 `<填写:...>` 形态，与既有占位风格一致）。
   - `sanitize_yaml` 对命中键同样走既有行块替换逻辑（键行+更深缩进续行），避免多行值泄漏的同类缺陷复现。
2. 占位后 `config.example.yaml` 中**不得再出现** `opencode.json` 路径字面量或 `C:\Users\` 前缀。
3. 不动 6 密钥键规则、不动 `sanitize_secrets_json`、不动清单/排除逻辑。

### 1.2 断言测试（`tests/test_make_package.py` 增补）

1. 生成（或直接调 sanitize 层）后断言：`config.example.yaml` 文本含 `config_path: <填写:` 且不含 `opencode.json` 实路径、不含 `C:\Users\`。
2. 断言原 6 密钥占位行为不变（既有测试保持原样通过）。
3. 全量 `python -X utf8 -m unittest discover -s tests`：**125 + 新增 ≥1 全绿**，输出无新增噪声。

### 1.3 全包扫描定案（在报告中列明，逐处给出处与处置）

对重打后的两个 zip 解压扫描（只报文件名+行内容形态，值不含密钥）：
- `热点预判/config.example.yaml`：应已占位（1.1 的验收）。
- 其它任何文件中的 `C:\Users\Admin\.config\opencode\opencode.json` 或裸 `opencode.json` 路径字面量：
  - README 类（`README-本地版.md`/`README-云端版.md`）：若是指引文字（"把 config_path 改成你的路径"）→ 记录为可接受；若含真实路径字面量 → 同步改为占位/通用表述。
  - `tests/test_llm_client.py`：真实路径=测试夹具 → **记录但不改**（全局约束）。
  - 其它文件：出现即在报告列出并给出改或不改的判断理由，不许静默漏报。

### 1.4 重打两包 + 验证

1. 重跑打包器生成两 zip（`python -X utf8 tools/make_package.py` 或既有调用方式，退出码 0、secret scan clean 计数如实）。
2. 独立复核（不得只信打包器自报）：
   - 两 zip 的 `config.example.yaml` 占位断言（含 `config_path: <填写:`、无实路径、无 6 密钥真实值——对级扫描沿用验收报告 §2 方法）；
   - 两 zip 清单核对：missing=[] forbidden=[]（沿用验收报告 §3 口径）；
   - 文件数/体积较上一版的差异如实记录。

### 1.5 验收报告同步（`docs/2026-09-29-打包验收报告.md`）

1. 追加新节 `## 7. 补充：config_path 占位化（2026-09-29）`：问题（遗留项原状+为何 6 键不含它）、修改（1.1 结构）、测试（新增用例名+全量计数）、全包扫描定案表（1.3）、重打复核证据（1.4 的数字，只报计数）。
2. 同步 §1 产物表的两 zip 文件数/大小为重打后的实际值（factual 刷新，保留 §7 说明前后差异）。
3. §4.2 的 `Ran 122 tests` 历史记录不改写（它是当时的如实记录），全量最新计数放 §7。

### 1.6 Commit

- add：`tools/make_package.py`、`tests/test_make_package.py`、`docs/2026-09-29-打包验收报告.md`、本计划文件 `docs/2026-09-29-config_path占位化修复-plan.md`（+1.3 若改了 README 一并）。
- commit 信息：`热点预判: config_path占位化(打包器+断言测试+重打两包+验收报告同步)`。
- zip 产物不进 git（gitignore 已含 `打包/`）。

### 本任务不做

- 不改 `tests/test_llm_client.py` 夹具行为、不动 `llm` 运行时逻辑、不碰 SCF/事故修复相关文件、不恢复本机计划任务。
