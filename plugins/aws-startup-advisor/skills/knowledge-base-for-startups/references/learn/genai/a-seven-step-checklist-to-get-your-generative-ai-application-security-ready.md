---
source_url: https://aws.amazon.com/startups/learn/a-seven-step-checklist-to-get-your-generative-ai-application-security-ready
title: "A Seven-Step Checklist to Get Your Generative AI Application Security-Ready"
---

## A Seven-Step Checklist to Get Your Generative AI Application Security-Ready

[Generative AI](https://aws.amazon.com/generative-ai/) has seen explosive growth in recent years, with applications transforming how startups create content, analyze data, and make critical decisions. Organizations are increasingly using the power of generative AI models to build custom applications. As such, the startups experimenting and wielding generative AI must make security and responsible usage a top priority.

In this post, we've developed a seven-item checklist outlining the essential security and compliance measures you should consider when moving your generative AI-powered applications from experimentation to production.

## Checklist Overview

1. Establish governance framework and compliance process
2. Review and comply with the large language model (LLM) provider's End User License Agreement (EULA) and data usage policies
3. Implement comprehensive access controls
4. Mitigate input and output risks
5. Protect your data
6. Secure your perimeter
7. Implement comprehensive monitoring and incident response

Implementing the checklist will help your startup mitigate risks, protect data, and maintain user trust. While checking off more items improves defense, you don't need to complete every checkpoint, as this will depend on what your application needs.

The security controls required will vary depending on the type of model (pre-trained, fine-tuned, or custom) you're using to build your application. Our focus will be on applications built using pre-trained models, which address most customer use cases.

---

## 1. Establish a Governance Framework and Compliance Process

Establishing a comprehensive governance and compliance framework is the foundation for responsible AI deployment. People and process are key, so start by forming a cross-functional AI governance committee with subject matter experts from legal, IT security, and relevant business units. This committee should create and enforce specific policies for your generative AI application, covering data handling, model selection, and usage guidelines.

Next, develop a compliance checklist tailored to your industry regulations (such as [GDPR](https://aws.amazon.com/compliance/gdpr-center/) or [PCI DSS](https://aws.amazon.com/compliance/pci-dss-level-1-faqs/)). This should cover data privacy measures, consent management, and transparency requirements. Implement a regular compliance review, such as quarterly audits, to make sure you adhere to developing standards.

**Further reading:**

- [Scaling a governance, risk, and compliance program for the cloud, emerging technologies, and innovation](https://aws.amazon.com/blogs/security/scaling-a-governance-risk-and-compliance-program-for-the-cloud/)
- [Securing generative AI: data, compliance, and privacy considerations](https://aws.amazon.com/blogs/security/securing-generative-ai-data-compliance-and-privacy-considerations/)

Finally, set up a documentation system to track decisions, changes, and compliance status of your generative AI application. Include features like version control for policies, audit logs for model changes, and a dashboard for compliance status. This system will not only help in maintaining compliance but also provide necessary evidence during external audits.

---

## 2. Review and Comply with the LLM Provider's EULA and Data Usage Policies

It's crucial to understand specific limitations and requirements to maintain compliance and avoid potential legal issues. Before integrating a pre-trained model into your application, review the EULA and data usage policies of your chosen LLM provider. Pay close attention to clauses on data handling, model outputs, and restrictions on commercial use.

- For [Amazon Bedrock](https://aws.amazon.com/bedrock/) users, refer to [Access Amazon Bedrock foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
- If you're self-deploying on [Amazon SageMaker](https://aws.amazon.com/sagemaker/), review the [model sources](https://docs.aws.amazon.com/sagemaker/latest/dg/jumpstart-foundation-models-choose.html) on the model details page

As well as ensuring compliance, keeping an eye out for new updates can also bring exciting opportunities. For instance, the [Meta Llama 3.1 license](https://llama.meta.com/llama3_1/license/) is considered more permissive than its predecessors, opening up new use cases such as analyzing lengthy documents and building advanced multilingual chatbots for global use.

---

## 3. Implement Comprehensive Access Controls

When developing and deploying your generative AI application, you will need robust access controls to protect your system and data. This includes setting up user authentication, authorization, and data access policies, all while adhering to the principle of least privilege (PoLP). The idea behind PoLP is that users and services only get the access they need to do their jobs.

### Key implementation steps:

- Implement user authentication using services like [Amazon Cognito](https://aws.amazon.com/cognito/) or [Amazon Verified Permissions](https://aws.amazon.com/verified-permissions/)
- Set access controls for every part of your generative AI app, including the LLM, databases, storage systems, and any connected services or APIs
- Use models that can be accessed through short-lived, temporary credentials (like those on Amazon Bedrock or Amazon SageMaker)
- Make sure user sessions and conversation contexts are isolated by implementing mechanisms to prevent users from accessing other users' content, session histories, or conversational information
- Use unique session identifiers for users and validate these every time a user accesses the system

### For RAG implementations:

For retrieval augmented generation (RAG) implementations, it's crucial to manage access to the knowledge bases used to augment LLM responses. You can simplify this by using [Amazon Bedrock Knowledge Bases](https://aws.amazon.com/bedrock/knowledge-bases/) with [metadata filtering](https://aws.amazon.com/blogs/machine-learning/access-control-for-vector-stores-using-metadata-filtering-with-knowledge-bases-for-amazon-bedrock/), which provides built-in access controls. If you're managing your own RAG, use [Amazon Kendra](https://aws.amazon.com/kendra/) to [filter responses based on user permissions](https://docs.aws.amazon.com/kendra/latest/dg/user-context-filter.html).

---

## 4. Mitigate Input and Output Risks

Once you've implemented access controls, you can now focus on evaluation mechanisms to assess and mitigate risks associated with user inputs and model outputs in your generative AI application. This helps protect against vulnerabilities such as prompt injection attacks, inappropriate content generation or hallucinations.

You can simplify this process using [Amazon Bedrock Guardrails](https://aws.amazon.com/bedrock/guardrails/). Guardrails allows you to configure defenses for prompt input and model output that can be applied across LLMs on Amazon Bedrock, including fine-tuned models and even generative AI applications outside of Amazon Bedrock.

As an additional precaution, implement a verified prompt catalog (a pre-approved set of prompts for common tasks) using [Amazon Bedrock Prompt Management](https://aws.amazon.com/bedrock/prompt-management/) to manage prompts effectively and protect the LLM from malicious instructions.

### Output validation best practices:

- LLM responses should be treated with caution—if the model is generating code or database queries, treat its output like it came from an untrusted user
- Always check permissions and run security checks before letting it interact with other systems
- Use safe methods like parameterized queries for databases and review the structure of any generated SQL before using it
- Use [prompt templates](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-templates-and-examples.html) within system prompts to control the format of the model's responses
- For languages like JavaScript or Markdown, always encode the output before showing it to users
- If the AI's code needs to run, do this in a sandbox (an isolated environment)

---

## 5. Protect Your Data

Make sure you protect the data your model uses and responds to (such as user queries, additional contexts, and knowledge bases used in RAG systems) through encryption.

### Recommended services:

- [AWS Key Management Service](https://aws.amazon.com/kms/) for secure management, storage, and rotation of encryption keys
- [AWS Identity and Access Management (IAM)](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html) for access controls
- Turn on versioning for your knowledge base storage (such as [S3 versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)) to track changes

If you're handling sensitive data, you can also implement data masking or blocking using [Bedrock Guardrail's sensitive information filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html).

---

## 6. Secure Your Perimeter

Now that your data is secured, you can focus on protecting your generative AI infrastructure. When using proprietary data, make sure to set up a secure perimeter to prevent exposure to the public internet.

- [Amazon Bedrock VPC endpoint](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html) creates a private connection between your Virtual Private Cloud (VPC) and Amazon Bedrock account, strengthening the security of your data and model interactions

LLMs use significant computing power, making them targets for abuse. To prevent this, you can set limits on how much users can access your application:

- Use [AWS Web Application Firewall (WAF)](https://aws.amazon.com/waf/) to set these limits
- Use [Amazon API Gateway](https://aws.amazon.com/api-gateway/) to control the rate of requests to your application

These measures will protect your infrastructure while ensuring your system performs well and runs consistently.

---

## 7. Implement Comprehensive Monitoring and Incident Response

Once you've secured your set-up and data, you can now look to securing system monitoring. This includes implementing response mechanisms to quickly detect and address security issues.

### Monitoring:

- Monitor LLM usage metrics such as request volume, latency, and error rates to understand your system's performance and detect anomalies
- [Amazon CloudWatch](https://aws.amazon.com/cloudwatch/) will create alerts when these metrics exceed your set levels

### Incident response:

- Develop an incident response plan to address scenarios such as prompt injections, unexpected model outputs, or data leaks
- Outline an escalation process for each scenario, including naming key tools and members of your team and their responsibilities
- Set up a system like [Andon cord](https://docs.aws.amazon.com/wellarchitected/latest/devops-guidance/oa.bcl.5-establish-clear-escalation-paths-and-encourage-constructive-disagreement.html) which allows you to quickly turn off a model, roll back to an earlier version, or switch to a safe mode if something goes wrong

Having these clear steps in place for security issues will help you respond faster and keep your AI application safe and stable.

---

## Conclusion

This seven-step checklist is an essential guide for moving your generative AI application from prototype to production. Addressing and actioning each item will help you build and deploy responsibly, protecting both your organization and your users.

Generative AI is evolving at a rapid pace, so it's important to keep up to date with the latest developments in AI security to keep your application (and your startup) at the forefront of innovation and trust.

Check out [AWS Community – Generative AI](https://community.aws/generative-ai) to catch the latest updates!

---

## Related Resources

- [Learn](/startups/learn) - AWS Startups learning resources
- [Generative AI Articles](/startups/learn/generative-ai) - More generative AI resources for startups
- [Technical Resources](/startups/learn/technical-resources) - Technical guides and learning resources
