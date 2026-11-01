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

run -d "$db" -i "$root/seed/001_demo_stores_pos.sql"
echo "Database is up to date"
