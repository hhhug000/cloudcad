import sys
import os
import json
import base64

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
    return {}

try:
    params = get_params()

    import FreeCAD
    import Part

    doc = FreeCAD.newDocument("CloudCAD")
    box = Part.makeBox(params.get("width", 10), 10, 10)
    doc.recompute()

    result = {"status": "ok", "volume": box.Volume}
    print("JSON_OUTPUT:" + json.dumps(result), flush=True)
    sys.stdout.flush()

    os._exit(0)

except Exception as err:
    sys.stderr.write(f"Worker Error: {str(err)}\n")
    sys.stderr.flush()
    os._exit(1)