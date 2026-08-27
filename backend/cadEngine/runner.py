import subprocess
import os
import base64
import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from schema import Workspace

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
FREECAD_CMD = os.path.join(ENGINE_DIR, "squashfs-root", "usr", "bin", "freecadcmd")
WORKER = os.path.join(ENGINE_DIR, "worker.py")

def build_cad_model(
    model_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str] = "output",
) -> dict:
    model_json = Path(model_path).read_text(encoding="utf-8")
    try:
        workspace = Workspace.model_validate_json(model_json)
    except ValidationError as error:
        raise ValueError(f"Invalid workspace JSON in '{model_path}':\n{error}") from error

    worker_payload = {
        "workspace": workspace.model_dump(mode="json"),
        "output_dir": str(Path(output_dir).resolve()),
    }
    encoded_params = base64.b64encode(
        json.dumps(worker_payload).encode("utf-8")
    ).decode("ascii")
    
    cmd = [FREECAD_CMD, WORKER, encoded_params]
    
    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=True,
            timeout=30
        )
    except subprocess.CalledProcessError as e:
        print("\n--- FREECAD STDOUT ---")
        print(e.stdout)
        print("\n--- FREECAD STDERR ---")
        print(e.stderr)
        raise e
    except subprocess.TimeoutExpired as e:
        print("\n--- FREECAD TIMED OUT ---")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        raise e
    
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("JSON_OUTPUT:"):
            raw_json = line.replace("JSON_OUTPUT:", "", 1)
            return json.loads(raw_json)
            
    raise RuntimeError(
        "FreeCAD completed but did not output a 'JSON_OUTPUT:' payload.\n"
        f"Raw STDOUT:\n{result.stdout}"
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate and process a CloudCAD workspace")
    parser.add_argument("model_path", type=Path, help="Path to a workspace JSON file")
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=Path("output"),
        help="Folder where the compiled STL is written (default: output)",
    )
    args = parser.parse_args()

    output = build_cad_model(args.model_path, args.output_dir)
    print(output)