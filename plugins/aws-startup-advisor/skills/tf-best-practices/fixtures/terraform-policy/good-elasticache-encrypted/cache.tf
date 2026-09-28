# Compliant fixture — MUST pass (POLICY_OK).
resource "aws_elasticache_replication_group" "good" {
  replication_group_id       = "good-redis"
  description                = "encrypted redis"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 2
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# Variable-driven value must fail open (not flagged).
resource "aws_elasticache_replication_group" "var_driven" {
  replication_group_id       = "var-redis"
  description                = "var-driven"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 2
  at_rest_encryption_enabled = var.encrypt_cache
}

variable "encrypt_cache" {
  type    = bool
  default = true
}
