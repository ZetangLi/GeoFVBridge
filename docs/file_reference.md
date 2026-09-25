# GeoFVBridge 文件职责说明

本文档按目录说明仓库中每个源文件和受版本控制文件的用途。运行时缓存、测试缓存和用户生成的求解器结果不属于源代码，单独列在末尾。

## 1. 根目录

| 文件 | 作用 |
|---|---|
| `.github/workflows/tests.yml` | GitHub Actions 自动测试流程，在 Windows 环境安装项目并运行静态检查和测试。 |
| `.gitignore` | 排除 Python/测试缓存、构建产物、运行时配置和生成的数据文件。 |
| `CITATION.cff` | GitHub 可识别的软件引用信息。 |
| `LICENSE` | 项目的 MIT 软件许可证。 |
| `pyproject.toml` | 项目名称、版本、依赖、可选开发依赖、命令行入口、pytest 与 Ruff 配置。 |
| `README.md` | 面向用户的项目简介、安装和启动方法、输出文件及支持范围。 |

## 2. 文档与示例

| 文件 | 作用 |
|---|---|
| `docs/architecture.md` | 技术架构和数据约定，包括真实体积质心、共享面交点距离、HDF5、二维求解器阶段拉伸和 TOUGH 后端语义。 |
| `docs/file_reference.md` | 本文件，说明仓库中每个文件的职责。 |
| `examples/synthetic/README.md` | 小型合成网格的运行说明和预期结果。 |
| `examples/synthetic/generate.py` | 生成可重复使用的合成 Gmsh 网格。 |
| `examples/synthetic/eco2m.json` | TOUGH2/ECO2M 后端配置示例。 |
| `examples/research/README.md` | 论文研究算例的发布和数据来源说明。 |

## 3. 公共入口与核心数据

| 文件 | 作用 |
|---|---|
| `src/geofvbridge/__init__.py` | 统一导出稳定公共 API、数据类和软件版本。 |
| `src/geofvbridge/__main__.py` | `python -m geofvbridge` 入口；有参数时进入 CLI，无参数时启动 GUI。 |
| `src/geofvbridge/api.py` | GUI、CLI 和第三方程序共用的高层接口；负责检查、转换、同名输出、加载、求解器模型准备和后端导出。 |
| `src/geofvbridge/cli.py` | `inspect`、`convert`、`validate`、`export`、`gui` 子命令。`convert` 保存原维度 FV 数据，不执行二维拉伸。 |
| `src/geofvbridge/config.py` | 用户语言和持久化配置管理。 |
| `src/geofvbridge/model.py` | `FVModel`、Cell、Face、Connection、Boundary、Source、转换选项和验证报告的数据结构。 |
| `src/geofvbridge/elements.py` | 支持单元的维数、节点数、局部面拓扑和节点顺序规范。 |
| `src/geofvbridge/geometry.py` | 真实长度/面积/体积、体积质心、面质心、法向和非平面度计算。 |
| `src/geofvbridge/converter.py` | 独立 FV 核心：读取 meshio 网格，构造单元/面/连接/边界/源项，并计算交点 `d1/d2`、重力项和非正交指标。 |
| `src/geofvbridge/extrusion.py` | 将 triangle/quad 按方向和层厚拉伸为 wedge/hexahedron，并迁移材料、边界和源项语义；只由求解器准备阶段使用。 |
| `src/geofvbridge/solver.py` | 统一求解器模型准备接口；3D 原样复制，2D 从 FVModel 重建语义网格后拉伸，保证 H5/MSH 来源走同一路径。 |
| `src/geofvbridge/validation.py` | 检查退化单元、退化面、非流形面、非法交点、距离一致性、非正交性和非平面四边形。 |
| `src/geofvbridge/persistence.py` | `.geofv.h5` schema 1.2 批量读写、Petrel 字段/成员/源连接保存，以及 schema 1.0/1.1 向后读取。 |
| `src/geofvbridge/visualization.py` | 将 FVModel 转换为 meshio/VTU/PyVista 数据，生成连接、边界、源项和 TOUGH 无限体积覆盖层，并按可见岩性创建只影响显示的单元/覆盖层子集。 |
| `src/geofvbridge/i18n.py` | 运行时语言选择和翻译键查询。 |
| `src/geofvbridge/styles.py` | 软件名称、版本、颜色、字体、尺寸和全局深色 Qt 样式。 |

### 3.1 Petrel 输入与大型转换

| 文件 | 作用 |
|---|---|
| src/geofvbridge/eclio.py | 读取 ECLIPSE 大端 Fortran 记录、EGRID/INIT/UNRST 关键字、GRDECL 重复值和 NNC 行。 |
| src/geofvbridge/petrel.py | 发现 Petrel 导出文件集，恢复角点网格、ACTNUM、MAPAXES、属性、TRAN/NNC 和可选首状态。 |
| src/geofvbridge/coarsening.py | 将同一 I/J 柱内连续活动 K 层合并，汇总属性和源连接并写入守恒元数据。 |
| src/geofvbridge/worker.py | GUI 独立转换进程；输出 JSON 进度事件，在临时目录验证和保存后提交成果。 |
| src/geofvbridge/gui/conversion_process.py | QProcess 控制器；解析进度、提供取消、超时终止和残留临时目录清理。 |
| tests/test_eclio.py | 合成 EGRID/INIT/GRDECL/NNC、原生 Petrel 转换及垂向合并守恒测试。 |

## 4. 求解器后端

| 文件 | 作用 |
|---|---|
| `src/geofvbridge/backends/__init__.py` | 注册内置 `tough2-eco2m` 后端及别名。 |
| `src/geofvbridge/backends/registry.py` | 后端适配器和注册表，定义 `validate`、完整 `export`、可选 `export_mesh`、`parse_results` 接口。 |
| `src/geofvbridge/backends/eco2m.py` | 独立生成固定宽度 MESH、五字符标签、材料映射、`cell_map.csv` 和 manifest；支持完整 API 的 flow.inp/INCON 导出并解析 flow.out。无限体积和 AHTX 只在此层处理。 |

## 5. 保留的 TOUGH GUI 辅助模块

这些模块不参与通用 FV 几何计算，只服务于第四步之后的 TOUGH 页面。

| 文件 | 作用 |
|---|---|
| `src/geofvbridge/core/__init__.py` | TOUGH 辅助模块包说明。 |
| `src/geofvbridge/core/inp.py` | 将 GUI 参数写入 flow.inp 的 ROCKS、MULTI、SELEC、PARAM、TIMES、GENER 和 OUTPU 块。 |
| `src/geofvbridge/core/incon.py` | 按稳定标签、求解器材料、压力温度梯度和材料状态生成 INCON。 |
| `src/geofvbridge/core/out.py` | 解析 MESH/flow.out 时间步、单元量和连接量，并输出 Tecplot 数据。 |

## 6. GUI 外壳与状态

| 文件 | 作用 |
|---|---|
| `src/geofvbridge/gui/__init__.py` | GUI 子包标识。 |
| `src/geofvbridge/gui/__main__.py` | `python -m geofvbridge.gui` 启动入口。 |
| `src/geofvbridge/gui/app.py` | 主窗口和七阶段状态机；组装菜单、工具栏、页面、可视化和日志，管理 MSH、原维度 FVModel 与求解器 FVModel 三种状态，并在线程中加载 HDF5。 |
| `src/geofvbridge/gui/sidebar.py` | 七阶段侧栏及页面启用控制。 |
| `src/geofvbridge/gui/console.py` | 底部彩色日志区，接收 stdout/stderr 并支持日志导出。 |
| `src/geofvbridge/gui/visualizer.py` | 右侧 PyVista 视图、岩性勾选筛选、显示模式、视角、原始 FE/FV/求解器网格显示和 Pop-out；缓存未筛选数据，内嵌与弹出视图共用当前筛选结果和渲染函数。 |
| `src/geofvbridge/gui/context.py` | `SolverMeshContext`；保存准备后的 3D FVModel、后端、来源、输出目录、配置、manifest、材料映射和 LegacyMeshView。 |
| `src/geofvbridge/gui/legacy.py` | 为 flow.inp/INCON 页面提供最小数据视图：中心、稳定标签、原材料和五字符求解器材料。 |

## 7. GUI 页面

| 文件 | 作用 |
|---|---|
| `src/geofvbridge/gui/pages/__init__.py` | 集中导出全部页面类。 |
| `src/geofvbridge/gui/pages/workflow.py` | 第一至第三页：原始有限元网格导入、原维度 FV 数据集确认/保存、求解器选择。 |
| `src/geofvbridge/gui/pages/page_mesh.py` | 第四页：H5/MSH 来源选择、二维拉伸、BOUND/材料/Z/顶部无限体积、AHTX、边界预览和仅生成 MESH。 |
| `src/geofvbridge/gui/pages/page_inp.py` | 第五页：flow.inp 参数、ROCKS、GENER 和最近求解器单元查找。 |
| `src/geofvbridge/gui/pages/page_incon.py` | 第六页：压力、温度、饱和度、材料状态和孔隙度，并生成 INCON。 |
| `src/geofvbridge/gui/pages/page_out.py` | 第七页：选择 flow.out/MESH，提取时间步并输出 Tecplot 数据。 |

## 8. 翻译文件

| 文件 | 作用 |
|---|---|
| `src/geofvbridge/locales/__init__.py` | 翻译包标识。 |
| `src/geofvbridge/locales/en_US.py` | 英文翻译键表，主要覆盖保留的详细 TOUGH 页面。 |
| `src/geofvbridge/locales/zh_CN.py` | 简体中文翻译键表。 |

## 9. 自动测试

| 文件 | 作用 |
|---|---|
| `tests/__init__.py` | 测试包标识。 |
| `tests/test_public_examples.py` | 随仓库发布的二维与三维网格检查。 |
| `tests/test_boundary_selection.py` | 边界选择、轴方向、缓存索引和兼容性测试。 |
| `tests/test_gui_reports.py` | GUI 检查和导出报告格式测试。 |
| `tests/test_visualization_filter.py` | 岩性筛选与边界覆盖层测试。 |
| `tests/test_tough_file_pages.py` | flow.inp 与 INCON 页面输出测试。 |
| `tests/test_geometry.py` | tetra、wedge、hexahedron、pyramid、voxel 的规则/畸变几何和高阶单元拒绝测试。 |
| `tests/test_topology.py` | 共享面、非流形、拉伸、物理边界和非正交交点距离测试。 |
| `tests/test_semantics_persistence.py` | 自动物理语义、HDF5 往返和 schema 1.0 向后读取。 |
| `tests/test_eco2m.py` | MESH、状态边界、AHTX、无限体积、距离覆盖和 flow.out 解析。 |
| `tests/test_native_solver_workflow.py` | 二维原样保存、H5/MSH 求解器准备一致、分层拉伸和 MESH-only 输出测试。 |
| `tests/test_cli_gui.py` | CLI、直接运行入口、无 toughio 导入、七阶段 GUI、HDF5 后台载入、页面状态和 Pop-out 一致性。 |
| `tests/test_example_regression.py` | 通过 `GEOFVBRIDGE_REGRESSION_ROOT` 可选启用的四组参考样例回归，比较材料、体积、质心、拓扑、面积、`d1/d2` 和重力项。 |

## 10. 运行时生成文件

| 文件或目录 | 作用 |
|---|---|
| `<输入名>.geofv.h5` | 与输入同目录、同基础名的权威 FV 数据集；二维保持二维。 |
| `<输入名>.summary.json` | 数据规模、材料、单位、转换参数和验证清单。 |
| `<输入名>.vtu` | ParaView/PyVista 可视化文件。 |
| `MESH` | 第四页生成的 TOUGH 网格。 |
| `cell_map.csv` | FV cell ID、五字符 TOUGH 标签和材料映射。 |
| `mesh_manifest.json` | MESH 阶段文件、边界、体积和 AHTX 清单。 |
| `flow.inp` | 第五页生成的 TOUGH/ECO2M 模拟参数。 |
| `INCON` | 第六页生成的初始条件。 |
| `export_manifest.json` | 仅在完整 API/CLI 一键后端导出时生成的完整清单。 |
| `flow.out`、`GeoFVBridge_Extract/` | 求解器结果及第七页提取目录。 |
| `.runtime/` | 本地用户配置；不属于核心源码。 |
| `__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`*.egg-info/` | Python、测试、静态检查和可编辑安装缓存。 |

## 11. 主要依赖方向

```text
GUI / CLI
  -> api.py
     -> converter.py -> geometry.py + elements.py
     -> persistence.py + visualization.py
     -> solver.py -> extrusion.py -> converter.py
     -> backends/registry.py -> backends/eco2m.py

GUI 的 flow.inp / INCON / 结果页
  -> SolverMeshContext
  -> core/inp.py + core/incon.py + core/out.py
```

通用 FV 层不读取 TOUGH 专属配置。无限体积、AHTX、五字符标签和求解器文件始终位于求解器准备、后端或 TOUGH 页面中。
