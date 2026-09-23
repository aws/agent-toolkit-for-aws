# Compliant fixture — MUST pass (POLICY_OK).
# A single-node Redis aws_elasticache_cluster with transit encryption on.
# NOTE: at_rest_encryption_enabled is NOT a valid argument on
# aws_elasticache_cluster (AWS provider schema) — at-rest encryption requires
# aws_elasticache_replication_group. Only transit_encryption_enabled applies here.
resource "aws_elasticache_cluster" "good" {
  cluster_id                 = "good-redis-cluster"
  engine                     = "redis"
  node_type                  = "cache.t4g.micro"
  num_cache_nodes            = 1
  transit_encryption_enabled = true
}
