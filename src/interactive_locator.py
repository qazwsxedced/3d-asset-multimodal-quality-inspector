"""Object-picking helpers for the inspection UI."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _normalise_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _issue_locator(issue: dict[str, Any]) -> dict[str, Any]:
    locator = issue.get("locator") or issue.get("location") or {}
    return locator if isinstance(locator, dict) else {}


def build_pickable_objects(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return stable object rows that can be selected in the 3D picker."""
    if not isinstance(result, dict):
        return []
    selected = result.get("selected_result", result)
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    names: dict[str, dict[str, Any]] = {}
    source_objects = metadata.get("source_mesh_objects", [])
    if isinstance(source_objects, list):
        for item in source_objects:
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                continue
            name = str(item["name"])
            names[_normalise_name(name)] = {
                "object_name": name,
                "face_count": item.get("face_count"),
                "vertex_count": item.get("vertex_count"),
                "issue_ids": [],
                "issue_titles": [],
            }
    if not names:
        for name in metadata.get("source_object_names", []) or []:
            if str(name).strip():
                names[_normalise_name(name)] = {
                    "object_name": str(name),
                    "face_count": None,
                    "vertex_count": None,
                    "issue_ids": [],
                    "issue_titles": [],
                }
    issues = selected.get("issues", []) if isinstance(selected, dict) else []
    if not isinstance(issues, list):
        issues = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        locator = _issue_locator(issue)
        issue_id = str(issue.get("issue_id", ""))
        title = str(issue.get("title_zh") or issue.get("title_en") or issue_id)
        object_names = list(locator.get("object_names", []) or [])
        object_names.extend(
            detail.get("object_name") or detail.get("name")
            for detail in locator.get("objects", []) or []
            if isinstance(detail, dict)
        )
        for name in object_names:
            key = _normalise_name(name)
            if not key:
                continue
            row = names.setdefault(
                key,
                {"object_name": str(name), "face_count": None, "vertex_count": None, "issue_ids": [], "issue_titles": []},
            )
            if issue_id and issue_id not in row["issue_ids"]:
                row["issue_ids"].append(issue_id)
            if title and title not in row["issue_titles"]:
                row["issue_titles"].append(title)
    return sorted(names.values(), key=lambda item: _normalise_name(item.get("object_name")))


def resolve_object_pick(
    object_name: str | None,
    result: dict[str, Any] | None,
    issue_id: str | None = None,
    face_id: int | None = None,
) -> dict[str, Any]:
    """Resolve a picked mesh name to its highest-priority issue, if present."""
    name_key = _normalise_name(object_name)
    if not name_key or not isinstance(result, dict):
        return {"status": "not_selected", "message": "尚未选择对象。"}
    selected = result.get("selected_result", result)
    issues = selected.get("issues", []) if isinstance(selected, dict) else []
    matches: list[dict[str, Any]] = []
    for issue in issues if isinstance(issues, list) else []:
        if not isinstance(issue, dict):
            continue
        issue_filter_match = False
        if issue_id:
            current_id = str(issue.get("issue_id", ""))
            short_id = current_id.split(":", 1)[-1]
            requested_id = str(issue_id).split(":", 1)[-1]
            if current_id != str(issue_id) and short_id != requested_id:
                continue
            issue_filter_match = True
        locator = _issue_locator(issue)
        names = list(locator.get("object_names", []) or [])
        names.extend(
            detail.get("object_name") or detail.get("name")
            for detail in locator.get("objects", []) or []
            if isinstance(detail, dict)
        )
        if issue_filter_match or any(_normalise_name(item) == name_key for item in names if item):
            matches.append(issue)
    severity_rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
    matches.sort(
        key=lambda item: (
            bool(item.get("blocking")),
            severity_rank.get(str(item.get("severity", "none")), 0),
        ),
        reverse=True,
    )
    if matches:
        issue = matches[0]
        return {
            "status": "matched",
            "object_name": object_name,
            "issue_id": issue.get("issue_id"),
            "title_zh": issue.get("title_zh"),
            "title_en": issue.get("title_en"),
            "matched_issue_count": len(matches),
            "locator": _issue_locator(issue),
            "picked_face_id": face_id,
            "picked_face_coordinate_space": "overlay_triangle" if face_id is not None else None,
        }
    return {
        "status": "object_without_issue",
        "object_name": object_name,
        "picked_face_id": face_id,
        "picked_face_coordinate_space": "overlay_triangle" if face_id is not None else None,
        "message": "对象已识别，但当前规则没有把它关联到问题卡片。",
    }


def _file_url(path: str | Path | None) -> str:
    if not path:
        return ""
    value = str(path)
    if value.startswith(("/file=", "http://", "https://")):
        return value
    return "/gradio_api/file=" + quote(value.replace("\\", "/"), safe="/:._-~")


def render_interactive_locator_html(
    model_path: str | Path | None,
    result: dict[str, Any] | None = None,
    language: str = "中文",
    issue_overlay_path: str | Path | None = None,
) -> str:
    """Render the picker shell consumed by the page-level JavaScript."""
    is_zh = language == "中文"
    payload = {"objects": build_pickable_objects(result), "has_result": isinstance(result, dict)}
    model_url = _file_url(model_path)
    issue_model_url = _file_url(issue_overlay_path)
    picker_path = issue_overlay_path or model_path
    try:
        model_bytes = Path(str(picker_path)).stat().st_size if picker_path else 0
    except (OSError, ValueError, TypeError):
        model_bytes = 0
    title = "点击模型对象定位问题" if is_zh else "Click a model object to locate issues"
    hint = (
        "点击模型中的对象；若该对象关联问题，右侧问题定位会自动展开。对象级拾取，面级证据仍以定位 JSON 为准。"
        if is_zh
        else "Click a mesh object. Object-level picking; face evidence remains canonical JSON."
    )
    empty = "检测后可点击对象" if is_zh else "Run inspection to enable object picking"
    rows_json = html.escape(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), quote=True)
    return (
        f"<div class='asset-interactive-locator' data-model-url='{html.escape(model_url, quote=True)}' "
        f"data-issue-model-url='{html.escape(issue_model_url, quote=True)}' "
        f"data-model-bytes='{model_bytes}' "
        f"data-pick-map='{rows_json}'>"
        f"<div class='asset-interactive-locator__header'><b>{html.escape(title)}</b>"
        f"<span class='asset-interactive-locator__status'>{html.escape(empty)}</span></div>"
        f"<div class='asset-interactive-locator__hint'>{html.escape(hint)}</div>"
        "<div class='asset-interactive-locator__body'><canvas class='asset-interactive-locator__canvas' aria-label='Interactive object picker'></canvas>"
        "<div class='asset-interactive-locator__objects'></div></div></div>"
    )


INTERACTIVE_LOCATOR_JS = r"""
() => {
  const state = window.__assetInspectorLocator || (window.__assetInspectorLocator = new WeakMap());
  const eventTarget = () => document.querySelector('#model-pick-event input, #model-pick-event textarea');
  const emitPick = (value) => {
    const input = eventTarget();
    if (!input) return;
    const text = typeof value === 'string' ? value : JSON.stringify(value || {});
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    if (setter) setter.call(input, text); else input.value = text;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  };
  const status = (root, text) => { const node = root.querySelector('.asset-interactive-locator__status'); if (node) node.textContent = text; };
  const buttons = (root, payload) => {
    const box = root.querySelector('.asset-interactive-locator__objects'); if (!box) return;
    box.innerHTML = '';
    const objects = Array.isArray(payload?.objects) ? payload.objects : [];
    if (!objects.length) { box.innerHTML = '<span class="asset-interactive-locator__muted">暂无可定位对象</span>'; return; }
    objects.forEach((item) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'asset-interactive-locator__object';
      button.textContent = item.issue_titles?.length ? `${item.object_name} · ${item.issue_titles.join('、')}` : item.object_name;
      button.addEventListener('click', () => { emitPick(item.object_name || ''); status(root, `已选择：${item.object_name || 'Unnamed object'}`); });
      box.appendChild(button);
    });
  };
  const fit = (scene, camera) => {
    const meshes = scene.meshes.filter((mesh) => mesh.getTotalVertices && mesh.getTotalVertices() > 0); if (!meshes.length) return;
    let min = new BABYLON.Vector3(Infinity, Infinity, Infinity), max = new BABYLON.Vector3(-Infinity, -Infinity, -Infinity);
    meshes.forEach((mesh) => { const box = mesh.getBoundingInfo().boundingBox; min = BABYLON.Vector3.Minimize(min, box.minimumWorld); max = BABYLON.Vector3.Maximize(max, box.maximumWorld); });
    camera.target = min.add(max).scale(0.5); camera.radius = Math.max(max.subtract(min).length() * 1.6, 1.2);
  };
  const loadScript = (src, marker, ready, label) => new Promise((resolve, reject) => {
    if (ready()) { resolve(); return; }
    let script = document.querySelector(`script[${marker}]`);
    if (!script) {
      script = document.createElement('script');
      script.src = src;
      script.setAttribute(marker, '1');
      document.head.appendChild(script);
    }
    const finish = () => ready() ? resolve() : reject(new Error(`${label}加载后不可用`));
    script.addEventListener('load', finish, {once: true});
    script.addEventListener('error', () => reject(new Error(`${label}加载失败`)), {once: true});
  });
  const ensureLoader = async () => {
    await loadScript(
      'https://cdn.babylonjs.com/v7.0.0/babylon.js',
      'data-asset-inspector-babylon-core',
      () => Boolean(window.BABYLON),
      'Babylon 核心库',
    );
    await loadScript(
      'https://cdn.babylonjs.com/v7.0.0/loaders/babylonjs.loaders.min.js',
      'data-asset-inspector-babylon-loader',
      () => Boolean(window.BABYLON?.SceneLoader),
      'Babylon 加载器',
    );
  };
  const init = async (root, force = false) => {
    if (!root) return;
    const previewLink = document.querySelector('#model-preview a[href]');
    const url = root.dataset.issueModelUrl || previewLink?.href || root.dataset.modelUrl;
    const previous = state.get(root);
    if (previous?.url === url && !force) return;
    state.set(root, {busy: false, url: url || null, initialized: true});
    let payload = {}; try { payload = JSON.parse(root.dataset.pickMap || '{}'); } catch (_) {}
    buttons(root, payload);
    if (!url) { status(root, '暂无可加载的模型；对象按钮仍可使用'); return; }
    if (!force) {
      const header = root.querySelector('.asset-interactive-locator__header');
      if (header && !header.querySelector('.asset-interactive-locator__load')) {
        const loadButton = document.createElement('button');
        loadButton.type = 'button';
        loadButton.className = 'asset-interactive-locator__load';
        loadButton.textContent = '加载 3D 定位 / Load 3D picker';
        loadButton.addEventListener('click', () => {
          loadButton.disabled = true;
          status(root, '正在加载大模型定位器，请稍候…');
          init(root, true);
        });
        header.appendChild(loadButton);
      }
      const modelBytes = Number(root.dataset.modelBytes || 0);
      const sizeHint = modelBytes >= 50 * 1024 * 1024
        ? `模型较大（${(modelBytes / 1024 / 1024).toFixed(1)} MB），已延迟加载 3D 定位器`
        : '3D 定位器已延迟加载';
      status(root, `${sizeHint}；对象按钮仍可使用`);
      return;
    }
    root.querySelector('.asset-interactive-locator__load')?.remove();
    const canvas = root.querySelector('.asset-interactive-locator__canvas');
    if (!canvas) { status(root, '3D 定位画布不可用'); return; }
    state.set(root, {busy: true, url});
    try {
      await ensureLoader();
      const engine = new BABYLON.Engine(canvas, true, {preserveDrawingBuffer: true, stencil: true});
      const scene = new BABYLON.Scene(engine); scene.clearColor = new BABYLON.Color4(0.97, 0.98, 1, 1);
      const camera = new BABYLON.ArcRotateCamera('asset-inspector-picker-camera', -Math.PI / 2, Math.PI / 2.6, 3, BABYLON.Vector3.Zero(), scene); camera.attachControl(canvas, true); camera.wheelPrecision = 80;
      new BABYLON.HemisphericLight('asset-inspector-picker-light', new BABYLON.Vector3(0, 1, 0), scene);
      const loaded = await BABYLON.SceneLoader.ImportMeshAsync('', '', url, scene); fit(scene, camera);
      const materialNameForPick = (mesh, faceId) => {
        let material = mesh?.material;
        const subMeshes = mesh?.subMeshes || [];
        const subMesh = subMeshes.find((item) => {
          const start = Math.floor((item.indexStart || 0) / 3), end = Math.floor(((item.indexStart || 0) + (item.indexCount || 0)) / 3);
          return faceId != null && faceId >= start && faceId < end;
        });
        if (subMesh && material?.subMaterials && material.subMaterials[subMesh.materialIndex]) material = material.subMaterials[subMesh.materialIndex];
        return material?.name || '';
      };
      scene.onPointerObservable.add((pointerInfo) => {
        if (pointerInfo.type !== BABYLON.PointerEventTypes.POINTERPICK) return;
        const pickInfo = pointerInfo.pickInfo || {};
        const mesh = pickInfo.pickedMesh;
        const name = mesh?.name || mesh?.parent?.name;
        if (!name) return;
        const materialName = materialNameForPick(mesh, pickInfo.faceId);
        const marker = 'issue_overlay_';
        const shortIssueId = materialName.startsWith(marker) ? materialName.slice(marker.length) : '';
        emitPick({object_name: name, issue_id: shortIssueId ? `defect:${shortIssueId}` : null, face_id: pickInfo.faceId ?? null, coordinate_space: shortIssueId ? 'overlay_triangle' : 'model_triangle'});
        status(root, shortIssueId ? `已选择问题区域：${shortIssueId}` : `已选择：${name}`);
      });
      engine.runRenderLoop(() => scene.render()); window.addEventListener('resize', () => engine.resize(), {passive: true});
      state.set(root, {engine, scene, camera, loaded, busy: false, url}); status(root, '可点击模型对象');
    } catch (error) { status(root, `模型拾取不可用：${error?.message || '加载失败'}`); state.set(root, {busy: false, url, error}); }
  };
  let scanTimer = null;
  const scan = () => {
    if (scanTimer) return;
    scanTimer = window.setTimeout(() => {
      scanTimer = null;
      document.querySelectorAll('.asset-interactive-locator').forEach(init);
    }, 50);
  };
  scan();
  new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
}
"""


INTERACTIVE_LOCATOR_CSS = """
.asset-interactive-locator{border:1px solid #d9e2ff;border-radius:10px;background:#fbfcff;padding:12px;margin:8px 0;color:#172033;font-family:inherit}.asset-interactive-locator__header{display:flex;justify-content:space-between;gap:12px;align-items:center;color:#1d39c4}.asset-interactive-locator__status{font-size:12px;color:#667085;font-weight:400}.asset-interactive-locator__hint{font-size:12px;color:#667085;margin:6px 0 10px}.asset-interactive-locator__body{display:grid;grid-template-columns:minmax(240px,1fr) minmax(170px,260px);gap:10px;align-items:stretch}.asset-interactive-locator__canvas{width:100%;height:260px;display:block;border-radius:8px;background:#f4f6fb}.asset-interactive-locator__objects{display:flex;flex-direction:column;gap:6px;max-height:260px;overflow:auto}.asset-interactive-locator__object,.asset-interactive-locator__load{border:1px solid #d9e2ff;background:white;border-radius:7px;padding:8px;text-align:left;cursor:pointer;color:#172033}.asset-interactive-locator__object:hover,.asset-interactive-locator__load:hover{border-color:#597ef7;background:#f0f5ff}.asset-interactive-locator__load{font-size:12px;white-space:nowrap}.asset-interactive-locator__muted{color:#98a2b3;font-size:12px;padding:8px}
"""
