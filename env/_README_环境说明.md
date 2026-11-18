# env 运行环境说明

> 本文件回答“怎么跑起来”。通用 API 写法见 [HANDOVER_环境交接卡.md](HANDOVER_环境交接卡.md)，项目入口见 [../README.md](../README.md)。

## 更新纪律

只有出现并验证了**新的、可复用、物理中立**的运行经验时才修改本文件。具体任务的几何、材料、工况、阈值、结果和一次性猜想不得写入。

坑和运行经验使用永久 ID，只追加、不重新编号。某条失效时保留 ID 并标注适用版本与替代写法，避免其他文档引用漂移。

## 一、运行链路

`comsol_boot.start_client()` 使用：

```text
Python → mph.Client → JPype 进程内 JVM → COMSOL 内核
```

它不在每次脚本中重新实现后端发现和 JVM 参数，也不需要独立 COMSOL server 的端口或命名管道。每个 Python 进程只创建一个客户端；多工况由 `run_cases.py` 顺序启动子进程。

## 二、安装与配置

1. 安装 [../requirements.txt](../requirements.txt)。
2. 复制 `config/config.example.toml` 为 `config/config.toml`。
3. 按本机填写 COMSOL 根目录、版本、build、核心数和状态目录。
4. 运行：

```powershell
python env/ctl/check.py preflight
python env/_smoke_csol_kit.py
```

`preflight` 检查路径、JVM、状态目录可写性和 Python 模块，不启动 COMSOL。可选真机验证：

```powershell
python env/_smoke_csol_kit.py --comsol
```

真机验证只创建最小几何、网格并保存/加载，不读取历史模型，也不证明任何具体物理接口正确。

## 三、csol_kit 的公共能力

| 函数 | 用途 |
|---|---|
| `ev` / `ev_scalar` | 标量直接返回；数组必须显式选择 max/min/mean/sum/first/last，不默认取最大值 |
| `check_mesh` | 网格单元数必须达到下限，否则抛 CsolError |
| `check_domains` | 检查几何域数量精确值或下限 |
| `check_solution` | 检查探测表达式有限；非零检查由调用方显式选择 |
| `solve` | 先划网格并校验，再求解和有限次重试 |
| `area_avg` / `vol_avg` | 普通面积、体积平均 |
| `masked_avg` | 掩码区域平均，分母是掩码积分 |
| `axisym_area` / `axisym_vol` | 二维轴对称平均，自动加入 2πr |
| `mem_gb` | 查询可用物理内存 |
| `logger` | 同时写 UTF-8 日志和可选控制台回显 |
| `atomic_write_json` | 同目录临时文件加原子替换，避免截断 JSON |
| `enum_entries` | 用 MPh inner(dataset) 枚举完整时间条目；研究用显示名，超限明确报错 |
| `sha256_file` / `sha256_obj` | 分块文件哈希与规范化 JSON 哈希，避免大型模型内存峰值 |
| `case_fingerprint` | 工况参数、NumPy/平台/COMSOL 等运行环境和完整执行依赖的续跑指纹 |
| `result_is_current` | 检查状态、完整指纹及 main/solved 双模型路径与哈希 |
| `aggregate_case_results` | 校验所有声明工况及 spec 哈希，生成带完整 provenance 的 values.json 和 manifest |

公共库不包含几何尺寸、材料、工况、阈值或具体物理变量。校验失败抛异常，不返回容易被忽略的 False。

## 四、产物落位

每个案例统一使用 `02_过程代码/paths.py`：

| 产物 | 位置 |
|---|---|
| 求解前模型 | `01_建模/main_<case>.mph` |
| 求解后模型 | `01_建模/solved_<case>.mph` |
| 正式脚本 | `02_过程代码/` |
| 一次性探针 | `02_过程代码/探针/` |
| 日志与归档旧结果 | `02_过程代码/日志/` |
| 原始数值与证据快照 | `03_结果/数据/` |
| 图片 | `03_结果/图片/` |

公共 `env/` 不写运行产物。真实配置和 COMSOL 状态分别在被忽略的 `config/config.toml` 与 `.runtime/` 中。

## 五、通用问题速查

| ID | 现象 | 处理 |
|---|---|---|
| RUN-001 | GUI 显示名被当成 Java API 类型名 | 先查注册表和手册；常见正名包括 Sweep、Map、BndLayer。未知名称先探针，不归因于安装缺能力 |
| RUN-002 | 独立 server 在自动化环境中遇到管道、端口或状态目录问题 | 优先使用已封装的进程内 standalone；不要仅凭端口报错判断网络故障 |
| RUN-003 | COMSOL 尝试写默认用户目录而被拒绝 | 检查 prefs、recovery、tmp 和 user.home 是否统一定向到可写状态目录 |
| RUN-004 | 同一 Python 进程第二次创建客户端失败 | 每进程一个客户端；多模型复用并在结束后 remove，多工况使用独立子进程 |
| RUN-005 | 大模型求解时进程无 traceback 消失 | 先查可用内存和网格规模；长跑前先只运行 mesh，保留日志和原子结果 |
| RUN-006 | Windows 控制台中文乱码或编码异常 | 使用 UTF-8 输出和日志文件，不把控制台编码当作求解失败证据 |
| GEOM-001 | Polygon 建完没有实体域 | 检查 type 是否需要 solid，并用 check_domains 读回验证 |
| GEOM-002 | Java 选择接口出现重载歧义 | 对需要 Java int 的参数使用 JInt；同时确认实体维度 |
| GEOM-003 | 重建几何后选择、算子或变量失效 | 全链读回并重建失效节点；不要沿用旧对象引用 |
| GEOM-004 | 绝对容差在不同尺度模型上选不到实体 | 按模型尺度设置容差，并用数量、面积或体积读回验证选择 |
| MESH-001 | mesh.run 没有报错但单元数为零 | 每次 mesh.run 后调用 check_mesh，检查选择与尺寸设置 |
| MESH-002 | Sweep 厚向层数未生效 | Distribution 应作为 Sweep 子特征；读回类型、子特征和单元数 |
| MESH-003 | 直接加密导致单元数和耗时失控 | 先只运行 mesh 记录规模，再决定求解时间盒；耗时外推必须留余量 |
| NUM-001 | evaluate 返回数组，标量转换失败或被误取最大值 | 使用 ev；转标量必须显式给 reducer 和数据集/inner/outer 口径 |
| NUM-002 | 一次点采样拼接多个分量导致异常 | 每个分量单独求值；点采样失败与求解失败分开判断 |
| NUM-003 | 求解后新建的积分或极值算子无法识别 | 在 solve 前创建算子；若后建则重新求解并验证 |
| NUM-004 | 二维轴对称积分差一个 2π 因子 | 使用 axisym_area 或 axisym_vol；普通三维不要重复加权 |
| NUM-005 | 掩码平均被全域分母稀释 | 使用 masked_avg，分母必须是掩码自身的积分 |
| NUM-006 | 域极值随网格跳动 | 区分极值与平均口径；按任务书报告并做收敛验证，不擅自替换 |
| NUM-007 | 单位表达式结果静默减半、归零或量级异常 | 将长度和单位显式绑定到参数，使用解析量级和积分归一化交叉检查 |
| STUDY-001 | Time Dependent 的显示名不能创建研究 | 当前注册表使用 Transient；创建后读回研究类型 |
| STUDY-002 | 按 solver tag 前缀猜测节点，调用空转或取错解 | 枚举并读回节点类型；用非平凡探测值和实际解存储验证求解发生 |
| STUDY-003 | 时域输出时刻或步进设置不生效 | 输出时刻由 study step 的 tlist 控制；步进属性设置后读回确认 |
| SAVE-001 | 加载模型后发现没有解 | 区分求解前和求解后保存；只有求解后保存的模型才包含解数据集 |
| DATA-001 | 多段或多解存储取数总拿到第一段，或按 std1 tag 过滤为空 | model.datasets() 是显示名；用 enum_entries 的 MPh inner(dataset) 完整索引，不按 tag 猜测，不静默截断 |

## 六、验收与收尾

```powershell
python env/ctl/check.py lint --sim <案例目录>
python env/ctl/check.py gate --sim <案例目录> --freeze --emit   # 建模前
python env/ctl/check.py gate --sim <案例目录> --bundle --emit   # 下结论前
python env/ctl/check.py env
python -m unittest discover -s tests -v
```

- `gate` 的阈值来源只能是任务书或人确认；每条判据必须字段完整，至少一条有效 blocking=true。
- `--freeze --emit` 只做结构校验和冻结；正式 gate 必须存在有效冻结元数据。
- NaN/Infinity、畸形 spec、blocking 未评估或 FAIL 时，结论不可引用；证据快照仍应保留。
- 正式 gate 还要求完整 provenance：所有声明工况当前指纹、双模型和 spec 哈希均有效；陈旧 values.json 不得通过。
- run_cases.py 只有全部声明工况通过校验后，才将输出聚合为 <工况>.<探针ID> 并写入 values.json 与 manifest。
- 收尾先整理本地任务，再筛选公共候选；没有通用新内容时，公共环境无需更新。
- 改动公共库后必须跑完整离线测试；真机验证结果按实际命令和退出码记录。
