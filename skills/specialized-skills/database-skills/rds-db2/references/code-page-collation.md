# RDS for Db2 — Code Page and Collation Selection

> **Source:** `04-db2-client/choose-proper-code-page-and-collation/choose-codepage-improved.md`
> (blog DBBLOG-5218, "Choosing the Right Code Page and Collation for Migrating from Mainframe Db2 to
> Amazon RDS for Db2":
> https://aws.amazon.com/blogs/database/choosing-the-right-code-page-and-collation-for-migration-from-mainframe-db2-to-amazon-rds-for-db2/).
> Placeholders `<DBNAME>`, `<MasterUserName>`, `<MasterUserPassword>` stand in for real values.

## Immutable after creation — choose carefully

**Code page, collation, and territory cannot be modified after database creation** in Amazon RDS for
Db2. A wrong choice forces database recreation and re-migration, so decide before you create the
database. RDS for Db2 defaults to UTF-8 with US territory: **do not** specify a default database name
during RDS instance creation, and instead create databases explicitly with `rdsadmin.create_database`.

## Mainframe CCSID inventory

Mainframe Db2 (z/OS) uses EBCDIC code pages by region:

- **Latin / Western European:** CCSID 37 (CP037, US/Canada/Netherlands/Portugal), 500 (CP500,
  international), 1047 (CP1047, Open Systems/USS), 273 (CP273, German/Austrian).
- **Euro-enabled:** CCSID 1141 (German/Austrian + €), 1390 (Japanese + €).
- **Japanese:** CCSID 930 (Katakana), 939 (Latin); 5026/5035 are *collation* sequences (not code
  pages) used with 930 and 939 respectively.

ISO-8859-1 (IBM code page 819) is the direct ASCII equivalent of Latin CCSIDs 37, 500, 1047, and 273,
enabling lossless conversion — but it **excludes the Euro symbol** (€).

## CCSID → code page → collation decision matrix

| Mainframe CCSID | RDS code set | Collation | Notes |
|---|---|---|---|
| 37 (US/Canada EBCDIC) | ISO-8859-1 | `EBCDIC_819_037` | EBCDIC US English |
| 500 or 1047 (International / Open Systems) | ISO-8859-1 | `EBCDIC_819_500` | EBCDIC International |
| 273 (German/Austrian) | ISO-8859-1 | `EBCDIC_819_500` | Latin-1; no Euro |
| 1141, 1390 (Euro-enabled) | UTF-8 or ISO-8859-15 | `SYSTEM` | Verify RDS ISO-8859-15 support |
| 930 (Japanese Katakana) | UTF-8 | `EBCDIC_932_5026` | Katakana collation |
| 939 (Japanese Latin) | UTF-8 | `EBCDIC_932_5035` | Latin collation |

The fifth `create_database` parameter is the collation sequence. Full set of source collation values:
`EBCDIC_819_037`, `EBCDIC_819_500`, `EBCDIC_850_037`, `EBCDIC_850_500`, `EBCDIC_932_5026`,
`EBCDIC_932_5035`, `EBCDIC_1252_037`, `EBCDIC_1252_500`. Use ISO-8859-1 for exact mainframe
compatibility, zero data loss, and preserved sorting; use UTF-8 for Japanese or multi-language data.

## Creating the database — `rdsadmin.create_database`

Parameter order from source: `create_database(name, pagesize, codeset, territory, collation)`.

```bash
$ db2 connect to rdsadmin user <MasterUserName> using <MasterUserPassword>

# ISO-8859-1, EBCDIC collation (CCSID 37 source):
$ db2 "call rdsadmin.create_database('<DBNAME>',32768,'ISO-8859-1','US','EBCDIC_819_037')"

# ISO-8859-1, EBCDIC collation (CCSID 500/1047 source):
$ db2 "call rdsadmin.create_database('<DBNAME>',32768,'ISO-8859-1','US','EBCDIC_819_500')"

# ISO-8859-15 (Euro support, if available):
$ db2 "call rdsadmin.create_database('<DBNAME>',32768,'ISO-8859-15','US','SYSTEM')"

# UTF-8 (multi-language / Japanese):
$ db2 "call rdsadmin.create_database('<DBNAME>',32768,'UTF-8','US','SYSTEM')"
```

Supported ISO-8859-1 territory codes include AL, AU, AT, BE, BR, CA, CH, CN, DE, DK, ES, FI, GB, IN,
IT, JP, KR, NL, NO, PT, TW, US, ZA. Consult IBM documentation for valid territory/code-page pairs.

## CODEUNITS32 vs OCTETS trade-offs

UTF-8 expands storage: Latin accented characters (à, é, ß, ¬, µ, ¼) use 1 byte on mainframe but 2 in
UTF-8; Japanese characters use 3 bytes. To avoid editing every CHAR/VARCHAR length, switch the default
string measurement to CODEUNITS32:

```bash
db2 "call rdsadmin.update_db_param('<DBNAME>','STRING_UNITS','CODEUNITS32','NO')"
```

`STRING_UNITS` is not dynamic — this requires an instance restart, and DDL objects must be created
**after** the change.

**Database-level CODEUNITS32 is costly:** default allocation grows from 1 to 4 bytes per character,
max `CHAR` drops from 255 to 63 characters, max `VARCHAR` from 32,704 to 8,174 bytes (32K page), and a
mostly-ASCII database can expand ~3.8x. Prefer adjusting OCTETS lengths over CODEUNITS32:

```sql
-- Inefficient: CHAR(2 CODEUNITS32) allocates 8 bytes
-- Recommended: CHAR(4 OCTETS) allocates exactly 4 bytes
```

Use CODEUNITS32 only when you are certain you will store 3–4 byte characters (e.g., East Asian text).

## EBCDIC vs SYSTEM collation ordering

The collation choice changes sort order:

- **EBCDIC:** special characters → lowercase → uppercase → numerals.
- **SYSTEM:** numerals → uppercase → lowercase → special characters.

Choose EBCDIC collation to preserve the exact mainframe sort order; choose SYSTEM for standard
ASCII/Unicode ordering.

## ISO-8859-1 silent `0x1A` substitution

ISO-8859-1 cannot store characters outside its range (e.g., Japanese 常). On insert, Db2 performs
**silent substitution with no error or warning** — the character becomes SUB (`0x1A`) and remaining
byte positions are filled with spaces (`0x20`):

```sql
db2 "insert into t1 values ('常')"
db2 "select c1, hex(c1) hex from t1"   -- hex shows 1A202020
```

Verify character compatibility before choosing ISO-8859-1; if the data contains unsupported
characters, use UTF-8 instead.

## Checking the source CCSID

Inspect the z/OS catalog before choosing the target encoding:

```sql
-- Table-level encoding (E = EBCDIC):
SELECT NAME, ENCODING_SCHEME FROM SYSIBM.SYSTABLES
 WHERE NAME = '<TABLE_NAME>' AND CREATOR = '<CREATOR_NAME>';

-- Column-level CCSID (0 = subsystem default):
SELECT NAME, CCSID FROM SYSIBM.SYSCOLUMNS
 WHERE TBNAME = '<TABLE_NAME>' AND TBCREATOR = '<CREATOR_NAME>';
```

## Validation

Insert international characters (for example 'café', 'niño') on the source, export, import into RDS for
Db2, and confirm display with a GUI client (DBeaver, DataGrip, IBM Data Studio). Round-trip
conversions (EBCDIC → ASCII → EBCDIC) can lose variants without exact mappings, so always verify
against IBM's official CCSID tables. Address code page and collation early — the choice is immutable.
