# Fixture Terraform — deliberately STALE relative to the live captures in
# ../live-capture/. Each divergence exercises a specific rule in
# discover-live.md Step 6 (Merge with IaC Discovery). Do not "fix" the drift.

resource "google_compute_network" "main" {
  name                    = "main"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "app" {
  name          = "app"
  region        = "us-central1"
  network       = google_compute_network.main.id
  ip_cidr_range = "10.0.0.0/24"
}

resource "google_service_account" "app" {
  account_id   = "app-sa"
  display_name = "App runtime SA"
}

# Drift: live tier is db-custom-2-8192 (someone scaled up in the console).
# → Step 6 rule 1 (config conflict on settings.tier, live value wins)
resource "google_sql_database_instance" "db" {
  name             = "orders-db"
  region           = "us-central1"
  database_version = "POSTGRES_16"
  settings {
    tier = "db-f1-micro"
    ip_configuration {
      private_network = google_compute_network.main.id
      ipv4_enabled    = false
    }
  }
}

# Declared as the LEGACY v1 resource type while the live capture maps the same
# service to google_cloud_run_v2_service (the real-project bug).
# → Step 6 type-alias rule: must merge as ONE resource (live+terraform, IaC
#   address kept, config.live_type = google_cloud_run_v2_service) — NEVER a
#   not_found_live + unmanaged_by_terraform pair. Also carries image drift
#   (v40 here vs v42 live).
resource "google_cloud_run_service" "orders_api" {
  name     = "orders-api"
  location = "us-central1"
  template {
    spec {
      service_account_name = google_service_account.app.email
      containers {
        image = "us-central1-docker.pkg.dev/acme-prod/apps/orders-api:v40"
        resources {
          limits = { cpu = "2", memory = "1Gi" }
        }
      }
    }
  }
}

# Declared but NOT deployed (absent from live buckets.json; buckets capture ok).
# → Step 6 rule 3 (not_found_live: true)
resource "google_storage_bucket" "assets" {
  name     = "acme-prod-assets"
  location = "US-CENTRAL1"
}

# Declared, and the pubsub live capture FAILED (API-not-enabled in manifest).
# → Step 6 rule 3 negative case: must NOT be marked not_found_live
#   (absence of evidence is not drift).
resource "google_pubsub_topic" "events" {
  name = "events"
}

# NOTE deliberate absences from this file (present in live captures):
# - google_redis_instance "cache"          → unmanaged_by_terraform (click-ops)
# - Cloud Run service "web-frontend"        → unmanaged_by_terraform
# - Secret Manager secrets (2)              → unmanaged_by_terraform
# - Storage bucket "acme-prod-uploads"      → unmanaged_by_terraform
