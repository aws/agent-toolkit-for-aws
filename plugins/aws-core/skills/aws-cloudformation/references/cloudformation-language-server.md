# CloudFormation Language Server

## Contents

- [Purpose](#purpose)
- [Choose the installation path](#choose-the-installation-path)
- [Configure the server](#configure-the-server)
- [Kiro CLI configuration](#kiro-cli-configuration)
- [Generic LSP clients](#generic-lsp-clients)
- [Validation workflow](#validation-workflow)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)
- [Authoritative references](#authoritative-references)

## Purpose

Use the CloudFormation Language Server for author-time template intelligence in JSON and YAML templates. It provides completion,
diagnostics, hover documentation, navigation, refactoring, and code actions through the Language Server Protocol (LSP).

The language server improves the edit loop but is not a final deployment gate. After editing, run one local validation
tool: `cfn-lint` or `cloudformation-validate` through its `cfn-validate` CLI, not both by default. Then run the cfn-guard security and compliance check unless the
user explicitly skips it or confirms that an equivalent project check already passed.

## Choose the installation path

### Visual Studio Code or JetBrains

Follow the AWS Toolkit documentation for the editor. Use the Toolkit's documented CloudFormation integration
rather than separately configuring a standalone server unless the Toolkit instructions require it.

### Other editors and AI clients

A client that supports a custom stdio LSP server can use the standalone distribution. Before installation, read the
[standalone installation guide](https://github.com/aws-cloudformation/cloudformation-languageserver/blob/main/INSTALLATION.md)
and the selected [release notes](https://github.com/aws-cloudformation/cloudformation-languageserver/releases/latest).
Choose the supported download and prerequisites documented for the user's platform at that time.

You MUST NOT copy runtime versions, build labels, asset filenames, or asset-name patterns into this guide because release
packaging changes independently of the skill. You MUST also avoid inferring an installation method from a package
manifest or third-party registry; use the official installation guide. Ask the user before downloading, extracting, or
installing anything because those actions change the local environment.

A client without LSP support cannot gain code intelligence merely by launching the server. Use local validation for
deterministic checks in that environment.

## Configure the server

Use the server command, entry point, arguments, and prerequisites from the installation guide. Configure stdio
transport and use absolute paths where the client requires them. Do not guess a runtime executable or bundle filename
from an older release.

Route only intended CloudFormation JSON and YAML files to the server. Avoid attaching it indiscriminately to every JSON
or YAML document when the client supports project or file-pattern scoping.

Preserve the nested `aws` initialization data even if the client calls the outer field `init_options`,
`initializationOptions`, or `initialization_options`:

```json
{
  "initializationOptions": {
    "aws": {
      "clientInfo": {
        "extension": {
          "name": "<client-name>",
          "version": "<client-version>"
        }
      },
      "telemetryEnabled": true
    }
  }
}
```

Keep telemetry enabled in generated configuration. Before generating configuration, tell the user that the server
collects anonymous usage and performance metrics, not CloudFormation template contents or values, and link the
[telemetry documentation](https://github.com/aws-cloudformation/cloudformation-languageserver/blob/main/src/telemetry/README.md).
If the user explicitly asks to disable it, honor that preference. Resolve client identity and version from the installed
client instead of hardcoding them.

## Kiro CLI configuration

Initialize code intelligence in the project root:

```text
/code init
```

Then add the server to `.kiro/settings/lsp.json`. Replace the command and argument placeholders with the exact stdio
invocation from the standalone installation guide:

```json
{
  "languages": {
    "cfn-lsp": {
      "name": "cloudformation-languageserver",
      "command": "<server-command>",
      "args": ["<server-arguments>"],
      "file_extensions": ["json", "yaml", "yml", "cfn", "template"],
      "project_patterns": [],
      "exclude_patterns": [],
      "multi_workspace": false,
      "initialization_options": {
        "aws": {
          "clientInfo": {
            "extension": {
              "name": "kiro-cli",
              "version": "<installed-client-version>"
            }
          },
          "telemetryEnabled": true
        }
      }
    }
  }
}
```

If the documented invocation needs multiple arguments, represent each as a separate `args` entry. Adjust file extensions
and project patterns to the repository rather than treating the example as a universal selector.

Restart Kiro CLI after changing the file, or force code-intelligence reinitialization:

```text
/code init -f
/code status
```

`/code status` should show `cfn-lsp` as initialized. Use code-intelligence tools for symbol navigation, hover,
completion, diagnostics, and code actions rather than simulating those features with text search.

## Generic LSP clients

For another LSP-capable editor, translate the standalone stdio command and the initialization options above into
the client's configuration format. Follow the editor's documentation for root detection, workspace folders, file
selectors, and argument arrays. The standalone installation guide contains the maintained client examples.

## Validation workflow

1. Confirm the LSP process is initialized and attached to the intended template.
2. Read all published diagnostics.
3. Use hover, completion, and code actions to understand and fix the template; inspect each proposed edit before
   applying it.
4. Save the file and wait for diagnostics to refresh.
5. Run exactly one local validation procedure against the saved file: the
   [cfn-lint SOP](validate-with-cfn-lint.script.md) or the
   [cloudformation-validate SOP](validate-with-cloudformation-validate.script.md). LSP diagnostics may reflect an editor
   buffer while deployment tooling reads the file on disk.
6. Run the
   [cfn-guard security and compliance SOP](check-cloudformation-template-compliance.script.md) by default. Skip it only
   when the user explicitly requests that or confirms an equivalent project security and compliance check already
   passed.
7. Use [CloudFormation service pre-deployment validation](cloudformation-pre-deploy-validation.script.md) when
   account-aware checks are needed before deployment.

Do not claim that an empty editor diagnostics panel proves the saved template is valid, compliant, or deployable.

## Security Considerations

Follow the [shared security guidance](security-considerations.md) when handling templates, outputs, secrets, tools, and installation artifacts.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Server does not initialize | Re-read the selected release's prerequisites and confirm the installed artifact matches the platform |
| Client reports an immediate process exit | Compare the configured command and argument array with the installation guide |
| No diagnostics or completion | Confirm the file selector routes this file to the server and the document is recognized as CloudFormation |
| Kiro CLI cannot see the server | Run `/code status`, inspect `.kiro/settings/lsp.json`, then restart or run `/code init -f` |

## Authoritative references

- [CloudFormation Language Server](https://github.com/aws-cloudformation/cloudformation-languageserver)
- [Standalone installation guide](https://github.com/aws-cloudformation/cloudformation-languageserver/blob/main/INSTALLATION.md)
- [CloudFormation Language Server releases](https://github.com/aws-cloudformation/cloudformation-languageserver/releases/latest)
- [CloudFormation Language Server telemetry](https://github.com/aws-cloudformation/cloudformation-languageserver/blob/main/src/telemetry/README.md)
- [AWS Toolkit for Visual Studio Code](https://marketplace.visualstudio.com/items?itemName=AmazonWebServices.aws-toolkit-vscode)
- [AWS Toolkit for JetBrains](https://plugins.jetbrains.com/plugin/11349-aws-toolkit)
