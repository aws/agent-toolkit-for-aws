# Compliant fixture — MUST pass (POLICY_OK).
# A Memcached aws_elasticache_cluster does not support the Redis encryption
# attributes, so it stays exempt (fail open) and must not be flagged.
resource "aws_elasticache_cluster" "memcached" {
  cluster_id      = "app-memcached"
  engine          = "memcached"
  node_type       = "cache.t4g.micro"
  num_cache_nodes = 2
}
