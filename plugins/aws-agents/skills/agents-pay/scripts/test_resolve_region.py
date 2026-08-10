import sys
import json
import tempfile
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents_pay_admin as m

d = tempfile.mkdtemp()
cfg = Path(d) / "config.json"
cfg.write_text(json.dumps({"resources": {"region": "us-east-1"}, "policy": {}}))

_saved_region = os.environ.pop("AWS_REGION", None)
_saved_default_region = os.environ.pop("AWS_DEFAULT_REGION", None)
try:
    assert m.resolve_region("eu-west-1", cfg) == "eu-west-1", "flag should win"

    os.environ["AWS_REGION"] = "ap-southeast-2"
    assert m.resolve_region(None, cfg) == "ap-southeast-2", "env should win over config"
    del os.environ["AWS_REGION"]

    assert m.resolve_region(None, cfg) == "us-east-1", "config region should be used, not hardcoded us-west-2"

    empty_cfg = Path(d) / "empty.json"
    empty_cfg.write_text(json.dumps({"resources": {}, "policy": {}}))
    assert m.resolve_region(None, empty_cfg) is None, "should fall through to None, not us-west-2"
finally:
    if _saved_region is not None:
        os.environ["AWS_REGION"] = _saved_region
    if _saved_default_region is not None:
        os.environ["AWS_DEFAULT_REGION"] = _saved_default_region

print("ALL RESOLVE_REGION TESTS PASSED")
