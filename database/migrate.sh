#!/usr/bin/env bash
# Applies database/migrations/*.sql once each, in name order. Forward-only.
set -euo pipefail
: "${SQLCMDPASSWORD:?SQLCMDPASSWORD is required}"
host=${SQLSERVER_HOST:-sqlserver}
db=${DB_NAME:-RTS_DB}
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
run() { /opt/mssql-tools18/bin/sqlcmd -S "$host" -U sa -C -I -b -f 65001 "$@"; }

run -d master -Q "IF DB_ID(N'$db') IS NULL CREATE DATABASE [$db];"
run -d "$db" -Q "IF OBJECT_ID(N'dbo.schema_migration') IS NULL CREATE TABLE dbo.schema_migration (version varchar(100) NOT NULL PRIMARY KEY, applied_at datetime2 NOT NULL DEFAULT SYSUTCDATETIME());"

for file in "$root"/migrations/*.sql; do
  version=$(basename -- "$file")
  applied=$(run -d "$db" -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.schema_migration WHERE version='$version';" | tr -d '[:space:]')
  if [[ "$applied" == "0" ]]; then
    echo "Applying $version"
    run -d "$db" -i "$file"
    run -d "$db" -Q "INSERT dbo.schema_migration (version) VALUES ('$version');"
  fi
done

for file in "$root"/seed/*.sql; do
  run -d "$db" -i "$file"
done
echo "Database is up to date"

# The simulated HQ (PB-18) has its own database and its own migration history.
hq_db=${HQ_DB_NAME:-RTS_HQ}
run -d master -Q "IF DB_ID(N'$hq_db') IS NULL CREATE DATABASE [$hq_db];"
run -d "$hq_db" -Q "IF OBJECT_ID(N'dbo.schema_migration') IS NULL CREATE TABLE dbo.schema_migration (version varchar(100) NOT NULL PRIMARY KEY, applied_at datetime2 NOT NULL DEFAULT SYSUTCDATETIME());"

for file in "$root"/hq/*.sql; do
  version=$(basename -- "$file")
  applied=$(run -d "$hq_db" -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.schema_migration WHERE version='$version';" | tr -d '[:space:]')
  if [[ "$applied" == "0" ]]; then
    echo "Applying HQ $version"
    run -d "$hq_db" -i "$file"
    run -d "$hq_db" -Q "INSERT dbo.schema_migration (version) VALUES ('$version');"
  fi
done
echo "HQ database $hq_db is up to date"
