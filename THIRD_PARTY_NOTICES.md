# 开源来源与第三方组件

| 来源 | 本项目使用范围 |
|---|---|
| [EOS-Bench](https://github.com/Ethan19YQ/EOS-Bench) | 场景结构、部分调度/约束内核、既有算法和可视化基础；保留原CITATION.cff及文件归属 |
| [FastAPI](https://github.com/fastapi/fastapi)、[Uvicorn](https://github.com/encode/uvicorn)、[Pydantic](https://github.com/pydantic/pydantic) | HTTP服务、请求/响应校验 |
| [Orekit](https://www.orekit.org/)、[orekit-jpype](https://github.com/CS-SI/orekit_jpype)、[JPype](https://github.com/jpype-project/jpype) | Java轨道/姿态计算与Python桥接；Orekit数据按SHA单独分发 |
| [NumPy](https://numpy.org/)、[SciPy](https://scipy.org/)、[scikit-learn](https://scikit-learn.org/)、[joblib](https://joblib.readthedocs.io/) | 数值计算、学习排序与受控模型序列化 |
| [Matplotlib](https://matplotlib.org/)、[ijson](https://github.com/ICRAR/ijson) | 绘图与流式数据审计 |
| [CesiumJS](https://cesium.com/platform/cesiumjs/) | 三维地球与轨道回放；浏览器加载1.136版及网络底图 |
| SQLite、Python与相关标准库 | 持久化、并发、进程/文件管理和导出 |

独立小组成果包括课程工作台、公共实验接口、Controller/Worker/IPC/Daemon、事务与终态控制、独立核验/数据来源协议、DARTIS/RABAS/CAABS/LAVIS路线及其接入、统计导出和交互整合。OS经典策略迁移保留原名称；既有开源算法不因成绩好而改名成小组自研。

本说明用于明确归属，不替代各项目本身的许可或引用要求。离线wheels保留各发行包自带元数据和许可；没有为缺少依据的原文件添加臆测许可证。模型joblib仅加载可信组内制品。
