# Vendored shared files — DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained** — it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then copy the changed file over every vendored copy in the same change so the
copies stay byte-identical:

```sh
# from the repository root, for each vendored path listed below
cp plugins/aws-startup-advisor/skills/shared/<path> \
   plugins/aws-startup-advisor/skills/gcp-to-aws/references/vendored/<path>
```

This repository has no automated sync task for these copies — keeping them
byte-identical is part of the change that touches the canonical file. Verify with
`md5sum` (or `md5 -q`) over the canonical file and every vendored copy before
opening a pull request; the hashes must match.

| Vendored path                      | Canonical source                                |
| ---------------------------------- | ----------------------------------------------- |
| `workshop/workshop-invariants.md`  | `skills/shared/workshop/workshop-invariants.md` |
