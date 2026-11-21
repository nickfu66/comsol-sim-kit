# COMSOL 通用 API 交接卡

> 本文件回答“怎么写才正确”。只收通用机制与已经核对的类型名，不提供具体物理模型。

## 验证边界

公共注册表和代码模板经过离线自动化测试。真机最小模型是否通过，以 `python env/_smoke_csol_kit.py --comsol` 的当次输出为准。任何新物理接口、属性、求解器和后处理变量都必须在自己的版本上重新做最小探针。

## 一、启动与配置

```python
from comsol_boot import start_client

client = start_client()       # 从 config/config.toml 读取配置
model = client.create("case")
# 结束后：client.remove(model)
```

不要在每个任务脚本里重复 monkeypatch，也不要在一个 Python 进程中创建多个客户端。

## 二、API 类型名守卫

```python
from api_registry import assert_type, create_checked, lookup, register_type

assert_type("mesh", "Sweep")
info = lookup("study", "Transient")
create_checked(geometry, "blk1", "Block", "geometry")
```

注册表不是完整能力清单。未收录只表示“尚未登记”，不表示“本机不可用”。

新增流程：

1. 查与安装版本匹配的官方资料。
2. 在最简单模型上创建并读回类型、属性和选择。
3. 记录验证版本、命令、退出码与适用边界。
4. 用 `register_type(category, name, source, aliases=...)` 登记，或由维护者写入公共注册表。

GUI 别名可以登记为错误提示，但 `assert_type` 不会静默替换用户输入。

## 三、几何与选择

- 创建几何后必须运行几何序列，并用域数、包围盒、面积或体积读回验证。
- 2D Polygon 若目标是实体域，检查 `type="solid"`。
- 布尔特征、WorkPlane、Revolve、Extrude 分属各自上下文，不能仅凭显示名称调用。
- Java 整数重载出现歧义时使用 `jpype.JInt(...)`。
- 选择集不能只凭编号猜测；用几何量或命名选择读回验证。

```python
import jpype
selection.set("entitydim", jpype.JInt(2))
```

重建几何后，原有选择、耦合算子和变量引用可能失效，必须重新读回。

**参数化扫描的几何量必须登记显式 setter**：用 `setattr(obj, 求解器参数名, 值)` 赋值，当宿主属性名与求解器参数名不一致（大小写、别名）时会**静默创建新属性**而不改真正字段，表现为「参数改了但几何没变」。正确做法：映射表给出每个几何量的显式 setter，未登记的量直接抛错，不允许 setattr 兜底。（本项目已落地此守卫，此处提炼既有做法。）

**盒选择须留余量并校验认领**（边界：2D 分层几何）：参数表达式几何与宿主浮点值有微小差异，Box 选择按坐标定位时要留小余量；定位后必须校验**所有实体都被认领**，漏一个域即可能报材料属性缺失或产生封闭腔伪结果。

**多点扫描的选择集生命周期**：每点应复用或先删除上一点的同名旧选择/坐标系，避免对象累积导致后续点编译变慢或失败。（与 GEOM-003 并列陈述；无分离实验，不断言主因。）

### 3.1 不同选择类型绑定实体维的方式不同

| 选择类型 | 绑定实体维的写法 | 备注 |
|---|---|---|
| `Box` | `set("entitydim", jpype.JInt(1))` | 有 `entitydim` 属性 |
| `Explicit` | `sel.geom("geom1", 1)` | **没有 `entitydim` 属性**；写 `set("entitydim", ...)` 会报「未知属性」 |

`Explicit` 未绑定几何与实体维就写入实体号时，会报
`Illegal input vector illegal entity number`。正确写法：

```python
sel = comp.selection().create("sel_both", "Explicit")
sel.geom("geom1", 1)                      # 先绑定几何与实体维
sel.set(jpype.JArray(jpype.JInt, 1)(entities))
```

需要把两个边界选择合并成一个 `Explicit` 选择时，先分别用 `Box` 取实体号，
再把两个列表拼起来写入——不要建两个选择。

### 3.2 恒等对（Identity Pair）的源与目标

```python
pair = comp.pair().create("id1", "Identity")
pair.source().set(source_entities)          # 方法是 source()/destination()
pair.destination().set(destination_entities)
```

`PairClient` 的 `source`/`destination` 是**方法**不是属性，必须用 `.set()` 绑定实体。

## 三·补　材料属性

材料的`RefractiveIndex` 属性组只提供 `n` 和 `ki`。电磁波类接口还需要相对磁导率等属性，
必须显式给出，否则求解报「未定义材料属性 mur」：

```python
mat = comp.material().create("mat1", "Common")
pg = mat.propertyGroup().create("RefractiveIndex", "Refractive index")
pg.set("n", "3.48")
pg.set("ki", "0")
mat.propertyGroup("def").set(
    "relpermeability", ["1", "0", "0", "0", "1", "0", "0", "0", "1"])
mat.propertyGroup("def").set(
    "relpermittivity", ["1", "0", "0", "0", "1", "0", "0", "0", "1"])
mat.propertyGroup("def").set("electricconductivity", ["0"] * 9)
```

三个 3×3 矩阵都按行展开为 9 元素列表。是否需要哪些属性取决于所用物理接口，
按接口要求逐项确认，不要默认其他接口也只需要折射率。

**有损材料**：上例是无损写法（单位阵 + σ=0）。有损材料的 `relpermittivity` 必须取复介电常数的**实部**，`electricconductivity` 由虚部换算（σ = ω·ε₀·|Im ε|，随频率更新）；沿用单位阵会把有损材料变成完美介质（实测表现为 R=0、T=1 的明显错误）。自检：与解析 Fresnel 反射/透射对比。

**无损对照**：只置零损耗项（虚部/电导率），**保留介电常数实部**；连实部一起重置会改变材料整体电磁响应，对照失去意义。
（验证边界：COMSOL 6.3 build 290、频域 emw 实测。）

## 四、网格

```python
from api_registry import create_checked
from csol_kit import check_mesh

create_checked(mesh, "ftet1", "FreeTet", "mesh")
mesh.run()
ne = check_mesh(mesh, expect_min=1)
```

已核对的通用类型包括 FreeTet、FreeTri、FreeQuad、Sweep、Map、BndLayer 等。Sweep 的 Distribution 是子特征，厚向层数和总单元数都要读回。

**尺寸设置静默不生效的两个独立原因**（同一失效模式，两条都要防）：

1. **Size 特征只作用于其后创建的剖分操作**。必须先建全部 Size，再建 FreeTri/FreeTet 等剖分特征；先剖分后补 Size，hmax/hmin 完全不生效。
2. **布尔型开关属性必须传布尔值**。字符串形式的开关（如 "on"）可能被静默忽略，读回仍是 off；`custom`、`hmaxactive` 等开关用 `True/False` 并逐项显式打开。

自检方法：同一几何改 hmax，若单元数不变即为顺序或开关错误；每个属性 set 之后读回确认实际值。
（验证边界：COMSOL 6.3 build 290、2D FreeTri 实测；其它版本须重做最小探针。）

长时间求解前，先单独执行网格阶段并记录单元数；不要用未经实测的线性耗时外推承诺完成时间。

## 五、研究与求解

- 稳态研究类型使用 Stationary，时域使用 Transient。
- 时域输出时刻由 study step 的 `tlist` 控制。
- solver 子节点 tag 必须枚举并读回类型，不按 `s`、`t` 等前缀猜测。
- 瞬态是否继承初值必须显式设置并验证，不能依赖默认状态。
- 求解后必须用实际探测表达式确认结果存在且有限。

### 5.1 研究节点的引用方式（易错）

`model.solve()` 只接受 **studies 下的显示名**或 **mph 节点对象**，**不接受 study tag**：

| 传入 | 结果 |
|---|---|
| `"std1"`（tag，默认显示名是本地化的「研究 1」） | 报 `Study "std1" does not exist` |
| `st.label()`（Java 字符串，`isinstance(str)` 为 False） | 报 `neither string nor node` |
| `str(st.label())` 或 `model / "studies" / str(st.label())` | 正确 |
| 把研究显示名显式设为 tag（`st.label("std1")`）后传 `"std1"` | 正确 |

推荐直接用公共函数 `csol_kit.study_node`，它会把标签规整为 Python `str` 再定位节点：

```python
from csol_kit import study_node

node = study_node(model, "std1")   # 返回可传给 model.solve() 的节点
model.solve(node)
```

`csol_kit.solve(model, mesh, study="std1")` 也接受 tag，内部会自动解析。

### 5.1b 频率表 plist 的写法（易错）

频点表必须走 Java 研究特征：`java.study("std1").feature("freq").set("plist", "range(...)[THz]")`，
并同设 `punit`。mph 的 Node 封装无 setp 方法；且**每次扫描都要重写 plist**——
粗扫与细扫共用一个模型时，不重写会让细扫沿用粗扫频表（表现为所有参数点结果完全相同）。
（验证边界：COMSOL 6.3 build 290、频域研究实测，证据 probe_plist 读回。）

### 5.2 求解器序列必须显式生成

新建研究后直接求解可能不产生解（`The solution has not been computed`）。研究创建后应显式生成求解器序列：

```python
study = model.java.study().create("std1")
study.create("freq", "Frequency")
study.createAutoSequences("sol")   # 生成求解器序列
```

### 5.3 求解与探测

```python
from csol_kit import check_solution, solve

ne = solve(model, mesh, study="std1", retries=1)
values = check_solution(
    model,
    {"K1": "maxop_case(expression_1)", "R1": "intop_case(expression_2)"},
    reducers={"R1": "last"},  # 数组必须显式指定；标量可不写
)
```

表达式只是占位；变量、单位和算子选择必须来自当前任务。

## 六、耦合算子与后处理

- 积分、平均和极值算子在 solve 前创建，并绑定正确的几何与实体维度。
- 普通面积/体积平均分别使用 area_avg、vol_avg。
- 掩码平均使用 masked_avg，分母不能换成全域积分。
- 二维轴对称使用 axisym_area、axisym_vol，自动加入 2πr。
- 点采样每个分量单独求值；失败时检查该变量是否定义在目标实体上。
- 多解存储时间取值使用 enum_entries 的 MPh inner(dataset) 完整索引；study 参数使用 "Study 1" 等显示名而不是 std1 tag，达到 max_inner 会明确报错。
- 保存结果前用 model.version() 核对实际 COMSOL 系列；只有 API 实际提供 build 时才核对 build，返回“6.3”这类短版本不得误判为不匹配。运行指纹同时记录 NumPy 和平台。
- **波长换算**：`emw.Wav` 的单位是 µm（不是 nm）；波长一律用 c/Re(freq) 自行换算，不直接读 Wav 当 nm。
- **功率归一化**：端口激励的入射功率用 `emw.port1.Pin` 读回做归一化，不要用自由空间 Poynting 估算。
- **S 参数保存复数对 [Re, Im]**，不要只存模或模平方：只存幅度会使相位、Smith 轨迹、群延迟全部无法事后补算，必须重跑。自检：由复数对算出的模平方与独立记录的反射率应在机器精度量级一致。
- **相位展开有采样前提**：unwrap 类算法假设相邻采样点相位变化小于半圈；粗扫违反该前提时会反复误触发并累加出整圈偏差，表现为粗细扫相位不一致的假象。展开前先检查最大相邻跳变，超过半圈则改用主值散点并声明欠采样（主值逐点精确，无分支问题）。
- **已解模型可离线取场**：client.load 已解模型后直接 evaluate 场量，再插值到规则网格，不必重跑求解。注意网格节点分布极不均匀（薄层附近密、大域内稀），直接按坐标切片会节点不足；应先插值到规则网格再做剖面与符号区计数。多表达式取数用 list-expr 一次调用（`m.evaluate(["x","y",expr...])`）可保证同一网格对齐；Grid2D/CutLine2D 的属性名在本版本未探通，不预设可用。

## 七、模型保存

```python
model.save(str(main_mph(case)))      # 求解前：该工况纯建模版
# mesh + solve
model.save(str(solved_mph(case)))    # 求解后：该工况含解版
```

是否含解由保存时机决定。只拿到纯建模版时，应重新网格化和求解，不能直接读取不存在的解。

**已解模型只保存扫描序列最后一点的解**：离线取场或事后补算前，必须核对已解模型当前参数与目标点是否一致；不一致时只能测到最后一点，或重跑该点。此条是对保存时机的重要补充。

## 八、参数复位与续跑

每轮开始前，build_model 先逐项应用 RESET_PARAMS，再覆盖当前工况参数，然后运行几何和研究序列。续跑不能只看结果文件存在：

- 状态必须为 OK；
- **求解去重池**（`csol_kit.SolvePool`）：相同 (物理指纹, 计算口径, 几何, 频表) 的求解只做一次，各验收视图从池取数、派生量仍按各自口径计算。「M 任务是验收视图，不是求解单元」。池是加速缓存不是验收数据源，删池即回到逐点求解；物理指纹与池目录由调用方注入，池本身物理中立。等价性验证用数值容差（两次独立求解有 ~1e-12 浮点末位差）而非逐字节；
- 指纹采用**三层语义分级**（`csol_kit.layered_fingerprint` / `fingerprint_status`）：物理构建层（建模/扫描/几何/执行核心）变 → 必须重跑；该工况计算配置（点表/窗口/研究设置）变 → 只有该工况重跑；后处理层变 → 离线重算即可。**编排文件不进任何层**，改它不作废结果。整文件 SHA256 全一致的老口径会让改一个工况的扫描参数导致全部工况失效，已弃用；
- 物理层依赖文件仍须全部登记，缺失抛错；新增 helper 按层归类登记；
- 逐工况 main_<case>.mph 与 solved_<case>.mph 存在且哈希一致；
- 旧结果需要归档，不删除历史证据。
- 聚合前对每个声明工况重新执行 result_is_current(..., require_models=True)，并绑定当前 spec_sha256；任何缺失或过期都会使 provenance.complete=false 并阻止正式 gate。

## 九、新写法的公共收录条件

只有写法经过最小探针、读回验证、适用条件明确且不含任务专属常量时，才可加入本文件。物理接口的专属节点、变量和后处理口径应在相应任务中积累，公共版只提取其中可复用的部分。
