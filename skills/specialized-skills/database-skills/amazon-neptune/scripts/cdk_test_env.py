#!/usr/bin/env python3
"""
Neptune Skill — Test Environment Setup (CDK)

Provisions a Neptune cluster inside a VPC for running end-to-end skill evals.
Run this before executing the eval suite that requires a live Neptune cluster.

Usage:
    pip install aws-cdk-lib constructs
    cdk deploy
"""

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Stack,
    Tags,
)
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_neptune_alpha as neptune
from constructs import Construct


class NeptuneSkillTestStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        generation_model: str = "unknown",
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # VPC with private subnets (Neptune requires VPC)
        vpc = ec2.Vpc(
            self,
            "NeptuneVpc",
            max_azs=2,
            nat_gateways=1,  # Required for CloudShell to download clients
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
            ],
        )

        # Security group for Neptune
        neptune_sg = ec2.SecurityGroup(
            self,
            "NeptuneSG",
            vpc=vpc,
            description="Neptune skill test cluster",
            allow_all_outbound=True,
        )

        # Allow inbound on port 8182 from within the VPC
        # (CloudShell VPC environments and Lambda will use this)
        neptune_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(8182),
            description="Neptune from within VPC",
        )

        # Neptune cluster (Serverless for cost efficiency in test)
        # Always enable encryption at rest, even in test — models secure patterns
        cluster = neptune.DatabaseCluster(
            self,
            "NeptuneCluster",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            instance_type=neptune.InstanceType.SERVERLESS,
            serverless_scaling_configuration=neptune.ServerlessScalingConfiguration(
                min_capacity=1,
                max_capacity=4,
            ),
            security_groups=[neptune_sg],
            storage_encrypted=True,  # KMS encryption at rest (AWS-managed key)
            iam_authentication=True,  # model production-secure auth (SigV4-signed connections)
            # This stack builds a THROWAWAY eval cluster that the harness must
            # tear down, so deletion protection is off. Production clusters
            # MUST set deletion_protection=True.
            deletion_protection=False,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Mandatory skill tags — applied to every resource in this stack.
        Tags.of(cluster).add("created_by", "neptune-skill")
        Tags.of(cluster).add("generation_model", generation_model)

        # Seed data Lambda IAM role
        seed_role = iam.Role(
            self,
            "SeedLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        # Grant seed Lambda access to Neptune
        cluster.grant_connect(seed_role)

        # Outputs for eval scripts
        CfnOutput(
            self,
            "NeptuneEndpoint",
            value=cluster.cluster_endpoint.hostname,
            description="Neptune cluster endpoint for eval scripts",
            export_name="NeptuneSkillTestEndpoint",
        )
        CfnOutput(
            self,
            "NeptunePort",
            value=str(cluster.cluster_endpoint.port),
            description="Neptune port (8182)",
        )
        CfnOutput(
            self,
            "VpcId",
            value=vpc.vpc_id,
            description="VPC ID — use when creating CloudShell VPC environment",
        )
        CfnOutput(
            self,
            "PrivateSubnetId",
            value=vpc.private_subnets[0].subnet_id,
            description="Subnet ID for CloudShell VPC environment",
        )
        CfnOutput(
            self,
            "NeptuneSecurityGroupId",
            value=neptune_sg.security_group_id,
            description="Security group — add client SGs as inbound sources",
        )


app = cdk.App()
NeptuneSkillTestStack(
    app,
    "NeptuneSkillTestStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)
app.synth()
