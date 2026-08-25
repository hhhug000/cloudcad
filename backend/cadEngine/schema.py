# region Imports and Constants
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import AwareDatetime, BaseModel, Field, model_validator
# endregion

# region User Schemas
class UserRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    COMMENTER = "commenter"

class WorkspaceUser(BaseModel):
    id: str
    role: UserRole = UserRole.VIEWER
    active_workbench_id: Optional[str] = None
#endregion

# region Helper Enums and Schemas
class Point2D(BaseModel):
    x: float = 0.0
    y: float = 0.0

class MergeScopeType(str, Enum):
    AUTO = "auto"
    SELECTIVE = "selective"

class BooleanMode(str, Enum):
    NEW = "new"
    ADD = "add"
    REMOVE = "remove"
    INTERSECT = "intersect"

    def to_freecad_mode(self) -> str:
        mapping = {
            BooleanMode.NEW: "new_body",
            BooleanMode.ADD: "Fuse",
            BooleanMode.REMOVE: "Cut",
            BooleanMode.INTERSECT: "Common",
        }
        return mapping[self]

class MeasuringUnit(str, Enum):
    MM = "mm"
    CM = "cm"
    INCH = "in"
    FEET = "ft"
# endregion

# region Reference Schemas
class TargetRef(BaseModel):
    """
    Universal reference model for any element in the CAD workspace.
    Covers primary origin planes, custom datums, topological sub-elements,
    2D sketch entities, and nested assembly paths.
    """
    path: List[str] = Field(default_factory=list)
    target_id: str

    target_type: Literal["datum", "topology", "sketch_entity"] = "topology"

    element_type: Literal["face", "edge", "vertex", "curve", "point"] = "face"
    role: Literal[
        "primary",        # Direct datum surface or primary face/entity
        "cap_start",      # Bottom cap of extrusion/revolve
        "cap_end",        # Top cap of extrusion/revolve
        "side_wall",      # Wall generated from a 2D sketch entity
        "intersection",   # Edge/vertex where entities intersect
        "start",          # Start point of line/arc
        "end",            # End point of line/arc
        "center",         # Center point of circle/arc
        "midpoint",       # Midpoint of line/arc
        "indexed"         # Fallback to direct indexing
    ] = "indexed"

    generator_ids: List[str] = Field(default_factory=list)

    native_selector: Optional[str] = None
    index: Optional[int] = None

    def to_freecad_selector(self) -> str:
        if self.target_type == "datum":
            return "Face1"

        if self.native_selector:
            return self.native_selector

        if self.role == "cap_start":
            return "cap:start"
        if self.role == "cap_end":
            return "cap:end"

        if self.role == "side_wall" and self.generator_ids:
            return f"Face;{self.target_id}.{self.generator_ids[0]}"

        if self.role == "intersection" and len(self.generator_ids) >= 2:
            return f"Edge;{self.generator_ids[0]}x{self.generator_ids[1]}"

        if self.index is not None:
            return f"{self.element_type.capitalize()}{self.index + 1}"

        return f"{self.element_type.capitalize()}1"

    def to_freecad_pos_id(self) -> int:
        """
        Maps target roles to FreeCAD Sketcher Point PosId integers:
        0 = None (Whole curve/line), 1 = Start point, 2 = End point, 3 = Center/Midpoint.
        """
        pos_map = {
            "primary": 0,
            "indexed": 0,
            "start": 1,
            "end": 2,
            "center": 3,
            "midpoint": 3,  # Maps to FreeCAD's arc mid-point index
        }
        return pos_map.get(self.role, 0)
#endregion

# region Operation Schemas
class BaseOperation(BaseModel):
    id: str
    name: str = "Untitled Operation"
    type: Literal["base"] = "base"

class BaseConstraint(BaseModel):
    id: str
    name: str = "Untitled Constraint"
    type: Literal["base"] = "base"

class ExtrudeOperation(BaseOperation):
    name: str = "Extrude"
    type: Literal["extrude"] = "extrude"
    
    # Universal reference: targets a full sketch, a sketch sub-profile loop, or a 3D face
    target: TargetRef
    
    distance: float = 10.0
    symmetric: bool = False
    reversed: bool = False
    mode: BooleanMode = BooleanMode.ADD

    # Merge Scope Controls
    merge_scope_type: MergeScopeType = MergeScopeType.AUTO
    # Populated only if merge_scope_type == MergeScopeType.SELECTIVE
    target_body_ids: List[str] = Field(default_factory=list)


class RevolveOperation(BaseOperation):
    name: str = "Revolve"
    type: Literal["revolve"] = "revolve"
    
    # Target profile (full sketch, sub-profile loop, or 3D face)
    target: TargetRef
    
    # Axis reference (e.g., target_id="line_3" inside sketch, or origin axis "Z")
    axis: TargetRef
    
    angle: float = 360.0
    mode: BooleanMode = BooleanMode.ADD

    # Merge Scope Controls
    merge_scope_type: MergeScopeType = MergeScopeType.AUTO
    # Populated only if merge_scope_type == MergeScopeType.SELECTIVE
    target_body_ids: List[str] = Field(default_factory=list)


class Chamfer3DOperation(BaseOperation):
    name: str = "3D Chamfer"
    type: Literal["chamfer_3d"] = "chamfer_3d"
    target_edges: List[TargetRef] = Field(min_length=1)
    distance: float = 1.0


class Fillet3DOperation(BaseOperation):
    name: str = "3D Fillet"
    type: Literal["fillet_3d"] = "fillet_3d"
    target_edges: List[TargetRef] = Field(min_length=1)
    radius: float = 2.0

# region Sketch Operation Schemas
class BaseSketchEntity(BaseModel):
    id: str
    name: str = "Untitled Sketch Entity"
    type: Literal["base"] = "base"

class PointEntity(BaseSketchEntity):
    name: str = "Point"
    type: Literal["point"] = "point"
    x: float = 0.0
    y: float = 0.0
    is_construction: bool = False

class LineEntity(BaseSketchEntity):
    name: str = "Line"
    type: Literal["line"] = "line"
    start_point_id: str
    end_point_id: str
    is_construction: bool = False

class CircleEntity(BaseSketchEntity):
    name: str = "Circle"
    type: Literal["circle"] = "circle"
    center_point_id: str
    diameter: float = 20.0
    is_construction: bool = False

class Arc3PointEntity(BaseSketchEntity):
    name: str = "3-Point Arc"
    type: Literal["arc_3point"] = "arc_3point"
    start_point_id: str
    end_point_id: str
    mid_point_id: str  # Point on the arc pass-through path
    is_construction: bool = False

class CornerRectangleEntity(BaseSketchEntity):
    name: str = "Corner Rectangle"
    type: Literal["corner_rectangle"] = "corner_rectangle"

    # Primary macro inputs
    corner1_point_id: str
    corner2_point_id: str

    # Explicit generated sub-element IDs for solver constraints
    top_left_point_id: str
    top_right_point_id: str
    bottom_right_point_id: str
    bottom_left_point_id: str

    line_top_id: str
    line_right_id: str
    line_bottom_id: str
    line_left_id: str

    is_construction: bool = False


class CenterRectangleEntity(BaseSketchEntity):
    name: str = "Center Rectangle"
    type: Literal["center_rectangle"] = "center_rectangle"

    # Primary macro controls
    center_point_id: str
    corner_point_id: str

    # Explicit generated sub-element IDs for solver constraints
    top_left_point_id: str
    top_right_point_id: str
    bottom_right_point_id: str
    bottom_left_point_id: str

    line_top_id: str
    line_right_id: str
    line_bottom_id: str
    line_left_id: str

    is_construction: bool = False

class SketchFilletEntity(BaseSketchEntity):
    name: str = "Sketch Fillet"
    type: Literal["fillet"] = "fillet"
    radius: float = 5.0
    vertex_point: Optional[TargetRef] = None
    target_entities: List[TargetRef] = Field(default_factory=list, max_length=2)
    
    arc_entity_id: Optional[str] = None
    center_point_id: Optional[str] = None
    
    @model_validator(mode="after")
    def validate_fillet_targets(self) -> "SketchFilletEntity":
        if not self.vertex_point and len(self.target_entities) < 2:
            raise ValueError(
                "A Fillet must specify either a 'vertex_point' or exactly 2 'target_entities'."
            )
        return self

# All the different types of entities, used for discriminated union in pydantic
# A discriminated union is a way to define a type that can be one of several different types
SketchEntity = Annotated[
    Union[PointEntity, LineEntity, CircleEntity, Arc3PointEntity, CornerRectangleEntity, CenterRectangleEntity, SketchFilletEntity],
    Field(discriminator="type")
]

class BaseSketchConstraint(BaseConstraint):
    name: str = "Untitled Sketch Constraint"

    @property
    def primary_target(self) -> TargetRef:
        """
        Returns the primary target regardless of whether the model uses
        'first_target' or 'target'.
        """
        if hasattr(self, "first_target"):
            return getattr(self, "first_target")
        if hasattr(self, "target"):
            return getattr(self, "target")
        raise AttributeError(f"Constraint {self.type} has no target attribute.")

class DistanceConstraint(BaseSketchConstraint):
    name: str = "Distance Constraint"
    type: Literal["distance"] = "distance"
    first_target: TargetRef
    second_target: Optional[TargetRef] = None
    value: float = Field(gt=0, description="Distance value in model units")


class HorizontalConstraint(BaseSketchConstraint):
    name: str = "Horizontal Constraint"
    type: Literal["horizontal"] = "horizontal"
    first_target: TargetRef
    second_target: Optional[TargetRef] = None


class VerticalConstraint(BaseSketchConstraint):
    name: str = "Vertical Constraint"
    type: Literal["vertical"] = "vertical"
    first_target: TargetRef
    second_target: Optional[TargetRef] = None


class ParallelConstraint(BaseSketchConstraint):
    name: str = "Parallel Constraint"
    type: Literal["parallel"] = "parallel"
    first_target: TargetRef
    second_target: TargetRef


class CoincidentConstraint(BaseSketchConstraint):
    """Constrains two points, or a point and an entity, to occupy the same position."""
    name: str = "Coincident Constraint"
    type: Literal["coincident"] = "coincident"
    first_target: TargetRef
    second_target: TargetRef


class TangentConstraint(BaseSketchConstraint):
    """Constrains an arc/circle and a line (or two arcs/circles) to be tangent."""
    name: str = "Tangent Constraint"
    type: Literal["tangent"] = "tangent"
    first_target: TargetRef
    second_target: TargetRef


class RadiusConstraint(BaseSketchConstraint):
    """Fixes the radius of an arc or circle."""
    name: str = "Radius Constraint"
    type: Literal["radius"] = "radius"
    target: TargetRef
    value: float = Field(gt=0, description="Radius value in model units")


class DiameterConstraint(BaseSketchConstraint):
    """Fixes the diameter of an arc or circle."""
    name: str = "Diameter Constraint"
    type: Literal["diameter"] = "diameter"
    target: TargetRef
    value: float = Field(gt=0, description="Diameter value in model units")


class PerpendicularConstraint(BaseSketchConstraint):
    """Constrains two lines to remain at a 90-degree angle to each other."""
    name: str = "Perpendicular Constraint"
    type: Literal["perpendicular"] = "perpendicular"
    first_target: TargetRef
    second_target: TargetRef


class EqualConstraint(BaseSketchConstraint):
    """Constrains two lines to equal length, or two arcs/circles to equal radius."""
    name: str = "Equal Constraint"
    type: Literal["equal"] = "equal"
    first_target: TargetRef
    second_target: TargetRef

# All the different types of constraints, used for discriminated union in pydantic
# A discriminated union is a way to define a type that can be one of several different types
SketchConstraint = Annotated[
    Union[DistanceConstraint, HorizontalConstraint, VerticalConstraint, ParallelConstraint, CoincidentConstraint, TangentConstraint, RadiusConstraint, DiameterConstraint, PerpendicularConstraint, EqualConstraint],
    Field(discriminator="type")
]

class SketchOperation(BaseOperation):
    name: str = "Untitled Sketch"
    type: Literal["sketch"] = "sketch"
    plane: TargetRef = Field(
        default_factory=lambda: TargetRef(target_id="XY", target_type="datum")
    )
    # A list of sketch entities, like lines, circles, arcs or rectangles
    entities: List[SketchEntity] = Field(default_factory=list)
    # A list of constraints, like dimension, horizontal, vertical, tangent or equal
    constraints: List[SketchConstraint] = Field(default_factory=list)
# endregion

# All the different types of operations, used for discriminated union in pydantic
# A discriminated union is a way to define a type that can be one of several different types
Operation = Annotated[
    Union[SketchOperation, ExtrudeOperation, RevolveOperation, Chamfer3DOperation, Fillet3DOperation],
    Field(discriminator="type")
]
# endregion

# region Workbench Schemas
class BaseWorkbench(BaseModel):
    id: str
    name: str = "Untitled Workbench"
    type: Literal["base"] = "base"
    # When the workbench is created and last updated, in ISO-8601 format with timezone offset
    # like "2023-08-01T12:34:56+00:00"
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ModelWorkbench(BaseWorkbench):
    name: str = "Untitled Model"
    type: Literal["model"] = "model"
    # A list of all operations parametrized by the user, in order of creation, to be applied to the model
    operations: List[Operation] = Field(default_factory=list)

class DocWorkbench(BaseWorkbench):
    name: str = "Untitled Document"
    type: Literal["document"] = "document"
    content: str = ""

    @model_validator(mode="after")
    def set_default_content(self) -> "DocWorkbench":
        if "content" not in self.__pydantic_fields_set__:
            self.content = f"# {self.name}"
        return self

# All the different types of workbenches, used for discriminated union in pydantic
# A discriminated union is a way to define a type that can be one of several different types
Workbench = Annotated[
    Union[ModelWorkbench, DocWorkbench],
    Field(discriminator="type")
]
# endregion

# region Workspace Schema
class Workspace(BaseModel):
    # Workspace ID, prob gonna be UUID4 string, like "550e8400-e29b-41d4-a716-446655440000"
    id: str
    # The current schema version, so new versions wont break old workspaces, use semantic versioning, like "1.0.0", "1.1.2", "2.0.0"
    # Semantic versioning: https://semver.org/
    # 1st num for breaking non backwards compatible changes, 2nd num for new features but backwards compatible, 3rd num for bug fixes
    schema_version: str = "1.0.0"
    # When the workspace is created and last updated, in ISO-8601 format with timezone offset
    # like "2023-08-01T12:34:56+00:00"
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # The name of the workspace, default to "Untitled Workspace"
    name: str = "Untitled Workspace"
    # Base64 encoded thumbnail image, optional, can be None
    # To avoid rerendering model every time its viewed in list, thumbnail is stored like this:
    # data:image/png;base64,iVBORw0KGgo...
    thumbnail: Optional[str] = None
    # List of users in the workspace, with a user id, a role and an active workbench id
    # List of user structs
    users: List[WorkspaceUser] = Field(default_factory=list)
    # Units of the workspace, defaults to milimeters (mm), can be changed to centimeters (cm), inches (in), or feet (ft)
    units: MeasuringUnit = MeasuringUnit.MM
    # A list of workbenches in the workspace
    workbenches: List[Workbench] = Field(default_factory=list)
    # Generic metadata to store aditional information about the workspace, like tags, description, etc.
    # This is a dictionary of key-value pairs, where keys are strings and values can be any JSON serializable type.
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_active_workbench_ids(self) -> "Workspace":
        valid_workbench_ids = {workbench.id for workbench in self.workbenches}
        for user in self.users:
            if user.active_workbench_id and user.active_workbench_id not in valid_workbench_ids:
                raise ValueError(
                    f"User '{user.id}' references active_workbench_id '{user.active_workbench_id}', "
                    f"which does not exist in workspace workbenches."
                )
        return self
# endregion 