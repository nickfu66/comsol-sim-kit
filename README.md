# COMSOL Sim Kit

一个**物理中立、任务书驱动、判据先行**的 COMSOL 仿真工作框架。

本仓库只提供通用方法、运行核心、空白模板、维护工具和离线测试，不包含真实仿真任务、模型、结果或本机配置。

> **仅下载本项目不会自动得到某个物理任务的仿真结果。** 必须先填写任务书，并由你或 AI 按任务书实现 `model_common.py`，成功求解后才会生成结果。

## 一、能做什么

- 通过 mph + JPype 以进程内 standalone 方式启动 COMSOL，集中管理配置与状态目录。
- 用 API 注册表和 `create_checked` 防止把 GUI 显示名误当成 Java API 类型。
- 提供取值、网格/域/解检查、求解重试、加权平均、轴对称权重、日志、原子 JSON、完整时域索引和续跑指纹。
- 用 `quality_spec.json` 冻结任务书判据；用当前指纹、双模型哈希和完整 provenance 防止陈旧结果通过验收。
- 从唯一空白模板创建本地案例，分别保存每个工况的模型、日志、数据、图片和证据。
- 上传前检查公开边界、完整 Git 最终索引和实际文件内容，避免私人任务、配置、凭据或未知资产被误传。

## 二、不能做什么

- 不提供默认几何、材料、物理场、边界条件、工况或验收阈值。
- 不用历史任务结果充当新任务的正确性证据。
- 不分发 COMSOL 安装文件、许可证、官方 PDF、文档数据库或第三方受限制内容。
- 不把“脚本运行结束”当作“物理结果正确”，也不保证任何物理接口开箱即算。
- 不通过 GitHub 同步本地模型和结果；公共仓库只同步公共方法与模板。

## 三、首次下载与环境准备

推荐使用 Git，方便以后取得公共更新：

```powershell
git clone <你的 GitHub 仓库地址>
cd comsol-sim-kit
python -m pip install -r requirements.txt
```

环境要求：

- Python 3.11+。
- COMSOL 与相应许可证；当前启动配置以 Windows + COMSOL 6.3 为范本。
- 其他操作系统和 COMSOL 版本需先调整配置并做最小探针。

复制并修改本机配置：

```powershell
Copy-Item config/config.example.toml config/config.toml
```

`config/config.toml` 只存在本机，包含 COMSOL 路径、版本、build、核心数和状态目录。它被 `.gitignore` 排除，不上传。

先做不依赖 COMSOL 的验证：

```powershell
python -B -m unittest discover -s tests -v
python -B env/_smoke_csol_kit.py
```

再检查本机配置；可选做真机最小模型验证：

```powershell
python env/ctl/check.py preflight
python -B env/_smoke_csol_kit.py --comsol
```

`preflight` 只检查配置，不启动 COMSOL。真机冒烟现场创建最小几何和网格并验证保存/加载，不读取历史模型。

## 四、一次完整仿真的操作顺序

### 1. 创建本地空白案例

```powershell
python tools/new_case.py "任务名称"
```

在项目根目录生成 `SIM01_任务名称/`，编号自动递增。首次创建还会生成 `README_任务导航.local.md`，用于记录本地任务索引；它和所有 `SIMxx_*` 都不会上传。

正式案例只能创建在本项目根目录。不要把案例生成到外部目录，也不要把真实结果转存到 `templates/`。

### 2. 填写任务书与判据

在案例目录完成：

1. `任务书_待填写.md`：目标、几何、材料、物理场、边界、研究、工况、输出和判据来源。
2. `quality_spec.json`：每条判据填写 id、metric、op、value、unit、blocking、source、category，至少一条有效 `blocking=true`。
3. `02_过程代码/case_spec.py`：填写 RESET_PARAMS、CASES 和执行依赖清单。
4. `02_过程代码/model_common.py`：实现 `build_model`，先应用 RESET_PARAMS，再应用当前工况参数。

输出 ID 统一为 `<工况>.<探针ID>`，例如 `C0.K1`。数组探针必须在 `reducers` 中显式选择 max/min/mean/sum/first/last，不会默认取最大值。

### 3. 建模前冻结与检查

```powershell
python env/ctl/check.py gate --sim SIM01_任务名称 --freeze --emit
python env/ctl/check.py lint --sim SIM01_任务名称
```

`--freeze --emit` 只做结构校验和冻结，没有实测值时不冒充正式验收。冻结后修改实质判据会触发哈希不匹配。

### 4. 求解与自动聚合

```powershell
Set-Location SIM01_任务名称/02_过程代码
python -B -u run_cases.py
Set-Location ../..
```

driver 会：

- 顺序执行工况，每个进程只启动一个 COMSOL 客户端；
- 检查参数、运行环境、公共执行核心、案例脚本和双模型哈希；
- 按工况分别保存 `main_<case>.mph` 与 `solved_<case>.mph`；
- 核对实际 COMSOL 版本与配置声明；
- 只有所有声明工况都通过当前校验后，才生成 `values.json` 并更新 `results_manifest.json`。

缺少工况、运行中断、指纹过期或模型缺失都会使 provenance 不完整，不能通过正式 gate。

### 5. 正式验收与证据快照

```powershell
python env/ctl/check.py gate --sim SIM01_任务名称 --bundle --emit
python env/ctl/check.py env
```

正式 gate 要求：

- 判据来源有效、结构完整且已冻结；
- 实测值和阈值都是有限数；
- 所有声明工况当前指纹与双模型哈希有效；
- provenance 完整，且与当前冻结 spec 哈希一致；
- blocking 判据全部 PASS。

只有同时给出 `--bundle --emit` 才会把 spec、values、verdict 和 SHA256 清单写入本次案例的证据快照。

## 五、会不会有结果，结果放在哪里

只有完成上述物理建模并成功求解后才会有任务结果。框架本身不包含你的物理答案。

| 结果 | 本地位置 | 产生条件 |
|---|---|---|
| 求解前模型 | `SIMxx_任务/01_建模/main_<case>.mph` | 建模成功并保存 |
| 含解模型 | `SIMxx_任务/01_建模/solved_<case>.mph` | 求解成功并保存 |
| 运行日志 | `SIMxx_任务/02_过程代码/日志/run_<case>.log` | driver 执行工况 |
| 单工况原始结果 | `SIMxx_任务/03_结果/数据/工况_<case>.json` | 单工况完成 |
| 聚合实测值 | `SIMxx_任务/03_结果/数据/values.json` | 所有声明工况当前校验通过 |
| 模型与结果台账 | `SIMxx_任务/03_结果/数据/results_manifest.json` | 聚合成功 |
| 验收证据 | `SIMxx_任务/03_结果/数据/证据快照/<时间戳>/` | 执行 gate --bundle --emit |
| 图片 | `SIMxx_任务/03_结果/图片/` | 任务脚本实际执行图片导出 |

**图片不是自动产生的**：模板没有假装知道你的物理场和所需图形，需在任务后处理中实现导出。

**真实结果绝不能放入 `templates/`**。模板只允许空白结构、说明、空 manifest 和 `.gitkeep`；扫描器与发布路径校验会拒绝模板中的 `values.json`、`工况_*.json`、证据快照和真实图片。

这些结果只留在生成它们的电脑上，**不会随 GitHub 上传，也不会出现在另一台电脑的下载中**。另一台电脑下载到的是纯净框架，需要重新建模和求解。

## 六、三段开工话术

完整文本见 [开工指令.md](开工指令.md)，阶段职责如下：

1. **§1 只做仿真**：不得修改公共环境，只完成本地建模、求解、验收和结果整理；通用发现仅登记为案例内候选。
2. **§2 反向更新与整理**：筛选已验证、可复用、物理中立的改进，更新公共代码和文档并运行检查，**不上传**。
3. **§3 上传§2的公共改进**：检查 diff、公开扫描、publish dry-run，经维护者确认后才实际提交和推送。

## 七、目录与文件职责

| 路径 | 用途 |
|---|---|
| `env/` | 公共运行核心、API 守卫、通用函数、质量门禁和运行文档 |
| `templates/case/` | 唯一空白案例模板，所有新任务从这里生成 |
| `templates/README_任务导航.template.md` | 本地任务导航的空白范本 |
| `tools/new_case.py` | 创建顺序编号案例和本地导航，拒绝覆盖 |
| `tools/check_public.py` | 公开边界、敏感内容和模板产物检查 |
| `tools/publish.py` | 维护者 dry-run、完整索引检查、提交和推送 |
| `tests/` | 不依赖 COMSOL 的标准库 unittest 测试 |
| `config/config.example.toml` | 本机配置范本，不含私人配置 |
| `requirements.txt / requirements.lock` | 依赖与已验证组合记录 |
| `CHANGELOG.md` | 公共改进摘要，不记录本地任务 |

三层文档分工：

- 本 README：项目和使用流程。
- [env/_README_环境说明.md](env/_README_环境说明.md)：怎么运行、通用报错怎么解决。
- [env/HANDOVER_环境交接卡.md](env/HANDOVER_环境交接卡.md)：通用 COMSOL API 怎么写才正确。

公共环境只收录**已验证、可复用、物理中立**的内容，扩展门槛见 [能力契约与扩展登记](env/docs/能力契约与扩展登记.md)。

## 八、维护者如何上传公共更新

当前只有**维护者**可以更新公共仓库；其他人只可以下载、复制和按许可证使用，**不接受外部 Pull Request**。

每次只修改公共原文件，不制作重复的“区别文件”或版本副本。小幅改进直接提交即可，不要求每次发布 Release；变化摘要写入 [CHANGELOG.md](CHANGELOG.md)。

日常更新：

```powershell
python tools/check_public.py
python tools/publish.py                 # dry-run
python tools/publish.py --yes --message "说明本次公共改进"
```

`publish.py` 要求当前分支就是目标 `main`，只暂存公共白名单路径，并在 commit 前检查**完整最终索引**和实际 blob 内容。即使历史误跟踪过敏感文件，也会阻止继续发布；删除这些文件后才可以继续。

首次上传本地项目：

```powershell
git init -b main
git remote add origin <你的 GitHub 仓库地址>
python tools/publish.py --yes --message "首个公共纯净版本"
```

如果本机尚未配置 Git 身份，先设置 `git config user.name` 和 `git config user.email`。

## 九、另一台电脑如何获取公共更新

```powershell
cd comsol-sim-kit
git pull --ff-only
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -v
python env/ctl/check.py preflight
```

`config/config.toml`、`README_任务导航.local.md` 和 `SIMxx_*` 被忽略，正常 pull 不会覆盖它们。公共模板升级不会自动改写已有案例；需要时由维护者审查并手动迁移。

非维护者不需要运行 `publish.py`。

## 十、验证记录与许可证

维护者本机曾完成 Windows / COMSOL 6.3 build 290 最小 Block + FreeTet 验证：16,554 个网格单元，保存和重新加载成功，退出码 0。该记录只证明当前启动链和最小几何流程，不外推到其他平台、物理接口或具体任务结果。

[MIT](LICENSE)。COMSOL 是 COMSOL AB 的产品；本项目是独立的方法框架，不附带或替代 COMSOL 许可证。
