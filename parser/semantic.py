from __future__ import annotations

import json
from typing import Any

def extract_style_system(raw_export: dict[str, Any]) -> dict[str, Any]:
    """
    Extract all unique style definitions into a global style map.
    Returns a dictionary of raw style configurations.
    """
    styles = raw_export.get("styles", {})
    if not isinstance(styles, dict):
        return {}

    style_system = {}
    for style_id, style_data in styles.items():
        if not isinstance(style_data, dict):
            continue
        
        # Only copy over properties that define the actual style
        name = style_data.get("name")
        if name:
            style_system[style_id] = {"name": name, "properties": style_data.get("properties", {})}
    
    return style_system

def extract_element_id_map(raw_export: dict[str, Any]) -> dict[str, str]:
    """
    Create a root dictionary mapping custom element IDs to their human-readable names.
    """
    id_map: dict[str, str] = {}

    def traverse(node: Any):
        if not node:
            return
        
        if isinstance(node, list):
            for item in node:
                traverse(item)
        elif isinstance(node, dict):
            # If it's a generic dictionary, could be an element
            _id = node.get("id") or node.get("_id") or node.get("uid") or node.get("unique_id")
            
            # For exact custom element properties
            props = node.get("properties") or {}
            custom_id = props.get("custom_id")
            
            name = node.get("name") or node.get("display_name") or node.get("label") or props.get("name")
            
            if custom_id and name:
                id_map[str(custom_id).strip()] = str(name).strip()
            # fallback to generic ids if it doesn't have custom_id but still has a name
            elif _id and name:
                id_map[str(_id).strip()] = str(name).strip()

            for key, val in node.items():
                traverse(val)

    traverse(raw_export)
    return id_map

def extract_dom_skeleton(elements_container: Any) -> list[dict[str, Any]]:
    """
    Recursively extract a simplified DOM skeleton from an elements container.
    Retains only type, id, name, and nested elements.
    """
    skeleton = []
    
    items: list[tuple[str, Any]] = []
    if isinstance(elements_container, list):
        items = [(str(i), x) for i, x in enumerate(elements_container) if isinstance(x, dict)]
    elif isinstance(elements_container, dict):
        items = [(k, v) for k, v in elements_container.items() if isinstance(v, dict)]
        
    for _key, node in items:
        # Determine basic fields
        _type = node.get("type")
        _id = node.get("id") or node.get("_id") or node.get("uid") or node.get("unique_id")
        
        props = node.get("properties") or {}
        name = node.get("name") or node.get("display_name") or node.get("label") or props.get("name")
        
        skeleton_node: dict[str, Any] = {}
        if _type:
            skeleton_node["type"] = _type
        if _id:
            skeleton_node["id"] = _id
        if name:
            skeleton_node["name"] = name
            
        child_elements = extract_dom_skeleton(node.get("elements"))
        if child_elements:
            skeleton_node["elements"] = child_elements
            
        # Only add valid nodes (ones that have at least a type or id)
        if skeleton_node and ("type" in skeleton_node or "id" in skeleton_node):
            skeleton.append(skeleton_node)
            
            
    return skeleton

def stringify_ast(node: Any, depth: int = 0) -> str:
    """
    Recursively evaluate a Bubble AST node to output a pseudo-code string.
    """
    if depth > 10:
        return "..."
    if node is None or node == "":
        return ""
        
    if isinstance(node, str):
        return node
        
    if isinstance(node, (int, float, bool)):
        return str(node)
        
    if isinstance(node, list):
        items = [stringify_ast(x, depth + 1) for x in node if x is not None]
        # Use space instead of AND for lists since they could be TextExpression entries
        return "".join([i for i in items if i])
        
    if isinstance(node, dict):
        # Base cases to extract from nodes
        node_type = node.get("type") or node.get("_type") or ""
        name = node.get("name") or node.get("display") or node.get("display_name") or ""
        value = node.get("value")
        
        # AST elements like expression or conditions
        if "entries" in node:
            return stringify_ast(node["entries"], depth + 1)
            
        if "expression" in node:
            return stringify_ast(node["expression"], depth + 1)
            
        if "args" in node:
            args_str = stringify_ast(node["args"], depth + 1)
            return f"{node_type}({args_str})" if node_type else f"({args_str})"
            
        if node_type or name:
            if value is not None:
                return f"{name or node_type} = {stringify_ast(value, depth + 1)}"
            return f"[{name or node_type}]"
            
        # Fallback for dicts
        parts = []
        for k, v in node.items():
            if k not in ["type", "_type", "id", "_id", "uid", "unique_id"]:
                val_str = stringify_ast(v, depth + 1)
                if val_str:
                    parts.append(val_str)
        return " | ".join(parts[:3]) # Limit noise
        
    return ""

def inject_ast_interpretations(node: Any) -> None:
    """
    Recursively traverse export payloads and inject __ai_interpretation_*__ 
    fields where complex AST patterns are found. Modifies the dict in place.
    """
    if isinstance(node, list):
        for item in node:
            inject_ast_interpretations(item)
    elif isinstance(node, dict):
        keys_to_interpret = ["condition", "expression", "states", "args", "actions", "properties"]
        
        # Recurse children
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                inject_ast_interpretations(v)
        
        # Inject translations for specific AST-heavy keys
        interpretations = {}
        for k, v in node.items():
            if k in keys_to_interpret and isinstance(v, (dict, list)):
                interp = stringify_ast(v)
                if interp and len(str(interp)) > 2:  # Avoid empty strings
                    interpretations[f"__ai_interpretation_{k}__"] = str(interp)
                    
        # Specific TextExpression or composite string detection
        if "entries" in node and isinstance(node["entries"], list):
            interp = stringify_ast(node["entries"])
            if interp:
                interpretations["__ai_resolved_text__"] = str(interp)
                
        # Apply interpretations
        node.update(interpretations)

def generate_workflow_summary(workflows: list[Any], page_name: str = "") -> str:
    """
    Generate a markdown summary of a collection of workflows.
    `workflows` is a list of Entity objects for a given page/reusable.
    """
    summary = ""
    if page_name:
        summary += f"# Workflows for {page_name}\n\n"
        
    if not workflows:
        return summary + "No workflows found.\n"
        
    for wf in workflows:
        wf_name = wf.source_name
        summary += f"## {wf_name}\n"
        
        raw = getattr(wf, "raw", {})
        if not isinstance(raw, dict):
            summary += "- (Invalid workflow payload)\n\n"
            continue
            
        actions = raw.get("actions", [])
        
        items: list[tuple[str, Any]] = []
        if isinstance(actions, list):
            items = [(str(i), x) for i, x in enumerate(actions) if isinstance(x, dict)]
        elif isinstance(actions, dict):
            items = [(k, v) for k, v in actions.items() if isinstance(v, dict)]
            
        if not items:
            summary += "- No actions defined.\n"
            
        for _key, action in items:
            action_type = action.get("type", "UnknownAction")
            action_name = action.get("name") or action.get("display_name") or action.get("label") or action_type
            summary += f"- **{action_type}**: {action_name}\n"
            
        summary += "\n"
        
    return summary
