"""heroku-to-aws EKS nodes boot the Amazon Linux 2023 AMI, not Amazon Linux 2.

EKS stopped publishing EKS-optimized Amazon Linux 2 AMIs on 2025-11-26 and never published them
for Kubernetes 1.33 or later. The self-managed node template used to read the
`.../amazon-linux-2/recommended/image_id` SSM parameter and run `/etc/eks/bootstrap.sh`; on any
current cluster version the parameter does not exist and `terraform plan` fails. AL2023 nodes
boot with nodeadm and need the cluster endpoint, CA and service CIDR in a NodeConfig document.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HEROKU = PLUGIN_ROOT / "skills" / "heroku-to-aws"
GENERATE_EKS = HEROKU / "references" / "phases" / "generate" / "generate-eks.md"
DESIGN_EKS = HEROKU / "references" / "phases" / "design" / "design-eks.md"
SIZING = HEROKU / "knowledge" / "design" / "eks-pod-sizing.json"


def _block(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def test_self_managed_nodes_use_the_al2023_ami_parameter() -> None:
    text = GENERATE_EKS.read_text(encoding="utf-8")
    assert "amazon-linux-2/recommended" not in text
    assert "/aws/service/eks/optimized-ami/<kubernetes_version>/amazon-linux-2023/<arch>/standard/recommended/image_id" in text
    # The arch placeholder is explained next to the lookup, with x86_64 and arm64 both named.
    lookup = _block(text, "# <arch> is x86_64", 'resource "aws_autoscaling_group"')
    assert "arm64" in lookup and "Graviton" in lookup


def test_self_managed_nodes_boot_with_nodeadm_not_bootstrap_sh() -> None:
    text = GENERATE_EKS.read_text(encoding="utf-8")
    template = _block(text, 'resource "aws_launch_template" "eks_nodes"', 'data "aws_ssm_parameter" "eks_ami"')
    user_data = _block(template, "user_data = base64encode(", "EOF\n  )")
    # The prose above the resource may name bootstrap.sh to explain the change; the emitted user data must not run it.
    assert "bootstrap.sh" not in user_data and "#!/bin/bash" not in user_data
    assert "apiVersion: node.eks.aws/v1alpha1" in user_data and "kind: NodeConfig" in user_data
    # nodeadm does not call DescribeCluster, so the four cluster fields must come from the cluster resource.
    for field, ref in (
        ("name", "${aws_eks_cluster.main.name}"),
        ("apiServerEndpoint", "${aws_eks_cluster.main.endpoint}"),
        ("certificateAuthority", "${aws_eks_cluster.main.certificate_authority[0].data}"),
        ("cidr", "${aws_eks_cluster.main.kubernetes_network_config[0].service_ipv4_cidr}"),
    ):
        assert f"{field}: {ref}" in user_data, field


def test_managed_node_group_names_an_al2023_ami_type() -> None:
    text = GENERATE_EKS.read_text(encoding="utf-8")
    group = _block(text, 'resource "aws_eks_node_group" "general"', "# Self-Managed Node Group")
    assert 'ami_type = "<ami_type>"' in group
    assert "AL2023_x86_64_STANDARD" in group and "AL2023_ARM_64_STANDARD" in group
    assert "Never an AL2_* type" in group


def test_kubernetes_version_fallback_is_in_standard_support_and_documented() -> None:
    cluster = json.loads(SIZING.read_text(encoding="utf-8"))["cluster"]
    fallback = cluster["kubernetes_version_fallback"]
    assert re.fullmatch(r"1\.\d{2}", fallback)
    # 1.31 left standard support on 2025-11-26; the fallback must be newer than any version whose
    # AL2 AMI still exists (<= 1.32), otherwise the AL2023 parameter is the only path that works.
    assert tuple(int(p) for p in fallback.split(".")) >= (1, 33)
    note = cluster["_kubernetes_version_note"]
    assert "describe-cluster-versions" in note and f"Do NOT treat {fallback} as pinned" in note
    assert "standard support runs to" in note, "the note must say why the fallback was chosen and when to re-check it"
    design = " ".join(DESIGN_EKS.read_text(encoding="utf-8").split())
    assert "`aws eks describe-cluster-versions`" in design and "describe-addon-versions" not in design


def test_self_managed_launch_template_does_not_expose_slash_tags_through_imds() -> None:
    """EC2 rejects a launch when instance tags are exposed through IMDS and a tag key contains "/"
    (work-with-tags-in-IMDS: keys may use only letters, digits and + - = . , _ : @). The node template
    must carry `kubernetes.io/cluster/<name>`, so `instance_metadata_tags` has to stay disabled while
    IMDSv2 token enforcement is kept."""
    text = GENERATE_EKS.read_text(encoding="utf-8")
    template = _block(text, 'resource "aws_launch_template" "eks_nodes"', 'data "aws_ssm_parameter" "eks_ami"')
    metadata = _block(template, "metadata_options {", "}")
    assert 'http_tokens                 = "required"' in metadata
    assert 'instance_metadata_tags      = "disabled"' in metadata
    assert '"enabled"' not in metadata.replace('http_endpoint               = "enabled"', "")
    tags = _block(template, "tag_specifications {", "}\n  }")
    slash_keys = re.findall(r'"([^"\n]*/[^"\n]*)"\s*=', tags)
    assert slash_keys, "the node template must still carry the kubernetes.io/cluster/<name> tag"
    # The rider that documents this block for every self-managed template must agree.
    rider = HEROKU / "references" / "phases" / "generate" / "generate-terraform.md"
    rider_text = rider.read_text(encoding="utf-8")
    rider_block = _block(rider_text, "**EKS launch-template rider", "**Emission conditions**")
    assert 'instance_metadata_tags      = "disabled"' in rider_block
    assert 'instance_metadata_tags      = "enabled"' not in rider_block
