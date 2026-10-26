"""architecture.json으로 architecture.drawio를 만든다.

사용법 (저장소 루트에서):
    python docs/architecture/generate_drawio.py          # .drawio 다시 만들기
    python docs/architecture/generate_drawio.py --check  # JSON과 .drawio가 같은지 비교만
    python docs/architecture/generate_drawio.py --png    # .drawio와 함께 페이지별 PNG도 내보내기 (draw.io 데스크톱 필요)

표준 라이브러리만 쓴다. 원본은 JSON이고 .drawio·PNG는 생성물이므로 직접 고치지 않는다.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "architecture.json"
TARGET = HERE / "architecture.drawio"
PNG_PAGES = {1: HERE / "architecture-system.png", 2: HERE / "architecture-endpoints.png"}

ZONE_STYLE = {
    "untrusted": ("#f8cecc", "#b85450", False),
    "server": ("#dae8fc", "#6c8ebf", False),
    "supabase": ("#d5e8d4", "#82b366", False),
    "external": ("#fff2cc", "#d6b656", False),
    "onetime": ("#f5f5f5", "#666666", True),
}
ROLE_SYMBOL = {"allow": "✓", "public_only": "△", "no_record": "○", "deny": "✗"}
ROLE_ORDER = (("visitor", "방문자"), ("member", "사용자"), ("operator", "운영자"))
GRID = "#bfbfbf"
AWS_INK = "#232F3E"
ICON_KEYS = ("image", "aws_shape", "aws_resource", "aws_group")
NODE_ICON = 60
ZONE_ICON = 22


def validate_icon(owner, icon, allow_group):
    if icon is None:
        return []
    keys = [k for k in ICON_KEYS if k in icon]
    if len(keys) != 1:
        return [f"{owner}: icon에는 {', '.join(ICON_KEYS)} 중 하나만 둔다"]
    if keys[0] == "aws_group" and not allow_group:
        return [f"{owner}: aws_group은 zone에만 쓴다"]
    if keys[0] == "image" and not (HERE / icon["image"]).is_file():
        return [f"{owner}: 아이콘 파일 없음 {icon['image']}"]
    return []


def validate(model):
    errors = []
    ids = set()
    for key in ("zones", "components", "flows", "trust_boundaries", "endpoint_groups", "endpoints"):
        for item in model[key]:
            if item["id"] in ids:
                errors.append(f"id 중복: {item['id']}")
            ids.add(item["id"])
    zones = {z["id"] for z in model["zones"]}
    components = {c["id"] for c in model["components"]}
    groups = {g["id"] for g in model["endpoint_groups"]}
    for zone in model["zones"]:
        if zone["kind"] not in ZONE_STYLE:
            errors.append(f"{zone['id']}: 알 수 없는 kind {zone['kind']}")
        errors += validate_icon(zone["id"], zone.get("icon"), allow_group=True)
    for comp in model["components"]:
        if comp["zone"] not in zones:
            errors.append(f"{comp['id']}: 없는 zone {comp['zone']}")
        errors += validate_icon(comp["id"], comp.get("icon"), allow_group=False)
    numbers = [f.get("no") for f in model["flows"]]
    if len(set(numbers)) != len(numbers):
        errors.append("flows의 no가 중복된다")
    for flow in model["flows"]:
        for end in (flow["from"], flow["to"]):
            if end not in components:
                errors.append(f"{flow['id']}: 없는 구성요소 {end}")
        if flow.get("type") not in ("data", "control"):
            errors.append(f"{flow['id']}: type은 data 또는 control")
    for ep in model["endpoints"]:
        if ep["group"] not in groups:
            errors.append(f"{ep['id']}: 없는 그룹 {ep['group']}")
        for use in ep["uses"]:
            if use not in components:
                errors.append(f"{ep['id']}: 없는 구성요소 {use}")
        for role, _ in ROLE_ORDER:
            if ep["roles"].get(role) not in ROLE_SYMBOL:
                errors.append(f"{ep['id']}: {role} 권한 값이 잘못됨")
    system = model["layout"]["system"]
    errors += [f"layout.system.zones에 {z} 없음" for z in sorted(zones - set(system["zones"]))]
    errors += [f"layout.system.components에 {c} 없음" for c in sorted(components - set(system["components"]))]
    drawn = {f["id"] for f in model["flows"] if f.get("drawn", True)}
    errors += [f"layout.system.flows에 그리지 않는 흐름 {f}" for f in sorted(set(system["flows"]) - drawn)]
    listed = [n for item in system["legend"] for n in item.get("flows", ())]
    errors += [f"범례에 없는 흐름 번호 {n}" for n in listed if n not in numbers]
    errors += [f"범례에 빠진 흐름 번호 {n}" for n in numbers if n not in listed]
    order = model["layout"]["endpoints"]["target_order"]
    errors += [f"target_order에 없는 구성요소 {t}" for t in order if t not in components]
    used = {u for ep in model["endpoints"] for u in ep["uses"]}
    errors += [f"target_order에 {u} 없음" for u in sorted(used - set(order))]
    return errors


def style(**kv):
    return "".join(f"{k}={v};" for k, v in kv.items())


class Page:
    def __init__(self, name, page_id):
        self.diagram = ET.Element("diagram", name=name, id=page_id)
        model = ET.SubElement(
            self.diagram, "mxGraphModel",
            grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1",
            fold="1", page="0", pageScale="1", math="0", shadow="0", background="#ffffff",
        )
        self.root = ET.SubElement(model, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")

    def vertex(self, cell_id, value, cell_style, box, parent="1"):
        cell = ET.SubElement(self.root, "mxCell", id=cell_id, value=value, style=cell_style, vertex="1", parent=parent)
        x, y, w, h = box
        ET.SubElement(cell, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"})

    def edge(self, cell_id, value, cell_style, source, target, points=()):
        cell = ET.SubElement(
            self.root, "mxCell", id=cell_id, value=value, style=cell_style,
            edge="1", parent="1", source=source, target=target,
        )
        geometry = ET.SubElement(cell, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            array = ET.SubElement(geometry, "Array", **{"as": "points"})
            for x, y in points:
                ET.SubElement(array, "mxPoint", x=str(x), y=str(y))


def group_style(kind, icon):
    """구성도의 영역. AWS 다이어그램처럼 채우지 않고 왼쪽 위에 아이콘을 둔다."""
    _, stroke, dashed = ZONE_STYLE[kind]
    if icon and "aws_group" in icon:
        return style(
            shape="mxgraph.aws4.group", grIcon=f"mxgraph.aws4.{icon['aws_group']}", outlineConnect="0",
            gradientColor="none", html="1", whiteSpace="wrap", fontSize="12", fontStyle="0", container="1",
            pointerEvents="0", collapsible="0", recursiveResize="0", verticalAlign="top", align="left",
            spacingLeft="30", fontColor=AWS_INK, strokeColor=AWS_INK, fillColor="none", dashed="0",
        )
    return style(
        rounded="0", whiteSpace="wrap", html="1", fontSize="12", fontStyle="0", container="1", collapsible="0",
        recursiveResize="0", verticalAlign="top", align="left", spacingLeft="34" if icon else "8",
        spacingTop="4" if icon else "2", fontColor=AWS_INK, fillColor="none", strokeColor=stroke,
        strokeWidth="2", dashed="1" if dashed else "0",
    )


def icon_style(icon, labeled=False):
    """aws_*는 aws-k8s-architecture-diagram 스킬 카탈로그(draw.io aws4)와 같은 스타일이다."""
    label = (
        {"fontColor": AWS_INK, "verticalLabelPosition": "bottom", "verticalAlign": "top", "align": "center",
         "fontSize": "12", "fontStyle": "0"} if labeled else {}
    )
    if "image" in icon:
        data = base64.b64encode((HERE / icon["image"]).read_bytes()).decode("ascii")
        return style(shape="image", html="1", aspect="fixed", imageAspect="1", **label, image=f"data:image/svg+xml,{data}")
    if "aws_resource" in icon:
        return style(
            sketch="0", outlineConnect="0", fillColor=icon.get("color", AWS_INK), strokeColor="#ffffff", dashed="0",
            html="1", aspect="fixed", **label, shape="mxgraph.aws4.resourceIcon",
            resIcon=f"mxgraph.aws4.{icon['aws_resource']}",
        )
    return style(
        sketch="0", outlineConnect="0", gradientColor="none", fillColor=AWS_INK, strokeColor="none", dashed="0",
        html="1", aspect="fixed", pointerEvents="1", **label, shape=f"mxgraph.aws4.{icon['aws_shape']}",
    )


def edge_style(route, kind):
    """선 종류는 스킬 규칙을 따른다. data = 진한 실선(요청·데이터), control = 회색 점선(관리 흐름)."""
    extra = {}
    if "exit" in route:
        extra.update(exitX=route["exit"][0], exitY=route["exit"][1], exitDx="0", exitDy="0")
    if "entry" in route:
        extra.update(entryX=route["entry"][0], entryY=route["entry"][1], entryDx="0", entryDy="0")
    base = dict(edgeStyle="orthogonalEdgeStyle", rounded="0", orthogonalLoop="1", jettySize="auto", html="1")
    if kind == "control":
        base.update(endArrow="open", endFill="0", strokeColor="#879196", strokeWidth="1", dashed="1", dashPattern="6 3")
    else:
        base.update(endArrow="classic", endFill="1", strokeColor=AWS_INK, strokeWidth="2")
    return style(**base, fontSize="11", labelBackgroundColor="#ffffff", **extra)


def text_style(**extra):
    """범례·출처 글 상자. 옅은 테두리 안에 여백을 두고 왼쪽 위부터 쓴다."""
    return style(**{"rounded": "0", "html": "1", "whiteSpace": "wrap", "align": "left", "verticalAlign": "top",
                    "spacingLeft": "8", "spacingTop": "4", "fontSize": "11", "strokeColor": "#D5DBDB",
                    "fillColor": "#ffffff", **extra})


def sources_line(meta):
    parts = [f"{s['name']} {s['version']}({s['status']} {s['date']})" for s in meta["sources"]]
    return "출처: " + ", ".join(parts) + ". 원본과 다르면 원본을 따른다."


def build_system_page(model):
    page = Page("구성도", "system")
    layout = model["layout"]["system"]
    origin = {}
    for zone in model["zones"]:
        icon = zone.get("icon")
        box = layout["zones"][zone["id"]]
        origin[zone["id"]] = box[:2]
        page.vertex(f"zone-{zone['id']}", escape(zone["label"]), group_style(zone["kind"], icon), box)
        if icon and "aws_group" not in icon:
            page.vertex(f"zone-{zone['id']}-icon", "", icon_style(icon), (8, 6, ZONE_ICON, ZONE_ICON), parent=f"zone-{zone['id']}")
    for comp in model["components"]:
        x, y = layout["components"][comp["id"]]
        zx, zy = origin[comp["zone"]]
        page.vertex(
            comp["id"], f"{escape(comp['label'])}<br>{escape(comp['sub'])}", icon_style(comp["icon"], labeled=True),
            (x - zx, y - zy, NODE_ICON, NODE_ICON), parent=f"zone-{comp['zone']}",
        )
    for flow in model["flows"]:
        if flow.get("drawn", True):
            route = layout["flows"].get(flow["id"], {})
            page.edge(flow["id"], str(flow["no"]), edge_style(route, flow["type"]), flow["from"], flow["to"],
                      points=route.get("points", ()))
    by_no = {f["no"]: f for f in model["flows"]}
    for i, item in enumerate(layout["legend"]):
        lines = [f"{n}. {escape(by_no[n]['label'])}" for n in item.get("flows", ())]
        lines += [escape(line) for line in item.get("lines", ())]
        page.vertex(f"legend-{i + 1}", f"<b>{escape(item['title'])}</b><br>" + "<br>".join(lines),
                    text_style(fontSize="12", fontColor=AWS_INK), item["box"])
    footer = (
        sources_line(model["meta"]) + " 아이콘: AWS Architecture Icons(draw.io 내장), Supabase·Vercel 공식 로고.<br>"
        + escape(model["icons"]["attribution"])
    )
    page.vertex("footer", footer, text_style(fontColor="#545B64"), layout["footer"])
    return page


def build_endpoint_page(model):
    page = Page("엔드포인트 표", "endpoints")
    lay = model["layout"]["endpoints"]
    widths = lay["widths"]
    zones = {z["id"]: z for z in model["zones"]}
    components = {c["id"]: c for c in model["components"]}
    order = lay["target_order"]

    columns = [("id", "ID", widths["id"]), ("method", "메서드", widths["method"]), ("path", "경로", widths["path"])]
    columns += [(role, short, widths["role"]) for role, short in ROLE_ORDER]
    columns += [(comp_id, components[comp_id]["label"], widths["target"]) for comp_id in order]
    total = sum(w for _, _, w in columns)

    def cell(cell_id, value, x, y, w, h, fill="#ffffff", **extra):
        page.vertex(cell_id, value, style(
            rounded="0", whiteSpace="wrap", html="1", strokeColor=GRID, fillColor=fill, fontSize="11", **extra,
        ), (x, y, w, h))

    x = lay["x"]
    y = lay["y"]
    for key, title, w in columns:
        fill = "#eeeeee"
        if key in components:
            fill = ZONE_STYLE[zones[components[key]["zone"]]["kind"]][0]
        cell(f"h-{key}", f"<b>{escape(title)}</b>", x, y, w, lay["header_height"], fill=fill)
        x += w
    y += lay["header_height"]

    for group in model["endpoint_groups"]:
        cell(group["id"], f"<b>{escape(group['label'])}</b>", lay["x"], y, total, lay["row_height"],
             fill=ZONE_STYLE["server"][0], align="left", spacingLeft="8")
        y += lay["row_height"]
        for ep in (e for e in model["endpoints"] if e["group"] == group["id"]):
            x = lay["x"]
            for key, _, w in columns:
                fill = "#ffffff"
                extra = {}
                if key == "id":
                    value = f"<b>{ep['id']}</b>"
                elif key == "method":
                    value = ep["method"]
                    extra = {"fontFamily": "Courier New"}
                elif key == "path":
                    value = escape(ep["path"])
                    extra = {"fontFamily": "Courier New", "align": "left", "spacingLeft": "6"}
                elif key in ep["roles"]:
                    value = ROLE_SYMBOL[ep["roles"][key]]
                elif key in ep["uses"]:
                    value = "AI" if key == "bedrock" else "●"
                    fill = ZONE_STYLE[zones[components[key]["zone"]]["kind"]][0]
                else:
                    value = ""
                cell(f"{ep['id']}-{key}", value, x, y, w, lay["row_height"], fill=fill, **extra)
                x += w
            y += lay["row_height"]

    legend = (
        "권한: " + ", ".join(f"{ROLE_SYMBOL[k]} {v}" for k, v in model["roles_legend"].items())
        + ". 색칠한 칸 = 그 엔드포인트가 쓰는 구성요소(세션 확인은 빼고 셈). AI = Bedrock 호출(예약 → 호출 → 정산).<br>"
        + sources_line(model["meta"])
    )
    page.vertex("legend", legend, text_style(), (lay["x"], y + 12, total, 40))
    return page


def render(model):
    mxfile = ET.Element("mxfile", host="generate_drawio.py")
    mxfile.append(build_system_page(model).diagram)
    mxfile.append(build_endpoint_page(model).diagram)
    ET.indent(mxfile, space="  ")
    return ET.tostring(mxfile, encoding="unicode") + "\n"


def find_drawio_cli():
    candidates = [os.environ.get("DRAWIO_CLI"), shutil.which("draw.io"), shutil.which("drawio")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Programs" / "draw.io" / "draw.io.exe"))
    candidates += [
        r"C:\Program Files\draw.io\draw.io.exe",
        "/Applications/draw.io.app/Contents/MacOS/draw.io",
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def export_png():
    cli = find_drawio_cli()
    if not cli:
        sys.exit("draw.io 데스크톱을 찾지 못했다. 설치하거나 DRAWIO_CLI 환경변수에 실행 파일 경로를 넣는다.")
    for index, out in PNG_PAGES.items():
        subprocess.run(
            [cli, "-x", "-f", "png", "-p", str(index), "-b", "10", "--disable-gpu", "-o", str(out), str(TARGET)],
            check=True, capture_output=True,
        )
        print(f"내보냄: {out.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="파일을 쓰지 않고 JSON과 .drawio가 같은지만 확인한다")
    parser.add_argument("--png", action="store_true", help=".drawio를 만든 뒤 페이지별 PNG도 내보낸다")
    args = parser.parse_args()

    model = json.loads(SOURCE.read_text(encoding="utf-8"))
    errors = validate(model)
    if errors:
        sys.exit("architecture.json 오류:\n" + "\n".join(f"- {e}" for e in errors))
    xml = render(model)

    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != xml:
            sys.exit("architecture.drawio가 architecture.json과 다르다. 생성 스크립트를 다시 실행한다.")
        print("일치: architecture.drawio = architecture.json")
        return

    TARGET.write_text(xml, encoding="utf-8", newline="\n")
    print(f"생성: {TARGET.name}")
    if args.png:
        export_png()


if __name__ == "__main__":
    main()
