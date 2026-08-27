import sys
import json
import base64
import os


def get_params():
    """Finds and decodes the base64 JSON payload from sys.argv."""
    for arg in reversed(sys.argv):
        try:
            padded_arg = arg + '=' * (-len(arg) % 4)
            decoded_bytes = base64.b64decode(padded_arg)
            decoded_str = decoded_bytes.decode('utf-8')
            if decoded_str.startswith('{') and decoded_str.endswith('}'):
                return json.loads(decoded_str)
        except Exception:
            continue
    raise ValueError("Worker did not receive a valid workspace JSON payload")


def target_shape(target, shapes):
    target_id = target["target_id"]
    if target_id not in shapes:
        raise ValueError(f"Operation target '{target_id}' has not been compiled")
    return shapes[target_id]


def compile_sketch(operation, context):
    import FreeCAD
    import Part

    plane_axes = {
        "XY": ("x", "y"),
        "XZ": ("x", "z"),
        "YZ": ("y", "z"),
    }
    plane_normals = {
        "XY": FreeCAD.Vector(0, 0, 1),
        "XZ": FreeCAD.Vector(0, 1, 0),
        "YZ": FreeCAD.Vector(1, 0, 0),
    }
    plane_id = operation["plane"]["target_id"].upper()
    if plane_id not in plane_axes:
        raise ValueError(f"Unsupported sketch plane '{plane_id}'")
    first_axis, second_axis = plane_axes[plane_id]

    def vector(x, y):
        coordinates = {"x": 0, "y": 0, "z": 0}
        coordinates[first_axis] = x
        coordinates[second_axis] = y
        return FreeCAD.Vector(coordinates["x"], coordinates["y"], coordinates["z"])

    local_points = {
        entity["id"]: (entity["x"], entity["y"])
        for entity in operation["entities"]
        if entity["type"] == "point"
    }
    points = {
        entity["id"]: vector(entity["x"], entity["y"])
        for entity in operation["entities"]
        if entity["type"] == "point"
    }
    outer_wires = []
    circle_wires = []
    for entity in operation["entities"]:
        entity_type = entity["type"]
        if entity_type == "corner_rectangle":
            first = local_points[entity["corner1_point_id"]]
            second = local_points[entity["corner2_point_id"]]
            corners = [
                vector(first[0], first[1]),
                vector(second[0], first[1]),
                vector(second[0], second[1]),
                vector(first[0], second[1]),
            ]
            outer_wires.append(Part.makePolygon(corners + [corners[0]]))
        elif entity_type == "center_rectangle":
            center = local_points[entity["center_point_id"]]
            corner = local_points[entity["corner_point_id"]]
            width = abs(corner[0] - center[0])
            height = abs(corner[1] - center[1])
            corners = [
                vector(center[0] - width, center[1] - height),
                vector(center[0] + width, center[1] - height),
                vector(center[0] + width, center[1] + height),
                vector(center[0] - width, center[1] + height),
            ]
            outer_wires.append(Part.makePolygon(corners + [corners[0]]))
        elif entity_type == "line":
            outer_wires.append(
                Part.makeLine(
                    points[entity["start_point_id"]],
                    points[entity["end_point_id"]],
                )
            )
        elif entity_type == "circle":
            center = points[entity["center_point_id"]]
            circle_wires.append(
                Part.Wire(
                    Part.makeCircle(
                        entity["diameter"] / 2,
                        center,
                        plane_normals[plane_id],
                    )
                )
            )

    if not outer_wires and not circle_wires:
        raise ValueError(f"Sketch '{operation['id']}' contains no supported geometry")
    faces = []
    circle_faces = [Part.Face(wire) for wire in circle_wires]
    for wire in outer_wires:
        try:
            face = Part.Face(wire)
            for circle_face in circle_faces:
                face = face.cut(circle_face)
            faces.append(face)
        except Part.OCCError:
            pass
    return Part.makeCompound(faces or circle_faces)


def compile_extrude(operation, context):
    import FreeCAD

    shape = target_shape(operation["target"], context["shapes"])
    normal = context["normals"].get(operation["target"]["target_id"])
    if normal is None:
        raise ValueError(f"Target '{operation['target']['target_id']}' has no extrusion plane")
    direction = normal * operation["distance"]
    if operation["reversed"]:
        direction = -direction
    if operation["symmetric"]:
        direction = direction * 2
        shape = shape.translated(-direction / 2)
    return shape.extrude(direction)


def compile_revolve(operation, context):
    import FreeCAD

    shape = target_shape(operation["target"], context["shapes"])
    axis_id = operation["axis"]["target_id"].upper()
    axes = {
        "X": FreeCAD.Vector(1, 0, 0),
        "Y": FreeCAD.Vector(0, 1, 0),
        "Z": FreeCAD.Vector(0, 0, 1),
    }
    if axis_id not in axes:
        raise ValueError(f"Unsupported revolve axis '{axis_id}'")
    return shape.revolve(FreeCAD.Vector(0, 0, 0), axes[axis_id], operation["angle"])


def compile_chamfer(operation, context):
    shape = target_shape(operation["target_edges"][0], context["shapes"])
    edges = [shape.Edges[target["index"]] for target in operation["target_edges"]]
    return shape.makeChamfer(operation["distance"], edges)


def compile_fillet(operation, context):
    shape = target_shape(operation["target_edges"][0], context["shapes"])
    edges = [shape.Edges[target["index"]] for target in operation["target_edges"]]
    return shape.makeFillet(operation["radius"], edges)


operation_handlers = {
    "sketch": compile_sketch,
    "extrude": compile_extrude,
    "revolve": compile_revolve,
    "chamfer_3d": compile_chamfer,
    "fillet_3d": compile_fillet,
}


def compile_workspace(workspace):
    import FreeCAD
    import Part

    document = FreeCAD.newDocument(workspace["name"])
    context = {
        "document": document,
        "shapes": {},
        "normals": {},
        "shape_kinds": {},
    }
    final_feature = None
    for workbench in workspace["workbenches"]:
        if workbench["type"] != "model":
            continue
        for operation in workbench["operations"]:
            handler = operation_handlers.get(operation["type"])
            if handler is None:
                raise ValueError(f"Unsupported operation type '{operation['type']}'")
            shape = handler(operation, context)
            feature = document.addObject("PartDesign::Feature", operation["id"])
            feature.Label = operation["name"]
            feature.Shape = shape
            context["shapes"][operation["id"]] = shape
            if operation["type"] == "sketch":
                plane_normals = {
                    "XY": FreeCAD.Vector(0, 0, 1),
                    "XZ": FreeCAD.Vector(0, 1, 0),
                    "YZ": FreeCAD.Vector(1, 0, 0),
                }
                context["normals"][operation["id"]] = plane_normals[
                    operation["plane"]["target_id"].upper()
                ]
                context["shape_kinds"][operation["id"]] = "profile"
            else:
                context["shape_kinds"][operation["id"]] = "solid"
            final_feature = feature
    document.recompute()
    if final_feature is None:
        raise ValueError("Workspace contains no model operations to export")
    solids = [
        shape
        for operation_id, shape in context["shapes"].items()
        if context["shape_kinds"].get(operation_id) == "solid"
    ]
    if len(solids) == 1:
        final_feature.Shape = solids[0]
    else:
        final_feature.Shape = solids[0].multiFuse(solids[1:]).removeSplitter()
    return document, final_feature


def export_stl(document, final_feature, output_dir, workspace_name):
    import Part

    os.makedirs(output_dir, exist_ok=True)
    filename = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in workspace_name
    )
    output_path = os.path.abspath(os.path.join(output_dir, f"{filename}.stl"))
    Part.export([final_feature], output_path)
    return output_path


try:
    payload = get_params()
    workspace = payload["workspace"]
    document, final_feature = compile_workspace(workspace)
    stl_path = export_stl(
        document,
        final_feature,
        payload["output_dir"],
        workspace["name"],
    )
    result = {
        "status": "success",
        "workspace_name": workspace["name"],
        "stl_path": stl_path,
    }
    print("JSON_OUTPUT:" + json.dumps(result), flush=True)
    os._exit(0)

except Exception as err:
    sys.stderr.write(f"Worker Error: {str(err)}\n")
    sys.stderr.flush()
    sys.exit(1)