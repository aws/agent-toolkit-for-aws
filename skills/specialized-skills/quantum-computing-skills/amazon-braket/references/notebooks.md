<!-- markdownlint-disable MD013 -->

# Braket Notebook Instance

Amazon Braket provides fully managed Jupyter notebooks to get you started.

## Creating a notebook instance

- **CloudFormation (recommended):** follow the templates at [Create a Braket notebook instance using CloudFormation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-cloudformation.html) to programmatically create a Braket notebook instance with all recommended libraries and plugins installed.
- **Console:** the user can create one manually following [Create an Amazon Braket notebook instance](https://docs.aws.amazon.com/braket/latest/developerguide/braket-get-started-create-notebook.html).

## Execution role requirements

See [setup.md](./setup.md) for details on setting up the Notebook role.

See [Notebooks and roles](https://docs.aws.amazon.com/braket/latest/developerguide/braket-manage-access.html#notebooks-and-roles) for more information on notebooks and permissions.

## Security considerations

If the user requires additional security configuration for the notebook instance, see these pages:

- [Configure security in Amazon SageMaker AI](https://docs.aws.amazon.com/sagemaker/latest/dg/security.html)
- [CreateNotebookInstance](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateNotebookInstance.html)
- [Restrict user access to certain notebook instances](https://docs.aws.amazon.com/braket/latest/developerguide/restrict-access-notebook-instances.html)

## References

- API:
  - [CreateNotebookInstance](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateNotebookInstance.html)
  - [StartNotebookInstance](https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_StartNotebookInstance.html)
- Developer guide:
  - [Create an Amazon Braket notebook instance](https://docs.aws.amazon.com/braket/latest/developerguide/braket-get-started-create-notebook.html)
  - [Create a Braket notebook instance using CloudFormation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-cloudformation.html)
  - [Managing access to Amazon Braket — notebooks and roles](https://docs.aws.amazon.com/braket/latest/developerguide/braket-manage-access.html#notebooks-and-roles)
  - [Restrict user access to certain notebook instances](https://docs.aws.amazon.com/braket/latest/developerguide/restrict-access-notebook-instances.html)
- IAM policy:
  - [`AmazonBraketFullAccess`](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonBraketFullAccess.html)
- SageMaker AI:
  - [Notebook instances](https://docs.aws.amazon.com/sagemaker/latest/dg/nbi.html)
  - [Lifecycle configuration](https://docs.aws.amazon.com/sagemaker/latest/dg/notebook-lifecycle-config.html)
  - [SageMaker AI roles](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-roles.html)
- CloudFormation:
  - [`AWS::SageMaker::NotebookInstance`](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sagemaker-notebookinstance.html)
  - [`AWS::SageMaker::NotebookInstanceLifecycleConfig`](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-sagemaker-notebookinstancelifecycleconfig.html)
