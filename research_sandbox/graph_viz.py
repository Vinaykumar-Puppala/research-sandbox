"""graph_viz.py — vis.js Network graph HTML generator for the Discovery Workspace."""
import json

VIS_CDN = (
    "https://cdn.jsdelivr.net/npm/vis-network@9.1.9"
    "/standalone/umd/vis-network.min.js"
)

NODE_COLORS: dict[str, dict] = {
    "dataset": {
        "background": "#4A90D9", "border": "#2C6FAC",
        "highlight": {"background": "#6AAEEE", "border": "#2C6FAC"},
        "hover":     {"background": "#6AAEEE", "border": "#2C6FAC"},
    },
    "discovery": {
        "background": "#F5A623", "border": "#C47D0E",
        "highlight": {"background": "#FFBD5A", "border": "#C47D0E"},
        "hover":     {"background": "#FFBD5A", "border": "#C47D0E"},
    },
    "pattern": {
        "background": "#27AE60", "border": "#1A7840",
        "highlight": {"background": "#52D68A", "border": "#1A7840"},
        "hover":     {"background": "#52D68A", "border": "#1A7840"},
    },
    "observation": {
        "background": "#9B59B6", "border": "#7D3C98",
        "highlight": {"background": "#C07FD4", "border": "#7D3C98"},
        "hover":     {"background": "#C07FD4", "border": "#7D3C98"},
    },
}

DEFAULT_COLOR = {
    "background": "#95A5A6", "border": "#717D7E",
    "highlight": {"background": "#ADB7B8", "border": "#717D7E"},
    "hover":     {"background": "#ADB7B8", "border": "#717D7E"},
}

LEGEND_ITEMS = [
    ("dataset",     "#4A90D9", "Dataset"),
    ("discovery",   "#F5A623", "Discovery"),
    ("pattern",     "#27AE60", "Pattern"),
    ("observation", "#9B59B6", "Observation"),
]


def _make_tooltip(node: dict) -> str:
    props: dict = {}
    if node.get("properties"):
        try:
            props = json.loads(node["properties"])
        except (json.JSONDecodeError, TypeError):
            pass

    lines = [
        f"<b>{node['label']}</b>",
        f"<em>Type: {node['node_type']}</em>",
    ]
    nt = node.get("node_type", "")
    if nt == "discovery":
        conf = props.get("confidence")
        if conf is not None:
            lines.append(f"Confidence: {float(conf):.2f}")
        disc_id = props.get("discovery_id", "")
        if disc_id:
            lines.append(f"ID: {disc_id[:12]}…")
    elif nt == "dataset":
        lines.append("Source dataset / table")
    elif nt == "pattern":
        lines.append("Extracted pattern")
    elif nt == "observation":
        lines.append("Evidence observation")

    return "<br>".join(lines)


def _build_vis_nodes(nodes: list[dict]) -> list[dict]:
    result = []
    for n in nodes:
        raw_label = n.get("label", "")
        display_label = raw_label if len(raw_label) <= 32 else raw_label[:29] + "…"
        result.append({
            "id":    n["node_id"],
            "label": display_label,
            "title": _make_tooltip(n),
            "color": NODE_COLORS.get(n.get("node_type", ""), DEFAULT_COLOR),
        })
    return result


def _build_vis_edges(edges: list[dict]) -> list[dict]:
    result = []
    for e in edges:
        result.append({
            "id":     e["edge_id"],
            "from":   e["source_node"],
            "to":     e["target_node"],
            "label":  e.get("relation", ""),
            "arrows": "to",
        })
    return result


def _build_legend_html() -> str:
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:14px;">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{color};'
        f'display:inline-block;margin-right:5px;"></span>{label}</span>'
        for _, color, label in LEGEND_ITEMS
    )
    return (
        f'<div style="font-family:sans-serif;font-size:12px;padding:6px 10px;'
        f'background:#f0f2f6;border-radius:4px;margin-bottom:6px;">'
        f'{items}</div>'
    )


def build_graph_html(
    nodes: list[dict],
    edges: list[dict],
    height: int = 600,
) -> str:
    """Return a self-contained HTML page embedding a vis.js Network graph.

    Parameters
    ----------
    nodes:
        List of dicts from db.graph(run_id)[0]. Expected keys: node_id,
        node_type, label, properties (JSON string).
    edges:
        List of dicts from db.graph(run_id)[1]. Expected keys: edge_id,
        source_node, target_node, relation.
    height:
        Pixel height of the graph div. Pass height+20 to components.html()
        to avoid an iframe scrollbar.
    """
    if not nodes:
        return (
            "<html><body style='font-family:sans-serif;color:#888;padding:20px;'>"
            "<p>No graph data available yet.</p></body></html>"
        )

    vis_nodes = _build_vis_nodes(nodes)
    vis_edges = _build_vis_edges(edges)
    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)
    legend_html = _build_legend_html()

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="{VIS_CDN}"></script>
  <style>
    body {{ margin: 0; padding: 4px; background: transparent; font-family: sans-serif; }}
    #graph-container {{ width: 100%; height: {height}px; border: 1px solid #ddd;
                        border-radius: 6px; background: #fafafa; }}
    div.vis-tooltip {{
      background: #2d2d2d !important; color: #fff !important;
      padding: 8px 12px !important; border-radius: 4px !important;
      font-size: 13px !important; max-width: 280px !important;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
    }}
  </style>
</head>
<body>
  {legend_html}
  <div id="graph-container"></div>
  <script>
    var visNodes = new vis.DataSet({nodes_json});
    var visEdges = new vis.DataSet({edges_json});
    var container = document.getElementById('graph-container');
    var network = new vis.Network(
      container,
      {{ nodes: visNodes, edges: visEdges }},
      {{
        layout: {{ improvedLayout: true }},
        physics: {{
          enabled: true,
          stabilization: {{ iterations: 200, updateInterval: 25 }},
          barnesHut: {{
            gravitationalConstant: -8000,
            springLength: 180,
            springConstant: 0.04,
            damping: 0.09
          }}
        }},
        interaction: {{
          hover: true,
          tooltipDelay: 80,
          zoomView: true,
          dragView: true,
          dragNodes: true,
          multiselect: false,
          navigationButtons: false
        }},
        nodes: {{
          shape: "ellipse",
          borderWidth: 2,
          shadow: {{ enabled: true, size: 4, x: 2, y: 2 }},
          font: {{ size: 13, face: "sans-serif" }}
        }},
        edges: {{
          width: 1.5,
          smooth: {{ type: "curvedCW", roundness: 0.15 }},
          font: {{ size: 11, align: "middle", strokeWidth: 0 }},
          color: {{ color: "#aaa", highlight: "#555", hover: "#555" }}
        }}
      }}
    );
    network.once('stabilizationIterationsDone', function () {{
      network.setOptions({{ physics: {{ enabled: false }} }});
    }});
  </script>
</body>
</html>"""
