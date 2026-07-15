"""Human-readable reports for the FE, FV, and solver GUI stages."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..i18n import get_language
from ..model import FVModel


def _translator(language: str | None = None):
    chinese = (language or get_language()) == "zh_CN"
    return lambda zh, en: zh if chinese else en


def _number(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return str(number)
    if number == 0.0:
        return "0"
    if abs(number) >= 1.0e5 or abs(number) < 1.0e-3:
        return f"{number:.6e}"
    return f"{number:,.6g}"


def _section(lines: list[str], title: str) -> None:
    if lines:
        lines.append("")
    lines.append(f"[{title}]")


def format_fe_inspection(inspection: dict[str, Any], language: str | None = None) -> str:
    """Format the stage-1 Gmsh inspection without exposing a JSON document."""
    tr = _translator(language)
    cell_types = dict(inspection.get("cell_types", {}))
    groups = dict(inspection.get("physical_groups", {}))
    bounds = dict(inspection.get("coordinate_bounds", {}))
    lines = [tr("原始有限元网格检查", "Original finite-element mesh inspection")]

    _section(lines, tr("网格概况", "Mesh overview"))
    lines.extend(
        [
            f"{tr('源文件', 'Source file')}: {inspection.get('path', '—')}",
            f"{tr('空间维数', 'Dimension')}: {inspection.get('dimension', '—')}D",
            f"{tr('节点数量', 'Points')}: {_number(inspection.get('points', 0))}",
            f"{tr('顶维单元数量', 'Top-dimensional cells')}: "
            f"{_number(sum(int(value) for value in cell_types.values()))}",
        ]
    )

    _section(lines, tr("单元类型", "Cell types"))
    if cell_types:
        lines.extend(f"- {name}: {_number(count)}" for name, count in cell_types.items())
    else:
        lines.append(tr("- 未发现支持的顶维单元", "- No supported top-dimensional cells found"))

    _section(lines, tr("物理组", "Physical groups"))
    if groups:
        for name, values in groups.items():
            dimension = values.get("dimension", "—")
            tag = values.get("tag", "—")
            lines.append(f"- {name}: {tr('维数', 'dimension')}={dimension}D, tag={tag}")
    else:
        lines.append(tr("- 未定义物理组", "- No physical groups defined"))

    _section(lines, tr("坐标范围", "Coordinate bounds"))
    for axis in ("x", "y", "z"):
        values = bounds.get(axis)
        if values and len(values) >= 2:
            lines.append(f"- {axis.upper()}: {_number(values[0])} ～ {_number(values[1])}")
    return "\n".join(lines)


def format_fv_model(
    model: FVModel,
    artifacts: Any | None = None,
    language: str | None = None,
) -> str:
    """Format the stage-2 solver-independent FV topology and validation summary."""
    tr = _translator(language)
    data = model.summary()
    validation = dict(data.get("validation", {}))
    valid = bool(validation.get("valid", False))
    unit = str(data.get("length_unit", "m"))
    measure_name = tr("面积", "Area") if model.dimension == 2 else tr("体积", "Volume")
    minimum_measure_name = tr(
        "最小单元面积" if model.dimension == 2 else "最小单元体积",
        "Minimum cell area" if model.dimension == 2 else "Minimum cell volume",
    )
    measure_unit = f"{unit}²" if model.dimension == 2 else f"{unit}³"
    lines = [tr("通用有限体积数据集", "Reusable finite-volume dataset")]

    _section(lines, tr("验证状态", "Validation status"))
    lines.append(
        f"{tr('结果', 'Result')}: "
        f"{tr('通过，可进入求解器阶段', 'Passed; ready for a solver') if valid else tr('未通过', 'Failed')}"
    )
    lines.append(
        f"{tr('错误', 'Errors')}: {_number(validation.get('errors', 0))}    "
        f"{tr('警告', 'Warnings')}: {_number(validation.get('warnings', 0))}"
    )

    _section(lines, tr("FV 拓扑", "FV topology"))
    topology = (
        (tr("空间维数", "Dimension"), f"{data.get('dimension', '—')}D"),
        (tr("节点", "Points"), _number(data.get("points", 0))),
        (tr("控制体", "Control volumes"), _number(data.get("cells", 0))),
        (tr("面", "Faces"), _number(data.get("faces", 0))),
        (tr("内部连接", "Internal connections"), _number(data.get("connections", 0))),
        (tr("外边界面", "Exterior boundary faces"), _number(data.get("boundaries", 0))),
        (tr("源项候选单元", "Source candidate cells"), _number(data.get("sources", 0))),
    )
    lines.extend(f"- {name}: {value}" for name, value in topology)

    _section(lines, tr("几何质量", "Geometry and quality"))
    lines.extend(
        [
            f"- {measure_name}{tr('总量', ' total')}: {_number(data.get('measure_total', 0))} {measure_unit}",
            f"- {minimum_measure_name}: {_number(data.get('measure_min', 0))} {measure_unit}",
            f"- {tr('最小正交性', 'Minimum orthogonality')}: "
            f"{_number(data.get('orthogonality_min', 0))}",
            f"- {tr('正交性中位数', 'Median orthogonality')}: "
            f"{_number(data.get('orthogonality_median', 0))}",
            f"- {tr('最大面非平面度', 'Maximum face non-planarity')}: "
            f"{_number(data.get('face_nonplanarity_max', 0))}",
        ]
    )

    _section(lines, tr("材料分布", "Material distribution"))
    materials = dict(data.get("materials", {}))
    if materials:
        lines.extend(f"- {name}: {_number(count)} {tr('个单元', 'cells')}" for name, count in materials.items())
    else:
        lines.append(tr("- 未记录材料", "- No materials recorded"))

    issues = list(validation.get("issues", []))
    _section(lines, tr("验证清单", "Validation checklist"))
    if not issues:
        lines.append(tr("- 未发现问题", "- No issues found"))
    else:
        for issue in issues:
            severity = str(issue.get("severity", "info")).lower()
            severity_text = {
                "error": tr("错误", "ERROR"),
                "warning": tr("警告", "WARNING"),
            }.get(severity, tr("信息", "INFO"))
            entity = ""
            if issue.get("entity") is not None:
                entity = f" ({issue['entity']} {issue.get('entity_id', '—')})"
            lines.append(f"- {severity_text}{entity}: {_issue_text(issue, tr)}")

    if artifacts is not None:
        _section(lines, tr("已保存文件", "Saved files"))
        for label, attribute in (
            (tr("完整 FV 数据", "Complete FV data"), "hdf5"),
            (tr("摘要", "Summary"), "summary"),
            (tr("可视化网格", "Visualization mesh"), "vtu"),
        ):
            path = Path(getattr(artifacts, attribute))
            status = tr("已生成", "created") if path.is_file() else tr("未找到", "not found")
            lines.append(f"- {label}: {path} ({status})")
    return "\n".join(lines)


def _reason_text(reason: str, tr) -> str:
    if reason == "explicit":
        return tr("手动选择", "manually selected")
    if reason.startswith("material:"):
        return f"{tr('按材料选择', 'selected by material')}: {reason.split(':', 1)[1]}"
    if reason.startswith("volume_override:"):
        return f"{tr('材料体积覆盖', 'material volume override')}: {reason.split(':', 1)[1]}"
    if reason.startswith("z>="):
        return f"{tr('达到高程阈值', 'meets elevation threshold')} ({reason})"
    if reason == "exposed_top":
        return tr("位于全局顶部外边界", "on the global exposed top boundary")
    return reason


def _issue_text(issue: dict[str, Any], tr) -> str:
    messages = {
        "invalid_dimension": ("模型维数必须为二维或三维。", "Model dimension must be 2 or 3."),
        "empty_model": ("模型中没有控制体。", "The model contains no control volumes."),
        "duplicate_cell_node": ("单元包含重复的节点编号。", "A cell contains repeated node IDs."),
        "degenerate_cell": ("发现退化单元。", "A degenerate cell was found."),
        "conflicting_boundary_groups": (
            "同一个边界面被分配到多个物理组。",
            "A boundary face belongs to conflicting physical groups.",
        ),
        "degenerate_face": ("发现退化面。", "A degenerate face was found."),
        "nonplanar_face": (
            "部分面节点不共面，计算时采用了代表性平面。",
            "Some face vertices are not coplanar; a representative plane was used.",
        ),
        "nonmanifold_face": (
            "存在被两个以上顶维单元共享的非流形面。",
            "A non-manifold face is shared by more than two cells.",
        ),
        "coincident_centroids": ("相邻单元的质心重合。", "Adjacent cells have coincident centroids."),
        "centroid_line_parallel_to_face": (
            "相邻质心连线与共享面平行，无法得到有效交点。",
            "The adjacent-centroid line is parallel to the shared face.",
        ),
        "invalid_measure": ("存在面积或体积非正的单元。", "A cell has non-positive measure."),
        "invalid_node_reference": ("单元引用了无效节点。", "A cell references an invalid node."),
        "invalid_face_measure": ("存在面积非正的面。", "A face has non-positive measure."),
        "invalid_face_normal": ("存在无效的面单位法向。", "A face normal is invalid."),
        "invalid_interface_intersection": (
            "连接的界面交点不是有限数值。",
            "A connection interface intersection is not finite.",
        ),
        "invalid_intersection_distance": (
            "存在非正的质心—界面交点距离。",
            "A centroid-to-interface distance is non-positive.",
        ),
        "interface_not_between_centroids": (
            "共享面交点不在两个相邻质心之间。",
            "A shared-face intersection is not between adjacent centroids.",
        ),
        "small_normal_distance": (
            "单元质心非常接近共享面平面。",
            "A cell centroid is very close to its shared-face plane.",
        ),
        "invalid_orthogonality": ("连接正交性超出有效范围。", "Connection orthogonality is invalid."),
        "poor_orthogonality": ("存在正交性低于 0.1 的连接。", "A connection has orthogonality below 0.1."),
        "isolated_cell": ("存在没有内部面或边界面的孤立单元。", "An isolated cell has no internal or boundary faces."),
        "unassigned_boundaries": (
            "一个或多个外边界面未归入具名物理组。",
            "One or more exterior faces do not belong to a named physical group.",
        ),
    }
    code = str(issue.get("code", ""))
    return tr(*messages[code]) if code in messages else str(issue.get("message", code))


def format_tough_report(value: Any, language: str | None = None) -> str:
    """Format a TOUGH preview/export manifest without listing every cell label."""
    tr = _translator(language)
    if not isinstance(value, dict):
        return str(value)
    files = dict(value.get("files", {}))
    exported = bool(files)
    title = (
        tr("TOUGH2/ECO2M MESH 导出结果", "TOUGH2/ECO2M MESH export result")
        if exported
        else tr("TOUGH2/ECO2M 边界预览", "TOUGH2/ECO2M boundary preview")
    )
    lines = [title]

    _section(lines, tr("状态与规模", "Status and size"))
    if value.get("valid") is False:
        lines.append(f"{tr('验证结果', 'Validation')}: {tr('未通过', 'failed')}")
        for error in value.get("errors", []):
            lines.append(f"- {tr('错误', 'Error')}: {error}")
        return "\n".join(lines)
    lines.append(f"{tr('验证结果', 'Validation')}: {tr('通过', 'passed')}")
    if value.get("backend"):
        lines.append(f"{tr('求解器后端', 'Solver backend')}: {value['backend']}")
    if "cells" in value:
        lines.append(f"{tr('ELEME 单元', 'ELEME cells')}: {_number(value['cells'])}")
    if "connections" in value:
        lines.append(f"{tr('CONNE 连接', 'CONNE connections')}: {_number(value['connections'])}")

    boundary_cells = list(value.get("boundary_cells", []))
    inactive_cells = list(value.get("inactive_cells", []))
    generated_cells = list(value.get("generated_boundary_cells", []))
    lines.append(
        f"{tr('特殊边界/体积处理单元', 'Special boundary/volume cells')}: "
        f"{_number(value.get('boundary_count', len(boundary_cells)))}"
    )
    lines.append(
        f"{tr('无限体积单元', 'Infinite-volume cells')}: "
        f"{_number(value.get('inactive_count', len(inactive_cells)))}"
    )
    if "ahtx_nonzero_cells" in value:
        lines.append(
            f"{tr('AHTX 非零单元', 'Cells with nonzero AHTX')}: "
            f"{_number(value['ahtx_nonzero_cells'])}"
        )
    labels = value.get("cell_labels")
    if isinstance(labels, dict):
        lines.append(f"{tr('单元名称映射数量', 'Cell-label mappings')}: {_number(len(labels))}")

    materials = dict(value.get("materials", {}))
    if materials:
        _section(lines, tr("材料名称映射", "Material-name mapping"))
        lines.extend(f"- {source} → {target}" for source, target in materials.items())

    if boundary_cells:
        _section(lines, tr("最终边界单元清单", "Final boundary-cell list"))
        for item in boundary_cells:
            reasons = ", ".join(_reason_text(str(reason), tr) for reason in item.get("reasons", []))
            lines.append(
                f"- {item.get('label', '—')} | {tr('FV 单元', 'FV cell')} {item.get('cell_id', '—')} | "
                f"{tr('材料', 'material')}={item.get('material', '—')} | "
                f"{tr('体积', 'volume')}={_number(item.get('volume', 0))} | "
                f"AHTX={_number(item.get('ahtx', 0))} | "
                f"{tr('原因', 'reason')}={reasons or tr('体积设置', 'volume setting')}"
            )
    else:
        _section(lines, tr("最终边界单元清单", "Final boundary-cell list"))
        lines.append(tr("- 当前配置没有特殊边界或无限体积单元", "- No special boundary or infinite-volume cells"))

    if generated_cells:
        _section(lines, tr("自动生成的边界单元", "Generated boundary cells"))
        for item in generated_cells:
            lines.append(
                f"- {item.get('label', '—')} | {tr('材料', 'material')}={item.get('material', '—')}"
            )

    if files:
        _section(lines, tr("生成文件", "Generated files"))
        labels_by_key = {
            "mesh": "MESH",
            "cell_map": "cell_map.csv",
            "manifest": "mesh_manifest.json",
        }
        for key, path in files.items():
            lines.append(f"- {labels_by_key.get(key, key)}: {path}")
        if files.get("cell_map"):
            lines.append(
                tr(
                    "- 完整单元名称映射请查看 cell_map.csv；GUI 不展开普通单元映射。",
                    "- See cell_map.csv for the complete label mapping; ordinary mappings are not expanded here.",
                )
            )
    return "\n".join(lines)
