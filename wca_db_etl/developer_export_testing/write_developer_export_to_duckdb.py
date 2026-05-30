import duckdb

with open("wca_db_etl/developer_export_testing/wca_developer_export_sample/wca-developer-database-dump.sql", "r") as wca_dev_db_sql_dump:
    while True:
        line = wca_dev_db_sql_dump.readline()
        if line:
            if "DROP TABLE IF EXISTS" in line:
                print(line)
        else:
            break
        

