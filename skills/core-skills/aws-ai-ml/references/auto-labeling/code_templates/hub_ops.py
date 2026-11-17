# Cell 0 [markdown]: Hub doors
# # Hub doors
#
# The project's Hub operations, one per run: resolve an input, register a DataSet, make a
# dataset-transformation view, promote an output as the next version, or clean up scratch
# DataSets. Anything that registers or deletes runs only after your yes.
# Cell 1: Configuration
ACTION = "[ACTION]"           # resolve | import-s3 | register | dt-view | register-output | promote | scratch
PROJECT_DIR = "[PROJECT_DIR]"  # the project directory (its run-log.jsonl records views, outputs and deletions)
REGION = None                 # [REGION]: the region; None = the session's (an ARN's own region wins)
# resolve
REF = None                    # [REF]: local path, s3:// URI or DataSet ARN
OUT = None                    # [OUT]: the local file the pipeline reads, e.g. <proj>/corpus/corpus.jsonl
DOWNLOAD = False              # True downloads a remote REF to OUT: the seed, the gold or review rows only; never the corpus (refused into corpus/)
# import-s3 / dt-view / register-output
S3_URI = None                 # [S3_URI]: import-s3: the object (or a folder with one .jsonl); dt-view: instead of ARN
NAME = None                   # [NAME]: import-s3 / dt-view with S3_URI / register-output: the DataSet name (from the conversation)
ARN = None                    # [ARN]: dt-view: the DataSet the dataset transformation job takes
HUB_NAME_OVERRIDE = None      # [HUB_NAME_OVERRIDE]: a hub other than the account's AI Registry hub
# register-output / promote
FROM_ARN = None               # [FROM_ARN]: the dataset transformation job's OutputDatasetArns entry (a version of the view)
TO_ARN = None                 # [TO_ARN]: promote: the labeled DataSet version the view was taken of (labeled_dataset.json's dataset_arn)
SOURCE_ARN = None             # [SOURCE_ARN]: register-output: the DataSet the job ran on, for the description
# register
LABELS = None                 # [LABELS]: register: the local labeled JSONL (the overlay rows)
S3_PREFIX = None              # [S3_PREFIX]: register: s3://bucket/prefix the file and its report upload under
REPORT = None                 # [REPORT]: register: held_out_report.json beside it (optional)
REPORT_HTML = None            # register: report.html (optional; ValidationReportS3Uri then points at it)
PROVENANCE = None             # [PROVENANCE]: register: the provenance sidecar `resolve` wrote (optional)
LABEL_SET = None              # [LABEL_SET]: register: JSON list of the classes (optional)
RUN_ID = None                 # [RUN_ID]: register: the run id in the description (optional)
APPEND = False                # register: the user agreed to add a version to the existing NAME
# scratch
DELETE = False                # True deletes each scratch version; run only after the customer said yes

import json
import sys
from pathlib import Path

from sagemaker.core import Attribution, set_attribution
from sagemaker.core.helper.session_helper import Session

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)

from sagemaker.ai_registry.data_preparer.auto_labeling.operators import print_client_reads
from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import (
    dt_handoff,
    hub_project,
    register,
)
from sagemaker.ai_registry.data_preparer.exceptions import DataPreparerOperatorError

print_client_reads()  # every client-side read of customer rows prints a `client-read:` line

# The corpus stays behind the API: a download into the project's corpus/ slot is refused.
if ACTION == "resolve" and DOWNLOAD and OUT and Path(OUT).parent.name == "corpus":
    sys.exit("ERROR: DOWNLOAD = True into corpus/ would copy the corpus to the client. The corpus "
             "is never downloaded: keep DOWNLOAD = False (the pointer and the first rows only). "
             "DOWNLOAD = True is for the seed, the gold or the review rows. Nothing was downloaded.")

# Cell 2: Run the action
try:
    if ACTION == "resolve":
        result = hub_project.resolve_input(REF, OUT, REGION, download=DOWNLOAD)
    elif ACTION == "import-s3":
        result = dt_handoff.register_s3_object(s3_uri=S3_URI, name=NAME,
                                               hub_name_override=HUB_NAME_OVERRIDE, region=REGION)
    elif ACTION == "register":
        prov = json.loads(Path(PROVENANCE).read_text()) if PROVENANCE else {}
        result = register.register_labeled_output(
            labels_path=LABELS, name=NAME, s3_prefix=S3_PREFIX, region=REGION or Session().boto_region_name,
            report_path=REPORT, report_html_path=REPORT_HTML, provenance=prov,
            label_set=json.loads(LABEL_SET) if LABEL_SET else None, hub_name_override=HUB_NAME_OVERRIDE,
            run_id=RUN_ID, allow_append=APPEND)
    elif ACTION == "dt-view":
        result = hub_project.dt_view_for_project(PROJECT_DIR, arn=ARN, s3_uri=S3_URI, name=NAME,
                                                 hub_name_override=HUB_NAME_OVERRIDE, region=REGION)
    elif ACTION == "register-output":
        result = hub_project.register_transform_output_for_project(
            PROJECT_DIR, from_arn=FROM_ARN, name=NAME, source_arn=SOURCE_ARN, region=REGION)
    elif ACTION == "promote":
        result = hub_project.promote_for_project(PROJECT_DIR, from_arn=FROM_ARN, to_arn=TO_ARN,
                                                 region=REGION)
    elif ACTION == "scratch":
        result = hub_project.cleanup_scratch(PROJECT_DIR, delete=DELETE)
    else:
        sys.exit(f"ACTION must be one of resolve, import-s3, register, dt-view, register-output, "
                 f"promote, scratch; got {ACTION!r}")
except DataPreparerOperatorError as e:
    sys.exit(f"ERROR: {e} Nothing was registered.")
print(json.dumps(result, indent=2))
