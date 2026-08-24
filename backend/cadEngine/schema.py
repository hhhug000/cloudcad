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
    and nested assembly paths.
    """
    # 1. Scope & Hierarchy
    path: List[str] = Field(default_factory=list)
    # Target operation or datum object ID (e.g., "XY", "XZ", "YZ", "DatumPlane001", "extrude_1")
    target_id: str

    # 2. Reference Target Type
    # 'datum' for origin/custom planes, 'topology' for B-Rep sub-elements
    target_type: Literal["datum", "topology"] = "topology"

    # 3. Topological Metadata (used when target_type == "topology")
    element_type: Literal["face", "edge", "vertex"] = "face"
    role: Literal[
        "primary",        # Direct datum surface or primary face
        "cap_start",      # Bottom cap of extrusion/revolve
        "cap_end",        # Top cap of extrusion/revolve
        "side_wall",      # Wall generated from a 2D sketch entity
        "intersection",   # Edge/vertex where entities intersect
        "indexed"         # Fallback to direct indexing
    ] = "indexed"

    generator_ids: List[str] = Field(default_factory=list)

    # 4. Direct Selectors & Fallbacks
    native_selector: Optional[str] = None
    index: Optional[int] = None

    def to_freecad_selector(self) -> str:
        """
        Converts the universal reference into a FreeCAD-compatible sub-element string.
        """
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

    def to_freecad_support_tuple(self, doc) -> tuple:
        """
        Resolves and returns the exact tuple expected by FreeCAD properties 
        like `Sketch.Support` or `Feature.Support`.
        Format: (FreeCAD_Object, (SubElementSelector,))
        """
        obj = doc.getObject(self.target_id)
        if not obj:
            raise ValueError(f"Target object '{self.target_id}' not found in document.")

        return (obj, (self.to_freecad_selector(),))
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

# region Sketch Operation Schemas
class BaseSketchEntity(BaseModel):
    id: str
    name: str = "Untitled Sketch Entity"
    type: Literal["base"] = "base"

class LineEntity(BaseSketchEntity):
    name: str = "Line"
    type: Literal["line"] = "line"
    start_point: Point2D
    end_point: Point2D
    is_construction: bool = False

# All the different types of entities, used for discriminated union in pydantic
# A discriminated union is a way to define a type that can be one of several different types
SketchEntity = Annotated[
    Union[LineEntity],
    Field(discriminator="type")
]

class BaseSketchConstraint(BaseConstraint):
    name: str = "Untitled Sketch Constraint"

class DistanceConstraint(BaseSketchConstraint):
    name: str = "Distance Constraint"
    type: Literal["distance"] = "distance"
    # Entity IDs targeted by this constraint, like 2 points or a line and a point
    target_ids: List[str] = Field(min_length=1)
    value: float  # Dimensional value (in current workspace units)

# All the different types of constraints, used for discriminated union in pydantic
# A discriminated union is a way to define a type that can be one of several different types
SketchConstraint = Annotated[
    Union[DistanceConstraint],
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
    Union[SketchOperation],
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