# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: elasticache_cluster_encryption failure path — a single-node Redis
# aws_elasticache_cluster (no replication_group_id) with no encryption set.
resource "aws_elasticache_cluster" "bad" {
  cluster_id = "bad-redis-cluster"
  engine     = "redis"
  node_type  = "cache.t4g.micro"
  num_cache_nodes = 1
}
