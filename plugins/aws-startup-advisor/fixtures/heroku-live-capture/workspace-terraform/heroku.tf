# Fixture Terraform — deliberately STALE relative to the live captures in
# ../live-capture/. Each divergence below exercises a specific rule in
# discover-assemble.md § Merge & Drift Rules. Do not "fix" the drift.

resource "heroku_app" "web" {
  name   = "acme-web"
  region = "us"
  stack  = "heroku-22"
}

# Drift: live runs 2x Standard-2X; Terraform says 1x standard-1x.
# → merge rule 1 (config conflicts on quantity + dyno_type, live wins)
resource "heroku_formation" "web" {
  app_id   = heroku_app.web.id
  type     = "web"
  quantity = 1
  size     = "standard-1x"
}

# Scaled-to-zero release process: invisible to `heroku ps`, declared here.
# → merge rule 4 (gap-fill from Terraform, expected complement not conflict)
resource "heroku_formation" "release" {
  app_id   = heroku_app.web.id
  type     = "release"
  quantity = 0
  size     = "standard-1x"
}

# Drift: live plan is standard-2; Terraform still says standard-0.
# → merge rule 1a (plan change = config conflict, NOT an add/remove pair)
resource "heroku_addon" "postgres" {
  app_id = heroku_app.web.id
  plan   = "heroku-postgresql:standard-0"
}

# Declared but never deployed (absent from live captures).
# → merge rule 3 (terraform-only, not_found_live: true)
resource "heroku_addon" "scheduler" {
  app_id = heroku_app.web.id
  plan   = "scheduler:standard"
}

# NOTE deliberate absences from this file (present in live captures):
# - app acme-staging and everything on it → merge rule 2 (unmanaged_by_terraform)
# - heroku-redis:premium-0 on acme-web    → merge rule 2 (unmanaged_by_terraform)
# - papertrail:choklad on acme-web        → merge rule 2 (unmanaged_by_terraform)
# - pipeline "acme" and custom domain     → merge rule 2 (unmanaged_by_terraform)
