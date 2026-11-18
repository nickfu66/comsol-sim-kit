"""本案例的建模实现；由任务书驱动，不提供默认物理模型。"""


def build_model(client, case_name, parameters, reset_params):
    """创建并返回本案例模型。

    实现后必须返回：
      {
        "model": mph 模型,
        "mesh": 可 run/stat 的网格对象,
        "study": 研究或求解标签,
        "probes": {"判据或输出ID": "COMSOL表达式"},
      }
    几何、材料、物理场、边界、网格和研究均在此按任务书实现。
    建模时先逐项应用 reset_params，再应用 parameters，然后再运行几何和研究序列。
    """
    raise NotImplementedError("请先在 model_common.py 按任务书实现 build_model")
