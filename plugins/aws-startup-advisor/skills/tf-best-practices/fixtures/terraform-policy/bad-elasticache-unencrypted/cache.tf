# Intentionally non-compliant fixture — DO NOT deploy, DO NOT sanitize.
# Exercises: elasticache_encryption_at_rest failure path (encryption disabled).
resource "aws_elasticache_replication_group" "bad" {
  replication_group_id       = "bad-redis"
  description                = "unencrypted redis"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 2
  at_rest_encryption_enabled = false
}
