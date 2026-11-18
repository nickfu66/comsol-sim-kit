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

## 四、网格

```python
from api_registry import create_checked
from csol_kit import check_mesh

create_checked(mesh, "ftet1", "FreeTet", "mesh")
mesh.run()
ne = check_mesh(mesh, expect_min=1)
```

已核对的通用类型包括 FreeTet、FreeTri、FreeQuad、Sweep、Map、BndLayer 等。Sweep 的 Distribution 是子特征，厚向层数和总单元数都要读回。

长时间求解前，先单独执行网格阶段并记录单元数；不要用未经实测的线性耗时外推承诺完成时间。

## 五、研究与求解

- 稳态研究类型使用 Stationary，时域使用 Transient。
- 时域输出时刻由 study step 的 `tlist` 控制。
- solver 子节点 tag 必须枚举并读回类型，不按 `s`、`t` 等前缀猜测。
- 瞬态是否继承初值必须显式设置并验证，不能依赖默认状态。
- 求解后必须用实际探测表达式确认结果存在且有限。

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

## 七、模型保存

```python
model.save(str(main_mph(case)))      # 求解前：该工况纯建模版
# mesh + solve
model.save(str(solved_mph(case)))    # 求解后：该工况含解版
```

是否含解由保存时机决定。只拿到纯建模版时，应重新网格化和求解，不能直接读取不存在的解。

## 八、参数复位与续跑

每轮开始前，build_model 先逐项应用 RESET_PARAMS，再覆盖当前工况参数，然后运行几何和研究序列。续跑不能只看结果文件存在：

- 状态必须为 OK；
- 工况参数、COMSOL/Python 依赖版本指纹一致；
- `DEPENDENCY_FILES` 中的案例脚本、paths.py 和公共执行核心 SHA256 全部一致；
- 新增本地 helper 必须登记到 DEPENDENCY_FILES，否则其变化不会触发重跑；
- 逐工况 main_<case>.mph 与 solved_<case>.mph 存在且哈希一致；
- 旧结果需要归档，不删除历史证据。
- 聚合前对每个声明工况重新执行 result_is_current(..., require_models=True)，并绑定当前 spec_sha256；任何缺失或过期都会使 provenance.complete=false 并阻止正式 gate。

## 九、新写法的公共收录条件

只有写法经过最小探针、读回验证、适用条件明确且不含任务专属常量时，才可加入本文件。物理接口的专属节点、变量和后处理口径应在相应任务中积累，公共版只提取其中可复用的部分。
