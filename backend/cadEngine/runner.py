import subprocess
import json
import os
import base64

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
# Direct path to the headless binary
FREECAD_CMD = os.path.join(ENGINE_DIR, "squashfs-root", "usr", "bin", "freecadcmd")
WORKER = os.path.join(ENGINE_DIR, "worker.py")

def build_cad_model(params: dict) -> dict:
    encoded_params = base64.b64encode(json.dumps(params).encode('utf-8')).decode('utf-8')
    
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
    params = {"width": 40}
    output = build_cad_model(params)
    print(output)