#!/usr/bin/env python3
"""Explicit account inspection for sharing setup. Never print signed proofs."""

import argparse
import json

from aws_account import AccountReportingError, AwsAccountReporter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", help="An existing AWS SDK profile")
    args = parser.parse_args(argv)
    try:
        # Account inspection is not a reporting request and does not sign a
        # report. The caller supplies the real audience for prepare_report().
        reporter = AwsAccountReporter(
            "startup-advisor:account-inspection:report:v1", args.profile
        )
        reporter.setup()
    except AccountReportingError as error:
        print(json.dumps(error.as_result()))
        return 1
    # setup() returns the account to in-process UI callers. Hook/CLI output
    # exposed to an agent carries status only, never identity or proof.
    print(json.dumps({"status": "READY"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
